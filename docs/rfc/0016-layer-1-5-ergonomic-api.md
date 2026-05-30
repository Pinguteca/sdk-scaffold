# RFC 0016: Layer 1.5 ergonomic API

- Status: Accepted
- Date: 2026-05-19
- Affects: every future `sdk-ergo-*` companion package and the
  `api-surface.yaml` source-of-truth that backs them.
- Depends on: RFC 0002 (layered architecture), RFC 0006 (retry
  contract) for composed-op semantics, RFC 0015 (caching) for the
  caching surface L1.5 inherits.

## Summary

Pin the contract for an opt-in ergonomic wrapper above generated
Layer 1 stubs. A single `api-surface.yaml` describes the
consumer-facing shape (resources, method names, required vs
optional parameters, composed multi-RPC ops, long-running-op
helpers, excluded services). Each language's `sdk-ergo-{lang}`
package is handwritten against that YAML, with a CI tool walking
the public-API AST to catch drift. No code ships from this RFC;
the reference implementation lands later in `sdk-ergo-go` once
Layer 2 stabilises, with backports to the other languages one
cycle at a time.

## Motivation

The L1 generated stubs are a faithful 1:1 mapping of the proto
schema. Correct, type-safe, unergonomic:

```
// L1, generated
resp, err := client.CreateUser(ctx, &userv1.CreateUserRequest{
    Name: "Alice", Email: "alice@example.com",
    Role: "admin", Locale: "en-US", Timezone: "UTC",
})
```

vs

```
// L1.5, handwritten against api-surface.yaml
user, err := client.Users.Create(ctx, "Alice", "alice@example.com",
    users.WithRole("admin"))
```

Across nine languages and dozens of services, wrappers diverge on
naming, required-vs-optional discipline, composed-op semantics,
LRO polling, and whether internal services are accessible. Pinning
the contract once keeps the ergonomic surface aligned. Deferring
it lets the surface drift unrecoverably as soon as a third SDK
adopts it.

## Guide-level explanation

### `api-surface.yaml`

```yaml
resources:
  users:
    service: user.v1.UserService
    methods:
      create:
        rpc: CreateUser
        required: [name, email]
        optional: [role, locale, timezone, notify_on_create]
        defaults: { locale: "en-US", timezone: "UTC", notify_on_create: true }
      get:    { rpc: GetUser,    required: [id] }
      list:   { rpc: ListUsers,  paginated: true }
      update: { rpc: UpdateUser, required: [id], optional: [name, email, role], idempotent: true }
      delete: { rpc: DeleteUser, required: [id], idempotent: false }

  files:
    service: file.v1.FileService
    methods:
      upload:
        composed: [CreateUploadSession, StreamChunks, FinalizeUpload]
        required: [name, reader]
        idempotent: false

  reports:
    service: report.v1.ReportService
    methods:
      generate:
        rpc: GenerateReport
        required: [type, date_range]
        long_running: true
        poll_rpc: GetReportOperation

excluded:
  - admin.v1.AdminService
  - debug.v1.DebugService
```

Lives at the SDK monorepo root next to the proto definitions.
Every `sdk-ergo-{lang}` package implements the surface this YAML
declares; the drift-check tool enforces it.

### Method renaming and resource grouping

L1.5 reorganises the procedure tree by resource:
`UserService/CreateUser` becomes `client.Users.Create`. The YAML's
`resources:` block drives both the grouping (`client.Users`) and
the spelling (`Create`). Each language casing follows its
convention without changing the YAML.

### Optional parameters by language idiom

Required params are positional. Optional params flow through each
language's idiom:

| Language | Optional-parameter idiom                                            |
|----------|---------------------------------------------------------------------|
| Go       | Functional options: `users.Create(ctx, name, email, users.WithRole("admin"))` |
| .NET     | Named parameters: `client.Users.Create(name, email, role: "admin")` |
| Rust     | Builder: `client.users().create(name, email).role("admin").send()`  |
| TS / Node| Options object: `{ name, email, role: "admin" }`                    |
| Java     | Builder: `client.users().create(name, email).role("admin").build()` |
| Kotlin   | Default args: `create(name, email, role = "admin")`                 |
| Python   | Kwargs: `create(name, email, role="admin")`                         |
| Dart     | Named params: `create(name: name, email: email, role: "admin")`     |
| Swift    | Labeled args: `create(name: name, email: email, role: "admin")`     |

### Composed multi-RPC operations

A method with `composed:` orchestrates several L1 calls under one
L1.5 entry point. Cross-SDK semantics:

1. **Per-leg idempotency keys.** The L1.5 method generates a
   composed-op id at entry and derives each sub-RPC's key as
   `{composed_op_id}/{leg_index}`. The L2 idempotency interceptor
   sees each leg as independent and never knows about composition.
2. **Single correlation ID across legs.** Either the incoming
   context carries one or the L1.5 method generates one at entry;
   every leg sees it via the logging companion (RFC 0010) hooks.
3. **Retries are per-leg.** L2 retry runs inside each sub-RPC. A
   terminally failing leg fails the composed op; the L1.5 method
   does not restart from leg 0.
4. **Cancellation aborts the current in-flight leg.** Subsequent
   legs do not start.
5. **Composed ops default to non-idempotent.** Schema authors flag
   `idempotent: true` only when the composition is safe to repeat.

Sub-RPCs remain accessible at L1; consumers wanting fine-grained
control over the multi-RPC sequence bypass L1.5 and call L1
directly.

### Long-running operation helpers

A method with `long_running: true` plus a `poll_rpc:` gets two
L1.5 surfaces:

```
op := client.Reports.Generate(ctx, type, dateRange)
// fire-and-forget; returns an operation handle

result := client.Reports.GenerateAndWait(ctx, type, dateRange)
// polls poll_rpc until completion or ctx deadline
```

Semantics:

- **Deadline scope is total wait, not per-poll.** The context's
  deadline budgets the whole polling loop. Per-poll timeouts come
  from the L2 timeout interceptor's per-call default.
- **Poll backoff matches RFC 0006.** Full jitter, capped at L2
  retry's `MaxDelay`. Server-supplied `retry-after` overrides per
  RFC 0006.
- **Operation handle exposes `poll_rpc` directly** for consumers
  who prefer custom polling.

### Excluded services

Services under `excluded:` are dropped from L1 codegen via the
per-output `paths:` filter in `buf generate`. L1.5 cannot
reference them because the generated stubs literally do not
exist. Stronger than relying on L1.5 to omit them: a power user
reaching into L1 gets a compile error rather than silent access.

### Caching surface

L1.5 inherits caching from the L3 caching companion (RFC 0015)
when the consumer wires it; it does not expose per-call cache
controls. The interceptor's schema annotations are the right
place for that complexity.

L1.5 may expose two thin helpers for explicit cache management:

```
client.Cache.Refresh(client.Users.Get, userId)
client.Cache.Invalidate(client.Users.Get, userId)
```

These call the cache store directly using the same key
composition the interceptor uses. SDKs without the caching
companion wired skip the helpers at construction.

L1.5 never surfaces underlying response metadata of cached
responses; cached-metadata lossiness (RFC 0015 trade-off) stays
invisible at the consumer surface.

### Drift enforcement

A per-language drift-check tool runs in CI:

1. Parse `api-surface.yaml`.
2. Walk `sdk-ergo-{lang}` public-API AST.
3. Verify every YAML-declared method exists with matching
   required-param count and language-idiomatic optional surface.
4. Verify YAML flags (`composed`, `long_running`, `paginated`)
   map to the right L1.5 shape.
5. Fail CI on mismatch.

Tools are per-language (different AST libraries) but read the
same YAML and follow the same shape.

### Type mapping deferred

V1 passes protobuf types through unchanged. `int64 amount_cents`
stays `int64`; `google.protobuf.Timestamp` stays the protobuf
type for the language. A future RFC may introduce an opt-in
`type_mappings.yaml` for canonical domain types (Money, Date,
Duration) once consumer demand crystallises.

## Reference-level explanation

### YAML schema

```yaml
resources:
  <resource>:
    service: <fqn>             # full proto service name
    methods:
      <method>:                # L1.5 method name, lowercase
        rpc: <RpcName>         # underlying RPC; mutually exclusive with composed
        composed: [<RpcA>, <RpcB>, ...]  # multi-RPC ops
        required: [<field>, ...]
        optional: [<field>, ...]
        defaults:
          <field>: <value>
        paginated: bool
        long_running: bool
        poll_rpc: <RpcName>    # required when long_running=true
        idempotent: bool       # safety-gate hint for L2 retry

excluded: [<fqn>, ...]

type_mappings: {}              # reserved; empty in v1
```

### Per-language package shape

```
sdk-core-{lang}/
  gen/                         # Layer 1, buf-generated
  ...                          # Layer 2 in core, Layer 3 companions
sdk-ergo-{lang}/
  users.{ext}                  # L1.5 handwritten Users resource
  files.{ext}                  # L1.5 handwritten Files resource
  reports.{ext}                # L1.5 handwritten Reports resource
  client.{ext}                 # wires resources, accepts L2/L3 options
```

`sdk-ergo-{lang}` depends on the core SDK and on whichever L3
companions a given resource method exercises.

### Composed-op idempotency key derivation

```
composed_op_id = uuid()    // generated at L1.5 method entry
for leg_index, sub_rpc in composed:
    set metadata.idempotency-key = f"{composed_op_id}/{leg_index}"
    call sub_rpc(ctx, ...)
```

Distinct legs get distinct keys (independent retryability);
distinct composed-op invocations get distinct composed_op_ids
(concurrent calls do not collide).

### Phased rollout

- Phase 1 (this RFC): contract pinned, no code.
- Phase 2: `sdk-ergo-go` reference implementation.
- Phase 3: backports per language, one cycle each.
- Phase 4 (future): codegen replaces handwritten L1.5 once the
  shape proves stable; the YAML becomes the authoritative
  generator input.

## Drawbacks

- Handwritten in v1: N language implementations per resource
  method. Phase 4 codegen amortises eventually; until then every
  new method costs N small implementations plus drift-check
  updates.
- `api-surface.yaml` is a third source of truth alongside protos
  and generated stubs. The drift-check tool catches YAML-vs-AST
  divergence; YAML-vs-proto drift requires schema-author
  discipline.
- Composed ops can leave server state partially written if a leg
  fails. The L2 idempotency interceptor + a server that
  deduplicates by key makes consumer retries safe; without that
  combination, a retried composed op re-executes early legs.
- The `client.Cache.Refresh` / `Cache.Invalidate` helpers create
  a second cache-aware code path beside the interceptor.
  Documented as advanced use; consumers calling both can confuse
  themselves about cache state.
- Required-vs-optional discipline is human-enforced. A
  miscategorised field silently changes the L1.5 surface; only
  the drift check (signature shape) catches a subset of these.

## Rationale and alternatives

- **Ship L1.5 default-on.** Rejected. Layer 2 is the cross-SDK
  invariant; consumers can mix and match. Forcing L1.5 onto every
  consumer locks them into the resource grouping even when they
  prefer L1.
- **Skip L1.5 entirely; let consumers wrap.** Rejected. Without a
  pinned contract every consumer reinvents the wrapper. The
  ergonomic surface drifts unrecoverably within a single language,
  let alone across nine.
- **Generate L1.5 from proto annotations.** Rejected for v1.
  Per-language idiom mapping (functional options, builders,
  kwargs, named params) is too varied for a single annotation set
  to capture cleanly. Phase 4 codegen revisits this when the shape
  stabilises.
- **Atomic composed operations.** Rejected. Cross-RPC atomicity
  needs a transaction primitive no current Connect/gRPC protocol
  supports. Composed ops are best-effort sequential.
- **Per-call cache controls in L1.5.** Rejected. Cache concerns
  belong to the cache layer; lifting them into L1.5 duplicates
  configuration and confuses state management.
- **Type mapping in v1.** Rejected. Cross-SDK consistency cost
  is high and the win is per-domain. Defer.

## Prior art

- Stripe SDKs (Go, Python, Ruby, Node, Java, .NET): handwritten
  ergonomic surface over generated stubs, resource grouping,
  composed multi-call operations:
  https://stripe.com/docs/api
- AWS SDK high-level clients (`aws-sdk-go-v2`, `boto3` resource
  API): resource grouping with method renaming on top of
  generated low-level operations:
  https://docs.aws.amazon.com/sdk-for-go/v2/developer-guide/sdk-utilities.html
- Microsoft Kiota: schema-driven SDK codegen with per-language
  ergonomic surfaces; the shape Phase 4 codegen would target:
  https://learn.microsoft.com/openapi/kiota/overview
- Google Cloud client libraries: hand-curated resource methods
  per language with consistent naming across SDKs:
  https://cloud.google.com/apis/design/design_patterns
- Apollo Client: normalised cache + composed query API over
  GraphQL operations; prior art for L1.5 cache-aware surfaces:
  https://www.apollographql.com/docs/react/

## Unresolved questions

- Whether `api-surface.yaml` should live in the proto monorepo or
  a separate ergonomic-spec repo. Today's answer is alongside the
  protos; revisit if the YAML grows beyond a couple thousand
  lines.
- Cross-language naming for composed operations whose component
  RPCs do not share a verb. Today the YAML's `methods:` key
  arbitrates; revisit if natural-language disagreements emerge.
- LRO surfaces in languages with weak async support. The default
  polling loop assumes cooperative scheduling; callback-based
  variants may be needed for some targets.
- Whether `Cache.Refresh` should pre-populate via a one-shot
  fetch or schedule a background refresh. Intentionally
  unspecified pending consumer feedback.

## Future possibilities

- **Phase 4 codegen.** A protoc-style plugin reads
  `api-surface.yaml` and emits per-language L1.5. Handwritten
  implementations become regression baselines.
- **Type mapping registry.** Sibling `type_mappings.yaml` opting
  consumers into canonical types (Money, Date, Duration).
- **Cross-language conformance tests.** A shared fixture suite
  walks `api-surface.yaml` and asserts every SDK exposes the
  declared methods with the declared shape.
- **L1.5 telemetry.** Opt-in usage counters per ergonomic method
  feed deprecation decisions.
- **Composed-op compensation primitives.** Per-leg rollback
  annotations executed when a later leg fails. Resolves the
  partial-write drawback; out of scope until a real consumer
  asks.
