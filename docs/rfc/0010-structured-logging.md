# RFC 0010: Structured logging

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `logging` Layer 3 companion
  module.
- Depends on: RFC 0002 (layered SDK architecture),
  RFC 0008 (resilience presets) for chain positioning.

## Summary

Pin one cross-SDK shape for how the SDK logs RPC activity: a single
structured record per RPC at completion (the canonical-log + wide-event
pattern), emitted through each language's de-facto structured logger
interface. No per-step debug noise. Attributes follow OTel semantic
conventions so the record joins to OTel spans via `trace.id` and
`span.id`. Ship the interceptor as a **Layer 3 companion module**
(separate package, opt-in by dependency) because the integration
target is each ecosystem's native structured-logger abstraction
(slog, MEL, SLF4J, tracing, swift-log, etc.) and Layer 2 reserves
itself for behaviour the SDK owns end-to-end without ecosystem
coupling. The first SDK (Go) shipped this as a local ADR; pinning it
across SDKs prevents the next implementer from re-deriving the choice
and breaking parity. Without a written contract, a third SDK author
would likely default to per-step debug logs and consumers would see
N log lines per RPC in one language and one wide event in another.

## Motivation

Two questions need a single cross-language answer:

1. **What gets logged per RPC?** Per-step logging ("auth attached",
   "retry attempt 2", "breaker half-open", "response received") produces
   N lines per RPC. At any non-trivial QPS the signal-to-noise ratio
   collapses; investigating a single failed request means filtering
   across many lines that share only a thin correlation ID. The
   canonical-log pattern emits one wide row per request, indexable by
   every attribute the responder needs.
2. **Which logger?** Every language ecosystem has a dominant structured
   logger interface. Mandating a specific implementation would force
   consumers to either adopt it or shim around it. The SDK targets the
   interface, not the implementation, and lets the consumer plug
   whatever handler/backend they prefer.

The constraint shared by all consumer populations: services already
have their own observability stack. The SDK must not mandate a log
backend, but the shape of what it emits should be opinionated enough
to plug into modern wide-event log stores (Honeycomb, Axiom, Datadog
Logs, Elastic, OpenSearch, ClickHouse) without per-consumer remapping.

## Guide-level explanation

### Layer placement

Logging ships as a **Layer 3 companion module**, not in the Layer 2
core package. Per RFC 0002:

- Layer 2 is what the SDK owns end-to-end with identical
  cross-language behaviour and zero third-party dependencies beyond
  the chosen RPC runtime.
- Layer 3 is companion packages whose value is integration with an
  ecosystem-specific abstraction. The SDK pins the contract; the
  consumer plugs the implementation.

Structured logging is the canonical case for Layer 3. Each ecosystem
has a dominant interface (`log/slog` in Go,
`Microsoft.Extensions.Logging.ILogger` in .NET, `org.slf4j.Logger`
in JVM, `tracing` crate macros in Rust, `swift-log` in Swift, etc.).
Targeting one would force consumers to adopt it or shim around it;
targeting each ecosystem's native interface is the whole point of
the companion. Three out of four placement criteria from RFC 0002
push logging out of Layer 2:

- *Does ecosystem integration matter?* Yes (every consumer already
  has a structured logger).
- *Does the behaviour need to be identical across SDKs?* Only at the
  canonical-record shape; the surface plugged into varies by
  language.
- *Does it exist in only some ecosystems?* The pattern is universal,
  but the interfaces are not interchangeable.

A consumer that wants canonical-log emission adds the companion
dependency (`Pinguteca.Sdk.Core.Logging` for .NET, the `logging`
sub-module for Go, etc.) and wires the interceptor into the chain.
Core consumers who do not wire the companion see no log records
from the SDK.

### One record per RPC, at completion

The logging interceptor emits exactly one structured record per RPC,
written when the call completes (success or error). The record carries
every attribute a responder needs:

- RPC identity (`rpc.system`, `rpc.service`, `rpc.method`)
- Timing (`rpc.duration_ms`)
- Status (`rpc.code`, one of the protocol's canonical codes)
- Correlation (`request.id` from configurable header, `trace.id` and
  `span.id` from the active span context when OTel is wired)
- Caller-supplied request and response attributes (via hooks)
- Error message when the call failed
- Redacted headers (opt-in)

No per-step logs. Retry attempts, breaker transitions, token refreshes
are not logged by this interceptor; they appear as span events under
the OTel interceptor when that companion is wired.

### Position in the interceptor chain

Logging sits in the observability layer alongside OTel, outside the
resilience and auth interceptors defined by RFC 0008:

```
outermost                                                          innermost
Logging  ->  OTel  ->  Breaker  ->  Idempotency  ->  Retry  ->  Auth
```

Logging wraps OTel so the canonical record's `rpc.duration_ms` matches
the OTel span's total duration end-to-end including span-creation
overhead. When OTel is not wired, logging sits at the outermost
position alone.

The chain still produces one log record per RPC even when the call
retries internally. The retry interceptor lives inside logging, so all
retries fold into a single canonical record. The `rpc.code` reflects
the final outcome, and `rpc.duration_ms` covers the full wait
including backoff.

### Structured logger interface, not implementation

Each SDK targets its ecosystem's de-facto structured logger
abstraction. The SDK does not bundle a backend, default formatter, or
log destination; the consumer wires those.

| Language | Interface the SDK targets                | Common backends                   |
|----------|------------------------------------------|-----------------------------------|
| Go       | `log/slog` (stdlib, Go 1.21+)            | JSON handler, OTel bridge, custom |
| .NET     | `Microsoft.Extensions.Logging.ILogger`   | Serilog, NLog, console, OTel      |
| TS / Node| `Logger` interface (`debug/info/warn/error` with attrs) | pino, winston, console |
| Java     | `org.slf4j.Logger`                       | Logback, Log4j2, OTel             |
| Kotlin   | `org.slf4j.Logger` or `KLogger`          | Logback, Log4j2, OTel             |
| Python   | `logging.Logger` (stdlib) with `extra={}` | structlog adapter, JSON formatter |
| Rust     | `tracing::Event` macros                  | tracing-subscriber, OTel layer    |
| Dart     | `package:logging`                        | log records to stdout / sink      |
| Swift    | `swift-log` `Logger`                     | console backend, OTel adapter     |

The SDK requires the caller to supply an instance and does not provide
a default. A nil/null logger is a configuration error, not a silent
no-op.

### Default redaction posture

When header logging is enabled, the SDK masks values for a default
list of sensitive headers (case-insensitive match):

- `Authorization`
- `Cookie`
- `Set-Cookie`
- `Proxy-Authorization`
- `X-Api-Key`

Masked values appear as `[REDACTED]` (or the language idiom) so the
header name still indexes for debugging. The redaction list is
extensible per consumer; the defaults cover the obvious cases but do
not pretend to be exhaustive (e.g. `X-Tenant-Token` or vendor-specific
auth headers).

Header logging itself is opt-in (off by default). The headers blob
bloats every record and offers little value once `request.id` is
present.

### Caller hooks for business attributes

Two hook fields let consumers inject business-domain attributes
without forking the interceptor:

- `AddRequestAttrs(ctx, request) -> attrs[]` runs before the call.
  Typical use: `tenant.id`, `actor.id`, `entity.kind`.
- `AddResponseAttrs(ctx, response, error) -> attrs[]` runs after the
  call. Typical use: outcome metadata that depends on the response
  (e.g. `entity.created_id`, `bytes.returned`).

Hook output appends to the canonical record. Hooks must not emit
separate log lines; the contract is one record per RPC.

### Streaming RPCs pass through

The streaming posture is the subject of a future RFC. Today every SDK
passes streaming RPCs through the logging interceptor unchanged
(no record emitted). Per-message logging contradicts the canonical-log
model; whether to emit one record per stream open/close, or one
per message, is deferred.

## Reference-level explanation

### Required attributes (OTel semantic conventions)

Every record carries these attributes when the data is available:

| Attribute         | Source                                            |
|-------------------|---------------------------------------------------|
| `rpc.system`      | `"connect_rpc"` or `"grpc"` depending on protocol |
| `rpc.service`     | Fully-qualified service name from the procedure   |
| `rpc.method`      | Method name from the procedure                    |
| `rpc.duration_ms` | Wall time from interceptor entry to exit          |
| `rpc.code`        | Final status code (`"OK"` for success)            |
| `request.id`      | Value of the request-id header when present       |
| `trace.id`        | From `SpanContext` when OTel is wired             |
| `span.id`         | From `SpanContext` when OTel is wired             |
| `error`           | Error message when the call failed                |

The status code uses the protocol's canonical name string
(`Unavailable`, `ResourceExhausted`, etc.) rather than a numeric code
so log queries are readable.

### Log level

Successful calls log at the SDK's success-level (default Info /
equivalent). Failed calls log at the error-level (default Error /
equivalent). Both are configurable per consumer.

The interceptor does not log at debug level for any per-step activity.
Debug-level RPC tracing is the OTel companion's responsibility (span
events).

### Boundary with OTel

Tracing is the causal graph (parent-child spans, durations,
attributes per step). Logging is the event store (one row per RPC,
indexable by every attribute). They join via `trace.id` and `span.id`.
The interceptors write both; consumer-side query tools correlate
downstream.

The logging interceptor does not duplicate per-step span events into
logs. If a retry happened, the canonical record's final code reflects
the outcome and the trace records each attempt as span events.

### Procedure name parsing

The protocol's procedure path (`/service.v1.UserService/CreateUser` in
Connect / gRPC) is split into `rpc.service` and `rpc.method` at the
last slash. The leading slash is trimmed.

### Constructor error contract

The interceptor constructor returns an error / throws an exception
when:

- The logger instance is null.
- (Future) Any other required configuration is missing.

It does not warn or no-op for missing required fields. Misconfigured
logging is a startup-time error, not a silent runtime degradation.

## Drawbacks

- Per-step debug logs from the interceptor itself are gone. Consumers
  who expected to grep for "retrying attempt 2" inside the SDK will
  not find it in logs; they have to inspect spans (which OTel records
  do represent). Net win in production, mild friction during initial
  integration.
- Wide records get large. A canonical row with caller attrs, headers
  (when enabled), error messages, and trace IDs can easily exceed
  1 KB. Most modern log backends absorb this fine; older syslog-style
  pipelines may truncate. Documented as a recommendation: use a
  wide-event-friendly backend.
- The default redaction list is necessarily short. Consumers with
  custom auth headers must extend it; the SDK cannot guess
  vendor-specific names. A missed redaction leaks the value into the
  log backend.
- The per-language logger interface choice freezes parts of the SDK
  surface. If a language's de-facto interface changes (e.g. Go
  community moves off `log/slog`), the SDK has a migration cost.

## Rationale and alternatives

- **Per-step interceptor logs (debug level on, info default).**
  Rejected: even off, the call-site bookkeeping clutters the codebase,
  and turning it on in production is a foot-gun (volume can spike 10x
  with no per-record value once OTel spans exist).
- **OTel logs only, no structured logger.** Rejected: OTel logs are an
  emerging standard with uneven backend support. Targeting each
  language's de-facto logger interface and letting consumers bridge to
  OTel logs via their handler is strictly more flexible.
- **Bundle a default logger / backend.** Rejected: every consumer has
  an opinion about formatting, destination, and rotation. The SDK
  staying agnostic avoids those fights.
- **Per-language logger naming custom to the SDK.** Rejected: forcing
  consumers to learn a new logger abstraction breaks the "feels
  native" criterion from RFC 0001.
- **Emit two records (request start, request end).** Rejected:
  doubles log volume for no investigative value over a single
  end-of-RPC record with `rpc.duration_ms`.
- **Mandate the same logger library in every language (e.g. always
  emit JSON to stdout).** Rejected: explicit non-goal per RFC 0001's
  identical-behaviour-not-identical-shape clause.

## Prior art

- Stripe's canonical log lines:
  https://stripe.com/blog/canonical-log-lines
- Logging Sucks. Wide Events:
  https://loggingsucks.com/
- OTel semantic conventions for RPC:
  https://opentelemetry.io/docs/specs/semconv/rpc/
- Go `log/slog` design:
  https://go.dev/blog/slog
- `Microsoft.Extensions.Logging` patterns:
  https://learn.microsoft.com/dotnet/core/extensions/logging
- SLF4J:
  https://www.slf4j.org/manual.html
- Rust `tracing` crate:
  https://docs.rs/tracing/
- sdk-core-go/docs/adr/0007 (logging strategy): Go-side reference
  implementation.

## Unresolved questions

- Streaming RPC logging shape: one record per stream open/close, one
  per message, or pass-through. Defer until a real streaming consumer
  reports a gap.
- Whether `rpc.duration_ms` should follow OTel semantic conventions
  exactly (which prefer seconds-as-double for histograms) or keep the
  milliseconds-as-int64 form that log backends index more cleanly.
  Today every SDK uses milliseconds; OTel histograms come from the
  OTel interceptor, not from the log record.
- A canonical schema for the caller-hook attribute keys
  (`tenant.id`, `actor.id`) so cross-consumer dashboards line up.
  Out of scope for this RFC; revisit if a real cross-consumer
  dashboard need appears.
- Whether to ship a default OTel-bridging handler / adapter so
  consumers who already wire OTel get logs flowing into the OTel
  collector without extra setup. Today the answer is "consumer wires
  their own bridge".

## Future possibilities

- Cross-language conformance tests asserting the canonical record's
  attribute set is identical for the same fixture call across every
  SDK.
- A capability flag exposing which logger interface this SDK targets,
  so consumers can branch at wire time when integrating into a
  polyglot service.
- Telemetry-driven default tuning of the redaction list: collect which
  custom header names consumers add and consider promoting common
  patterns to the default list.
- A schema annotation
  (`option (pinguteca.logging.exclude_from_canonical) = true`) that
  lets the service author opt a method out of canonical logging
  (e.g. health checks, metrics scrapes). Out of scope until volume
  becomes a real complaint.
