# RFC 0011: Compression strategy

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `compression` Layer 3 companion
  module on both client and handler sides.
- Depends on: RFC 0001 (multi-language parity baseline),
  RFC 0002 (layered SDK architecture).

## Summary

Pin a three-algorithm compression matrix across every SDK: Brotli,
Zstd, and Gzip, with Brotli as the default Send compression and Gzip
as the universal fallback. Ship the providers as a **Layer 3
companion module** (separate package, opt-in by dependency) because
Brotli or Zstd require a third-party implementation in most target
languages and Layer 2 forbids third-party dependencies outside the
RPC runtime itself. The first SDK (Go) shipped this as a local ADR;
pinning it across SDKs prevents a third implementer from picking
gzip-only, different defaults, or smuggling the third-party deps into
core. The contract is the algorithm set, the default, the negotiation
rule, and the layer placement. The wire mechanism differs per
protocol (Connect uses HTTP-level `Content-Encoding`; gRPC uses
message-level `grpc-encoding`) and the implementation library
differs per language.

## Motivation

Wire size matters. JSON and text-encoded protobuf payloads compress
well; uncompressed traffic costs bandwidth, latency, and money for
every SDK consumer. The naive defaults shipped by each language's
RPC library cover only Gzip; modern alternatives (Brotli, Zstd) ship
meaningfully better ratios or speed but require explicit registration
in most stacks.

Two cross-SDK questions:

1. **Which algorithms to register?** Brotli and Zstd are the two
   modern alternatives to Gzip. Brotli wins on ratio for text-heavy
   payloads; Zstd wins on speed for binary or high-throughput
   server-to-server traffic. Gzip stays as universal fallback.
2. **Which to use by default for outbound requests?** The Send
   default determines what consumers get without per-call
   configuration. The wrong default produces uncompressed requests
   on a non-trivial fraction of deployments.

Without a pinned answer, every SDK author defaults to whatever their
language stack ships (typically gzip-only) and consumers see different
wire behaviour depending on which SDK they import. Locking this in
RFC space keeps the matrix and the defaults identical across the
family.

## Guide-level explanation

### Layer placement

Compression ships as a **Layer 3 companion module**, not in the Layer
2 core package. Per RFC 0002:

- Layer 2 is built-in interceptors and helpers with zero third-party
  dependencies beyond the chosen RPC runtime itself.
- Layer 3 is companion packages that may pull third-party deps;
  consumers opt in by adding the dependency.

Every target language needs at least one third-party implementation
to register Brotli or Zstd:

- Go has no stdlib Brotli or Zstd; both algorithms require external
  modules (`andybalholm/brotli`, `klauspost/compress/zstd`).
- .NET has stdlib Brotli (`System.IO.Compression.BrotliStream`) and
  Gzip, but Zstd requires a third-party package (`ZstdSharp.Port`)
  until stdlib support lands.
- Rust uses `brotli` and `zstd` crates outside the stdlib.
- Java needs `brotli4j` and `zstd-jni`.
- TS / Node has stdlib Brotli and Gzip but needs an external Zstd
  module.
- Python, Dart, Swift all need external packages for at least one of
  the two non-Gzip algorithms.

To keep the Layer 2 zero-third-party rule clean and to give every
SDK a consistent shape, compression is Layer 3 across the family
even in languages where one or two of the three algorithms could be
satisfied by stdlib. The companion module groups Brotli and Zstd
together; Gzip is left to whatever the RPC runtime registers by
default (Grpc.Net.Client, Connect-Go, etc. all register Gzip as a
built-in).

A consumer that wants compression adds the companion dependency
(`Pinguteca.Sdk.Core.Compression` for .NET, the `compression`
sub-module for Go, etc.) and wires the providers onto their channel
or handler using the companion's helper.

### Three algorithms, one default

Every SDK registers three algorithms on both client and handler:

| Algorithm | Header value | Role                                          |
|-----------|--------------|-----------------------------------------------|
| Brotli    | `br`         | Default Send. Highest realistic acceptance.   |
| Zstd      | `zstd`       | Opt-in via negotiation. Best speed/ratio.     |
| Gzip      | `gzip`       | Universal fallback. Always advertised.        |

Brotli is the **default Send compression**. The client compresses
outbound requests with Brotli unless the server's advertised
Accept-Encoding (Connect) or `grpc-accept-encoding` (gRPC) excludes
it; in that case the client falls back to Zstd if advertised, then
Gzip.

Why Brotli as the default:

- Proxy and CDN acceptance is ~95% as of 2026 (Cloudflare, Fastly,
  Akamai, CloudFront, Google Cloud CDN, modern nginx/HAProxy/Envoy
  builds all decompress Brotli on ingress).
- Text-payload ratio leads Zstd by 10-20% on JSON and text-encoded
  protobuf, which dominates SDK consumer traffic.
- Browser support shipped in 2017; Connect-Web clients negotiate
  Brotli natively.

Why not Zstd as the default:

- Server-side acceptance is ~70% as of 2026. Cloudflare, Fastly, and
  CloudFront shipped support in 2024, but enterprise on-prem proxies
  and many nginx deployments still lack it. A Zstd default would
  silently downgrade those consumers to uncompressed or gzip.

Why register Zstd at all:

- Inside high-throughput server-to-server topologies, Zstd's
  decompression speed advantage is large enough to justify the
  registration. Consumers controlling both ends of a deployment can
  flip the default Send compression to Zstd per RFC-0001's
  per-consumer configurability allowance.

### Negotiation rule

Negotiation is protocol-defined and the SDK does not invent its own
algorithm:

- **Connect-protocol SDKs** (Go, TS, Swift, Kotlin, Dart, Python):
  the client sets `Accept-Encoding` for inbound responses and
  `Content-Encoding` for outbound requests. The server's response
  carries `Content-Encoding` indicating which algorithm it used. The
  Connect runtime handles the round-trip.
- **gRPC-protocol SDKs** (.NET, Java, Rust): the client sets
  `grpc-accept-encoding` for inbound responses and `grpc-encoding` on
  the outbound message frame. The server matches by header set on
  registered compressors. The gRPC runtime handles negotiation.

Each SDK registers compressors with its language's RPC stack and
does not implement message-level negotiation manually.

### Default Brotli quality level

Brotli quality level 4 (range 0..11). Level 4 gives ~90% of the
best-level ratio at a fraction of the CPU cost. The sweet spot for
RPC traffic where compression and decompression both happen on the
request path with latency budgets to respect.

Higher levels (6, 8, 11) marginally improve ratio at much higher CPU
cost and rarely pay back for typical SDK payload sizes (~1-100 KB).

### Default Zstd level

Use the library's default level. Per-library defaults are well-tuned
for general use; explicit overrides are deferred until production
traffic shows a wrong trade-off.

### Pure-language dependencies, no CGO/JNI

Where possible, each SDK uses pure-language implementations of Brotli
and Zstd rather than C-binding wrappers:

- **Static binary builds.** CGO/JNI breaks `CGO_ENABLED=0` builds in
  Go and complicates Java native-image / GraalVM builds.
- **FIPS 140-3 posture.** Native binding wrappers often link OpenSSL
  or other crypto material the SDK does not control; the audit
  surface grows.
- **Supply-chain auditability.** Pure-language packages are easier to
  vendor, mirror, and scan than packages that pull in compiled
  artifacts.

The exception is languages with no viable pure-language
implementation (e.g. Swift, where `libzstd` via Compression framework
or Swift Package binding is the only path). Such cases are documented
per-SDK in the local ADR.

## Reference-level explanation

### Per-language implementation matrix

| Language | Brotli source                                   | Zstd source                                | Gzip source                  |
|----------|-------------------------------------------------|--------------------------------------------|------------------------------|
| Go       | `github.com/andybalholm/brotli` (pure Go)       | `github.com/klauspost/compress/zstd` (pure Go) | stdlib `compress/gzip`     |
| .NET     | stdlib `System.IO.Compression.BrotliStream`     | `ZstdSharp.Port` (pure managed)            | stdlib `System.IO.Compression.GZipStream` |
| TS / Node| stdlib `zlib.brotliCompress` (Node 11.7+)       | `@mongodb-js/zstd` or `fzstd`              | stdlib `zlib.gzip`           |
| Java     | `com.aayushatharva.brotli4j` (pure Java where avail) | `com.github.luben:zstd-jni`            | stdlib `java.util.zip.GZIPOutputStream` |
| Kotlin   | same as Java (JVM target)                       | same as Java                               | same as Java                 |
| Python   | `brotli` (pure C ext, no alt) or `brotlicffi`   | `zstandard` (pure C ext) or `pyzstd`       | stdlib `gzip`                |
| Rust     | `brotli` crate (pure Rust)                      | `zstd` crate (Rust bindings to libzstd)    | `flate2` crate               |
| Dart     | `brotli` pub package                            | `zstandard` pub package                    | stdlib `dart:io` `GZipCodec` |
| Swift    | `swift-brotli` package or `Compression` framework | `libzstd` via SPM binding                | `Compression` framework (zlib) |

Where the de-facto package is a C-binding (e.g. Python's `brotli`,
Rust's `zstd` crate against `libzstd`, .NET Zstd in some scenarios),
the per-language ADR documents the trade-off explicitly. The SDK
prefers pure-language implementations when both options exist.

### Algorithm name strings

The SDK uses the protocol's canonical header values, not custom
spellings:

- Brotli: `br`
- Zstd: `zstd`
- Gzip: `gzip`

These are exposed as constants in each SDK
(`compression.NameBrotli`, `Compression.Names.Brotli`, etc.) so
consumers do not type-fudge magic strings.

### Registration API per protocol

The shape of the SDK's compression module differs by protocol:

- **Connect-protocol SDKs.** Expose `ClientOptions()` /
  `HandlerOptions()` (or equivalent) returning the runtime options
  needed to register Brotli + Zstd and select Brotli as the default
  Send. Gzip is left to the runtime's default registration if it has
  one.
- **gRPC-protocol SDKs.** Expose explicit `CompressionProvider`
  implementations for Brotli and Zstd and a builder helper that wires
  them onto the channel/server with Brotli as the default outbound
  encoding. Gzip is typically registered by the runtime; the SDK does
  not re-register it.

### Streaming compression

Per-message compression in streaming RPCs is on by default when
negotiated. The SDK does not implement per-message threshold tuning
(e.g. "skip compression for messages under 100 bytes"); modern
compressors handle small messages cheaply enough that the threshold
adds complexity without meaningful wins.

### Decompression bombs

The SDK does not impose a decompressed-size cap. Connect and gRPC
runtimes already enforce maximum-message-size limits before the
decompressed payload reaches the application; consumers tune those
limits per their threat model.

This is intentional: a cap inside the compression module would either
duplicate the runtime's cap (wasteful) or override it (wrong layer).

## Drawbacks

- Two new third-party dependencies per language in most cases (Brotli
  and Zstd implementations). Both are actively maintained for every
  target language, but they grow the supply-chain surface.
- The default Brotli quality level (4) is picked, not measured against
  every consumer's traffic. Some payloads benefit from level 6 or
  higher. Future revisit if production telemetry shows uneven results.
- Brotli's default Send means servers that cannot decode Brotli see
  the round-trip fall back via Accept-Encoding negotiation, which
  costs one round-trip of header exchange. Cheap, but non-zero.
- Languages where the only viable Zstd implementation is a C-binding
  (Rust against libzstd, Java's zstd-jni) carry CGO/JNI penalties the
  Go and TS SDKs avoid. Documented per-language; not preventable
  today.

## Rationale and alternatives

- **Gzip-only across the family.** Rejected. Gzip is universally
  supported but produces 20-30% larger payloads than Brotli for JSON
  and text-encoded protobuf, with slower decompression than Zstd. SDK
  consumers care about wire size and request latency; gzip-only
  forfeits both.
- **Zstd default.** Rejected. Server-side acceptance is ~70% as of
  2026; defaulting to Zstd silently downgrades a non-trivial fraction
  of deployments. Brotli hits the 95%+ band that justifies
  "compress everything" defaults.
- **CGO/JNI bindings as defaults.** Rejected where a pure-language
  alternative exists. Static-binary and FIPS 140-3 builds break when
  CGO is required.
- **Skip Brotli, ship only Zstd as alt to Gzip.** Rejected. Brotli's
  text-payload ratio still leads Zstd on the JSON-heavy workloads
  most consumers see, and Brotli has shipped in browsers since 2017.
- **Configurable quality level per-call.** Considered. Deferred. The
  current contract is one quality level per SDK (level 4 for Brotli,
  library default for Zstd). A per-call override adds a tuning knob
  most consumers will not use and a non-trivial test matrix.
- **Per-language defaults (e.g. Brotli for Go, Zstd for .NET).**
  Rejected by RFC 0001's identical-behaviour clause. The default Send
  must match across SDKs.

## Prior art

- Brotli RFC 7932:
  https://datatracker.ietf.org/doc/html/rfc7932
- Zstd RFC 8478:
  https://datatracker.ietf.org/doc/html/rfc8478
- Connect protocol compression:
  https://connectrpc.com/docs/protocol#compression
- gRPC compression spec:
  https://github.com/grpc/grpc/blob/master/doc/compression.md
- Cloudflare zstd announcement (2024):
  https://blog.cloudflare.com/new-standards/
- Mozilla HTTP Brotli encoding:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Encoding
- sdk-core-go/docs/adr/0004 (compression strategy): Go-side reference
  implementation.

## Unresolved questions

- Whether the default Brotli quality level should follow each
  language's library default (varies) or be pinned to 4 across the
  family. Current answer is pinned to 4; revisit if a language's
  default Brotli implementation makes 4 expensive to reach (some
  bindings only expose presets).
- Per-call quality override: configuration knob versus per-RPC option.
  Deferred until a real consumer asks.
- Whether to expose a "compression off" preset for consumers running
  inside a service mesh that compresses at the sidecar (and where
  per-message compression in the SDK is redundant CPU work). Today the
  answer is "consumers wire their own client options"; revisit if
  RFC 0008's `Mesh` preset gains a compression-aware variant.
- Cross-language conformance test for negotiation behaviour: given a
  matrix of client + server encodings, does each SDK pair select the
  same algorithm? Future work, after the per-language modules ship.

## Future possibilities

- Migrate to language stdlib implementations where they ship. Go,
  .NET, and TS already have Brotli in stdlib; once Zstd reaches
  stdlib across the family, drop the third-party dependencies.
- Telemetry-driven default tuning of the Brotli quality level
  (collect compression ratios and CPU times from deployed SDKs and
  adjust the pinned default).
- A schema annotation
  (`option (pinguteca.compression.disable) = true`) that opts a
  specific method out of compression (e.g. for already-compressed
  payloads like images or pre-encrypted blobs). Out of scope until a
  real consumer hits the case.
- Streaming-specific compression policy (per-message vs per-stream).
  Today the SDK uses the protocol default; if profiling shows a
  meaningful difference for streaming RPCs, define one.
