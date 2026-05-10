# RFC 0002: Layered SDK architecture

- Status: Accepted
- Date: 2026-05-10
- Affects: every `sdk-core-*` repo and the contracts in `sdk-scaffold`
- Depends on: RFC 0001 (parity baseline)

## Summary

Split every SDK into three layers. Layer 1 is generated stubs and
lives in consumer repos. Layer 2 is hand-written interceptors that
ship in the core SDK module with no third-party dependencies beyond
the language's stdlib (and stdlib-adjacent first-party extensions).
Layer 3 is opt-in companion modules that bridge the core to ecosystem
libraries. Each SDK is a mono-repo with sub-modules per companion so
the maintenance unit stays "one repo per language" while consumers
opt in to dependencies they actually use.

## Motivation

Two failure modes drive this RFC:

1. **All-in-core** packaging forces every consumer to download every
   third-party dependency the SDK touches (OTel, brotli, zstd, oauth
   helpers, pkcs12). Build size, audit surface, and supply chain
   pressure scale with feature count instead of consumer need.
2. **Repo-per-companion** packaging (one repo per language per
   feature) explodes the maintenance unit. Eight Primary languages
   times five-plus companions is forty-plus repos to release, sign,
   and version.

The middle path is one repo per language with multiple publication
units inside. Every Primary-tier ecosystem (Go modules, pnpm
workspaces, .NET solutions, Cargo workspaces, Gradle multi-module,
Python workspaces, melos) supports this natively.

A layered split also forces consistency. Behaviour that should be
identical across SDKs (retry curve, idempotency key lifecycle, token
refresh timing) lives in Layer 2 where we own the code. Behaviour
that should be idiomatic to the host ecosystem (logging, telemetry,
hedging primitives) lives in Layer 3 where we adapt to whatever the
ecosystem already provides.

## Guide-level explanation

### Layer 1 - generated stubs

What is in it: type-safe request/response types, serialization,
service client interfaces. Output of `buf generate`.

Where it lives: in the consumer's repo, regenerated from schema.
Not shipped from `sdk-core-*`.

Dependencies: only the Connect runtime for the target language.

Maintenance: zero. Regenerated mechanically.

### Layer 2 - core interceptors

What is in it: built-in interceptors implementing every Must feature
plus the Should features that can be done with stdlib-only.

Examples: retry with backoff and jitter, timeout propagation,
idempotency key generation, token injection, OAuth 2.0
client_credentials, mTLS PEM, pagination, correlation ID
propagation.

Where it lives: the root module of `sdk-core-<lang>`.

Dependencies: language stdlib plus stdlib-adjacent first-party
extensions (see "Reference-level explanation" below for the per-
language allow list). No third-party libraries.

Maintenance: written and owned per language. Same behavioural
contract across all Primary SDKs.

### Layer 3 - companion modules

What is in it: thin adapters that bridge the Layer 2 interceptor
contract to the ecosystem's first-class libraries.

Examples: OTel instrumentation, structured logging, advanced
resilience patterns (hedging, circuit breaker), compression beyond
gzip, metrics export.

Where it lives: as a sub-module in the same repo as Layer 2. Each
companion publishes independently so consumers pull only what they
import.

Dependencies: whatever the adapter wraps. Each companion declares its
own.

Maintenance: tracks the upstream ecosystem library. Companion can
be contributed by community once the Layer 2 contract is stable.

## Reference-level explanation

### Layer assignment by feature

| Feature                              | Priority | Layer | Notes                                             |
|--------------------------------------|----------|-------|---------------------------------------------------|
| Generated stubs                      | Must     | 1     | per consumer repo                                 |
| Retry with backoff and jitter        | Must     | 2     | identical curve across SDKs                       |
| Timeouts and deadline propagation    | Must     | 2     | wires Connect deadline                            |
| Idempotency key generation           | Must     | 2     | coupled to retry                                  |
| Token injection                      | Must     | 2     | bearer or API key                                 |
| OAuth 2.0 client_credentials         | Must     | 2     | including caching and proactive refresh           |
| mTLS PEM                             | Should   | 2     | stdlib TLS                                        |
| Pagination iterators                 | Should   | 2     | language primitives                               |
| Correlation ID propagation           | Should   | 2     | header forwarding                                 |
| Compression: Gzip                    | Should   | 2     | stdlib in every Primary lang                      |
| Compression: Brotli, Zstd            | Should   | 3     | third-party deps in most langs                    |
| Structured logging                   | Should   | 3     | adapt to ecosystem logger                         |
| OpenTelemetry                        | Should   | 3     | adapt to ecosystem OTel SDK                       |
| Circuit breaker                      | Should   | 3     | adapt to ecosystem resilience lib if available    |
| mTLS PKCS#12                         | Should   | 3     | extra parser dep                                  |
| Connection pool controls             | Should   | 2     | stdlib HTTP client knobs                          |
| PKCE / Authorization Code            | Should   | 3     | adapt to ecosystem oauth lib                      |
| Hedged requests                      | Nice     | 3     | only where ecosystem supports it                  |
| HTTP/3                               | Nice     | 3     | only where ecosystem supports it                  |
| ETag caching                         | Nice     | 3     | optional cache store dep                          |
| Metrics export                       | Nice     | 3     | adapt to ecosystem metrics lib                    |

### Per-language allow list for Layer 2

"Stdlib-adjacent first-party extensions" means modules maintained by
the same authority as the language stdlib, treated as de facto core
by the ecosystem.

| Language | Allowed in Layer 2                                             |
|----------|----------------------------------------------------------------|
| Go       | stdlib, `golang.org/x/*`                                       |
| .NET     | BCL, `Microsoft.Extensions.*`                                  |
| Java     | stdlib (`java.*`, `javax.*`)                                   |
| Kotlin   | stdlib, `kotlinx.*`                                            |
| TS/Node  | Node built-ins, `@types/node`                                  |
| Python   | stdlib                                                         |
| Rust     | std, `core`, `alloc`. Tokio is Layer 3.                        |
| Dart     | `dart:*`. `package:http` is Layer 3.                           |

Anything else is Layer 3, even if widely used.

### Repository layout

Each SDK is a mono-repo with the layout:

```
sdk-core-<lang>/
  <root manifest>          # core: stdlib-only Layer 2
  retry/   auth/   ...
  otel/                    # Layer 3 companion
  compression/             # Layer 3 companion
  resilience/              # Layer 3 companion
  ...
```

Each companion has its own manifest (`go.mod`, `package.json`,
`Cargo.toml`, `csproj`, `build.gradle.kts`, `pyproject.toml`,
`pubspec.yaml`). Versioning per companion is independent; releases
are tagged `<dir>/vX.Y.Z`. Local development uses the language's
workspace mechanism (`go work`, `pnpm-workspace.yaml`,
`Cargo workspace`, `dotnet sln`, Gradle settings, `uv workspace`,
`melos.yaml`).

### Companion adapter contract

Every Layer 2 interceptor exposes a typed contract that companions
target. The contract lives in the core module so the dependency
direction is `companion -> core`, never the reverse. Companions do
not re-export core types; consumers import from core for the types
and from the companion for the wiring.

### Tier 2 application

Tier 2 SDKs (RFC 0001) ship Layer 1 plus a reduced Layer 2 surface
(retry, timeout, token injection, idempotency, mTLS PEM, pagination)
and no companions. The mono-repo layout still applies; companion
directories are simply absent until demand surfaces.

## Drawbacks

- Multi-module versioning is fiddlier than single-module. Tag
  conventions, changelog generation, and release tooling have to
  understand sub-modules. Not a new problem; AWS SDK Go v2 and
  OpenTelemetry have solved it, but the tooling still needs writing
  per-repo.
- The Layer 2 allow list per language is judgement, not mechanism. A
  contributor can pull a forbidden dependency in a PR and the only
  guard is review. A lint rule per language can mitigate (a per-repo
  CI step) but is not free.
- Layer 3 companion stability constrains the core. Once a companion
  ships, the Layer 2 interceptor contract it wraps is effectively
  public API. Breaking Layer 2 cascades to every published companion.
- Eight Primary SDKs means eight implementations of every Layer 2
  feature. The architecture does not eliminate that cost, only
  contains it.

## Rationale and alternatives

- **All-in-core (single module).** Simpler maintenance, but every
  consumer pays for every dependency. Ruled out for browser, edge,
  WASM, and supply-chain-sensitive consumers.
- **Companion-per-repo (forty-plus repos).** Cleanest dependency
  story. Maintenance unit is too large; release coordination and
  signing pipelines do not scale.
- **Conditional compilation / build tags.** Does not solve the
  problem in any of the Primary languages: dependency manifests are
  module-level, not file-level, so deps are pulled regardless of
  compile-time selection.
- **Pure interface in core, no implementation.** Pushes Must-feature
  implementation onto consumers. Defeats the purpose of an SDK.
- **Hex monolith with feature flags.** A runtime flag still requires
  the dependency at build time. Same problem as all-in-core.

## Prior art

- AWS SDK Go v2 multi-module layout:
  https://github.com/aws/aws-sdk-go-v2
- OpenTelemetry Go component modules:
  https://github.com/open-telemetry/opentelemetry-go
- gRPC-ecosystem middleware (Go) sub-packages:
  https://github.com/grpc-ecosystem/go-grpc-middleware
- Tonic and Tower (Rust) layer model:
  https://github.com/tower-rs/tower
- `@opentelemetry/*` scoped npm packages:
  https://github.com/open-telemetry/opentelemetry-js
- Microsoft.Extensions.Http.Resilience packaging:
  https://learn.microsoft.com/dotnet/core/resilience/http-resilience

## Unresolved questions

- Naming convention for companion modules across languages. Options:
  scoped (`@pinguteca/sdk-core-otel`, `Pinguteca.Sdk.Core.Otel`),
  suffixed (`sdk-core-go-otel`), or directory-only with no rebrand
  (Go: `github.com/Pinguteca/sdk-core-go/otel`).
- Whether to enforce the Layer 2 allow list with a CI lint rule per
  language, or rely on review.
- Versioning policy: do companions track core's version, or version
  independently? Independent is simpler; tracking is more
  predictable for consumers.
- Whether the companion adapter contract is a Layer 2 export or
  lives in a dedicated `contract/` sub-module that both core and
  companions depend on (avoids the "core is API for companions"
  coupling).
- How Tier 2 SDKs handle features that are Layer 3 in Primary SDKs
  but stdlib-feasible in their language (e.g. Brotli is stdlib in
  Erlang but Layer 3 in Go).

## Future possibilities

- A capability discovery API in core: `caps.Has("otel")` returns
  true if the OTel companion is wired. Lets consumers branch on
  availability at runtime.
- Cross-language conformance tests: a contract suite consumers can
  point any Layer 2 implementation at to verify behavioural parity.
- Community-contributed companions for ecosystem libraries the team
  does not maintain, with a documented promotion path from
  community to first-party.
- A scaffold generator inside `sdk-scaffold` that lays out a new
  companion (manifest, CI, README) given a language and a feature
  name.
