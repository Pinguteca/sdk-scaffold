# RFC 0004: Companion module naming convention

- Status: Accepted
- Date: 2026-05-10
- Affects: every `sdk-core-*` repo's companion sub-modules; package
  registry coordinates (npm scope, PyPI distribution, NuGet, Maven,
  crates.io, pub.dev).
- Depends on: RFC 0002 (layered SDK architecture).

## Summary

Pin the published name of every Layer 3 companion module in every
Primary-tier language. Each ecosystem has its own naming idiom (npm
scopes, NuGet PascalCase, Cargo hyphenated, PyPI hyphenated, pub.dev
snake_case, Maven groupId/artifactId pairs, Go module paths). This
RFC names the canonical companion tokens (`otel`, `compression`,
`hedge`, etc.), the per-ecosystem mapping rule, and the small set of
cross-cutting decisions (language qualifier in name, version line,
deprecation contract).

## Motivation

RFC 0002 left companion naming as an unresolved question. Without an
answer:

- Each SDK first-publisher decides on the spot, and every later SDK
  is forced to follow whatever shape they picked.
- Documentation cannot reference companions by stable names.
- Cross-language search ("which package adds OTel for the Pinguteca
  SDK in language X?") becomes a per-language lookup.
- Renaming a companion after publish is a breaking change for every
  consumer of that ecosystem.

Pinning the names before `sdk-core-dotnet` ships keeps every later
SDK from having to retroactively realign.

## Guide-level explanation

### The canonical companion vocabulary

Every Layer 3 companion is named by a short, lowercase token that
maps to its directory in the repo:

| Token         | What it wraps                                    |
|---------------|--------------------------------------------------|
| `otel`        | OpenTelemetry instrumentation                    |
| `compression` | Brotli + Zstd (gzip stays in core)               |
| `hedge`       | Hedged requests                                  |
| `breaker`     | Circuit breaker                                  |
| `logging`     | Ecosystem-native structured logging adapter      |
| `presets`     | Canned interceptor compositions                  |
| `pkcs12`      | mTLS PKCS#12/PFX bundle loader                   |
| `cache`       | ETag and conditional-request caching             |
| `metrics`     | Metrics export (Prometheus / OTel metrics)       |

The token is the same in every ecosystem. Future companions add a
row here; renaming an existing token is a breaking change and goes
through a deprecation cycle (see "Reference-level explanation").

### Per-ecosystem mapping

The published name is derived mechanically from the token by the
ecosystem rule below. There is no hand-tuned exception list.

| Ecosystem | Published name                                                |
|-----------|---------------------------------------------------------------|
| Go        | `github.com/Pinguteca/sdk-core-go/<token>`                    |
| .NET      | `Pinguteca.Sdk.Core.<TokenPascal>`                            |
| TS/Node   | `@pinguteca/sdk-core-<token>`                                 |
| Python    | distribution: `pinguteca-sdk-core-<token>`                    |
|           | import: `pinguteca_sdk_core_<token>`                          |
| Java      | `com.pinguteca.sdk-core:<token>` (groupId:artifactId)         |
| Kotlin    | `com.pinguteca.sdk-core:<token>` (shares Maven coordinates)   |
| Rust      | `pinguteca-sdk-core-<token>`                                  |
| Dart      | `pinguteca_sdk_core_<token>`                                  |

Worked example for the OTel companion:

| Ecosystem | Coordinate                                                |
|-----------|-----------------------------------------------------------|
| Go        | `github.com/Pinguteca/sdk-core-go/otel`                   |
| .NET      | `Pinguteca.Sdk.Core.Otel`                                 |
| TS/Node   | `@pinguteca/sdk-core-otel`                                |
| Python    | `pinguteca-sdk-core-otel` / `pinguteca_sdk_core_otel`     |
| Java      | `com.pinguteca.sdk-core:otel`                             |
| Kotlin    | `com.pinguteca.sdk-core:otel`                             |
| Rust      | `pinguteca-sdk-core-otel`                                 |
| Dart      | `pinguteca_sdk_core_otel`                                 |

### Cross-cutting decisions

1. **No language qualifier in package names.** The registry already
   identifies the language (npm is JavaScript, crates.io is Rust,
   pub.dev is Dart, etc.). Embedding the language in the name is
   redundant. Go is the only exception, because the module path is
   the GitHub URL and so naturally carries the language token via
   the repo name (`sdk-core-go`).
2. **Repo names keep the language token.** `sdk-core-go`,
   `sdk-core-dotnet`, `sdk-core-ts`, `sdk-core-py`, `sdk-core-java`,
   `sdk-core-kotlin`, `sdk-core-rust`, `sdk-core-dart`. The repo is
   where you go to read the code; the package is what you install.
3. **Casing follows ecosystem norms** (lowercase hyphenated for
   npm/Cargo/PyPI/Maven, PascalCase for .NET, snake_case for
   Dart/Python imports). Tokens stay lowercase in every ecosystem
   except .NET.

## Reference-level explanation

### Token rules

A new companion token must be:

- Lowercase, ASCII letters and digits only. No hyphens or
  underscores inside the token; word breaks belong to the
  ecosystem-specific transformation.
- A single concept per token. `otel` good; `metrics-otel` bad
  (split into `metrics` and `otel`).
- Stable across languages. The same companion in every SDK uses
  the same token. The token table at the top of this document is
  the canonical list; PRs amend it before publishing a new
  companion.

### Per-ecosystem transformations

The token transforms to a published name by these rules:

- **Go**: append the token verbatim to the repo path:
  `github.com/Pinguteca/sdk-core-go/<token>`. Module path of the
  sub-module's `go.mod`.
- **.NET**: PascalCase the token (`otel` -> `Otel`,
  `compression` -> `Compression`, `pkcs12` -> `Pkcs12`), prepend
  `Pinguteca.Sdk.Core.`. NuGet package id and root namespace match.
- **TS/Node**: `@pinguteca/sdk-core-<token>` as the package name.
  Workspace path inside the repo is `<token>/` matching the Go
  shape.
- **Python**: distribution name is `pinguteca-sdk-core-<token>`
  (PyPI hyphenated). The import name uses underscores per PEP 8:
  `pinguteca_sdk_core_<token>`. Both come from the same package
  via `pyproject.toml` (`name` field for distribution, package
  directory for import).
- **Java / Kotlin**: groupId is `com.pinguteca.sdk-core`, artifactId
  is the token. Maven Central coordinate
  `com.pinguteca.sdk-core:<token>:<version>`. Kotlin reuses the
  same coordinates because the JVM ecosystem shares Maven.
- **Rust**: `pinguteca-sdk-core-<token>` as the crate name on
  crates.io. The crate's `lib.rs` re-exports symbols at the
  namespace `pinguteca_sdk_core_<token>` (Rust crate names auto-map
  hyphens to underscores at import).
- **Dart**: `pinguteca_sdk_core_<token>` as the pub.dev package
  name. Dart requires snake_case in package and import names.

### Versioning

Companion modules version independently of the core module. RFC
0002 already pinned this for Go (sub-module tags `<token>/vX.Y.Z`).
This RFC extends the rule to every ecosystem: the companion's
version is its own, not the core's. Consumers of a companion thus
declare the companion's version explicitly and inherit the core
through transitive constraints.

### Deprecation contract

Renaming a published companion (changing the token, or moving to
a new ecosystem-specific transformation) is a breaking change. The
process:

1. Publish a new companion under the new name.
2. Mark the old companion's published metadata as deprecated
   (npm `deprecate`, NuGet `<PackageReadme>` deprecation block,
   PyPI `Development Status :: 7 - Inactive`, etc.) with a
   pointer to the new name.
3. Keep the old companion buildable but no longer accept new
   features for at least one minor release of every Primary SDK.
4. Drop the old companion only when telemetry shows usage has
   fallen below the threshold defined in the future
   "Deprecation policy" RFC (out of scope here).

## Drawbacks

- Eight ecosystems means eight transformation rules to remember
  when adding a companion. Mitigated by the worked-example tables
  in this document and a future scaffold generator that emits the
  manifests automatically (RFC 0002 future possibility).
- The `com.pinguteca.sdk-core` Maven groupId hyphenates the
  middle segment. Some Java teams prefer dot-separated groupIds
  (`com.pinguteca.sdk.core`). Sticking with the hyphen keeps the
  repo name visible in the coordinate and matches the npm /
  Cargo / PyPI shape, at the cost of a minor JVM-conventional
  oddity. Reversible without a breaking change for first-time
  consumers.
- The Python distribution / import asymmetry
  (`pinguteca-sdk-core-otel` vs `pinguteca_sdk_core_otel`) is
  baked into PEP 8 and cannot be avoided. The doc spells it out
  every time the package is referenced in user-facing material.
- The "no language qualifier" rule disagrees with some ecosystems
  where the language qualifier is the norm (e.g. `aws-sdk-go-v2`
  on crates.io would never be just `aws-sdk-v2`). We accept the
  disagreement because the registry already implies the language.

## Rationale and alternatives

- **Suffix every package with the language token**
  (`pinguteca-sdk-core-go-otel`, `@pinguteca/sdk-core-ts-otel`,
  ...). Considered. Rejected: redundant with the registry name and
  doubles the typing for every consumer.
- **Single scope per language, no `sdk-core-` prefix**
  (`@pinguteca/otel`, `Pinguteca.Otel`, ...). Considered.
  Rejected: `otel` alone is too generic; readers cannot tell from
  the package name that it belongs to the SDK family.
- **Per-language repo for every companion** (one repo per token
  per language). Already rejected by RFC 0002 for the maintenance
  reason; named here for completeness.
- **Reuse OpenTelemetry's
  `@opentelemetry/instrumentation-<lib>` shape**
  (`@pinguteca/instrumentation-otel`). Considered. Rejected: most
  of our companions are not "instrumentation" in the OTel sense
  (compression, pkcs12, breaker, etc.) so the prefix would lie.

## Prior art

- npm scoped packages: https://docs.npmjs.com/about-scopes
- NuGet PackageId conventions:
  https://learn.microsoft.com/nuget/create-packages/package-authoring-best-practices#package-id
- PEP 8 import naming: https://peps.python.org/pep-0008/#package-and-module-names
- PEP 503 normalized project names:
  https://peps.python.org/pep-0503/#normalized-names
- Maven coordinate guidance:
  https://maven.apache.org/guides/mini/guide-naming-conventions.html
- Cargo naming guidelines:
  https://doc.rust-lang.org/cargo/reference/manifest.html#the-name-field
- Dart package naming:
  https://dart.dev/tools/pub/pubspec#name
- AWS SDK Go v2 multi-module names:
  https://github.com/aws/aws-sdk-go-v2
- OpenTelemetry SDK package names per language:
  https://opentelemetry.io/docs/languages/

## Unresolved questions

- Whether the JVM groupId is `com.pinguteca.sdk-core` (hyphenated
  middle segment) or `com.pinguteca.sdk.core` (dot-separated). The
  hyphenated form is recorded above; revisit before the first JVM
  publish.
- Whether the npm scope is `@pinguteca` or a more specific scope
  like `@pinguteca/sdk` (allowing future non-SDK packages under
  `@pinguteca`). The single-scope form is simpler; the qualified
  form keeps the SDK packages collocated.
- Reservation of registry names. The names defined here must be
  reserved on each registry (npm, PyPI, crates.io, NuGet, Maven
  Central, pub.dev) before a typosquatter takes them. Reservation
  itself is operational, not RFC-level, but the list is sourced
  from this document.
- Deprecation thresholds (when to drop a renamed companion) are
  flagged out of scope and need a follow-up RFC.

## Future possibilities

- A scaffold generator inside `sdk-scaffold` that, given a token,
  emits per-language manifests with the canonical name, group,
  and namespace already filled in. Removes the chance of drift
  during companion bootstrap.
- A registry-reservation script that takes the token list from
  this RFC and the per-language transformation rules, then walks
  the registries to confirm reservation status. Surfaces unowned
  names as alerts before a typosquatter notices.
- Automatic cross-references in generated documentation: when a
  language-A SDK doc mentions the OTel companion, the generator
  links to the language-B/C/... equivalents using the per-
  ecosystem transformation rule.
- A deprecation-policy RFC that pins the metrics, thresholds, and
  migration windows for renaming or removing a companion.
