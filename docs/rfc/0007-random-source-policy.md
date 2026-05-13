# RFC 0007: Random source policy

- Status: Accepted
- Date: 2026-05-14
- Affects: every `sdk-core-*` repo that needs randomness (retry jitter,
  hedging delays, idempotency keys, sampling decisions).
- Depends on: RFC 0002 (layered SDK architecture).

## Summary

Every byte of randomness produced by an SDK comes from the language's
cryptographically-secure RNG. Predictable RNGs (`math/rand` in Go,
`java.util.Random` in Java, `Math.random()` in JavaScript, etc.) are
banned at the package level, not just where it matters for security.
The rule is uniform across SDKs so that a FIPS 140-3 audit against any
one SDK passes by construction, and there is no per-language exception
to remember.

## Motivation

Predictable RNGs leak into "non-security" use cases like retry jitter,
sampling, and load distribution. A FIPS 140-3 audit fails when any
randomness in the binary comes from a non-validated module, regardless
of how that randomness is used. Multiple SDKs in the family raises the
chance that one of them silently reaches for the cheap PRNG. Banning
the predictable RNGs at the SDK package level removes the failure mode
without per-call review.

The cost is real (CSPRNGs are slower than predictable PRNGs) but
irrelevant in the contexts where SDKs use randomness. Jitter happens
before a sleep; idempotency keys happen before a network round-trip.
The CSPRNG call takes microseconds; the operation it gates takes
milliseconds.

## Guide-level explanation

### Rule

All randomness produced by SDK code (Layer 2 and Layer 3) reads from
the language's cryptographically-secure RNG. No predictable RNG, even
for "non-security" callers like jitter. The rule applies regardless of
build flag (`GOFIPS140`, `FIPS_MODE`, etc.).

### Approved RNG per language

| Language | Source                                                          |
|----------|-----------------------------------------------------------------|
| Go       | `crypto/rand`                                                   |
| .NET     | `System.Security.Cryptography.RandomNumberGenerator`            |
| TS/Node  | `crypto.webcrypto.getRandomValues` (or `crypto.randomBytes`)    |
| Python   | `secrets` module                                                |
| Java     | `java.security.SecureRandom` (strong instance)                  |
| Kotlin   | `java.security.SecureRandom` via stdlib `kotlin.random.Random.Default` is NOT acceptable; use the JVM API directly |
| Swift    | `SystemRandomNumberGenerator` (CSPRNG-backed on Apple platforms) |
| Dart     | `Random.secure()`                                               |
| Rust     | `rand::rngs::OsRng` (or `getrandom` directly)                   |

### Jitter-source contract

When randomness feeds a jitter computation (RFC 0006 retry, hedging,
backoff elsewhere), the value is a uniform `[0, 1)` double sourced
from 8 bytes via the language's CSPRNG, then converted with the
canonical 53-bit recipe:

```text
bits  := uint64(8 bytes from CSPRNG) >> 11
sample := bits / (1 << 53)
```

Taking the top 53 bits matches the IEEE 754 double-precision
significand width, giving an unbiased uniform sample. SDKs implement
this once per language; the function signature returns the
`[0, 1)` value, not the raw bytes, so callers cannot accidentally
re-bias the distribution.

### Failure handling

If the CSPRNG call returns an error (effectively impossible on a
healthy Linux/macOS/Windows host, possible briefly at boot under
entropy starvation), the jitter helper returns `0.5`. Degrading to
mid-jitter is acceptable; panicking on boot-time entropy starvation
is not. Callers needing strict failure surfaces (key generation, etc.)
do not use the jitter helper and propagate the error.

### Pluggable hook

SDKs expose the jitter source as a function parameter on the
interceptor's options so tests can inject a deterministic source.
Production code never sets this parameter and the default uses the
CSPRNG. This is an escape hatch for unit tests, not a policy bypass
for production performance.

## Reference-level explanation

### What counts as "randomness in SDK code"

- Jitter draws (RFC 0006 retry, RFC-future hedging).
- Idempotency key generation (UUIDv7's random component).
- Sampling decisions if the SDK ever ships an OTel sampler.
- Any future feature that draws a number unpredictable to the caller.

### What does not count

- Test-fixture data (out of the SDK's shipped surface).
- Generated stub code's wire serialization (no randomness involved).
- Consumer code that imports the SDK and does its own randomness
  elsewhere. The rule binds SDK code, not consumer code.

### Per-language enforcement notes

- **Go**: the L2 allow-list guard (RFC 0003) does not reject
  `math/rand` because it ships in the stdlib. An additional lint rule
  (forbidigo or a custom check) is recommended in each Go SDK's
  `.golangci.yml` to reject `math/rand` and `math/rand/v2` imports.
- **.NET**: a Roslyn analyzer is wired in `Directory.Build.props` to
  flag `System.Random` usage in production code paths.
- **Python**: a `flake8` rule (`bandit` B311 or similar) catches
  `random.*` imports; SDK packages exclude these via per-module
  configuration.
- **Java/Kotlin**: a SpotBugs rule (`PREDICTABLE_RANDOM`) flags
  `java.util.Random` and `kotlin.random.Random`.
- **TS/Node**: an ESLint rule (custom or
  `no-restricted-syntax`) bans `Math.random()` in SDK source.
- **Rust**: a `cargo-deny` or `clippy::lint` ban on the `rand` crate's
  `thread_rng` and `SmallRng` types (only `OsRng` allowed).

Lint-rule implementation is per-SDK; this RFC pins the contract, not
the tooling.

### FIPS 140-3 alignment

Every approved RNG above routes through the OS-level CSPRNG or a
FIPS-validated module when one is available. A FIPS audit on any SDK
passes by construction; no per-SDK opt-in is required.

## Drawbacks

- CSPRNG calls cost more than predictable PRNG calls (roughly 500 ns
  vs 10 ns per draw in Go; similar ratios in other languages). For
  hot-path randomness this would matter. SDK randomness is never on a
  hot path; the cost is below the noise of the operation that follows.
- Per-language lint enforcement is per-SDK setup that this RFC does
  not centralise. A future RFC could pin the lint rule itself.
- The `0.5` fallback on CSPRNG failure is a quiet degradation. Loud
  failure would catch entropy starvation faster but blow up retries
  during boot-time recovery, which is the opposite of what backoff is
  for.

## Rationale and alternatives

- **Allow predictable RNG for "non-security" uses.** Rejected. The
  per-call review burden is permanent, and the cost saving is below
  the surrounding network noise.
- **Allow predictable RNG behind a build flag.** Rejected. A flag
  that flips production behaviour is exactly the kind of thing FIPS
  audits look for and reject; the rule must hold in every build.
- **Source jitter randomness only when FIPS mode is on.** Rejected.
  Per-environment behaviour change is harder to reason about than a
  uniform rule.
- **Use a language-specific seeded PRNG with crypto-seeded reseed.**
  Rejected. Adds complexity for a perf saving the SDK does not need.

## Prior art

- AWS Architecture Blog, "Exponential Backoff And Jitter":
  https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Go release notes, crypto/rand FIPS 140-3 module (1.24):
  https://go.dev/doc/go1.24
- .NET RandomNumberGenerator FIPS notes:
  https://learn.microsoft.com/dotnet/standard/security/cross-platform-cryptography
- Python secrets module:
  https://docs.python.org/3/library/secrets.html
- sdk-core-go/docs/adr/0001 (RNG and jitter) - Go-side
  implementation reference.

## Unresolved questions

- A central pinact-style helper that emits the per-language lint
  rule. Worth it once a third SDK lands and the manual setup count
  exceeds three.
- Whether `0.5` is the right fallback or whether some draws should
  fail loudly (e.g. UUIDv7 prefix on key endpoints). Today the SDK
  uses UUIDv7 with crypto-rand for keys and the fallback for jitter,
  which is the right split, but the boundary deserves documentation.
- Hardware-backed RNGs (TPM, HSM) for callers under stricter
  compliance regimes. Out of scope; the language CSPRNG already
  routes through hardware where available.

## Future possibilities

- Conformance tests that seed every SDK's jitter source with the
  same deterministic sequence and confirm identical backoff curves.
- A FIPS-mode integration test in CI: build with `GOFIPS140=v1.0.0`
  (Go), equivalent FIPS-mode flags in .NET/Java/Python, and confirm
  the SDK boots and runs the smoke suite.
- A bench harness that measures CSPRNG call cost per language to
  refute the perf argument with numbers rather than estimates.
