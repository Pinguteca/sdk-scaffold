# RFC 0018: Integration test harness

- Status: Accepted
- Date: 2026-06-07
- Affects: every `sdk-core-*` repo. Each SDK ships an integration
  test surface that boots a Connect-speaking server and exercises
  the L2 interceptor matrix against real network traffic.
- Depends on: RFC 0002 (layered architecture) for where the surface
  sits, RFC 0006 (retry contract), RFC 0008 (resilience presets),
  RFC 0013 (hedged requests), RFC 0014 (mTLS), RFC 0017 (OAuth
  flows) for what gets asserted.

## Summary

Pin the shape of every SDK's integration test surface: which server
to mock against, how to pin its image, what `.proto` contract each
SDK must exercise, and which interceptor behaviours must be covered
end-to-end. The server is FauxRPC, distributed as a Docker image.
The proto contract is per-SDK; the harness pattern is shared.

## Motivation

Unit tests of the L2 interceptors cover decision logic in isolation
with stubbed transports. They miss the wire: gRPC trailers vs
HTTP/2 headers, Connect protocol error mapping, real
`Accept-Encoding` negotiation, real deadline propagation, real TLS
behaviour when an interceptor swaps the handler.

Each SDK already has its own integration story (or none). Without a
contract:

1. SDKs adopt different mock servers, so the behaviour the .NET
   tests assert against is not the behaviour the Go tests assert
   against. Drift hides in the harness.
2. Image pinning practice drifts. One repo pins by tag, another by
   digest, another floats `:latest`. Supply-chain posture varies
   per-SDK for no good reason.
3. Coverage gaps emerge unequally. .NET tests retry but not hedge;
   Go tests hedge but not breaker. The parity matrix lies.

Three questions need cross-SDK answers:

1. What mock server, and how is it pinned.
2. What contract shape must each SDK exercise.
3. Which interceptor behaviours are mandatory at the integration
   layer rather than optional.

## Guide-level explanation

### Server choice

FauxRPC. Descriptor-driven, single binary, one port serves gRPC +
gRPC-Web + Connect + REST. Distributed as `sudorandom/fauxrpc` on
Docker Hub. Has a Go `testcontainers` integration that validates
the orchestration pattern; other languages reproduce it through
their own container-orchestration idiom.

Alternatives considered and rejected:

- **Hand-rolled mock per SDK**: redoes the work, drifts.
- **Buf Conformance suite**: tests Connect protocol conformance,
  not SDK behaviour. Orthogonal concern.
- **Real staging environment**: hard dependencies on availability
  and credentials in CI. Belongs in a separate contract-test
  harness, not this one.

### Image pinning is digest-only

Every SDK pins FauxRPC by SHA-256 digest:

```
docker.io/sudorandom/fauxrpc@sha256:<hex>
```

Never by tag. Never `:latest`. Each SDK picks its own digest; the
RFC does not pin a shared version because release cadences differ
and a shared pin would block one SDK on another's upgrade window.

Rationale: a tag is mutable upstream. Pinning by digest is the same
posture as the cross-org ban on GHA caches (cache poisoning is the
threat model). A bumped digest goes through a PR that records the
upstream release link in the body so the change is auditable.

### Descriptor input

FauxRPC consumes a protobuf `FileDescriptorSet` in `binpb` form,
produced by either:

- `buf build -o tests/.../contract.binpb`, or
- `protoc --descriptor_set_out=tests/.../contract.binpb --include_imports`.

The `.binpb` artifact is committed to the repo. Reasons:

- CI does not need `buf` or `protoc` installed for the common case
  (no proto change in the PR).
- The exact bytes FauxRPC loads are reviewable in PRs that touch
  the contract.
- A mise task (`proto:descriptor` or equivalent) regenerates the
  file; a CI check verifies idempotency on PRs that touch the
  `.proto`.

### Sample `.proto` contract

Each SDK owns its own minimal contract under
`tests/<integration-project>/proto/`. The contract is not shared
across SDKs because:

- The shape is a harness implementation detail. Sharing it would
  couple every SDK release to a shared schema bump.
- Tests assert SDK behaviour, not contract conformance, so the
  exact field set does not matter.

The contract MUST cover at minimum:

- One unary RPC.
- One server-streaming RPC.
- One client-streaming RPC.
- One bidirectional-streaming RPC.

Without all four, interceptor coverage has holes (e.g. retry
behaviour differs between unary and streaming).

### Mandatory interceptor coverage

Every SDK's integration tests MUST exercise:

| Interceptor          | Assertion |
|----------------------|-----------|
| retry                | injected `Unavailable` triggers configured retry count and final success or `DeadlineExceeded` |
| circuit breaker      | sustained injected failure trips breaker; subsequent call short-circuits before network |
| hedge                | latency injection on first attempt; hedged second attempt wins; only one response surfaces |
| timeout              | client-side deadline shorter than server latency surfaces as `DeadlineExceeded` |
| auth + token source  | injected token appears in server-received metadata; rotation across requests |
| OAuth grants         | for SDKs shipping `sdk-core-*-oauth`: token endpoint flow against a FauxRPC-mocked IdP |

Compression and pagination integration tests are OPTIONAL. Add
when the SDK ships the feature; do not gate the harness on them.

### Boundary

Integration tests are additive to unit tests, not a replacement.
Unit tests stay the primary coverage mechanism (fast, deterministic,
no Docker). Integration tests catch wire-level drift that unit
tests cannot see.

Integration tests assert SDK behaviour. They do NOT assert FauxRPC
behaviour; FauxRPC is upstream, its bugs are upstream's problem.
If a test fails only because FauxRPC changed, the digest bump PR is
where that surfaces.

### Orchestration is per-language idiom

How the container boots is each SDK's call:

| SDK    | Orchestration                                                                 |
|--------|-------------------------------------------------------------------------------|
| .NET   | Aspire AppHost via `TUnit.Aspire`; container resource with bind-mounted `.binpb` |
| Go     | `fauxrpc/testcontainers` package, or raw testcontainers-go                    |
| Dart   | TBD; likely raw docker invocation from a test fixture until a Dart           |
|        | testcontainers equivalent matures                                            |

The RFC does not pin orchestration tooling because each language's
fixture ergonomics differ. What is pinned: the image source, the
pinning rule, the descriptor format, the contract shape, and the
coverage matrix.

### Codegen is per-language idiom

Client codegen for the integration tests uses each SDK's native
toolchain:

| SDK    | Codegen                                                                       |
|--------|-------------------------------------------------------------------------------|
| .NET   | `Grpc.Tools` NuGet, `<Protobuf Include="..."/>` MSBuild items                 |
| Go     | `buf generate` with local plugins                                             |
| Dart   | `protoc_plugin` package                                                       |

`buf` is required server-side to build the `.binpb` descriptor
regardless of the client codegen path. That is the only shared
toolchain dependency.

## Reference-level details

### Per-SDK layout

```
sdk-core-<lang>/
  tests/
    <integration-project>/
      proto/
        contract.proto
        contract.binpb         # committed; regenerated by mise task
      <fixtures>/
      <tests>/
```

### Digest rotation

A digest bump is a single-line change in one well-known location
per SDK (mise task, AppHost source, or testcontainers fixture, not
all three). PR body links the upstream FauxRPC release notes.
Reviewer verifies the link before approving.

### CI gating

Integration tests run on every PR that touches `tests/<integration-
project>/` or any L2 interceptor. SDKs may opt to run them on every
PR if startup cost is tolerable; the harness does not pin the
trigger policy.

## Drawbacks

Docker is a hard dependency for running the suite locally. No
in-process fallback. Contributors without Docker cannot run the
integration tests, only the unit suite.

Container startup adds ~1-5s per test class to wall-clock time.
Acceptable for nightly or per-PR-on-relevant-paths; not acceptable
for tight inner-loop TDD on the interceptors themselves (unit
tests stay primary for that).

FauxRPC's synthetic responses do not catch real-server quirks
(timeouts under load, partial writes, malformed framing from
specific server implementations). A future contract-test harness
against a real staging Connect server is the right answer to that
class of bug, not this RFC.

Digest pinning blocks automated dependabot-style bumps. Each
upgrade is a human review. That is the point.

## Unresolved questions

- Whether per-test schema swaps via `fauxrpc registry add` warrant
  blessing in this RFC. Current shape: out of scope; add to the
  RFC if a second SDK needs the pattern.
- Whether telemetry assertions (OTel spans, metrics) are pinned in
  a follow-up RFC or left per-SDK. .NET gets OTel capture free via
  `TUnit.OpenTelemetry`; Go and Dart have no equivalent yet.
- Whether to require running integration tests on every PR
  cross-SDK, or leave the trigger policy per-SDK.

## Future work

- Contract-test harness against a real staging Connect server,
  separate from this RFC.
- Telemetry assertion contract (spans emitted per interceptor,
  attributes pinned).
- Performance benchmark harness reusing the same `.binpb`
  descriptor.
