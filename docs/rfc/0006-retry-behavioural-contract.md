# RFC 0006: Retry behavioural contract

- Status: Accepted
- Date: 2026-05-11
- Affects: every `sdk-core-*` repo's retry interceptor.
- Depends on: RFC 0002 (layered SDK architecture).

## Summary

Pin the retry algorithm, defaults, and safety contract that every
SDK must implement. The first SDK (Go) shipped these as a local
ADR; the second SDK (.NET) is now adopting the same shape. Without
a written cross-SDK contract, a third SDK author would re-derive
the choice and may pick differently, breaking the "identical
behaviour across SDKs" principle from RFC 0002.

## Motivation

Retry is a Must feature. The user-visible behaviour - how long the
caller waits, how many attempts the server sees, when retries are
skipped for safety - must be identical regardless of which SDK the
caller imports. The values are not arbitrary: they come from
public references (AWS builders' library on backoff with jitter,
gRPC retry-throttling proposal, the canonical RetryInfo detail in
`google.rpc`). Pinning them once avoids per-SDK drift.

## Guide-level explanation

### Two jitter strategies

- **Full jitter (default).** `delay = MinDelay + rand(0, max(0, min(MaxDelay, ceiling) - MinDelay))`,
  where `ceiling` grows by `Multiplier` each retry. The classic AWS
  scheme. Allows zero-wait retries when `MinDelay = 0`, which
  de-synchronises retry storms most aggressively.
- **Decorrelated jitter (opt-in).** `delay = BaseDelay + rand(0, max(0, min(MaxDelay, prev * DecorrelationFactor) - BaseDelay))`.
  Bounds the next delay relative to the previous one rather than to
  an attempt counter. Useful under sustained load where the attempt
  counter loses meaning. Ignores `MinDelay`.

Both schemes outperform proportional jitter at desynchronising
retry storms.

### Defaults

| Field                  | Value                                              |
|------------------------|----------------------------------------------------|
| MaxAttempts            | 4 (including the first call)                       |
| BaseDelay / Initial    | 100 ms                                             |
| MaxDelay / Max         | 30 s                                               |
| Multiplier             | 2.0                                                |
| DecorrelationFactor    | 3.0                                                |
| MinDelay               | 0 (full jitter only)                               |
| Strategy               | Full                                               |
| HonorRetryAfter        | true                                               |
| AllowNonIdempotent     | false                                              |
| Retryable codes        | Unavailable, ResourceExhausted, Aborted, DeadlineExceeded |

### Retryable status set

The default predicate retries exactly the four codes above. They
are the gRPC / Connect status codes that almost always indicate
transient failure on a well-behaved server:

- **Unavailable** - the server is briefly unreachable or refusing
  new work.
- **ResourceExhausted** - quota or rate limit; retry once the
  budget refills.
- **Aborted** - optimistic-concurrency conflict; retry will see
  fresh state.
- **DeadlineExceeded** - the caller's deadline elapsed (often a
  transient slow path).

Other codes are not retried by default. Callers can supply a
custom predicate to broaden or narrow the set.

### Server-supplied retry hint

When the server returns a `retry-after` header (textual seconds) or
a structured `google.rpc.RetryInfo` detail in the trailers, the
interceptor uses that delay instead of the locally-computed
backoff. `HonorRetryAfter = false` is the opt-out.

### Idempotency safety gate

Default `AllowNonIdempotent = false`. When false, retry is **skipped
entirely** for methods the schema does not declare safe (i.e. lack
the `idempotency_level` option set to `IDEMPOTENT` or
`NO_SIDE_EFFECTS`). The schema author opts a method into retry by
adding the annotation. Caller can flip the gate off when paired
with the idempotency-key interceptor and a server that deduplicates
by key.

The gate prevents the dangerous case (retrying a `CreateOrder` RPC
on a transient failure and double-charging) by default.

### Composition with breaker, idempotency, auth

Same as RFC 0002:

```
outermost -> innermost
OTel  ->  Breaker  ->  Idempotency  ->  Retry  ->  Auth
```

Breaker before retry: short-circuited calls do not consume retry
budget. Idempotency before retry: the key is generated once on the
first attempt and replayed on every retry attempt. Auth innermost:
each retry attempt re-runs the auth interceptor.

### Random source

The jitter draw uses cryptographically-secure randomness
(`crypto/rand` in Go, `RandomNumberGenerator` in .NET, the language
equivalent elsewhere). Aligns with the SDK's FIPS-compliance default
and removes a class of weak-PRNG vulnerabilities.

## Reference-level explanation

### Computed delay, full jitter

```
ceiling[0] = BaseDelay
ceiling[N] = min(MaxDelay, ceiling[N-1] * Multiplier)
upper      = min(MaxDelay, ceiling[attempt])
delay      = MinDelay + rand(0, max(0, upper - MinDelay))
```

`rand(0, x)` is a uniform draw in `[0, x)`. The `ceiling` value is
not the delay; it is the maximum of the random draw for that
attempt. With `MinDelay = 0` the formula degenerates to the
classic AWS recipe `rand(0, min(MaxDelay, ceiling[attempt]))`.

### Computed delay, decorrelated jitter

```
prev[0] = BaseDelay
upper   = min(MaxDelay, prev * DecorrelationFactor)
delay   = BaseDelay + rand(0, max(0, upper - BaseDelay))
prev    = delay
```

`BaseDelay` is both the initial state and the floor of every draw.
`MinDelay` is not used.

### Idempotency safety gate per language

The gate requires the SDK to read the proto `idempotency_level`
option at runtime. Coverage varies by language:

| Language | Schema-level access at runtime                     | Gate enforcement              |
|----------|----------------------------------------------------|-------------------------------|
| Go       | Connect-Go exposes `req.Spec().IdempotencyLevel`   | Default-enforced              |
| TS/Node  | connect-es exposes `MethodInfo.idempotency`         | Default-enforced              |
| Swift    | connect-swift exposes method metadata              | Default-enforced              |
| Kotlin   | connect-kotlin exposes method metadata             | Default-enforced              |
| Dart     | connect-dart exposes method metadata               | Default-enforced              |
| Python   | connect-python exposes method metadata             | Default-enforced              |
| Java     | gRPC-Java; no schema metadata at runtime           | Caller predicate or opt-out   |
| .NET     | gRPC-Net; no schema metadata at runtime            | Caller predicate or opt-out   |
| Rust     | tonic; no schema metadata at runtime               | Caller predicate or opt-out   |

For languages without runtime schema metadata, the SDK exposes an
`IsIdempotent(string method) -> bool` (or equivalent) hook the
caller fills in. When the hook is null, the SDK defaults to
`AllowNonIdempotent = true` for those languages only, documents the
divergence in the README, and recommends consumers wire the hook.

A future evolution is a custom protoc/buf plugin that emits an
attribute or registry per method so the gate can default-enforce
in every language. Out of scope for this RFC.

### Server retry hint precedence

When both `retry-after` and `google.rpc.RetryInfo` are present, the
SDK prefers `RetryInfo` because it is structured and the spec
designates it for cross-protocol use. Plain `retry-after` is the
fallback. The caller-side cap (`MaxDelay`) is not applied to a
server-supplied hint; if the server says wait 60 s, the SDK waits
60 s even if `MaxDelay` is 30 s. Rationale: the server speaks with
more authority about its own readiness than the client's local
ceiling.

### Composition guarantees

- An attempt that fails with `Unavailable` after the breaker
  short-circuited never reaches the retry interceptor; retries do
  not feed the breaker's failure window.
- The idempotency key is set once on the first attempt and is the
  same on every retry, so the server deduplicates correctly when
  the idempotency-key interceptor is wired.
- Auth runs inside retry, so a token that expired between attempts
  is refreshed by the auth interceptor before the next network
  call.

## Drawbacks

- The default `Retryable = {Unavailable, ResourceExhausted, Aborted, DeadlineExceeded}`
  occasionally surprises authors who expected `Internal` or
  `Unknown` to retry. Documented as deliberate: retrying those
  codes blindly can amplify a bug.
- Languages without runtime schema metadata diverge from the
  default-safe gate. We accept the divergence and document it.
- The decision to ignore `MaxDelay` for server-supplied hints
  means a misconfigured server can stall a client beyond the
  client's nominal cap. Acceptable because the alternative
  (clamping the server hint) introduces a per-call asymmetry that
  is worse to debug.

## Rationale and alternatives

- **Single strategy (full only).** Simpler. Rejected: high-traffic
  callers benefit from decorrelated jitter under sustained load and
  removing the option means they fork the SDK.
- **Exponential backoff without jitter.** Rejected: thundering-herd
  is well-documented; the cost of adding jitter is one random draw.
- **Different defaults per language.** Rejected by RFC 0002's
  identical-behaviour clause.
- **Clamp server retry hints to `MaxDelay`.** Considered. Rejected
  because debugging a "why did my client retry after 4 s when the
  server said 60 s" is harder than the surprise of waiting longer
  than `MaxDelay` once.
- **Default `AllowNonIdempotent = true` everywhere.** Rejected:
  double-charge risk on transient `CreateOrder` failures is too
  large for an opt-out default in languages where we can enforce
  the gate.

## Prior art

- AWS builders' library, "Timeouts, retries, and backoff with
  jitter":
  https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- gRPC retry policy proposal:
  https://github.com/grpc/proposal/blob/master/A6-client-retries.md
- google.rpc RetryInfo:
  https://github.com/googleapis/googleapis/blob/master/google/rpc/error_details.proto
- Connect protocol error model:
  https://connectrpc.com/docs/protocol#error-codes
- sdk-core-go/docs/adr/0001 (RNG and jitter) and
  sdk-core-go/retry: implementation reference for Go.

## Unresolved questions

- A custom buf/protoc plugin that emits idempotency metadata as a
  runtime attribute per language. Removes the per-language gate
  divergence. Worth its own RFC once a second language hits the
  problem.
- Per-method retry budgets (gRPC `retry_throttling`). Today's
  contract is per-call, with no global budget. Listed in
  RFC 0002's `Revisit when` for `presets`.
- Whether streaming RPCs should ever support a retry-on-connect
  step (open the stream, fail before the first message, retry the
  open). Today every SDK passes streaming through untouched.

## Future possibilities

- Per-language conformance tests that hit a shared fixture server
  and assert identical attempt counts and delays for the same
  configuration. Catches drift before release.
- A capability flag exposing whether the idempotency safety gate
  is default-enforced for this SDK, so consumers can branch on it
  at wire time.
- Retry-budget telemetry (attempts-to-success ratio) surfaced via
  the OTel companion.
