# RFC 0005: Per-language wire protocol

- Status: Accepted
- Date: 2026-05-10
- Affects: every `sdk-core-*` repo's transport layer, generated-stub
  toolchain, and the Connect runtime exemption table in RFC 0002.
- Depends on: RFC 0001 (parity baseline), RFC 0002 (layered SDK
  architecture).

## Summary

The server is Connect-Go and serves the Connect protocol, gRPC, and
gRPC-Web on the same handlers (Connect-Go feature). Every SDK uses
the Connect protocol when an official Connect runtime exists for
that language. When it does not, the SDK falls back to gRPC over
HTTP/2 instead of blocking on a Connect implementation that may
never ship. The list of fallback languages is small and is pinned in
this RFC so the same wire-format gap does not have to be re-
litigated per SDK.

## Motivation

Connect-for-Go, -ES, -Swift, -Kotlin, -Dart, and -Python all exist
as official runtimes maintained by the `connectrpc` organisation.
The corresponding SDKs use the Connect protocol directly.

There is no official Connect runtime for .NET, Rust, or Java (a
JVM-level Connect runtime exists as connect-kotlin, but Java
consumers reading Kotlin types in their code is not the same thing
as a Java runtime). Without a decision, three of the eight Primary
SDKs in RFC 0001 are blocked: either they wait indefinitely for a
runtime that may never ship, or each first-publisher invents a
solution locally and later SDKs are forced to mirror it.

Connect-Go's multi-protocol serving makes the resolution cheap. The
server already accepts gRPC clients on the same endpoints. An SDK
that talks gRPC speaks to the same handlers a Connect SDK does.

## Guide-level explanation

### Default and fallback

- **Default: Connect protocol.** Used by every SDK whose language
  has an official Connect runtime.
- **Fallback: gRPC over HTTP/2.** Used by SDKs whose language has
  no Connect runtime. The schema is the same; only the wire format
  and the generated client differ.

### Per-language assignment

| Language | Protocol         | Runtime                        |
|----------|------------------|--------------------------------|
| Go       | Connect          | `connectrpc.com/connect`       |
| TS/Node  | Connect          | `@connectrpc/connect`          |
| Swift    | Connect          | connect-swift                  |
| Kotlin   | Connect          | connect-kotlin                 |
| Dart     | Connect          | connect-dart                   |
| Python   | Connect          | connect-python                 |
| Java     | gRPC             | `io.grpc:grpc-netty-shaded`    |
| .NET     | gRPC             | `Grpc.Net.Client`              |
| Rust     | gRPC             | `tonic`                        |

Java is gRPC even though connect-kotlin runs on the JVM, because
Java callers reading Kotlin types in their code is an interop pain
point not worth carrying for an SDK.

Tier 2 SDKs follow the same rule: Connect runtime if it exists,
gRPC otherwise.

### What gRPC-fallback SDKs lose vs Connect

1. **HTTP GET caching for read-only RPCs.** Connect's
   `NO_SIDE_EFFECTS` RPCs become HTTP GET, cacheable by URL at any
   CDN. gRPC is always POST.
2. **Curl and browser DevTools debuggability.** Connect unary is
   POST + body, readable in curl. gRPC needs grpcurl or equivalent.
3. **HTTP/1.1 fallback.** Connect speaks HTTP/1.1 fine. gRPC is
   HTTP/2 end-to-end. Restrictive corporate proxies that strip
   HTTP/2 break gRPC. gRPC-Web is a separate protocol, not a drop-
   in.
4. **Errors in the HTTP body.** Connect puts the error structure
   in the response body. gRPC puts status in HTTP/2 trailers.
   Middleware that logs only headers and body sees `200 OK` with
   empty body and misses gRPC errors.

For backend SDK consumers (the primary audience per RFC 0001),
items 2-4 affect debugging and proxy compatibility. Item 1 affects
edge caching, which Phase 4 caching depends on.

### What gRPC-fallback SDKs gain over hand-rolling Connect

1. Mature, vendor-maintained runtime (Microsoft's
   `Grpc.Net.Client`, hyperium's `tonic`, gRPC-Java).
2. First-class HTTP/3 in .NET and tonic.
3. Native integration with the host ecosystem's resilience,
   logging, and observability libraries.
4. Schema-driven code generation via `protoc-gen-grpc-*` plugins
   already maintained by the gRPC project.

### Caching consequences for Phase 4

Phase 4 of the SDK roadmap (caching layer) was designed around
Connect's HTTP GET on read-only RPCs. gRPC-fallback SDKs cannot
participate in the CDN-cache path. They can still participate in
the app-layer cache (ETag-driven, pluggable cache store). RFC 0002's
companion model already isolates the cache as L3, so the .NET, Rust,
and Java cache companions ship the app-layer half only. The Connect-
GET caching companion is Connect-SDK-only.

## Reference-level explanation

### Server side

No change. Connect-Go already serves Connect, gRPC, and gRPC-Web on
the same handlers. The schema (`.proto` files) is the contract; the
wire format is a per-client choice.

### L1 generated stubs

Different generator per protocol:

| Protocol | Generator                                                    |
|----------|--------------------------------------------------------------|
| Connect  | `buf generate` with the language's Connect plugin            |
| gRPC     | `buf generate` with `protoc-gen-grpc-*` for that language    |

Both run from buf, so the schema pipeline stays unified. Only the
plugin in `buf.gen.yaml` differs per consumer repo. L1 is per
consumer (RFC 0002), so the choice lives in the consumer's
`buf.gen.yaml`, not in the SDK.

### L2 interceptor surface

The interceptor contract from RFC 0002 (retry, idempotency,
timeouts, token injection, OAuth client_credentials, pagination,
mTLS PEM, correlation ID) is wire-format-agnostic in shape but
binds to different runtime types per protocol. For gRPC-fallback
SDKs the L2 interceptor adapts to the host language's gRPC
interceptor type (`Grpc.Core.Interceptors.Interceptor` in .NET,
`tower::Service` layering in tonic, `io.grpc.ClientInterceptor` in
Java). The behavioural contract is identical; the binding differs.

### L3 companion catalogue (RFC 0004)

Tokens unchanged. The companion implementation per language wraps
either the Connect runtime's hooks or the gRPC runtime's hooks
depending on which protocol that SDK uses. Cross-language behaviour
parity is preserved by the L2 contract; companion code is per-
language anyway.

The `presets` companion's canned interceptor compositions in gRPC
SDKs use the gRPC-native interceptor stack but produce the same
observable behaviour (retry curve, breaker state, idempotency
keying).

### RFC 0001 parity score reframing

The "Connect protocol client" row in RFC 0001 is reframed as "wire
protocol client" with the per-language assignment from this RFC.
Languages with an official Connect runtime score on Connect; gRPC-
fallback languages score on gRPC. gRPC support is mature or first-
party in every Primary language, so scores rise for .NET, Java, and
Rust. The parity baseline percentages are recomputed in the
appendix.

### RFC 0002 Connect runtime exemption update

The Connect runtime exemption table in RFC 0002 gains gRPC
equivalents per fallback language. The clause "the Connect runtime
is exempt" becomes "the wire-protocol runtime for the SDK's chosen
protocol is exempt", with per-language entries:

| Language | Exempt runtime modules                                                  |
|----------|-------------------------------------------------------------------------|
| Go       | `connectrpc.com/connect`, `google.golang.org/protobuf`, genproto/googleapis |
| TS/Node  | `@connectrpc/connect`, `@bufbuild/protobuf`                             |
| Swift    | connect-swift, swift-protobuf                                           |
| Kotlin   | connect-kotlin, `com.google.protobuf:protobuf-kotlin`                   |
| Dart     | connect-dart, `package:protobuf`                                        |
| Python   | connect-python, `protobuf`                                              |
| Java     | `io.grpc:grpc-netty-shaded`, `io.grpc:grpc-protobuf`, `io.grpc:grpc-stub`, `com.google.protobuf:protobuf-java` |
| .NET     | `Grpc.Net.Client`, `Grpc.Tools`, `Google.Protobuf`                      |
| Rust     | `tonic`, `tonic-build`, `prost`                                         |

## Drawbacks

- Two wire protocols in production. Operational tooling (request
  tracing dashboards, log indexes) must understand both. Most modern
  observability stacks already handle both; the cost is
  documentation, not code.
- Phase 4 caching's CDN path applies only to Connect SDKs. We ship
  the app-layer cache to everyone and document the asymmetry.
- The gRPC-fallback SDKs cannot consume a future Connect-only
  server feature (e.g. a hypothetical Connect-protocol-only header
  semantic). We bind ourselves to the lowest-common-denominator
  feature set on the gRPC side.
- If an official Connect runtime ships for .NET / Java / Rust
  later, switching is a breaking change for consumers (the
  generated stub types live in different namespaces). Mitigation:
  the L2 interceptor contract is wire-format-agnostic, so the
  upper-layer code stays. The break is at L1.

## Rationale and alternatives

- **Wait for Connect runtimes to ship.** Indefinite. Reject.
- **Build Connect runtimes ourselves.** Multi-person-month scope
  per language. Out of scope for this team.
- **gRPC for every non-Go SDK.** Tempting for protocol uniformity
  but throws away mature Connect runtimes in TS/Node, Swift, Kotlin,
  Dart, Python. Reject.
- **gRPC-Web for browser TS instead of Connect.** Reject. connect-es
  already runs in browsers and is the better TS story.
- **Java uses connect-kotlin via JVM interop.** Considered. Rejected:
  Kotlin types in Java code are a recurring interop pain point in
  every JVM polyglot codebase. A dedicated Java story is gRPC.

## Prior art

- Connect-Go multi-protocol serving:
  https://connectrpc.com/docs/go/serving-grpc
- `Grpc.Net.Client` documentation:
  https://learn.microsoft.com/aspnet/core/grpc/client
- tonic (Rust gRPC):
  https://github.com/hyperium/tonic
- gRPC-Java:
  https://github.com/grpc/grpc-java
- buf code generation plugins:
  https://buf.build/docs/generate/overview

## Unresolved questions

- Whether to revisit Rust's choice if a community Connect-Rust
  runtime gains traction. The decision review trigger is "a Rust
  Connect runtime publishes a 1.0 with a Cargo download count above
  some threshold". Threshold and review cadence are out of scope
  here.
- Whether Java should switch to connect-kotlin (with Kotlin types
  surfaced as Java idioms via a generated facade) if the JVM
  interop tooling improves materially.
- Whether the L2 interceptor abstraction in gRPC-fallback SDKs
  should expose Connect-style ergonomics (`req.Header()` style) or
  the gRPC-native ergonomics (`ClientCall.Listener`, etc). The
  natural answer is the gRPC-native one because consumers already
  know gRPC, but it slightly diverges from the Connect SDKs'
  ergonomics.
- How to communicate the protocol choice in each SDK's README so
  consumers do not file bugs asking why a gRPC SDK does not behave
  like a Connect SDK in HTTP/1.1 environments.

## Future possibilities

- A Connect runtime for .NET, Java, or Rust ships and we migrate
  the corresponding SDK. The migration path is documented as a
  breaking-change RFC at that time.
- Capability flags per SDK exposing the wire protocol, so
  consumers and integration tests can branch on it.
- A shared conformance suite (extending the existing
  connectrpc/conformance tests) that runs both Connect and gRPC
  clients against the same server and asserts behavioural parity
  on the L2 contract.
