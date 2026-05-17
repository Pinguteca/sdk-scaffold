# RFC 0012: Token rotation policy

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `auth` module
  (`RotatingTokenSource`, `RotationInterceptor`, and the OAuth 2.0
  caching token source).
- Depends on: RFC 0002 (layered architecture), RFC 0006 (retry
  behavioural contract), RFC 0008 (resilience presets) for chain
  positioning.

## Summary

Pin how every SDK handles credential rotation when the server returns
`Unauthenticated` mid-flight. A separate `RotationInterceptor` sits
between the retry interceptor and the auth interceptor; on a single
`Unauthenticated` it invalidates the cached token, lets the inner
auth layer fetch a fresh one, and retries the call exactly once. The
first SDK (Go) shipped this as a local ADR; pinning it across SDKs
prevents the next implementer from baking rotation into the auth
interceptor as a flag (which couples two responsibilities) or skipping
rotation entirely (which leaves consumers stuck behind the cached
token until natural expiry).

## Motivation

OAuth 2.0 access tokens expire. The naive flow (auth interceptor
attaches a cached token; on expiry the cache refreshes) handles the
predictable case where the local clock and the server's clock agree
on validity. It does not handle the race where:

1. The local cache says the token is still valid for 30 seconds.
2. The auth interceptor attaches it.
3. The server's clock skews ahead, or the IdP revokes the token
   mid-flight, and the server replies `Unauthenticated`.

Without a rotation step the SDK sees a 401 with a still-cached "valid"
token, and the next call sees the same cached token and fails again
until natural expiry. With rotation, the SDK invalidates the cache,
re-fetches, and retries once.

Two cross-SDK questions need pinning:

1. **Where in the interceptor chain does rotation live?** Inside the
   auth interceptor as a flag, or as a separate interceptor; if
   separate, between retry and auth or outside retry.
2. **When does rotation refuse to retry?** Blind retry of a non-
   idempotent mutation after a 401 risks a duplicate write if the
   server processed the original request before sending the 401.

A pinned answer prevents one SDK from defaulting safe-but-stale
(no rotation), another from defaulting unsafe-but-fresh (rotate every
401 including non-idempotent writes), and a third from picking
something in between.

## Guide-level explanation

### Separate interceptor, not a flag

Every SDK ships a dedicated `RotationInterceptor` rather than adding
a `RetryOn401` flag to the auth interceptor. Two responsibilities
(attach the bearer header, react to a 401 by invalidating the cache)
stay in two interceptors. Consumers wiring a static token source
(`StaticBearer` and equivalents) omit the rotation interceptor; only
deployments with a refresh-capable token source pay for the wiring.

### `RotatingTokenSource` extends the base contract

Each SDK defines a `RotatingTokenSource` (or language idiom)
interface that extends the base `TokenSource` with an `Invalidate()`
method:

```
TokenSource:
    Token(ctx) -> (token, error)

RotatingTokenSource extends TokenSource:
    Invalidate()
```

Token sources that do not need rotation (static bearers, mTLS-only
clients, no-auth flows) keep implementing `TokenSource` and stay
unaffected. Token sources that own a cache (OAuth 2.0 client
credentials, OIDC refresh tokens, IdP-specific sources) implement
`RotatingTokenSource` and expose cache invalidation.

### Caching token source owns its cache

Every SDK's OAuth 2.0 client-credentials token source owns its cache
directly rather than delegating to a language stdlib helper that does
not expose invalidation. Concretely:

- **Go**: rewrite of `oauth2.ReuseTokenSource` semantics inside the
  SDK's `cachingOAuth2Source`. Stdlib helper does not expose
  `Invalidate`.
- **.NET**: cache the `AccessToken` + expiry inside
  `ClientCredentialsTokenSource` under a `SemaphoreSlim`;
  `Invalidate()` clears the field.
- **TS/Node**: same shape with a `Promise<Token>` cache and a
  `null`-on-invalidate.
- **Other languages**: equivalent under the language's concurrency
  primitive (mutex, actor, structured-concurrency lock).

Owning the cache also lets the SDK enforce single-flight refresh
(concurrent callers triggering a refresh share one IdP call rather
than each hitting the IdP) under the same lock.

### Composition order

The composition order pinned in RFC 0008 extends to include
`Rotation`:

```
outermost                                                                          innermost
Logging  ->  OTel  ->  Breaker  ->  Idempotency  ->  Retry  ->  Rotation  ->  Auth
```

`Rotation` sits **inside Retry** and **outside Auth**.

- **Inside Retry:** A successful rotation followed by a transient
  transport failure still benefits from retry's backoff. If rotation
  were outside retry, a flaky network after a perfectly successful
  re-auth would surface as a bare error.
- **Outside Auth:** The rotation interceptor needs to wrap the call
  that auth attached its header to. The retry-after-invalidate
  attempt re-enters the inner auth interceptor, which now sees the
  cleared cache and fetches a fresh token before reattaching the
  header.

### One-shot retry

A persistent `Unauthenticated` after rotation indicates bad
credentials or misconfiguration, not credential expiry. The
interceptor retries exactly once after invalidating; the second 401
surfaces unchanged. Looping would mask misconfiguration and amplify
load on the IdP.

### Idempotency safety gate

`AllowNonIdempotent` defaults to false. When false, the rotation
interceptor skips rotation+retry for methods the schema does not
declare safe (idempotency level is unknown or `IDEMPOTENT_UNKNOWN`).

The original RPC may have been processed server-side before the 401
came back (auth check after mutation in some servers, race between
mutation commit and auth check on the response path). Retrying a
non-idempotent mutation after rotation risks a duplicate write. The
gate prevents the dangerous case by default.

Callers wiring the idempotency-key interceptor with a server that
deduplicates by key may set `AllowNonIdempotent = true`. The gate is
the safety floor, not a permanent limit.

Per RFC 0006, languages without runtime schema metadata (.NET, Java,
Rust under gRPC) fall back to a caller-supplied `IsIdempotent(method)`
predicate; the same hook applies here, reused rather than reimplemented.

### Streaming RPCs pass through

A stream cannot be replayed safely. The rotation interceptor lets
streaming RPCs through unchanged. Consumers needing rotation on
stream open/close handle it at the application layer.

## Reference-level explanation

### Detection: `Unauthenticated` status

The interceptor reacts to the protocol's canonical
"unauthenticated" status code:

- **Connect SDKs**: `connect.CodeUnauthenticated`.
- **gRPC SDKs**: `StatusCode.Unauthenticated` (numeric 16).

Other authentication-related codes (`PermissionDenied`,
`Unauthorized` in HTTP fallback paths) are **not** rotation triggers.
PermissionDenied means the token was valid but lacked authority;
rotating gets a token with the same scopes. Only Unauthenticated
indicates the credential itself was rejected.

### Single-flight refresh

When N concurrent calls trigger rotation at the same time, only one
IdP refresh fires. The remaining N-1 callers wait on the in-flight
refresh and reuse its result. Implementations use the language's
single-flight primitive (Go's `sync/singleflight`, .NET's
`SemaphoreSlim`, Tokio's `OnceCell` or `RwLock`, etc.).

This matters because credential expiry tends to be correlated:
a token issued at 12:00 expires for every concurrent caller at 13:00
at once. Without single-flight, the IdP sees N concurrent
re-authentications.

### Error semantics on second-call failure

Second-call outcomes:

- **Success**: returned to caller unchanged. Caller does not know
  rotation happened.
- **Unauthenticated again**: returned to caller as-is. The error
  message is the server's; the SDK does not wrap or annotate it.
- **Any other error** (transient failure, downstream service error):
  returned to caller. Retry sees this error if rotation is inside
  retry (which it is, by design).

The interceptor does **not** add structured metadata indicating "this
was a post-rotation attempt"; consumers who need that signal wire
correlation IDs through the logging interceptor.

### Streaming and bidirectional RPCs

The interceptor `WrapStreamingClient` / `WrapStreamingHandler` (or
language equivalent) is a pass-through. The rotation contract is
unary-only:

- Streams are long-lived; the cached token at stream open may have
  expired by the time it's used.
- Replaying a stream means re-establishing it, which is the consumer's
  decision.
- Consumers with long-lived streams set a short retry window on the
  application layer, or use a token source with proactive refresh.

A future RFC may define a streaming-aware rotation pattern (proactive
refresh on the stream before the token expires); out of scope here.

### Per-language interface shape

| Language | Base interface     | Rotation extension                       | Invalidate signature        |
|----------|--------------------|------------------------------------------|-----------------------------|
| Go       | `TokenSource`      | `RotatingTokenSource` (embeds TokenSource) | `Invalidate()`            |
| .NET     | `ITokenSource`     | `IRotatingTokenSource : ITokenSource`    | `void Invalidate()`         |
| TS / Node| `TokenSource`      | `RotatingTokenSource` (interface)        | `invalidate(): void`        |
| Java     | `TokenSource`      | `RotatingTokenSource extends TokenSource`| `void invalidate()`         |
| Kotlin   | `TokenSource`      | `RotatingTokenSource : TokenSource`      | `fun invalidate()`          |
| Python   | `TokenSource` (Protocol) | `RotatingTokenSource(Protocol)`    | `def invalidate(self)`      |
| Rust     | `TokenSource` trait | `RotatingTokenSource: TokenSource` trait| `fn invalidate(&self)`      |
| Dart     | `TokenSource`      | `RotatingTokenSource` extends            | `void invalidate()`         |
| Swift    | `TokenSource`      | `RotatingTokenSource: TokenSource`       | `func invalidate()`         |

The interface names follow each ecosystem's casing and prefixing
conventions. The contract is `Invalidate()` returning void / no
result; it must not block on an IdP call.

### Bad-credentials versus expired-credentials

The wire surface (`Unauthenticated`) does not distinguish bad
credentials from expired credentials. The rotation interceptor cannot
tell them apart before the rotation attempt. The cost on misconfigured
deployments is one extra RPC plus one IdP token fetch. Acceptable as
the price for transparent rotation in the expired-token case.

## Drawbacks

- The auth module owns its OAuth 2.0 token cache instead of leaning on
  the language stdlib. Each SDK is responsible for keeping the cache
  correct under concurrent reads and writes. Test coverage for the
  cache is non-trivial (concurrent invalidate+fetch races).
- Custom token-source implementations that want rotation must
  implement `Invalidate()` themselves. Documentation has to flag
  this; future contributors might add a `TokenSource` and forget to
  wire `Invalidate`, silently disabling rotation. A type system that
  refuses to compile a static `TokenSource` where a
  `RotatingTokenSource` is expected catches this in 7 of 9 languages;
  Python and TS rely on lint/test coverage.
- Streaming RPCs not covered. Consumers with long-lived streams and
  short-lived tokens need an application-layer pattern.
- Misconfigured (permanently-bad) credentials pay one extra IdP call
  per RPC. Acceptable but not free.

## Rationale and alternatives

- **Rotate inside the auth interceptor via a `RetryOn401` flag.**
  Rejected: tangles two responsibilities (token attachment vs.
  rotation-on-401) and forces consumers to opt out individually. The
  flag pattern also makes the chain ordering implicit (where in the
  chain does the retry-on-401 happen?) instead of explicit.
- **Rotate outside retry.** Rejected: a transient post-rotation
  network failure would not benefit from retry's backoff, and the
  caller would see a bare error after a perfectly successful re-auth.
- **Loop rotation indefinitely.** Rejected: hides misconfiguration
  and amplifies load on the IdP. One shot is the safety stop.
- **Allow rotation for unknown idempotency by default.** Rejected:
  silent-double-mutation risk is too large for an opt-out default.
- **No rotation at all, rely on natural expiry.** Rejected: the
  clock-skew and mid-flight-revocation cases are real and visible to
  consumers, who would file bugs and roll their own retry logic.
- **Use the language stdlib's OAuth 2.0 helper as the cache.**
  Rejected for Go (the stdlib helper does not expose invalidation).
  Where a language's stdlib does expose invalidation (rare), the SDK
  uses it; the per-language ADR documents the choice.

## Prior art

- RFC 6749, OAuth 2.0 §5.2: `invalid_token` error response semantics.
  https://datatracker.ietf.org/doc/html/rfc6749#section-5.2
- RFC 6750, OAuth 2.0 Bearer Token Usage §3.1: 401 with
  `WWW-Authenticate: Bearer error="invalid_token"`.
  https://datatracker.ietf.org/doc/html/rfc6750#section-3.1
- `golang.org/x/oauth2` reuse-token-source semantics:
  https://pkg.go.dev/golang.org/x/oauth2#ReuseTokenSource
- Go `sync/singleflight`:
  https://pkg.go.dev/golang.org/x/sync/singleflight
- gRPC status code definitions:
  https://grpc.io/docs/guides/status-codes/
- sdk-core-go/docs/adr/0006 (token rotation policy): Go-side reference
  implementation.

## Unresolved questions

- An IdP that distinguishes "expired" from "revoked" via a header or
  body attribute. The interceptor could skip rotation on revocation
  (where rotation gains zero but the IdP call still costs). Today the
  SDK treats every Unauthenticated as a rotation trigger; revisit if
  a target IdP exposes the distinction.
- Request-scoped rotation barrier for high-fanout consumers. Today
  rotation is per-RPC; a single user action that fans out to 50 RPCs
  and gets a 401 on the first triggers 50 independent rotations (one
  succeeds, 49 wait on its single-flight). A request-scoped barrier
  could collapse the fan-out into a single rotation event. Out of
  scope until a real consumer reports this.
- Streaming-aware rotation (proactive refresh on long-lived streams
  before token expiry). A future RFC if streaming consumers report
  the gap.
- Whether `RotationInterceptor` should expose a callback hook
  (`OnRotation func(ctx, oldErr)`) for telemetry-aware consumers.
  Today the answer is "wire it through the logging interceptor's
  caller-attr hooks"; revisit if that proves insufficient.

## Future possibilities

- Cross-language conformance tests that hit a shared fixture IdP +
  service and assert each SDK's rotation behaviour is identical
  (single retry, single-flight refresh under concurrent triggers,
  safety gate on non-idempotent methods).
- A capability flag exposing whether rotation is wired so consumers
  can branch on it at wire time when the deployed token source is
  static vs rotating.
- Schema annotation for methods that should never rotate (e.g.
  `option (pinguteca.auth.no_rotation) = true` for the IdP's own
  token endpoint). Out of scope until needed.
- Integration with proactive refresh strategies (refresh-token grant,
  background refresh ahead of expiry). Today the SDK refreshes
  reactively on 401; proactive refresh is a token-source concern
  rather than a rotation-interceptor concern.
