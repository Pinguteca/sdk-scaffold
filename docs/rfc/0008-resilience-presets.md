# RFC 0008: Resilience presets and mesh coexistence

- Status: Accepted
- Date: 2026-05-14
- Affects: every `sdk-core-*` repo's `presets` companion and the
  interceptor composition order for retry, breaker, idempotency, auth.
- Depends on: RFC 0002 (layered architecture), RFC 0006 (retry
  behavioural contract).

## Summary

Pin two canned interceptor compositions every SDK ships: `Standalone`
and `Mesh`. Define the composition order from outermost to innermost
(observability, breaker, idempotency, retry, auth) and how each layer
cooperates with the next. Pin the retry-amplification-avoidance
contract so the same SDK is safe to wire inside or outside a service
mesh. The first SDK (Go) shipped these as a local ADR; pinning them
across SDKs prevents the next implementer from picking a different
order and breaking cross-language behaviour parity.

## Motivation

The SDK serves two consumer populations with opposite needs. Mesh-
resident services (sidecars, eBPF redirectors) already have circuit
breakers, retries, and observability at the data plane; another layer
of those in the SDK amplifies failures
(`total_attempts = mesh_retries * sdk_retries`). External consumers
(mobile, CLIs, third-party backends) have none of those and need the
SDK to provide them.

Without a named contract, the first user who writes a presets list
becomes the default for every later SDK. Codifying the two
compositions and their order keeps every SDK aligned on what
"standalone" and "mesh" mean.

## Guide-level explanation

### Two presets, named by deployment topology

- **Standalone.** The SDK runs without a mesh in the request path
  (mobile, CLI, edge worker, external service caller, bare-VM
  backend). Full resilience stack: observability + breaker +
  idempotency + retry + auth.
- **Mesh.** The SDK runs inside a service mesh (Istio, Linkerd,
  Consul, Cilium, etc.). The mesh already does retries and circuit
  breaking; the SDK adds only what the mesh cannot do for it.
  Composition: observability + idempotency + auth. No breaker, no
  retry.

Naming follows the topology, not whether a sidecar is present. A
proxyless eBPF mesh is still "mesh"; a bare-VM service with no mesh
is still "standalone". The choice keys on whether the surrounding
infrastructure does retry and CB, not on the proxy shape.

### Composition order (both presets)

```
outermost                                            innermost
OTel  ->  Breaker  ->  Idempotency  ->  Retry  ->  Auth
```

Mesh skips Breaker and Retry; OTel, Idempotency, and Auth keep their
positions.

Each adjacency is intentional:

- **OTel outermost.** Every other interceptor's work appears under one
  span. Otherwise retries and breaker openings live in separate
  traces.
- **Breaker before Retry.** Short-circuited calls do not consume
  retry budget or generate idempotency keys. The breaker's open-state
  error carries a structured retry-after detail; the retry layer
  reads it and waits the suggested cooldown, so retry composes with
  breaker without explicit coupling.
- **Idempotency before Retry.** The idempotency key is generated once
  on the first attempt and the same key replays on every retry
  because retry reuses the same request object. Without this order
  the server cannot deduplicate.
- **Auth innermost.** Each retry attempt re-runs auth, which means a
  token that expired between attempts gets refreshed before the next
  network call.

### Retry safety gate

The retry interceptor (RFC 0006) defaults to `AllowNonIdempotent =
false`. When false, retry is skipped entirely for methods whose
schema does not declare them safe. The schema author opts a method
into retry by adding `idempotency_level = IDEMPOTENT` (or
`NO_SIDE_EFFECTS`) on the proto. Callers who pair retry with the
idempotency-key interceptor and a server that deduplicates may flip
the gate off.

Per RFC 0006, gRPC-fallback SDKs without schema metadata at runtime
(.NET, Java, Rust) degrade to caller-supplied predicate or opt-out;
the preset documentation in those SDKs flags the divergence.

### Breaker error model

When the breaker short-circuits, it returns the protocol's
"Unavailable" code with a structured retry-after detail
(`google.rpc.RetryInfo` for Connect/gRPC). The retry layer reads the
hint and waits without needing breaker-specific knowledge.

Per-host breakers are out of scope. A consumer with multiple clients
to different services wires one breaker per client. Per-host sharding
becomes a separate companion if a real consumer needs it.

## Reference-level explanation

### Preset surface

Every SDK exposes two functions on its `presets` companion:

| Function          | Composition                                       |
|-------------------|---------------------------------------------------|
| `Standalone(...)` | OTel, Breaker, Idempotency, Retry, Auth           |
| `Mesh(...)`       | OTel, Idempotency, Auth                           |

Both take the configuration each layer needs (retry options, auth
source, etc.) and return an interceptor chain in the canonical order.

### What is NOT in either preset

- **PKCE / Authorization Code.** User-interactive flows are scope of
  a different consumer pattern. Wired separately.
- **Hedged requests.** Nice-tier and opt-in (RFC 0002). Available as
  a separate L3 companion; not in either preset.
- **mTLS PEM / PKCS#12.** Transport-layer concern below the
  interceptor chain. Wired on the underlying client.
- **Compression beyond gzip.** Separate companion; orthogonal to
  resilience.

A consumer whose mix does not match either preset (e.g. internal
service on bare VMs with no mesh and no breaker need) handcrafts the
chain from L2 + L3 modules. The preset is a convenience, not a
constraint.

### Mesh detection

Not done. Auto-detection (sidecar port probing, envvar sniffing) is
brittle and silent failures are worse than explicit choice. The
preset name forces the choice at wire time.

### Breaker behaviour expectations

- **Per-client instance.** The breaker tracks failures for the
  client it is wired into. Multiple clients = multiple breakers.
- **Open state ships a retry-after hint.** The error returned to the
  caller (or the retry layer) carries a structured field with the
  remaining open duration.
- **Half-open probe.** Standard half-open behaviour: after the open
  window expires, one probe is allowed through. Success closes the
  breaker; failure reopens for another window.
- **Default thresholds**: 50% failure rate over a 30-second window
  with at least 20 sample calls. Open duration starts at 5 seconds.
  Per-SDK tuning is allowed but the defaults are aligned.

### Retry-amplification rule

Mesh + SDK retry is forbidden by default. The Mesh preset skips
retry to avoid `mesh_retries * sdk_retries`. Consumers who
deliberately want both wire it themselves with explicit knowledge.

Mesh + SDK breaker is forbidden by default for the same reason.

### Per-language ergonomics

The preset surface is identical in shape; the call sites differ per
language idiom:

- **Go**: `presets.Standalone(connect.WithInterceptors(...), retry.Config{...}, ...)`
- **TS**: `presets.standalone({ retry, auth, otel })` returning an
  array of interceptors.
- **.NET**: `Presets.Standalone(new() { Retry = ..., Auth = ... })`
  returning a chain of `ClientInterceptor`.
- **Java/Kotlin**: builder pattern returning an interceptor list.
- **Python**: dict-config returning a list.
- **Rust**: tower layer stack.
- **Dart**: function returning a list of interceptors.

Naming matches each ecosystem's casing convention; the contract is
the composition and order, not the API shape.

## Drawbacks

- Two preset names is a small learning surface, and the boundary
  between them is judgement, not mechanism. A consumer on bare VMs
  may not fit either name cleanly. The doc comment on each preset
  has to be explicit about what it does and does not include.
- The breaker defaults are picked, not measured against any specific
  service. A future telemetry pass may move the numbers.
- Per-host breakers are deferred. The current shape is per-client,
  which matches the typical case (one client per service) but loses
  granularity for clients fanning out to multiple hosts.

## Rationale and alternatives

- **Single preset.** Reject. The two consumer populations are real;
  one preset would either over-resilient mesh consumers or under-
  resilient external consumers.
- **`presets.Bare`** as a third option (just OTel, no resilience).
  Considered. Deferred until a consumer asks. Today the answer is
  "handcraft your own chain", and that path stays available.
- **Auto-detect mesh.** Reject. Sniffing for sidecars is fragile and
  silent no-op hides deploy bugs.
- **Different composition order across SDKs.** Reject. Cross-SDK
  parity is the whole point of RFC 0002.
- **Per-host breakers as the default.** Reject for now. Adds runtime
  introspection cost and most consumers run one client per service.
  Revisit if a real consumer hits the limit.

## Prior art

- Envoy circuit breaking:
  https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking
- Linkerd retries and CB:
  https://linkerd.io/2/features/retries-and-timeouts/
- gRPC retry policy and throttling:
  https://github.com/grpc/proposal/blob/master/A6-client-retries.md
- Microsoft Azure Architecture, Circuit Breaker pattern:
  https://learn.microsoft.com/azure/architecture/patterns/circuit-breaker
- sdk-core-go/docs/adr/0002 (resilience and mesh coexistence) -
  Go-side implementation reference.

## Unresolved questions

- A `retry_throttling`-style client budget (stop retrying when the
  retry-to-success ratio exceeds a threshold). Not implemented today.
  Worth a follow-up once consumers report amplification storms.
- Per-host breakers as a separate companion (`breaker/perhost` or
  equivalent). Wait for a real ask.
- Whether the Mesh preset should keep a *very narrow* breaker
  (e.g. for retry-after honouring) even though the data plane has
  one. Today's answer is no; revisit if a mesh ships without per-
  client CB.
- A `presets.Bare` (interceptors with no defaults) for consumers
  whose mix is too irregular for either named preset.

## Future possibilities

- Cross-language conformance tests asserting both presets produce
  the same observable behaviour against a shared fixture server.
- Telemetry-driven default tuning: collect breaker open/close ratios
  across deployed SDKs and adjust defaults at the RFC level.
- A capability flag exposing which preset was wired so consumers
  can branch at wire time.
- Optional `Mesh` variant that keeps breaker enabled for callers
  whose mesh declares "no client-side CB" explicitly.
