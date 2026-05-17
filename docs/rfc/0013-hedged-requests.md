# RFC 0013: Hedged requests

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `hedge` Layer 3 companion
  module.
- Depends on: RFC 0002 (layered architecture), RFC 0006 (retry
  behavioural contract), RFC 0008 (resilience presets) for chain
  positioning, RFC 0012 (token rotation policy) for chain ordering
  relative to rotation.

## Summary

Pin how every SDK ships hedged requests: as a **Layer 3 companion
module** (separate package, opt-in by dependency); never part of
the canned presets; default policy hedges only methods marked
`NO_SIDE_EFFECTS` in the proto schema; default tuning is 3 total
attempts with 50 ms between launches; the interceptor sits inside
retry and outside rotation when wired. First-success-wins semantics;
if every attempt fails the last observed error is returned. Layer 3
placement is the right home because the orchestration primitives
that drive parallel attempts (goroutines + channels, Tasks +
Channels, Tokio mpsc, structured-concurrency TaskGroups, etc.) are
ecosystem-native and the integration shape is part of the value.
The first SDK (Go) shipped this as a local ADR; pinning it across
SDKs prevents the next implementer from defaulting hedge-always-on
(load amplification disaster) or hedging IDEMPOTENT writes by
default (doubles billed load) or returning the first error when all
attempts fail (stale state) or shipping it inside the core package.

## Motivation

Hedged requests dispatch multiple parallel attempts of the same RPC
and return the first successful response, cancelling the others. The
technique is a well-known tail-latency killer for read-heavy workloads
against variable-latency backends (Dean and Barroso, Tail at Scale,
CACM 2013). It is also load-amplifying: an N-attempt hedge with the
wrong policy multiplies request volume on a backend that may already
be the reason latency is variable.

Three cross-SDK questions need pinning:

1. **Default state.** Hedging always-on amplifies cost for every
   consumer, including those whose backends are healthy and need no
   help. Hedging off-by-default forces consumers to opt in for the
   cases where it actually helps.
2. **Safety floor.** Hedging a non-idempotent RPC is always a bug;
   the server may process more than one parallel attempt before the
   loser cancels propagate. This is independent of deliberate backend
   cost; it can corrupt data.
3. **Composition with retry, rotation, breaker, idempotency-key.**
   Each composition order has different amplification properties.

Without a pinned answer one SDK ships hedge in the Standalone preset
("better tail latency out of the box"), another ships it off-by-
default but defaults to `IDEMPOTENT` hedging, and a third returns the
first error instead of the last. Consumers see different request
volume, different safety floors, and different error messages
depending on which SDK they import.

## Guide-level explanation

### Layer placement

Hedge ships as a **Layer 3 companion module**, not in the Layer 2
core package. Per RFC 0002:

- Layer 2 holds behaviour the SDK owns end-to-end with identical
  cross-language semantics and zero ecosystem coupling.
- Layer 3 holds companions whose value depends on language-native
  primitives: structured concurrency, cancellation propagation,
  bounded queues, task orchestration.

Hedge fits Layer 3 cleanly. The contract is identical (NO_SIDE_EFFECTS
gate, first-success-wins, LAST-error semantics, stagger schedule),
but the orchestration primitive differs per ecosystem:

| Language | Primitive                                           |
|----------|-----------------------------------------------------|
| Go       | goroutines + `time.Timer` + buffered channel        |
| .NET     | `Task` + `Task.Delay` + `System.Threading.Channel`  |
| TS / Node| `Promise.race` + `setTimeout` + `AbortController`   |
| Rust     | `tokio::select!` + `tokio::time::sleep` + `mpsc`    |
| Java     | `ScheduledExecutorService` + `BlockingQueue`        |
| Kotlin   | structured-concurrency `coroutineScope` + `Channel` |
| Python   | `asyncio.create_task` + `asyncio.sleep` + `Queue`   |
| Dart     | `Timer` + `Completer` + `StreamController`          |
| Swift    | `Task.sleep` + `TaskGroup` + `AsyncStream`          |

Locking these into Layer 2 would force a single concurrency
abstraction across the family; making it Layer 3 lets every SDK
feel native while keeping the externally observable behaviour
identical.

Consumers add the dependency (`Pinguteca.Sdk.Core.Hedge` for .NET,
the `hedge` sub-module for Go, etc.) and wire the interceptor
explicitly. The Standalone and Mesh presets do not include hedge.

### Opt-in only, never in a preset

Hedge is not part of `presets.Standalone` or `presets.Mesh`.
Consumers wire it explicitly. The opt-in surface acknowledges the
load amplification trade-off: every hedged call is up to N times the
backend cost of a single call.

A consumer enabling hedge must also lower their retry `MaxAttempts`
accordingly. Total request volume per logical RPC is bounded by
`retry.MaxAttempts * hedge.MaxAttempts`; forgetting to lower retry's
budget silently doubles or triples request volume. The hedge module's
documentation must flag this explicitly per-language.

### Idempotency-level scope

The default policy hedges only methods marked
`option idempotency_level = NO_SIDE_EFFECTS` in the proto schema.

| Idempotency level    | Default behaviour                              |
|----------------------|------------------------------------------------|
| `NO_SIDE_EFFECTS`    | Hedge eligible.                                |
| `IDEMPOTENT`         | Skipped unless `HedgeIdempotent = true`.       |
| Unknown / unset      | Never hedged. No opt-in flag exists.           |

`IDEMPOTENT` is skipped by default because the proto marker only
guarantees the method tolerates duplicates, not that the duplicates
are cheap. Hedging an `IDEMPOTENT` mutation doubles billing-relevant
load (writes, charges, external API calls). The opt-in
`HedgeIdempotent` flag lets a consumer decide per use case (internal
metrics writes versus external billing API calls).

Unknown idempotency level is never hedged, no flag, no opt-out. The
default-deny gate prevents the worst class of bug (duplicate writes
from accidentally hedging a non-idempotent RPC).

### Default tuning

- `MaxAttempts = 3` (primary plus two hedges).
- `Delay = 50 ms` between successive launches.

`Delay` should be close to the typical P50 of the target RPC so
hedges fire only when an attempt is definitely slow. Lowering `Delay`
amplifies load on the median case for marginal tail benefit; raising
it gives the primary more chance to win on its own at the cost of
tail-latency reduction.

These are starting points, not commandments. The hedge module
documents how to tune for specific backends.

### Composition order

The composition order pinned in RFC 0008 + RFC 0010 + RFC 0012
extends to include `Hedge`:

```
outermost                                                                                       innermost
Logging  ->  OTel  ->  Breaker  ->  Idempotency  ->  Retry  ->  Rotation  ->  Hedge  ->  Auth
```

`Hedge` sits **inside Retry**, **inside Rotation**, and **outside
Auth**.

- **Inside Retry:** Each hedge attempt is one retry attempt from the
  perspective of the outer retry interceptor. When hedging is on,
  retry's `MaxAttempts` must be lowered so the product remains
  bounded.
- **Inside Rotation:** Rotation observes the hedge as one logical
  operation. If every hedge attempt fails with `Unauthenticated`,
  rotation sees the aggregate failure once, invalidates the cached
  token, and re-runs the entire hedge with a fresh token. Putting
  rotation inside hedge would mean N parallel rotation interceptors
  competing on the same cache (single-flight collapses the IdP call,
  but the chain becomes harder to reason about).
- **Outside Auth:** Each hedge attempt invokes the inner auth
  interceptor, which attaches the current cached token. After
  rotation invalidates and re-runs, all N attempts of the new hedge
  see the fresh token.

### First-success-wins

The interceptor returns the first successful response (status code
OK) and cancels every other in-flight attempt. Cancellation uses the
language's native primitive (context cancel, `CancellationToken`,
`AbortSignal`, drop on Rust futures).

The cancelled attempts may still complete on the wire (the network
does not know about client-side cancellation until the next read).
This is unavoidable; the server-side cost is the duplicate processing
the consumer signed up for when enabling hedge.

### Last error on all-fail

If every attempt fails, the SDK returns the **last** observed error,
not the first.

The first attempt is the longest in flight by definition; its error
is more likely to reflect the state-at-the-time-it-was-launched,
which has been superseded by later attempts. The last attempt's
error reflects the most recent backend state.

This is the opposite of the intuitive "first error wins" pick. The
RFC pins LAST explicitly so no SDK defaults the other way.

### Streaming RPCs pass through

A stream cannot be replayed safely; per-message acknowledgement
multiplexing across parallel streams with reconciliation on cancel
has no standard primitive in any target language's RPC stack. The
hedge interceptor lets streaming RPCs through unchanged.

Future RFC may revisit if Connect / gRPC ships a stream-hedge
primitive; today the answer is "consumers handle stream replay at
the application layer".

## Reference-level explanation

### Schema-level idempotency lookup

Per RFC 0006 (retry contract), languages divide into two camps:

- **Schema-aware** (Go, TS, Swift, Kotlin, Dart, Python via
  Connect-protocol stacks): the runtime exposes the method's proto
  `idempotency_level` directly. The hedge interceptor reads it from
  the request spec.
- **Schema-blind** (.NET, Java, Rust via gRPC stacks): no runtime
  schema metadata. The hedge interceptor exposes an
  `IsHedgeEligible(method) -> Eligibility` hook the caller fills in.
  When the hook is null, the SDK defaults to `Unknown` for every
  method (no hedging) and the per-language README documents how to
  wire the hook.

The eligibility return is a tri-state (`NoSideEffects`, `Idempotent`,
`Unknown` or equivalent) rather than a bool, because the
`HedgeIdempotent` opt-in needs to distinguish the two safe-but-
different cases.

### Stagger semantics

The N attempts launch on a staggered schedule:

- Attempt 1: fires immediately.
- Attempt 2: fires after `Delay` if Attempt 1 has not completed.
- Attempt K: fires after `Delay * (K-1)` if no prior attempt has
  succeeded.

When an attempt succeeds, all pending timers cancel and all in-flight
attempts get cancellation. When the consumer's deadline elapses
before any attempt succeeds, the interceptor returns the
context/deadline error and cancels all in-flight attempts.

### Buffered result aggregation

Each attempt writes its result onto a results buffer sized to
`MaxAttempts`. The buffer prevents in-flight goroutines / tasks /
async functions from blocking on an unread channel after the
interceptor has already returned with an early winner. This avoids
attempt-goroutine leaks that would otherwise persist beyond the
logical RPC.

### Per-language orchestration primitive

| Language | Stagger primitive                                | Result aggregation                   |
|----------|--------------------------------------------------|--------------------------------------|
| Go       | `time.Timer` (or injectable `Clock`)             | buffered channel                     |
| .NET     | `Task.Delay(token)` with cancellation            | `Channel<Result>` (System.Threading) |
| TS / Node| `setTimeout` + `AbortController` per attempt     | `Promise.race` with accumulator      |
| Java     | `ScheduledExecutorService`                       | `BlockingQueue<Result>`              |
| Kotlin   | `delay()` inside structured-concurrency `coroutineScope` | `Channel<Result>` (kotlinx)  |
| Python   | `asyncio.create_task` + `asyncio.sleep`          | `asyncio.Queue`                      |
| Rust     | `tokio::time::sleep` + `tokio::select!`          | `tokio::sync::mpsc`                  |
| Dart     | `Timer` + `Completer` per attempt                | `StreamController<Result>`           |
| Swift    | `Task.sleep(for:)` + `TaskGroup`                 | `AsyncStream<Result>`                |

The user-visible behaviour (stagger interval, cancellation on win,
LAST-error on all-fail) is identical; the implementation primitive
follows each ecosystem's idiom.

### Cancellation propagation

When the interceptor returns (winner found, or all attempts failed,
or context cancelled), all in-flight attempts receive cancellation
**before** the interceptor returns control to the caller. The
guarantee is that on return, no SDK-spawned task is still consuming
backend resources from the consumer's perspective; what the network
does with already-sent bytes is the server's problem.

This requires the interceptor to wait briefly for cancellation
acknowledgement on cancelled attempts, which the per-language
primitives above handle natively.

### Composition with breaker

Each hedge attempt traverses the outer interceptors before reaching
hedge, including the breaker. An open breaker short-circuits every
attempt, which prevents hedge from amplifying load on an already-
unhealthy backend. The breaker's open-state error counts as a single
failure per attempt; if every attempt sees the open breaker, the
last error returned is the breaker's "Unavailable + RetryInfo" per
RFC 0008.

## Drawbacks

- N times request volume on hedged calls. Backends already throttling
  via `ResourceExhausted` see worse contention. Breakers partly
  mitigate (an open breaker short-circuits all parallel attempts),
  but consumers must size their backends with the hedge
  amplification in mind.
- The `MaxAttempts` knob on hedge multiplies with retry's
  `MaxAttempts`. Forgetting to lower retry's budget when enabling
  hedge silently inflates request volume. Documented across every
  SDK's hedge module, but documentation is no substitute for the
  consumer noticing.
- Tests against real backends are tricky; race ordering depends on
  real network latency. Every SDK ships hedge with a deterministic
  clock injection point for unit-test coverage. Integration testing
  is left to consumer test suites.
- The `IsHedgeEligible` hook duplicates the equivalent retry hook in
  schema-blind languages; both ask "is this method safe to repeat".
  Future work: unify into one schema-shape hook used by retry,
  rotation, and hedge.
- The LAST-error decision will surprise consumers who expected FIRST
  on debug. The hedge module documentation has to call it out.

## Rationale and alternatives

- **Default-on hedging in the Standalone preset.** Rejected. Many
  consumers do not have tail-latency problems; defaulting hedge on
  multiplies their backend cost for no gain. Opt-in keeps the
  trade-off visible.
- **Aggressive defaults (`MaxAttempts = 5`, `Delay = 0`).**
  Rejected. Best for tail-latency reduction in benchmarks; worst for
  backend cost in production.
- **Default-allow on `IDEMPOTENT`.** Rejected. The class of methods
  marked `IDEMPOTENT` is "writes that tolerate duplicates", not
  "writes that are cheap to duplicate". Defaulting hedge on them
  doubles every billed write the consumer makes.
- **Hedge outside retry (each hedge attempt has its own retry
  budget).** Rejected. Even worse amplification:
  `hedge.MaxAttempts * retry.MaxAttempts` per logical call, with
  retries firing inside each parallel attempt.
- **Rotation inside Hedge (each parallel attempt has its own
  rotation).** Rejected. N concurrent rotation interceptors share a
  single token cache. Single-flight per RFC 0012 collapses the IdP
  call, but the chain becomes harder to reason about and the test
  matrix grows. Rotation outside hedge gives one rotation event per
  logical call, which is the cleaner mental model.
- **Hedge streaming RPCs.** Rejected for v1. Per-message
  acknowledgement multiplexing across parallel streams with
  reconciliation on cancel has no standard primitive in any target
  language's RPC stack.
- **Return FIRST error on all-fail.** Rejected in favour of LAST.
  The first attempt's error reflects state superseded by later
  attempts; the last attempt's error reflects the most recent
  backend state.

## Prior art

- Dean and Barroso, "The Tail at Scale", CACM 2013:
  https://research.google/pubs/the-tail-at-scale/
- gRPC retry policy and throttling design:
  https://github.com/grpc/proposal/blob/master/A6-client-retries.md
- AWS builders' library on tail-latency mitigation:
  https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/
- `resty/hedging.go` (Go HTTP client library) prior art.
- sdk-core-go/docs/adr/0005 (hedged requests): Go-side reference
  implementation.

## Unresolved questions

- Retry-throttling budget interaction. When retry gains a
  retry-throttling budget (gRPC `retry_throttling`-style), hedge
  attempts should consume the same budget so opt-in hedging cannot
  bypass the throttle. Captured in RFC 0008's revisit list; will
  return here once retry-throttling lands.
- Per-host load awareness. Today hedge fires unconditionally on
  eligible methods; if the target is already saturated, hedge makes
  the saturation worse. A future load-balancer-aware variant would
  skip hedge when peer signals indicate saturation. Out of scope
  until per-host load signals exist in the SDK.
- Streaming hedge with per-message reconciliation. Wait for a real
  consumer ask and a standard protocol primitive.
- Unifying the schema-blind `IsIdempotent` / `IsHedgeEligible` hooks
  in .NET, Java, Rust into a single schema-shape provider. Worth its
  own RFC once a second consumer hits the duplication.
- Whether hedge should ever fire on a method marked `IDEMPOTENT` even
  if `HedgeIdempotent` is false, for very-low-latency methods where
  the duplicate cost is trivially small. Today the answer is no;
  the opt-in is the gate. Revisit if a real consumer reports the
  case.

## Future possibilities

- Cross-language conformance tests against a shared fixture server
  asserting identical stagger timing, identical cancellation
  propagation, and identical LAST-error semantics for every SDK
  under the same configuration.
- Telemetry-driven default tuning (`Delay` and `MaxAttempts`)
  derived from per-method P50 observations across deployed SDKs.
- A capability flag exposing the configured hedge `MaxAttempts` so
  observability dashboards can attribute backend load amplification
  correctly.
- Schema annotation for methods that should never hedge even when
  marked `NO_SIDE_EFFECTS` (e.g. expensive queries where the
  duplicate cost dwarfs the latency benefit). Out of scope until a
  real consumer reports the case.
