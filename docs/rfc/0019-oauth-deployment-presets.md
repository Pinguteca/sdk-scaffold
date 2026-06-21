# RFC 0019: OAuth deployment presets

- Status: Accepted
- Date: 2026-06-21
- Affects: every `sdk-core-*-oauth` companion package.
- Depends on: RFC 0008 (resilience presets) for the
  Standalone-vs-Mesh precedent, RFC 0012 (token rotation) for the
  `RotatingTokenSource` contract, RFC 0014 (mTLS helper), RFC 0017
  (OAuth grant flows) for the in-SDK surface being preset over.

## Summary

Pin two named deployment modes for OAuth: **Direct** (the SDK
acquires, refreshes, and hardens tokens itself) and **Broker** (an
upstream component fronts the IdP and hands the SDK an
already-bound token). Both modes share the same `TokenSource`
contract. The mode determines which features the SDK engages and
which it delegates. Same SDK binary, different wiring. The Direct
vs Broker split mirrors the Standalone vs Mesh resilience presets
pinned in RFC 0008.

## Motivation

The OAuth surface from RFC 0017 assumes the SDK owns the full
lifecycle: discovery, grant flow, refresh, optional mTLS binding.
That is correct when the consumer ships standalone (mobile, CLI,
browser, partner integrator with no broker in front of them).

It is wrong when the consumer runs behind a broker IdP. A broker
already centralises:

- Token acquisition for service-to-service callers, often via
  workload identity (SPIFFE, cloud metadata, sidecar).
- Refresh, caching, and per-method scope minting.
- Hardening features like DPoP (RFC 9449) and mTLS token binding
  (RFC 8705): the broker mints the bound token, the SDK only
  forwards it.
- Introspection (RFC 7662) and revocation (RFC 7009) as an admin
  surface, not a per-call concern.

Today consumers behind a broker either bypass the SDK's OAuth
companion entirely (losing the typed error surface and rotation
guarantees) or wire it as if there were no broker (duplicating
work and signing material). Neither is good. RFC 0008 already
solved the equivalent problem for transport concerns (retry,
breaker, hedge) by naming Standalone and Mesh presets. This RFC
applies the same idea to OAuth.

## Guide-level explanation

### The two modes

- **Direct.** No broker between the SDK and the IdP. The SDK runs
  the grant flow, holds refresh tokens, mints DPoP proofs, and
  presents mTLS client certificates at the token endpoint.
- **Broker.** A broker IdP sits between the SDK and the IdP. The
  SDK does not own the grant flow. It fetches an already-acquired
  (and possibly already-bound) token from a broker-supplied
  endpoint and forwards it on outgoing calls. Hardening features
  (DPoP, mTLS binding) are owned upstream.

Mode is not a runtime enum on a shared options object. Mode is
the choice of which `TokenSource` implementation the consumer
wires. The contract below pins what each implementation must
and must not do.

### What stays constant across modes

- `RotatingTokenSource` contract (RFC 0012): consumers always
  call `Token()` / `Invalidate()` and get the same shape back.
- `OAuthException` (RFC 0017): same error type and code surface.
- Bearer-token attachment to outgoing calls via the existing
  `AuthInterceptor`. The interceptor does not branch on mode.
- The Standalone / Mesh resilience preset axis from RFC 0008.
  Deployment mode is orthogonal to resilience mode. A consumer
  picks one of each (Standalone+Direct, Standalone+Broker,
  Mesh+Direct, Mesh+Broker are all valid).

### What changes per mode

| Concern                        | Direct                              | Broker                                              |
|--------------------------------|-------------------------------------|-----------------------------------------------------|
| Token acquisition              | SDK calls token endpoint            | SDK reads token from broker contract                |
| OIDC discovery                 | SDK fetches `.well-known`           | Broker caches, SDK skips                            |
| Authorization code + PKCE      | SDK runs the full state machine     | Broker drives, SDK awaits the result                |
| DPoP (RFC 9449)                | SDK mints proof per request         | Broker mints, SDK forwards bound token              |
| mTLS at token endpoint         | SDK presents client cert            | Broker terminates, SDK gets the bound access token  |
| Refresh                        | SDK schedules refresh from `exp`    | Broker rotates, SDK re-fetches when prompted        |
| Token introspection            | SDK calls `/introspect` if wired    | Broker exposes, SDK does not                        |
| Token revocation               | SDK calls `/revoke` on logout       | Broker admin surface, SDK does not                  |
| Device code (RFC 8628)         | SDK polls token endpoint            | Broker polls, SDK awaits notification               |

Hedged requests, retry, circuit breaker, and timeout are RFC 0008
concerns and do not appear here.

### Broker contract

The companion exposes a small abstract base for Broker-mode token
sources. Concrete subclasses pick the transport between the SDK
and the broker. The contract pins the shape, not the wire.

Two transport shapes are blessed. A third is left to consumers.

1. **Local exchange endpoint.** The broker (typically a sidecar
   or workload-identity agent) exposes a localhost HTTP endpoint.
   The SDK POSTs the target audience or scope and receives a
   token plus an optional binding hint. Used by SPIFFE Workload
   API consumers, cloud workload identity, and most service-mesh
   identity sidecars. The SDK does not assume the endpoint speaks
   any specific protocol family. The concrete subclass owns that.
2. **Header passthrough.** The broker is a reverse proxy in front
   of the consumer. The consumer's incoming request already
   carries a bound token in an `Authorization` header set by the
   broker, and the SDK forwards it on outgoing calls. The SDK
   reads the token from the inbound request context handed to it
   by the consumer's framework.
3. **Consumer-supplied** `BrokerTokenSource` implementation. The
   companion ships the abstract base. The consumer provides the
   transport when neither of the above fits.

A Broker-mode token source MUST NOT:

- Run OIDC discovery.
- Mint DPoP proofs.
- Present mTLS client certificates.
- Talk to the IdP directly.

A Broker-mode token source MUST:

- Implement `RotatingTokenSource` so consumers see the same
  surface as Direct mode.
- Surface broker-side errors as `OAuthException` with a Broker-
  origin code (e.g. `broker_unavailable`, `broker_unauthorised`)
  so consumers can branch on cause without importing
  broker-specific types.

### Mode selection is consumer-side

The companion does not auto-detect mode. Auto-detection would
either probe localhost endpoints at startup (slow, brittle) or
read env vars whose meaning differs by deployment platform.
Consumers wire the mode they know they are in. The SDK enforces
the contract that wiring implies.

### Presets in the ergonomic layer (RFC 0016)

The Layer 1.5 ergonomic wrapper exposes deployment mode and
resilience mode as constructor arguments:

```
SdkClient(resilience: Standalone, oauth: Direct(idp_config))
SdkClient(resilience: Mesh,       oauth: Broker(local_endpoint))
```

L2 callers wire `IRotatingTokenSource` directly and pick the
implementation themselves.

## Reference-level details

### Cross-SDK type map

| Concept                  | Dart                              | .NET                                | Go                          |
|--------------------------|-----------------------------------|-------------------------------------|-----------------------------|
| Direct mode marker       | implicit (Direct sources)         | implicit (Direct sources)           | implicit (Direct sources)   |
| Broker mode base         | `BrokerTokenSource`               | `BrokerTokenSource`                 | `BrokerSource`              |
| Local exchange impl      | `LocalEndpointBrokerTokenSource`  | `LocalEndpointBrokerTokenSource`    | `LocalEndpointBrokerSource` |
| Header passthrough impl  | `HeaderPassthroughTokenSource`    | `HeaderPassthroughTokenSource`      | `HeaderPassthroughSource`   |
| Broker error code root   | `broker_*` prefix on `code`       | `broker_*` prefix on `Code`         | `broker_*` prefix on `Code` |

Names follow each language's idiom. Behaviour is identical.

### Feature ownership table

| Feature           | Mode-gated | Direct ships it? | Broker delegates to upstream? |
|-------------------|------------|------------------|-------------------------------|
| client_credentials| no         | yes              | yes (broker fetches)          |
| authorization_code| yes        | yes              | no (broker drives)            |
| OIDC discovery    | yes        | yes              | no                            |
| PKCE              | yes        | yes              | no                            |
| DPoP              | yes        | yes              | no                            |
| mTLS token bind   | yes        | yes              | no                            |
| device_code       | yes        | yes              | no                            |
| introspection     | yes        | optional         | no                            |
| revocation        | yes        | optional         | no                            |
| TokenSource API   | no         | yes              | yes                           |
| OAuthException    | no         | yes              | yes                           |

### Concurrency and refresh

Both modes serialise refresh under a single-flight guard. In
Direct mode the guard wraps the token-endpoint call. In Broker
mode it wraps the broker-endpoint call. Same semantics, different
upstream.

### Caching policy

Direct sources cache the access token until expiry, with the
30-second skew window from RFC 0017. Broker sources cache for the
shorter of the broker-supplied `expires_in` and 30 seconds. The
broker can rotate tokens out from under the SDK without warning,
and tight caching keeps the SDK aligned. Consumers can widen the
broker cache via configuration when their broker guarantees
longer validity.

### Transport

All Direct-mode endpoints (token, discovery, introspection,
revocation) are HTTPS-only, per RFC 0017. Broker-mode local
exchange endpoints are typically HTTP on loopback. The companion
allows plaintext localhost without ceremony but rejects plaintext
non-loopback at construction.

## Drawbacks

Naming two modes risks consumers picking the wrong one. The
default is no default: the companion does not pre-select, and
wiring a `TokenSource` is a deliberate choice. Documentation
carries that weight.

Broker mode reduces the value the SDK adds for in-broker
consumers. The remaining value is the typed error surface, the
`RotatingTokenSource` contract, and the resilience interceptor
chain. That is still load-bearing.

The `broker_*` error-code prefix opens a vocabulary that may
expand over time. Pinning it now risks bikeshedding later. The
RFC accepts that risk because consumers branching on cause is
more important than perfect taxonomy.

## Unresolved questions

- Whether to ship a third blessed broker transport for SPIFFE
  Workload API specifically. Current shape: covered by the
  `LocalEndpointBrokerTokenSource` base, but a typed SPIFFE
  subclass would save consumers boilerplate.
- Whether Broker mode should expose a hook for consumers to
  observe broker-supplied audit data (e.g. token id, broker
  request id) on every refresh. Not required for correctness.
  Asked for by observability-heavy consumers.
- Whether the Layer 1.5 wrapper accepts deployment mode as part
  of the resilience preset enum or as a separate axis. Current
  shape: separate axis, both selectable.

## Future work

- Typed SPIFFE Workload API broker source if a consumer needs it.
- Automatic broker probing for development environments only,
  gated behind an explicit `Auto` mode selector that is never the
  default.
- Cross-SDK conformance tests for the broker contract once a
  second SDK implements it.
