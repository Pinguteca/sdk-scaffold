# RFC 0017: OAuth grant flows

- Status: Accepted
- Date: 2026-06-07
- Affects: every `sdk-core-*-oauth` companion package (the L3 OAuth
  module sitting beside `sdk-core-*`).
- Depends on: RFC 0002 (layered architecture) for L3 placement,
  RFC 0004 (companion module naming), RFC 0007 (random source
  policy) for verifier and state generation, RFC 0012 (token
  rotation) for the `RotatingTokenSource` contract, RFC 0014 (mTLS
  helper) for the underlying client-cert plumbing.

## Summary

Pin the OAuth 2.0 surface every SDK ships in its OAuth companion:
which grants are in scope, the PKCE mode, the OIDC discovery shape,
the authorization-code flow, mTLS client authentication at the
token endpoint (RFC 8705), and the error model. The Dart companion
(`sdk_core_dart_oauth`) shipped these first; this RFC promotes its
de-facto shape into a contract so the .NET, Go, and future SDKs do
not drift.

## Motivation

OAuth 2.0 is an underspecified family. Two SDKs can each claim
"client credentials support" and disagree on whether the secret
goes in the Authorization header or the form body, whether the
token cache exposes invalidation, and whether PKCE is enforced or
optional on confidential clients. The same is true for
authorization code, OIDC discovery, and mTLS binding.

The first SDK to ship a grant flow defines the consumer-visible
shape by accident: option names, refresh behaviour, error type,
clock-skew tolerance. Without a pinned contract, the second SDK
either copies the accident or invents a new shape, and consumers
porting between languages discover the surface differs in subtle
ways at runtime.

Three questions need cross-SDK answers:

1. Which grants are in scope and which are explicitly excluded.
2. For each in-scope grant, what is the contract: required inputs,
   transport, token-source shape, error model.
3. Which OAuth 2.0 / 2.1 hardenings are mandatory rather than
   optional (PKCE, state, exact redirect-URI match, HTTPS-only).

## Guide-level explanation

### In-scope grants

Every `sdk-core-*-oauth` package ships exactly these grants:

- **client_credentials** (RFC 6749 §4.4) for service-to-service
  callers with their own credentials.
- **authorization_code with PKCE** (RFC 6749 §4.1 + RFC 7636) for
  interactive callers acting on behalf of a human.

Optional add-on:

- **mTLS client authentication** at the token endpoint (RFC 8705
  §2), composable with both grants above.

### Out of scope

The following are explicitly excluded from the companion package.
A future RFC may add any of them; do not add them by accident:

- **password / resource_owner_password_credentials** (RFC 6749 §4.3,
  deprecated by OAuth 2.0 Security BCP).
- **implicit** (RFC 6749 §4.2, deprecated by OAuth 2.1).
- **device_code** (RFC 8628). Requires a separate UX surface and a
  polling loop; warrants its own RFC if needed.
- **token exchange** (RFC 8693). Same reason.
- **private_key_jwt / client_assertion** (RFC 7521). Defer until a
  consumer needs it; mTLS covers the equivalent threat model.
- **JWT bearer assertions** (RFC 7523).
- **refresh_token as a standalone entry point**. Refresh is internal
  to `AuthorizationCodeTokenSource`; consumers do not call it
  directly.

### PKCE is S256-only and mandatory

Every authorization code flow uses PKCE (RFC 7636) with
`code_challenge_method = S256`. The `plain` method is forbidden,
per OAuth 2.1 BCP §2.1.1. PKCE applies even when the client is
confidential.

The verifier is a 43-character base64url-no-pad string sampled from
the cross-SDK crypto RNG (RFC 0007). The challenge is
`base64url-no-pad(SHA-256(verifier))`. SHA-256 is the only FIPS
140-3 approved primitive used here.

### OIDC discovery

Discovery follows RFC 8414. The package exposes a single function:

```
discoverOidc(config) -> OidcMetadata
```

`config` carries the issuer URL and the HTTP client. The function
fetches `<issuer>/.well-known/openid-configuration`, validates that
the response `issuer` field exactly equals the requested issuer
(RFC 8414 §3.3), and returns the parsed metadata.

Discovery is **uncached at the SDK layer**. Consumers wrap with
their own cache if needed; the SDK does not own the cache because
TTL policy varies (browser vs. service, short-lived vs. always-on,
fail-open vs. fail-closed).

HTTPS-only. The package rejects plaintext issuers at the function
boundary.

### Authorization code flow

The companion exposes three pieces:

- `AuthorizationCodeConfig`: client_id, optional client_secret,
  redirect_uri, scopes, OIDC metadata (or token + auth endpoints
  directly), HTTP client.
- `AuthorizationCodeFlow`: stateless helper with
  `buildAuthorizationUrl(state, pkce)`, `exchange(code, verifier)`,
  `refresh(refreshToken)`. Two factories: `fromIssuer(issuer)`
  (runs discovery inline) and direct construction.
- `AuthorizationCodeTokenSource`: implements `RotatingTokenSource`
  (RFC 0012). Caches the access token until expiry, refreshes via
  the refresh token, surfaces `Invalidate()` for cache-busting on
  401.

State parameter is mandatory on every authorization URL.
Consumers supply it; the SDK does not generate it because state
binds to consumer-side session state. The SDK rejects empty state
at `buildAuthorizationUrl`.

Redirect URI is exact-match per RFC 6749 §3.1.2.2. The SDK echoes
back whatever the consumer passes; servers enforce the match.

Refresh tokens are persisted in memory only. Each SDK exposes a
hook for consumers to plug in their own storage (encrypted disk,
keychain, secret manager); the default is in-process and dies with
the source instance.

### Client authentication modes

A single `ClientAuthMode` enum (or language idiom) per SDK:

- **basic**: HTTP Basic header per RFC 6749 §2.3.1. Default when a
  client_secret is configured and mTLS is not.
- **formPost**: client_id and client_secret in the body per RFC
  6749 §2.3.1 fallback. Used when the IdP rejects Basic.
- **mtls**: no secret; client cert presented at the TLS layer
  authenticates the request. Selecting this mode without an
  `MtlsConfig` is a configuration error caught at construction.

`private_key_jwt` is intentionally absent (see Out of scope).

### mTLS token endpoint (RFC 8705)

The companion accepts an `MtlsConfig` declaring the client
certificate, private key, and trust chain. When supplied, the HTTP
client used for token-endpoint calls presents the client cert
during the TLS handshake. The server binds the issued access token
to the cert thumbprint; subsequent resource-server calls must
present the same cert.

`MtlsConfig` shape is the cross-SDK contract pinned in RFC 0014;
the OAuth companion consumes it without reshaping. Platform
restrictions (web cannot present client certs from JS) surface as a
construction-time error rather than a runtime failure mid-flow.

### Error model

A single OAuth exception type per SDK (`OAuthException` /
`OAuthError` / language idiom). Carries:

- The RFC 6749 §5.2 error code as a string (e.g.
  `invalid_request`, `invalid_client`, `invalid_grant`,
  `unauthorized_client`, `unsupported_grant_type`, `invalid_scope`).
- The optional human-readable `error_description`.
- The optional `error_uri`.
- HTTP status code of the failing token request.
- Underlying transport exception when the failure was network-level.

Discovery and PKCE validation errors raise the same type with a
distinct error code (`invalid_issuer`, `invalid_verifier`). The
SDK does NOT collapse these into `SdkError`; OAuth has its own
boundary because consumers branch on `error` to decide whether the
fault is recoverable (e.g. `invalid_grant` means re-auth, not retry).

### `TokenResponse` shape

The parsed token endpoint response per RFC 6749 §5.1, plus the
OIDC `id_token`:

- `access_token` (required).
- `token_type` (required; expected `Bearer`).
- `expires_in` (seconds, optional but populated when known).
- `refresh_token` (optional).
- `scope` (optional).
- `id_token` (optional; populated for OIDC flows).

The shape is exposed because consumers call `exchange()` /
`refresh()` directly in flows that need the `id_token` (login
flows). The `TokenSource` interface yields the access token only.

## Reference-level details

### Cross-SDK type map

| Contract concept           | Dart                              | .NET                                  | Go                          |
|----------------------------|-----------------------------------|---------------------------------------|-----------------------------|
| Package                    | `sdk_core_dart_oauth`             | `Pinguteca.Sdk.Core.OAuth`            | `pingutecasdkcore.oauth`    |
| Discovery                  | `discoverOidc()`                  | `OidcDiscovery.DiscoverAsync()`       | `oauth.Discover()`          |
| PKCE primitive             | `PkcePair.generate()`             | `PkcePair.Generate()`                 | `oauth.NewPkcePair()`       |
| Authorization code flow    | `AuthorizationCodeFlow`           | `AuthorizationCodeFlow`               | `AuthorizationCodeFlow`     |
| Authorization code source  | `AuthorizationCodeTokenSource`    | `AuthorizationCodeTokenSource`        | `AuthorizationCodeSource`   |
| Client credentials source  | `ClientCredentialsTokenSource`    | `ClientCredentialsTokenSource`        | `ClientCredentialsSource`   |
| Client auth mode           | `ClientAuthMode` enum             | `ClientAuthMode` enum                 | `ClientAuthMode` constants  |
| mTLS config                | `MtlsConfig` (re-exported)        | `MtlsConfig` (re-exported)            | `mtls.Config` (re-exported) |
| OAuth error                | `OAuthException`                  | `OAuthException`                      | `*OAuthError`               |

Names follow each language's idiom. Behaviour is identical across
languages.

### Mandatory inputs vs. defaults

| Field                        | Required | Default if omitted                                  |
|------------------------------|----------|-----------------------------------------------------|
| issuer (discovery)           | yes      | -                                                   |
| client_id                    | yes      | -                                                   |
| client_secret                | no       | absent; selects `mtls` mode unless mode is set      |
| redirect_uri (auth code)     | yes      | -                                                   |
| scopes                       | no       | empty list; server decides                          |
| ClientAuthMode               | no       | `basic` if secret set, else `mtls` if cert set      |
| MtlsConfig                   | no       | none; required only when mode is `mtls`             |
| PKCE                         | yes      | generated by `PkcePair.generate()` if not supplied  |
| state                        | yes      | -                                                   |
| HTTP client                  | yes      | -                                                   |

### Clock and expiry

`access_token` expiry is computed as `now() + expires_in` at the
moment of the token-endpoint response. The cached source treats the
token as expired `30s` before that absolute timestamp to absorb
clock skew. Both `now()` and the skew window come from the cross-
SDK clock abstraction so tests can advance time deterministically.

### Concurrency

`ClientCredentialsTokenSource` and `AuthorizationCodeTokenSource`
serialize refresh under a single-flight guard. N concurrent
`token()` calls during a refresh produce one network call; the
others await the same outcome. Implementation idiom is per-
language (`SemaphoreSlim` in .NET, `singleflight.Group` in Go,
`Future` deduplication in Dart).

### Transport

All token-endpoint and discovery calls use HTTPS. Plain HTTP
issuers are rejected at config construction; loopback HTTP for
development tooling is out of scope for the SDK and lives in the
consumer's HTTP client overrides if needed.

## Drawbacks

Pinning the surface now ossifies decisions before .NET and Go have
written their own implementations. A misread of an RFC in the Dart
impl propagates to the contract.

The exclusion of `private_key_jwt` will force consumers to drop to
a hand-rolled token request if their IdP mandates it. The mTLS
escape hatch covers most cases but not all.

`refresh_token` storage is consumer-owned. SDKs that expected the
companion to ship an encrypted-disk store have to wire their own.

## Unresolved questions

- Whether to ship a `device_code` grant in a follow-up RFC; the
  pull is from CLI consumers, the push-back is that polling logic
  belongs higher than L3.
- Whether to expose token introspection (RFC 7662) and revocation
  (RFC 7009) endpoints. Cheap to add later; no current consumer.
- Whether OIDC `nonce` validation is the SDK's job or the
  consumer's. Current shape: consumer supplies and validates;
  revisit if a Dart consumer reports drift.

## Future work

- Standalone `device_code` companion if CLI consumers ask.
- DPoP (RFC 9449) as an alternative to mTLS binding.
- A hook for refresh-token storage backends (keychain, file,
  secret manager) once a second consumer needs one.
