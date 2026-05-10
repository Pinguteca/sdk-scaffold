# RFC 0001: Multi-language SDK feature parity baseline

- Status: Accepted
- Date: 2026-05-10
- Affects: every `sdk-core-*` repo and the contracts in `sdk-scaffold`

## Summary

Pin which languages get an SDK, what level of feature parity each one
commits to, and how those tiers are derived. Eight languages are
Primary and receive full SDKs. Ten more are Tier 2 and receive a
reduced surface, on demand.

## Motivation

Without a baseline, every feature decision is re-derived in
conversation. Pinning the matrix turns each call into a lookup.

It also names the maintenance bound: the wider the matrix, the more
bespoke per-language code we own. Making the cut between Primary and
Tier 2 explicit scopes the work.

## Guide-level explanation

### Tiers

**Primary** SDKs receive:

- The full Layer 2 surface (Must features in the feature catalogue):
  retry with jitter, timeouts, idempotency keys, token injection,
  OAuth 2.0 client_credentials, pagination, mTLS PEM, correlation ID
  propagation.
- Selected Layer 3 companion modules where the ecosystem has a
  first-class library: OTel, structured logging, advanced resilience,
  compression beyond gzip.
- CI matrix membership. Any Primary failure blocks the release.
- Documentation: language-specific README, runnable examples,
  generated API reference.

**Tier 2** SDKs receive:

- Layer 1 generated stubs.
- A minimum Layer 2 surface: token injection, retry, timeouts, mTLS
  PEM, pagination idiom, idempotency keys.
- No Layer 3 companions until a consumer asks.
- Best-effort CI: failures tracked as issues, not release blockers.
- Documentation: a quickstart only.

### How a language gets a tier

Each language is scored on the per-feature parity matrix (mature
first-party = 3, mature third-party = 2, experimental = 1, missing
= 0) across the in-scope features, then compared to the maximum.
The cut between Primary and Tier 2 is qualitative (consumer demand,
ecosystem direction) but anchored to the score so the call can be
revisited as ecosystems mature.

## Reference-level explanation

### In-scope features for the score

- Connect protocol client (Must)
- Retry with backoff and jitter (Must)
- Circuit breaker (Should)
- Hedged requests (Nice)
- OAuth 2.0 client_credentials (Must)
- PKCE / Authorization Code (Should)
- Compression: Gzip, Brotli, Zstd (Should)
- Pagination iterators (Should)
- Structured logging (Should)
- OpenTelemetry (Should)
- mTLS PEM (Should)
- mTLS PKCS#12 (Should)
- HTTP/3 (Nice)
- Connection pool controls (Should)

### Combined ranking

Score is the sum across the feature matrix. Percentage is the score
against the theoretical maximum. Tier is the operational commitment.

| Rank | Language | Score | %  | Tier    |
|-----:|----------|------:|---:|---------|
|    1 | .NET     |    45 | 94 | Primary |
|    2 | Go       |    40 | 83 | Primary |
|    3 | Kotlin   |    38 | 79 | Primary |
|    3 | Swift    |    38 | 79 | Tier 2  |
|    5 | Rust     |    37 | 77 | Primary |
|    5 | TS/Node  |    37 | 77 | Primary |
|    7 | Java     |    36 | 75 | Primary |
|    8 | Python   |    34 | 71 | Primary |
|    9 | C++      |    33 | 69 | Tier 2  |
|   10 | Ruby     |    32 | 67 | Tier 2  |
|   10 | Elixir   |    32 | 67 | Tier 2  |
|   12 | Dart     |    31 | 65 | Primary |
|   13 | PHP      |    27 | 56 | Tier 2  |
|   14 | Erlang   |    26 | 54 | Tier 2  |
|   15 | C        |    16 | 33 | Tier 2  |
|   16 | OCaml    |    11 | 23 | Tier 2  |
|   17 | Zig      |    10 | 21 | Tier 2  |
|   18 | Lua      |     6 | 13 | Tier 2  |

### Notes on tier assignments

- Swift ties Kotlin in score but sits in Tier 2 because there is no
  current Apple-platform consumer story. Promotion is a matter of
  demand, not score.
- Dart sits at rank 12, the lowest Primary, because Flutter is a
  stated target ecosystem.
- C, OCaml, Zig, and Lua sit deep in Tier 2 because their ecosystems
  lack mature Connect, OAuth, and OTel libraries. SDKs there will
  ship Layer 1 plus a hand-rolled Layer 2 minimum.

### Per-feature matrix

The per-feature scoring is maintained as an appendix and revised as
ecosystems shift (Zstd in .NET 11, HTTP/3 in `java.net.http`, Connect
maturity across runtimes). Appendix updates do not require a full RFC
revision so long as tier assignments remain correct.

## Drawbacks

- Eight Primary languages is a large matrix. Even with the layered
  architecture, eight implementations of every Must feature is real
  ongoing maintenance.
- Score is a snapshot. A language can move tiers as its ecosystem
  evolves; the RFC commits us to revisiting at each ecosystem change.
- Tier 2 risks becoming "Tier never". Without explicit demand, none
  of these SDKs get built. The contract has value if demand arrives.

## Rationale and alternatives

- **Single tier.** Reject. Eight Primary plus opportunistic ports
  reflects what we actually staff.
- **Three tiers (Primary / Standard / Best-effort).** Considered.
  Adds taxonomy without adding decisions. Two tiers cover the
  operational difference.
- **Tiers anchored only to demand, not to score.** Reject. Demand
  alone hides the maintenance cost of a language whose ecosystem
  fights us. Score keeps that visible.
- **Adopt an existing matrix (Stripe, AWS, Google).** Their matrices
  reflect their consumer mix, not ours. Reuse the shape, not the cut.

## Prior art

- Stripe's library reference: https://stripe.com/docs/libraries
- AWS SDK version support matrix:
  https://docs.aws.amazon.com/sdkref/latest/guide/version-support-matrix.html
- Google Cloud client library tiers:
  https://cloud.google.com/apis/docs/cloud-client-libraries
- Rust RFC process and template:
  https://rust-lang.github.io/rfcs/

## Unresolved questions

- Where the per-feature appendix lives: a sibling Markdown file or a
  data file (`docs/data/parity-matrix.csv`).
- How ecosystem-shift events are tracked: scheduled review (every six
  months) or event-driven (when a target stdlib ships a capability).
- Tier promotion criteria: consumer demand only, score threshold
  only, or both.

## Future possibilities

- A versioned support contract per tier (Primary patch-level fixes
  for N years; Tier 2 best-effort).
- A capability flag in every generated SDK exposing which Layer 3
  companions are wired, so consumers can branch on availability.
- Automatic tier review in the release workflow: a Primary SDK whose
  score drops below threshold for two consecutive releases gets
  flagged for triage.
