# sdk-scaffold

Language-agnostic Copier template for Pinguteca SDK libraries. Generates a
new SDK repository with the cross-cutting tooling layer plus one or more
language overlays.

## What you get

- **Cross-cutting:** mise (tool versions and tasks), Cocogitto (conventional
  commits), prek (pre-commit hooks), Renovate, secret scanning (Kingfisher),
  GitHub Actions Pinact, Octo STS per-workflow OIDC identities, OpenSSF
  Scorecard (public repos), gitsign commit verification, image/SVG
  optimization, ADR scaffolding, LICENSE menu.
- **Go overlay:** golangci-lint v2, GoReleaser (libraries: tag-driven release
  with attached SBOM and Cosign signatures), build and release workflows.
- **.NET overlay:** central package management, .slnx, NuGet lockfiles in
  CI, Directory.Build/Packages/targets, dotnet pack and push with NuGet
  Trusted Publishing.

## Generating a new repo

```bash
# Install copier once
uv tool install copier   # or pipx, pip, brew

# Generate
copier copy gh:Pinguteca/sdk-scaffold ./my-sdk
cd my-sdk
git init && git add . && git commit -m "chore: bootstrap from sdk-scaffold"
```

## Updating an existing repo

```bash
copier update            # pulls upstream improvements, prompts for new answers
```

## What's intentionally out of scope

- App-level release pipelines (Aspire deploy, container images with kos,
  multi-platform binary archives). Use `Pinguteca/dotnet-scaffold` for
  service projects.
- Proto/buf generation. SDK consumers wire that themselves once the
  upstream API contract is decided.
- Per-language registry publishing automation beyond what each ecosystem's
  Trusted Publishing flow gives you.

## Conventions captured here

See `docs/adr/` for the rationale behind each default. Each ADR documents
context, decision, consequences, and revisit conditions.
