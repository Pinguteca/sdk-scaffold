# RFC 0003: L2 dependency allow-list CI guard

- Status: Accepted
- Date: 2026-05-10
- Affects: every `sdk-core-*` repo's CI pipeline.
- Depends on: RFC 0002 (layered SDK architecture).

## Summary

RFC 0002 fixes a per-language allow list for what may appear in a Layer
2 (root module) dependency manifest. RFC 0002 left enforcement open:
"judgement, not mechanism." This RFC closes that gap by requiring
every Primary-tier SDK repo to ship a CI guard that fails the build
when the root module's direct dependencies escape the allow list. The
guard is small, language-specific, and run as part of the existing
`mise run lint` task so contributors hit it before pushing.

## Motivation

The allow list is a contract that drifts silently. A contributor adds
a dependency for what looks like a Must feature, the PR reviewer does
not catch the ecosystem mismatch, the dep ships in core, and every
consumer pays. By the time a parity audit catches it, the dep is
load-bearing and removing it is a breaking change.

A CI guard fails at PR time, when removing the dep is cheap. It also
forces the conversation about whether the new feature belongs in
Layer 2 at all, or should split into a Layer 3 companion sub-module.

The guard is not a substitute for review; it is a backstop. Reviewers
still judge whether a dep is appropriate even when it is on the
allow list.

## Guide-level explanation

### What the guard checks

For each `sdk-core-*` repo, the guard inspects the **root module's
direct dependencies only**. Indirect deps are out of scope: they are
pulled in by deps we already accepted, and pinning the allow list
across the transitive graph would be impractical.

The check passes when every direct dep falls into one of:

1. The language's stdlib-adjacent allow list from RFC 0002 (e.g.
   `golang.org/x/*`, `Microsoft.Extensions.*`, `kotlinx.*`).
2. The Connect runtime exemption list from RFC 0002 (e.g.
   `connectrpc.com/connect`, `google.golang.org/protobuf`).

A failing check prints the offending dep and the allow-list snippet
it violated, so the contributor sees the contract immediately.

### What the guard does NOT check

- Layer 3 sub-module manifests. Companions are explicitly allowed to
  depend on whatever they wrap; that is the point of the layer.
- Test-only deps in `_test.go` files (Go), `tests/` directories
  (Python), or framework-specific test scopes (`testImplementation`
  in Gradle, `Test.csproj` in .NET). Tests can pull mocks, fixtures,
  or assertion libraries without affecting consumers.
- Dev-time tooling (linters, formatters, code generators) declared in
  `mise.toml`, `.tool-versions`, or equivalent. These do not ship to
  consumers.

### Where the guard lives

In each repo's `mise run lint` task chain, after the language linter
and before the lint task succeeds. CI runs `mise run lint` in the
existing build workflow, so no new workflow file is needed.

The implementation is a small script committed to the repo (e.g.
`tools/check-l2-deps/main.go` for Go, `tools/check-l2-deps.ts` for
TS/Node, etc.). Implementation detail is per-repo and tracked by a
local ADR; this RFC pins only that the guard exists, runs in CI, and
checks the items above.

## Reference-level explanation

### Per-language implementation hooks

| Language | Manifest source                | Direct-dep filter                                    |
|----------|--------------------------------|------------------------------------------------------|
| Go       | `go.mod` `require` block       | exclude lines tagged `// indirect`                   |
| .NET     | `*.csproj` / `Directory.Packages.props` | top-level `<PackageReference>` entries only |
| TS/Node  | `package.json`                 | `dependencies` only (skip `devDependencies`)         |
| Python   | `pyproject.toml`               | `[project.dependencies]` (skip `[dependency-groups.*]`) |
| Java     | `build.gradle.kts` / `pom.xml` | `implementation` / `api` only (skip `testImplementation`) |
| Kotlin   | same as Java                   | same as Java                                         |
| Rust     | `Cargo.toml`                   | `[dependencies]` only (skip `[dev-dependencies]`)    |
| Dart     | `pubspec.yaml`                 | `dependencies` only (skip `dev_dependencies`)        |

### Allow-list source of truth

Each repo carries the allow list as a small data file
(`tools/check-l2-deps/allowlist.txt` or equivalent), one prefix per
line. The file is the operational artifact; RFC 0002 is the
documentation that explains why each entry is on it. When RFC 0002
changes (e.g. a new ecosystem-shift event promotes a module to
stdlib-adjacent), the corresponding allow-list files are updated in
the same PR series.

A CI cross-check between RFC 0002's tables and the per-repo files is
a future possibility (see "Future possibilities").

### Failure behaviour

The guard exits non-zero when any direct dep is not on the allow
list. Output format:

```
ERROR: dependency 'github.com/example/foo' is not on the L2 allow list.
Allow list (G:\Workspace\Pinguteca\sdk-core-go\tools\check-l2-deps\allowlist.txt):
  - golang.org/x/*
  - connectrpc.com/connect
  - google.golang.org/protobuf
  - google.golang.org/genproto/googleapis/*
If this dep belongs in Layer 2, add it to the allow list and update RFC 0002.
If it belongs in Layer 3, move the package that uses it into a companion sub-module.
```

The message names both paths so contributors do not assume the only
fix is "add to allow list".

## Drawbacks

- A new script per language to maintain. Low-cost individually but
  multiplied by eight Primary languages it is non-trivial.
- The data file (allow-list per repo) duplicates information that
  RFC 0002 already encodes. Drift between the two is possible.
  Documented in "Future possibilities" as a candidate for a
  RFC-to-data check.
- False negatives: the guard cannot catch a dep that masquerades as
  a stdlib-adjacent prefix (e.g. a malicious package on a
  `golang.org/x/...` look-alike domain is impossible because
  `golang.org/x/*` is uniquely owned, but a fork of
  `Microsoft.Extensions.X` published by someone else would slip
  through if the allow list checks only by prefix). Mitigated by
  publish-source pinning at the package manager level (we already
  pin sources for npm, NuGet, Cargo, etc.), but worth flagging.

## Rationale and alternatives

- **Rely on review, no guard.** Status quo. Drift is silent until
  parity audit catches it months later. Rejected.
- **Hard-code the allow list in the language linter (e.g. a custom
  golangci-lint rule).** Considered. More invasive, harder to share
  the data file across tools, and ties enforcement to the linter's
  configuration model. Rejected in favour of a small script.
- **Generate the allow-list file from RFC 0002 at lint time.**
  Considered for the future. Adds a parser for the RFC's Markdown
  table and another moving piece. Worth doing once the table
  stabilizes; not worth doing while the RFC is still being amended.
- **Block at PR time only, not in `mise run lint`.** Rejected:
  contributors should hit the guard locally before pushing.

## Prior art

- Renovate's package allow lists for monorepo policies:
  https://docs.renovatebot.com/configuration-options/#allowedversions
- Cargo's `cargo-deny` (Rust): https://github.com/EmbarkStudios/cargo-deny
- npm's `package-lock-only` mode for stricter dep tracking:
  https://docs.npmjs.com/cli/v10/configuring-npm/package-lock-json
- .NET's CentralPackageManagement enforcement via build targets:
  https://learn.microsoft.com/nuget/consume-packages/central-package-management

## Unresolved questions

- Whether the allow-list data files should live in each repo or
  centrally in `sdk-scaffold` and be copied into each SDK at scaffold
  time.
- Whether to extend the guard to companion sub-modules (e.g. ensure
  no companion accidentally depends on a peer companion in a way
  that creates a layer-direction violation).
- Whether `tools/check-l2-deps` is the canonical name across
  languages, or each ecosystem keeps its idiom (e.g. `scripts/`
  in TS, `Tools/` in .NET).

## Future possibilities

- A meta-check that parses RFC 0002's allow-list tables and verifies
  the per-repo data files match. Catches drift in either direction.
- A reverse check: enumerate every Layer 3 sub-module's deps and
  confirm none of them appear as a direct dep in the root module.
  Today this is impossible by construction (the layer-direction rule
  is enforced by import-graph review), but a script makes the rule
  testable.
- Surface the guard's output as a GitHub PR comment that explains
  the allow list to first-time contributors.
- Cargo-deny-style integration that catches license, advisory, and
  source-domain violations alongside the allow list.
