# Design docs

Documentation about **the project itself**, not user-facing API references.
ADRs capture cross-cutting decisions inherited from the upstream
sdk-scaffold template plus any project-specific defaults this repo adds.

## Contents

- `adr/` — Architecture Decision Records. Each ADR records a default with
  Context / Decision / Consequences / Revisit-when sections.

## When to add an ADR

Add one when:

- A default would be surprising to a new contributor (RNG choice, error
  model, retry strategy, etc.).
- A tool or library was rejected and someone might propose it again later.
- A compliance posture (FIPS 140-3, SLSA, supply chain) shapes the
  implementation.

Don't ADR routine bumps, refactors, or implementation details that are
obvious from reading the code.
