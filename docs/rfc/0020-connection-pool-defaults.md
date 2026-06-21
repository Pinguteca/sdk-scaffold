# RFC 0020: Connection pool defaults

- Status: Accepted
- Date: 2026-06-21
- Affects: every `sdk-core-*` repo's transport-layer connection pool
  (Layer 2). Companion-layer transports (mtls, caching, hedging)
  consume the resulting pool transport unchanged.
- Depends on: RFC 0002 (layered architecture), RFC 0014 (mTLS
  helper) for the TLS config consumer pattern.

## Summary

Pin a single set of HTTP connection-pool defaults across every SDK
so behaviour is predictable regardless of language. Defaults target
typical service-to-service RPC workloads (steady traffic, dozens of
in-flight calls, mostly HTTP/2). Consumers override per-knob
through a typed `Config` exposed in each language's transport-layer
package. Hot reload, dynamic resizing, and pool-per-host policy
plug-ins are out of v1 scope.

## Motivation

Without a pinned baseline each SDK inherits its runtime's
defaults. Those defaults vary widely (Go stdlib caps idle
keep-alive at 2 per host, .NET defaults to 0 for max connections
per server meaning unlimited, Dart's `dart:io` inherits OS limits).
Consumers do not expect "the same call costs 50 ms more in Go than
in .NET because keep-alive thrashes." A single contract removes
that class of surprise and lets resilience presets (RFC 0008)
reason about a known pool capacity.

## Decision

Every SDK exposes a transport-layer `pool` package (or equivalent)
with a typed `Config` struct and a constructor that returns the
language's native HTTP client/transport type. The constructor
validates every cap and duration is non-negative and surfaces
typed errors when not.

### Default values

| Knob | Default | Rationale |
|---|---|---|
| MaxIdleConns (total) | 100 | Caps memory growth under burst load |
| MaxIdleConnsPerHost | 10 | Keeps warm pool for the common single-upstream case without starving multi-host clients |
| MaxConnsPerHost | 0 (unbounded) | Resilience presets and consumer-side semaphores handle concurrency caps; pool does not |
| IdleConnTimeout | 2 minutes | Survives normal RPC idle gaps without holding connections through long idle windows |
| TLSHandshakeTimeout | 10 seconds | Bounds the handshake on a partitioned network |
| ExpectContinueTimeout | 1 second | Standard for `Expect: 100-continue` interplay |
| ForceAttemptHTTP2 | true | HTTP/2 first when ALPN agrees; falls back automatically |
| DisableKeepAlives | false | Reuse is the point |
| DisableCompression | false | Transport-layer gzip remains on unless a compression interceptor takes over |

### Config surface

Each language exposes the same logical knobs through a typed
`Config` struct. Field names track the canonical names in the
table above; language-idiomatic casing applies (`MaxIdleConns`,
`max_idle_conns`, `maxIdleConns`). Where the runtime exposes a
union of the knobs under a different name, the SDK's `Config`
field name is the contract and the runtime name is an
implementation detail.

The constructor accepts an optional TLS config (typically supplied
by the mTLS helper from RFC 0014) and applies it before returning.

### Validation

- Negative cap or duration: reject at construction with a typed
  error wrapping a `ErrInvalidConfig` sentinel.
- Zero on `MaxConnsPerHost`, `MaxIdleConns`, `ResponseHeaderTimeout`:
  means unbounded for that knob.

## Drawbacks

- The defaults will not be optimal for every workload. Consumers
  with bursty fan-out, very long-poll, or extreme low-latency
  targets will need to tune.
- Pinning a `MaxIdleConnsPerHost` above the stdlib default (Go: 2)
  raises minimum steady-state memory.

## Unresolved

- Pool-per-host policy (different caps for different upstreams) is
  deferred. Most consumers run with a single primary upstream and
  the per-host knob is sufficient.
- Whether to expose connection lifetime ceilings
  (`max-connection-age`) is deferred to the resilience-preset
  layer where it intersects with circuit-breaker reset windows.

