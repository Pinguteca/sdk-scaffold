# RFC 0021: Timeout interceptor

- Status: Accepted
- Date: 2026-06-22
- Affects: every `sdk-core-*` repo's interceptor layer (Layer 2).
- Depends on: RFC 0002 (layered architecture), RFC 0008 (resilience
  presets) for the Standalone vs Mesh split, RFC 0006 (retry) for
  how retries interact with the outer deadline.

## Summary

Every SDK ships a TimeoutInterceptor that ensures every outgoing
call carries a deadline. The interceptor takes the smaller of the
caller-supplied deadline and a configured default. It never
extends a deadline the caller already set. When the deadline
fires, the interceptor surfaces a canonical timeout error so
consumers can branch on cause uniformly.

## Motivation

Languages differ in how naturally deadline propagation reaches
the wire. Go threads `context.Context` through every call; .NET
and Dart rely on per-call cancellation tokens that not every
consumer wires consistently. Without a pinned interceptor, an
SDK that defaults to no deadline can hang indefinitely during an
upstream partition. With a pinned interceptor, every SDK behaves
the same under the same failure: a call without an explicit
deadline gets the configured default ceiling, and the upstream
either responds, errors, or is cancelled within that ceiling.

## Decision

### Surface

Each SDK exposes a constructor with the language-idiomatic name
(`interceptor.Timeout(d)`, `TimeoutInterceptor.create(d)`,
`new TimeoutInterceptor(d)`). It accepts a single duration.

### Behaviour

For each outgoing call:

1. Read the caller's deadline (from `context.Context`,
   `CancellationToken`, or equivalent).
2. Compute `effective = min(caller-deadline, now + configured-default)`.
   If the caller has no deadline, `effective = now + configured-default`.
3. Propagate `effective` to the inner transport.
4. When `effective` fires, surface a canonical timeout error
   (`context.DeadlineExceeded` in Go, `TimeoutException` in .NET,
   `TimeoutException` in Dart) wrapped in the SDK's typed error
   boundary so `errors.Is` / `is` checks succeed.

The interceptor MUST NOT extend a caller-supplied deadline. A
caller who passed a 5-second context.WithTimeout never waits
longer than 5 seconds even if the configured default is 30s.

### Defaults

- `defaultTimeout = 30 seconds`. Aligns with typical RPC SLAs and
  is short enough that a hung call surfaces within one human
  attention span.
- Standalone preset (RFC 0008): 30 seconds.
- Mesh preset (RFC 0008): the interceptor is omitted; the service
  mesh enforces deadlines at the sidecar.

### Interaction with retry

The TimeoutInterceptor sits OUTSIDE the RetryInterceptor in the
default preset chain. The total budget for all retry attempts is
`effective`. A single attempt does not get its own 30s budget;
the configured `defaultTimeout` is the ceiling for the whole
retried call. Consumers who need per-attempt ceilings install a
second TimeoutInterceptor inside the retry loop, but that is
opt-in.

### Go-specific note

Go consumers already pass `context.WithTimeout` per call. The
interceptor's primary value in Go is the **default ceiling** when
the caller passes a deadline-less context. It MUST be a no-op
when the caller already supplied a tighter deadline.

## Drawbacks

- 30 seconds is a guess. Long-running uploads, streaming reads,
  or back-channel operations will need explicit overrides.
- The "smaller wins" rule means a misconfigured interceptor (very
  short default) silently ceilings every call; observability hooks
  on timeout firings are recommended but not required.

## Unresolved

- Per-method default overrides (different timeout for read vs
  write) are deferred. Consumers compose multiple interceptors
  if they need this today.
