# RFC 0015: Caching strategy

- Status: Accepted
- Date: 2026-05-19
- Affects: every `sdk-core-*` repo's `caching` Layer 3 companion
  module.
- Depends on: RFC 0002 (layered SDK architecture), RFC 0006 (retry
  behavioural contract) for the schema-aware-vs-predicate split,
  RFC 0010 (structured logging) for cache-hit observability.

## Summary

Pin how every SDK ships consumer-side response caching: as a
**Layer 3 companion module** (separate package, opt-in by
dependency) with schema-driven per-method opt-in, content-hashed
cache keys, mandatory tenant-scope isolation, TTL plus ETag plus
write-triggered invalidation, opt-in stale-while-revalidate, opt-in
negative caching, default-on single-flight, and explicit
streaming-pass-through. Pluggable cache store interface lets
consumers wire in-memory by default and Redis (or any other backend)
without the SDK depending on a specific implementation. Without a
pinned contract, every SDK author re-derives cache-key composition,
invalidation semantics, and tenant isolation independently, which
guarantees at least one of them ships a cross-tenant data leak.

## Motivation

Read-heavy gRPC and Connect workloads spend most of their backend
budget re-fetching data that has not changed. A consumer-side cache
collapses that into a hit-and-return on subsequent calls. The
mechanics are well understood at the HTTP layer (RFC 9111) but
gRPC-protocol SDKs lose the protocol-level affordances and need an
SDK-layer interceptor instead; Connect-protocol SDKs get half the
work for free via Connect's HTTP GET support for `NO_SIDE_EFFECTS`
methods.

Cross-SDK questions needing pinned answers:

1. **Opt-in scope.** Per-method via schema annotation versus
   per-client global config. Mixing models leads to inconsistent
   defaults across SDKs.
2. **Key composition.** Serialised request bytes versus content-hash.
   Key size and payload-leak-through-keys risk differ.
3. **Miss semantics.** Transparent fetch versus surfaced miss.
   Interceptor pattern breaks if every call site handles miss.
4. **Invalidation.** TTL only, write-triggered, or both. Distributed
   replicas with TTL-only see stale data after writes for the full
   TTL window.
5. **Stale-while-revalidate.** Hide P99 latency at the cost of
   returning slightly older data than TTL allows.
6. **Tenant isolation.** Multi-tenant deployments need cache keys
   that include a tenant scope; forgetting to wire one is a data
   leak.
7. **Negative caching.** Caching `NotFound` defends against cache
   penetration attacks; not caching it keeps freshly-created
   records discoverable immediately.
8. **Streaming.** Pass-through or attempt to cache.

Without a pinned contract one SDK ships content-hash keys, another
ships serialised-bytes keys, a third defaults to caching every
`NO_SIDE_EFFECTS` method globally without tenant scope. Consumers
switching SDKs see different cache behaviour and at least one
deployment leaks user data across tenants.

## Guide-level explanation

### Layer placement

Caching ships as a **Layer 3 companion module**, not in the Layer 2
core. Two reasons per RFC 0002's criteria:

- Realistic deployments need a distributed cache store (Redis,
  Memcached, KeyDB), which is third-party. Layer 2 forbids
  third-party dependencies outside the RPC runtime.
- The store abstraction is ecosystem-native: `IDistributedCache`
  in .NET, a `cache.Cache` interface in Go, `redis.Redis` clients
  in Python, etc. Companion-shape integration matches the structured
  logging and compression precedents.

The in-memory default could technically live in Layer 2 (zero 3P),
but splitting the in-memory and Redis adapters across two packages
fractures the contract. The companion ships the store interface,
the in-memory default, and a Redis adapter alongside.

Consumers add the dependency
(`Pinguteca.Sdk.Core.Caching` for .NET, the `caching` sub-module
for Go) and wire the interceptor explicitly. The Standalone and
Mesh presets do not include caching.

### Schema-driven opt-in

Caching is off by default. Schema authors mark methods cacheable
with proto options:

```protobuf
service UserService {
  rpc GetUser(GetUserRequest) returns (User) {
    option idempotency_level = NO_SIDE_EFFECTS;
    option (pinguteca.cache.ttl) = "60s";
    option (pinguteca.cache.swr) = "5s";
    option (pinguteca.cache.negative_ttl) = "5s";
  }
  rpc ListUsers(ListUsersRequest) returns (ListUsersResponse) {
    option idempotency_level = NO_SIDE_EFFECTS;
    option (pinguteca.cache.ttl) = "30s";
  }
  rpc UpdateUser(UpdateUserRequest) returns (User) {
    option (pinguteca.cache.invalidates) = "GetUser,ListUsers";
  }
}
```

Options:

| Option              | Applies to     | Meaning                                                  |
|---------------------|----------------|----------------------------------------------------------|
| `ttl`               | read methods   | Cache hit window after a successful fetch.               |
| `swr`               | read methods   | Stale-while-revalidate window beyond `ttl`.              |
| `negative_ttl`      | read methods   | Cache hit window for `NotFound` responses. Opt-in.       |
| `invalidates`       | write methods  | Comma-separated method names to invalidate after write.  |

Cache is only consulted when `ttl > 0`. `swr` and `negative_ttl`
default zero (off).

Per RFC 0006, languages without runtime access to proto options
(.NET, Java, Rust under gRPC) supply a `CacheSpec` predicate hook:

```
CacheSpec IsCacheable(string method);
```

returning `ttl`, `swr`, `negative_ttl`, and `invalidates` fields.
When the predicate is null in those languages, the interceptor
treats every method as uncacheable and the per-language README
documents the divergence.

### Cache key composition

Keys are composed as:

```
{scope}:{method}:{sha256(serialized-request)}
```

- `scope`: tenant identifier from the `KeyScope(ctx)` hook. Empty
  string for explicit single-tenant.
- `method`: fully-qualified procedure path (`/service.v1.Svc/Get`).
- `sha256(serialized-request)`: hex-encoded SHA-256 of the protobuf
  serialised request body.

Hash composition reasons:

- Stable key size regardless of request payload size.
- No request payload leakage through the key (matters for shared
  Redis where keys appear in `MONITOR`, slow-log, and metrics).
- Collision-resistant at the SHA-256 strength.

The cache store sees only the composed key string; the SDK never
hands raw request bytes to the store.

### Default-deny tenant isolation

The interceptor refuses to cache anything unless the consumer
wires a `KeyScope(ctx) -> string` hook:

- Single-tenant deployments wire `_ => ""` to opt in with empty
  scope.
- Multi-tenant deployments extract the tenant identifier from the
  request context (JWT claim, header, subdomain, etc.) and return
  it.

When the hook is null the interceptor passes every call through
uncached and emits a one-time startup warning through the logging
companion (when wired). Default-deny because:

- A multi-tenant deployment that forgets to wire `KeyScope` and
  defaults to empty scope serves Tenant A's cached response to
  Tenant B. The failure mode is a cross-tenant data leak, not
  slow-but-correct behaviour.
- The cost of explicit opt-in is one line of consumer code.
- The cost of accidental cross-tenant leak is an incident.

### Transparent miss semantics

A cache miss triggers the underlying fetch, populates the cache
with the response (subject to status: positive responses cached
for `ttl`, `NotFound` for `negative_ttl` when set, other errors
not cached), and returns the response to the caller. The caller
sees no miss signal; the cache is invisible to call-site code.

Cache hits short-circuit the fetch. The full interceptor chain
(retry, breaker, auth) still runs on cache misses because the
caching interceptor sits outside them.

### Mandatory single-flight

Concurrent callers for the same key collapse to one backend
fetch. The first call dispatches; subsequent calls wait on its
result and share the response. Default-on; not configurable.

Reasons:

- Cold-cache thundering-herd is the most common cache-related
  outage. Default-off would mean every consumer eventually files
  the same incident.
- Per RFC 0012's single-flight precedent (token rotation), this
  pattern is already a cross-SDK requirement and we use the same
  primitive (Go's `sync/singleflight`, .NET's `SemaphoreSlim`,
  Tokio's `OnceCell`, etc.).

### Invalidation: TTL plus ETag plus write-triggered

Three independent expiry signals:

1. **TTL.** Entry expires `ttl` seconds after write to cache.
   Hard upper bound regardless of staleness opinion.
2. **ETag.** When the server returns `etag` (Connect) or
   `x-etag` (gRPC metadata) on the response, the cached entry
   stores it. Subsequent fetches in the `swr` window send
   `If-None-Match`; a 304 keeps the cached body, otherwise the
   fresh response replaces it. ETag use is automatic when the
   server supplies one; opt-out is per-method.
3. **Write-triggered.** A successful write method whose schema
   declares `invalidates = "GetX,ListY"` removes matching cache
   entries (by method-name prefix) after the write completes.
   The write itself is not cached.

Distributed coherence per cache store:

- **Shared cache (Redis, Memcached, etc.):** write-invalidation
  removes the key globally; every replica sees fresh data on
  next read.
- **In-memory cache (local-only):** write-invalidation removes
  the entry on the writing replica only; other replicas keep
  the cached entry until `ttl` expires. Per-language ADR must
  document this so consumers running in-memory across a k8s
  fleet do not expect coherence.

Cross-replica pub/sub invalidation broadcast is out of scope; a
future RFC if real consumers ask.

### Stale-while-revalidate

When `swr > 0` and a request lands during the `[ttl, ttl+swr]`
window, the interceptor returns the stale cached value
immediately and asynchronously fetches a fresh value in the
background. Subsequent requests within the same `swr` window
share the in-flight fresh fetch.

This hides P99 latency on hot-but-not-fresh keys at the cost of
returning data up to `swr` seconds older than the strict TTL
window. Off by default; schema author opts in per method.

### Negative caching

When `negative_ttl > 0`, a `NotFound` response is cached for
`negative_ttl` seconds with a tombstone value. Subsequent
identical requests return `NotFound` from the cache without a
backend fetch.

Reason: defends against cache-penetration DoS. An attacker
generating random non-existent IDs against an uncached endpoint
sees every request hit the backend; with `negative_ttl = 5s`,
each random ID consumes the backend once per 5 seconds at most.

Off by default because a 5-second negative cache means a
freshly-created record is invisible for up to 5 seconds.
Consumers exposing public lookup surfaces (user search, sku
lookup, etc.) opt in; internal endpoints leave it off.

Other error codes (`Unavailable`, `ResourceExhausted`, transient
failures) are never cached. Only `NotFound` qualifies, and only
when `negative_ttl` is explicitly set.

### Streaming RPCs pass through

Server-streaming, client-streaming, and bidi-streaming RPCs pass
through the caching interceptor unchanged. A stream of events
does not fit a request/response cache model: each event is
potentially unique, the stream is open-ended, and caching the
first message buys nothing. Mirrors RFC 0012 and RFC 0013's
streaming pass-through.

## Reference-level explanation

### Composition order

Caching sits **outside** the resilience chain so a hit
short-circuits before any of retry, breaker, idempotency, or
auth run. Extending the canonical chain:

```
outermost                                                                                                                  innermost
Logging  ->  OTel  ->  Cache  ->  Breaker  ->  Idempotency  ->  Retry  ->  Rotation  ->  Hedge  ->  Auth
```

Hits skip the entire inner chain (no auth token attached, no
retry budget consumed, no breaker statistics updated). Misses
fall through and the inner chain runs normally.

### Per-protocol layer placement

The composition diagram above is the logical position; the
physical layer where caching attaches splits by wire protocol.

- **Connect-protocol SDKs** (Go, TS, Swift, Kotlin, Dart, Python)
  attach caching at the **HTTP transport layer**: wrap an
  `http.RoundTripper` / `fetch` / `URLSession` / equivalent. When
  the consumer opts read-only methods into Connect's HTTP GET
  mode for `NO_SIDE_EFFECTS`, the request becomes a real HTTP GET
  with standard `Cache-Control`, `ETag`, and `If-None-Match`
  semantics. Any cache in the network path (CDN, reverse proxy,
  browser) can also cache the same response without per-consumer
  configuration; the SDK companion just adds a local layer for
  consumers without external caches.
- **gRPC-protocol SDKs** (.NET, Java, Rust) attach caching at the
  **client interceptor layer**: wrap the unary call inside the
  SDK. gRPC over HTTP/2 is always POST, response status codes are
  always HTTP 200 with gRPC status in trailers, and bodies are
  length-prefixed binary frames. No HTTP cache in the network can
  cache gRPC traffic; the interceptor is the only path to a cache
  hit. Negative caching maps to gRPC `NotFound` rather than
  HTTP 404; ETag uses a metadata entry rather than an HTTP header.

Cache semantics (TTL, SWR, invalidation, tenant scope,
single-flight, streaming pass-through) are identical across both
shapes. The split affects only where in the stack the cache lives
and what surface it exposes (RoundTripper vs interceptor).

A future SDK adopting a third protocol picks its layer by the
same rule: protocol carries cacheable HTTP semantics -> transport
layer; protocol does not -> interceptor layer.

### `Cache` store interface

Every SDK exposes a minimal store interface:

```
Cache:
  Get(key)             -> (value, found, error)
  Set(key, value, ttl)
  Delete(key)
  DeleteMatching(prefix)   // for write-triggered invalidation
```

In-memory implementation is shipped by the companion. Redis,
Memcached, and other adapters live alongside or in further
sub-modules per language.

### Per-language type mapping

| Language | Cache interface name        | In-memory default                          | Distributed adapter                 |
|----------|-----------------------------|--------------------------------------------|-------------------------------------|
| Go       | `Cache` interface           | `sync.Map` + TTL goroutine                 | `redis/go-redis` adapter            |
| .NET     | `ICache` interface          | `MemoryCache` (Microsoft.Extensions.Caching) | `IDistributedCache` (Microsoft.Extensions.Caching.StackExchangeRedis) |
| TS / Node| `Cache` interface           | `Map` + `setTimeout` eviction              | `ioredis` adapter                   |
| Java     | `Cache` interface           | Caffeine                                   | Lettuce / Jedis Redis adapter       |
| Kotlin   | same as Java                | same as Java                               | same as Java                        |
| Python   | `Cache` Protocol            | `cachetools.TTLCache`                      | `redis-py` adapter                  |
| Rust     | `Cache` trait               | `moka`                                     | `redis-rs` adapter                  |
| Dart     | `Cache` interface           | in-process `Map` + `Timer`                 | `package:redis_client` adapter      |
| Swift    | `Cache` protocol            | `NSCache`                                  | `RediStack` adapter                 |

Where the chosen library is third-party it ships as a separate
sub-module of the caching companion so consumers using the
in-memory default do not pull the Redis dependency.

### Sentinel logging fields

When the logging companion (RFC 0010) is wired alongside, the
caching interceptor contributes the following fields to each
canonical log record:

| Field             | Values                                                |
|-------------------|-------------------------------------------------------|
| `cache.outcome`   | `hit` / `miss` / `swr-hit` / `negative-hit` / `bypass`|
| `cache.key.hash`  | First 8 hex characters of the SHA-256 key (debugging) |
| `cache.age_ms`    | Time since cached entry was written (on hits)         |

Full keys are never logged. Tenant scope is logged separately as
`cache.scope` only when explicitly enabled per consumer
configuration.

### Failure modes

- **Cache store unavailable.** Treated as a miss; the underlying
  fetch runs. The interceptor never propagates a cache-store
  error to the caller. Errors are logged through the logging
  companion.
- **Serialisation failure.** The interceptor skips caching for
  that call, logs, and lets the request through.
- **Tenant scope returns null/empty unexpectedly in multi-tenant
  context.** The consumer's `KeyScope` hook is contract: empty
  string means explicit single-tenant. Non-empty strings are
  tenant scopes. The interceptor never enforces a particular
  shape; consumers misusing the hook get whatever isolation they
  asked for.

### Capacity bounds and eviction

The in-memory default ships an LRU eviction policy with a
configurable maximum entry count (default 1024). Distributed
adapters delegate to the underlying store's configuration. Per-
language ADR documents the chosen LRU implementation and any
default-cap rationale.

## Drawbacks

- Stale-read window after writes for in-memory caches across
  replicas. Documented loud; not preventable without shared
  cache or pub/sub broadcast.
- Schema-blind languages depend on the consumer wiring the
  `IsCacheable` predicate accurately. A wrong return value
  caches a non-idempotent write (catastrophic) or misses an
  obvious read opportunity.
- Default-deny tenant isolation adds one line of opt-in for
  single-tenant deployments. Acceptable; the alternative is
  default-allow with documented danger.
- ETag handling requires server cooperation; servers that do not
  emit ETags get TTL-only invalidation, weaker than what HTTP
  consumers expect.
- The `invalidates` annotation declares cross-method
  dependencies in the schema, which couples write methods to
  read methods at the schema level. Schema authors must keep
  the list up to date as methods are added.
- SHA-256 key hashing costs a few microseconds per call. Hot
  loops doing millions of cached calls per second see it. Not
  the typical SDK workload.
- **Response metadata is lossy on cached hits.** Cached entries
  store the response body and status, but the headers and
  trailers attached to a cached return are best-effort: gRPC SDKs
  cannot replay original trailers through the `AsyncUnaryCall`
  shape, and HTTP SDKs do not preserve every header. Consumers
  needing correlation between cached and live responses route
  identifiers through the logging companion (RFC 0010) rather
  than through response metadata.
- **Hand-rolled single-flight in gRPC SDKs has a tiny race
  window.** Connect-protocol SDKs can lean on the underlying
  HTTP client's built-in coalescing or a community singleflight
  primitive (Go's `golang.org/x/sync/singleflight`). gRPC-protocol
  SDKs hand-roll a per-key semaphore map; concurrent callers
  briefly racing on key creation may end up on different
  semaphores, splitting the singleflight collapse for one extra
  backend call. Acceptable for v1; revisit if benchmarks show
  contention.

## Rationale and alternatives

- **Per-client global config instead of per-method schema
  annotation.** Rejected. Cacheability is a property of the
  method (does it have side effects? is the response stable?),
  not of the client. Schema-level annotation puts the decision
  next to the contract definition.
- **Serialised request bytes as cache key.** Rejected. Key size
  grows with payload, requests with sensitive fields leak
  through cache logs.
- **Surface cache misses to call sites.** Rejected. Breaks the
  interceptor pattern; every consumer call site would need to
  re-implement the fetch-on-miss loop.
- **TTL-only invalidation, no write-triggered.** Rejected.
  Distributed deployments need cache coherence after writes;
  waiting out a TTL is unacceptable for user-visible state
  changes.
- **Default-allow tenant isolation with empty scope.**
  Rejected. Cross-tenant leak is too severe a default failure
  mode.
- **Always-on negative caching.** Rejected. Freshly created
  records becoming invisible for a TTL window is a worse default
  than the cache-penetration risk for most consumers.
- **Cache streaming RPCs by replaying recorded events.**
  Rejected. Each event is unique, the stream model does not fit
  request/response caching, the implementation complexity is not
  justified by realistic use cases.
- **Single-flight as opt-in.** Rejected. Thundering-herd is the
  most common cache-related outage; defaulting it off would mean
  every consumer eventually files the same incident.
- **Layer 2 placement (zero-third-party in-memory only).**
  Rejected for consistency. Splitting in-memory across L2 and
  distributed across L3 fractures the contract; companion
  shape is identical across compression, logging, hedge, and
  caching.

## Prior art

- RFC 9111, HTTP Caching:
  https://datatracker.ietf.org/doc/html/rfc9111
- ETag and `If-None-Match` semantics (RFC 9110 section 8.8):
  https://datatracker.ietf.org/doc/html/rfc9110#section-8.8
- Cloudflare Workers KV stale-while-revalidate:
  https://developers.cloudflare.com/workers/runtime-apis/cache/
- Stripe SDK idempotency-key and cache patterns:
  https://stripe.com/docs/api/idempotent_requests
- Apollo Client normalised cache (GraphQL):
  https://www.apollographql.com/docs/react/caching/cache-configuration/
- AWS SDK paginators and ETag-aware read patterns:
  https://docs.aws.amazon.com/sdk-for-go/v2/developer-guide/sdk-utilities.html
- Cache penetration attack pattern (Tencent Cloud writeup):
  https://www.tencentcloud.com/document/product/239/30912
- Single-flight pattern in Go:
  https://pkg.go.dev/golang.org/x/sync/singleflight

## Unresolved questions

- Cross-replica invalidation broadcast (pub/sub) for in-memory
  caches. Today's answer is "use a shared cache if you need
  coherence"; revisit if a real consumer reports the gap.
- Schema-driven cache warm-up: emit a `cache.warmup()` helper
  that pre-populates the cache from a list of method+request
  pairs at startup. Useful for known hot paths; out of v1.
- GraphQL-style normalised cache for the L1.5 ergonomic layer
  (`client.Users.Get(id)` consults the cache transparently and
  merges across queries that return the same entity). Tied to
  Layer 1.5 design; the L1.5 RFC will reference this one.
- Unifying the schema-blind `IsCacheable` predicate with the
  equivalent hooks in retry, hedge, and rotation. Four predicate
  hooks for the same "is this method idempotent / cacheable"
  question is duplication. A shared schema-shape provider RFC
  is worth opening once a second consumer reports the friction.
- Per-method rate limiting at the cache layer for negative-
  caching defense in depth. Defer to an L3 rate-limit companion
  RFC.
- Versioned cache keys keyed off a resource `etag` or version
  field, so writes naturally never query stale entries instead
  of relying on explicit invalidation. Tied to schema design and
  out of v1.

## Future possibilities

- Cross-language conformance tests against a shared fixture
  server: given a matrix of methods with known TTLs, do all
  SDKs hit / miss / invalidate identically? Catches drift
  before release.
- L1.5 ergonomic surfacing: `client.Users.Get(id, useCache:
  true)` exposes per-call cache control, and `cache.refresh()`
  exposes explicit warm-up / invalidation. Tied to Layer 1.5
  RFC.
- Telemetry-driven default tuning of `ttl` and `swr` per method,
  collected from deployed SDKs through the metrics export
  companion (when that ships).
- A `cache.dryrun` mode that logs every would-be hit/miss
  without serving from the cache. Helps consumers audit
  cacheability decisions before flipping the schema annotation
  on.
- Encrypted cache values for shared stores: per-tenant encryption
  keys so a compromised Redis cannot exfiltrate plaintext
  responses. Out of v1; revisit alongside any FIPS or
  compliance-driven workload.
