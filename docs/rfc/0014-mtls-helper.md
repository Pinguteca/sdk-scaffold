# RFC 0014: mTLS helper and mesh coexistence

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `transport/mtls` helper module
  (Layer 2 core for PEM; Layer 3 sub-module for PKCS#12 in
  languages whose PKCS#12 parser is a third-party dependency) and
  the corresponding `presets` documentation around mesh coexistence.
- Depends on: RFC 0002 (layered architecture), RFC 0008 (resilience
  presets) for the mesh-vs-standalone split.

## Summary

Pin how every SDK ships client mTLS support: as a transport-layer
helper that builds a TLS configuration and (where applicable) a
configured HTTP transport, not as an interceptor. **PEM lives in
the Layer 2 core package** because every target language's stdlib
TLS supports PEM directly and the behaviour is identical across the
family. **PKCS#12 lives in a Layer 3 sub-module** in languages
whose PKCS#12 parser requires a third-party dependency (Go, Rust);
languages with stdlib PKCS#12 support (Java, .NET, Node, Python,
Dart, Swift) keep both formats in core. Defaults pin TLS 1.3,
system root pool plus optional private CA bundle, and reject
`InsecureSkipVerify` at construction. Mesh awareness lives in the
preset documentation, not in the helper itself. Hot reload, SPIFFE
workload identity, and HSM-backed keys are out of v1 scope. The first
SDK (Go) shipped this as a local ADR; pinning it across SDKs prevents
a third implementer from defaulting TLS 1.2, accepting
`InsecureSkipVerify`, or shipping mTLS as an interceptor where it
cannot influence the handshake.

## Motivation

Service-to-service mTLS is a standard ask. The consumer population
splits the same way RFC 0008 splits resilience:

- **Mesh-resident services**: a sidecar (Istio, Linkerd, Consul) or
  eBPF redirector already terminates mTLS for the workload. SDK mTLS
  would duplicate or break the handshake.
- **Standalone consumers**: no sidecar. SDK mTLS is the only way to
  present a client identity.

Without a helper, standalone consumers hand-roll TLS configuration
and tend to forget `MinVersion`, root pool composition, server name
handling, or unsafe `InsecureSkipVerify` opt-outs. With a helper,
mesh consumers may wire it by accident and break their handshake.

Cross-SDK questions needing pinned answers:

1. **Layer placement.** Interceptor or transport helper? Interceptors
   sit above TLS in the chain and cannot influence the handshake; the
   helper has to be transport-layer.
2. **Input formats.** PEM is universal in modern pipelines. PKCS#12
   is common in Java, Windows, and some cert-manager outputs. Both
   or only one.
3. **Defaults.** Minimum TLS version, root pool composition, server
   name override, insecure-skip-verify policy.
4. **Hardening.** Path-traversal and size-bomb resistance on
   caller-supplied cert paths.

Without pinned answers, one SDK ships a TLS-1.2-by-default helper,
another silently accepts `InsecureSkipVerify`, and a third wires
mTLS through the interceptor chain where it can never take effect.

## Guide-level explanation

### Layer placement

mTLS splits across two layers per RFC 0002's placement criteria:

- **PEM helper: Layer 2 core.** Every target language's stdlib TLS
  reads PEM-encoded certificates and keys without a third-party
  dependency. The behaviour is identical across the family (TLS
  1.3 default, system root pool + optional CA append, reject
  `InsecureSkipVerify`, file-loading hardening). Cross-SDK identical
  behaviour matters and there is no ecosystem coupling, so Layer 2
  is the right home.
- **PKCS#12 entry: Layer 3 sub-module where 3P is required.** PKCS#12
  parsers are stdlib in some languages (Java's `KeyStore`, .NET's
  `X509Certificate2`, Node's `tls.createSecureContext({ pfx })`,
  Python's `cryptography.hazmat.primitives.serialization.pkcs12`,
  Dart's `SecurityContext.useCertificateChainBytes`, Swift's
  `SecPKCS12Import`) and third-party in others (Go needs
  `software.sslmate.com/src/go-pkcs12`, Rust needs the `p12` crate).
  Where the parser is stdlib, the PKCS#12 entry point stays in the
  core module alongside PEM; where it is third-party, the PKCS#12
  entry point lives in a Layer 3 sub-module (`transport/mtls/pkcs12`
  in Go, the equivalent crate split in Rust). Consumers who do not
  need PKCS#12 do not pull the third-party dependency.

Both layers share construction and hardening rules (TLS 1.3 default,
file-bound reads, magic-number sniff, `InsecureSkipVerify`
rejection); the Layer 3 sub-module calls back into a Layer 2
`Assemble` entry point so the same TLS configuration is produced
whichever input format the caller used.

### Transport-layer helper, not an interceptor

Every SDK ships `transport/mtls` as a transport-layer module. The
helper returns the language's native TLS configuration object and,
where the RPC stack uses a configurable HTTP transport, a transport
factory that applies the TLS configuration. The consumer wires the
configured transport into the RPC client constructor.

TLS negotiation happens below the RPC layer. An interceptor cannot
influence the handshake; if the handshake fails the interceptor
never gets a chance to run. Shipping mTLS as a helper avoids the
miscategorisation.

### PEM and PKCS#12 are both supported

Every SDK exposes two construction entry points:

- `Config(certPath, keyPath, caCertPath, options)` for PEM input.
- `ConfigFromP12(p12Path, password, caCertPath, options)` for
  PKCS#12 / PFX input.

The PEM entry point is universal; PKCS#12 is common enough in Java,
.NET, Windows, and Kubernetes cert-manager outputs that excluding
it would push consumers to bypass the helper.

Languages where PKCS#12 requires a separate dependency (Go's
`software.sslmate.com/src/go-pkcs12`, Rust's lack of a native PKCS#12
parser in `rustls`) split the PKCS#12 entry point into a sibling
sub-module (`transport/mtls/pkcs12` in Go) so consumers who never
need PKCS#12 do not pull the dependency. Languages with native
PKCS#12 support in stdlib (Java's `KeyStore`, .NET's
`X509Certificate2`, Node's `tls.pfx`, Python's `cryptography.hazmat`)
keep both entry points in the same module.

### Defaults

| Setting              | Default                              | Override                            |
|----------------------|--------------------------------------|-------------------------------------|
| Minimum TLS version  | TLS 1.3                              | `Options.MinVersion = TLS 1.2`      |
| Root pool            | System pool + optional CA append     | `caCertPath` parameter              |
| Server name          | Derived from request URL host        | Not overridable                     |
| `InsecureSkipVerify` | Rejected at construction             | Build your own TLS config           |

TLS 1.3 default: forward secrecy by construction, no legacy cipher
suites, no RSA key exchange.

System pool composition: the helper appends the optional CA bundle
to the system root pool rather than replacing it. Replacing would
break system-trusted certificates that the consumer relied on
implicitly.

`InsecureSkipVerify` rejected: a consumer who genuinely needs to
skip verification (tests against self-signed servers, expired-cert
debugging) builds the TLS configuration directly. The helper is
opinionated about safe defaults and does not provide an unsafe path.

Server name not overridable: stdlib derives it from the request URL
host, which is the correct behaviour for every realistic consumer.
Overriding `ServerName` is a footgun (consumers set it to the cert's
CN and break SAN matching). If a real consumer surfaces a case where
override is necessary, this RFC revisits.

### Mesh awareness in preset docs, not in the helper

The helper has no `if-mesh-skip` flag and no auto-detection.
Auto-detection (sidecar port probing, envvar sniffing) is fragile;
silent no-op hides deploy bugs.

Mesh awareness lives in the preset documentation per RFC 0008:

- `presets.Standalone(...)` references the `transport/mtls` helper
  and links to a wiring example.
- `presets.Mesh(...)` documents that the sidecar handles client
  identity and the SDK should not wire mTLS.

A misconfigured deploy that wires `transport/mtls` inside a mesh
fails at handshake time. It looks like a cert error and is actually
a topology error; the per-SDK README under "Common misconfigurations"
must call this out.

### Strict failure on misconfiguration

Every misconfiguration surface returns an error / throws an
exception at construction time, not at first-RPC time:

- Missing or empty cert path.
- Missing or empty key path.
- Cert / key mismatch (the pair does not load).
- CA file present but contains no PEM certificates.
- File exceeds size cap (DoS hardening).
- File is not a PEM-encoded structure (magic-number sniff).
- `InsecureSkipVerify` set to true.

Construction-time failures surface during application startup where
they are easy to debug; first-RPC failures surface during request
processing where they look like cert errors.

### File-loading hardening

Every SDK's mTLS helper applies the same hardening rules to
caller-supplied file paths:

1. **Path cleaning.** Paths go through the language's
   path-normalisation function (`filepath.Clean` in Go,
   `Path.GetFullPath` in .NET, `os.path.realpath` in Python, etc.).
2. **Bounded read.** Reads are capped at `MaxCertFileSize`
   (recommended: 1 MiB). Real cert bundles are well under 100 KiB;
   the cap exists to bound DoS pressure if a caller points the
   helper at an unexpected file (a bind mount that turned into a
   log, a sparse file).
3. **Magic-number sniff.** PEM bundles are checked for the
   `-----BEGIN ` prefix before any decode step runs. Catches the
   "fed the helper a binary by mistake" case early.

The hardening is identical across SDKs. The per-language ADR
documents the chosen path-normalisation function and any
language-specific gotchas (e.g. Go's `os.Open` triggers a
gosec G304 advisory that is silenced with a justifying comment
because the path is variable by API design).

### What is out of scope for v1

- **Hot reload of certificates.** Long-lived clients with
  short-lived certs must restart until the watcher ships. Add as
  `transport/mtls/Watcher` in a follow-up when a real consumer hits
  rotation pain.
- **SPIFFE / SPIRE workload identity.** Adds a SPIFFE runtime
  dependency. Add as `transport/mtls/spiffe` if a non-mesh SPIFFE
  consumer surfaces.
- **TPM / HSM-backed keys.** Different per platform; deferred until
  stated.
- **Auto-rotation via filesystem watcher.** Same scope as
  hot-reload.

## Reference-level explanation

### Per-language type and module mapping

| Language | TLS configuration type             | HTTP transport type                | PKCS#12 source                                      |
|----------|------------------------------------|------------------------------------|-----------------------------------------------------|
| Go       | `*crypto/tls.Config`                | `*net/http.Transport`              | `software.sslmate.com/src/go-pkcs12` (sub-module)   |
| .NET     | `SslClientAuthenticationOptions`    | `SocketsHttpHandler`               | stdlib `X509Certificate2(.pfx, password)`           |
| TS / Node| `tls.SecureContextOptions`          | `https.Agent`                      | stdlib `tls.createSecureContext({ pfx, passphrase })` |
| Java     | `SSLContext`                        | `HttpClient.newBuilder().sslContext(...)` | stdlib `KeyStore.getInstance("PKCS12")`      |
| Kotlin   | `SSLContext` (JVM target)           | `HttpClient` (Ktor or JDK)         | same as Java                                        |
| Python   | `ssl.SSLContext`                    | `httpx.HTTPTransport` / `aiohttp.TCPConnector` | `cryptography.hazmat.primitives.serialization.pkcs12` |
| Rust     | `rustls::ClientConfig`              | `hyper_rustls::HttpsConnector`     | `rustls-pemfile` + `p12` crate (sub-module)         |
| Dart     | `SecurityContext`                   | `HttpClient` (`dart:io`)           | stdlib `SecurityContext.useCertificateChainBytes`   |
| Swift    | `URLSessionConfiguration` + `SecIdentity` | `URLSession`                  | stdlib `SecPKCS12Import`                            |

The contract is the behaviour (TLS 1.3 default, system pool + CA
append, reject InsecureSkipVerify, strict failure, file-loading
hardening). The type names and module organisation follow each
ecosystem's idiom.

### Browser-side mTLS

Browser-targeted SDKs (TS/Node when running in a browser context)
do not expose `transport/mtls` for the browser target. Browser mTLS
is OS-managed (the browser presents an OS-trusted client cert from
the user's keystore on the server's request); the SDK has no
configuration surface for this and the per-SDK README documents the
omission.

Node-target builds of the TS SDK do expose `transport/mtls` because
the `tls` and `https` modules provide the configuration surface.

### CA pool composition rule

The CA pool used for server verification is constructed as:

```
pool = SystemRootPool()
if caCertPath != "":
    bundle = ReadBoundedFile(caCertPath)
    requireMagicNumber(bundle, "-----BEGIN ")
    pool.AppendFromPEM(bundle)
    if appended_count == 0:
        return ErrNoCAInFile
return pool
```

Append, never replace. Languages whose stdlib pool builder defaults
to replace must explicitly compose system + custom.

### Sentinel error contract

Each SDK exposes sentinel errors / exception types that consumers
can branch on without string matching:

- `ErrInsecureSkipVerify` (or `InsecureSkipVerifyException`)
- `ErrEmptyCertPath`
- `ErrEmptyKeyPath`
- `ErrNoCAInFile`
- `ErrCertFileTooLarge`
- `ErrInvalidPEM`

Sentinel names follow the language's casing convention.

### Construction never probes the connection

The constructor returns a valid TLS configuration on success; it does
not establish a connection to validate the certificate against a
real server. The first RPC surfaces server-trust errors when they
occur.

Connection probing at construction would be a different operation
(a "verify reachable" preflight) and belongs in a separate helper
if needed. The mTLS helper is a configuration builder, not a
liveness checker.

## Drawbacks

- A misconfigured deploy that wires `transport/mtls` inside a mesh
  fails at handshake time. The error looks like a cert error and is
  a topology error. Documentation can warn but cannot prevent.
- Long-lived clients with short-lived certs (e.g. SPIFFE-style
  rotation every hour) must restart until the watcher ships. Cert
  rotation is a stated v2 need.
- `ServerName` not overridable rules out a small class of legitimate
  cases (SNI override for testing against a host that does not match
  DNS). Tests that need it build their own TLS configuration.
- The PKCS#12 sub-module split in Go and Rust adds friction
  (consumer must import a second module). Documented per-SDK; the
  alternative is forcing every consumer to pull the PKCS#12
  dependency.
- Caller-supplied paths in 9 languages mean 9 different
  path-normalisation gotchas. Per-language ADR documents the
  specifics.

## Rationale and alternatives

- **Auto-detect mesh and silently no-op mTLS.** Rejected. Detection
  is unreliable (envvar sniffing, port probing both fragile) and a
  silent no-op hides deploy bugs.
- **mTLS as an interceptor.** Rejected. TLS negotiation happens below
  the RPC layer; an interceptor cannot influence the handshake.
- **PEM only.** Rejected. PKCS#12 is standard enough across Java,
  .NET, Windows, and Kubernetes cert-manager pipelines that
  excluding it would push consumers to bypass the helper. The PKCS#12
  parser is in a sub-module for languages where it costs a
  third-party dependency.
- **TLS 1.2 default.** Rejected. Known weaker; require explicit
  opt-in via `Options.MinVersion`.
- **Allow `InsecureSkipVerify: true`.** Rejected. Tests that
  genuinely need it bypass the helper. The helper is opinionated
  about safe defaults.
- **Hot reload in v1.** Rejected. Filesystem-watcher dependency,
  atomic-replace semantics, and Kubernetes secret-mount edge cases
  deserve their own pass. Ships in v2 as `transport/mtls/Watcher`.
- **SPIFFE in v1.** Rejected. SPIFFE adds a workload-identity runtime
  dependency. Ships as `transport/mtls/spiffe` companion if a
  non-mesh consumer surfaces.
- **Probe connection at construction.** Rejected. Construction
  builds a configuration; reachability is a separate operation that
  belongs in a different helper.
- **Configurable server name.** Rejected for v1. Stdlib-derived
  behaviour is correct for every realistic consumer; consumer needs
  for SNI override surface as a v2 ask if real.

## Prior art

- IETF RFC 8446 (TLS 1.3):
  https://datatracker.ietf.org/doc/html/rfc8446
- IETF RFC 7292 (PKCS #12 v1.1):
  https://datatracker.ietf.org/doc/html/rfc7292
- Istio mutual TLS:
  https://istio.io/latest/docs/concepts/security/#mutual-tls-authentication
- Linkerd automatic mTLS:
  https://linkerd.io/2/features/automatic-mtls/
- SPIFFE / SPIRE workload identity:
  https://spiffe.io/
- cert-manager Kubernetes operator:
  https://cert-manager.io/
- Rustls project:
  https://github.com/rustls/rustls
- sdk-core-go/docs/adr/0009 (mTLS and mesh coexistence): Go-side
  reference implementation.

## Unresolved questions

- Whether the PKCS#12 sub-module split should be uniform across all
  languages (always a sibling module) or per-language (sibling only
  where the parser costs a dependency). Today the answer is per-
  language; consistency may be worth a future pass.
- Whether the helper should expose a "verify reachable" preflight
  (one-shot connection establishment that validates the server
  cert against the configured pool). Today the answer is "build a
  separate helper if you want this"; revisit if a real consumer
  reports the gap.
- `ServerName` override for SNI-based virtual hosting. Today not
  overridable; revisit on real ask.
- Whether to add a `MinVersion = TLS 1.2` warning emit (log line at
  construction time) when the consumer downgrades from the TLS 1.3
  default. Today silent; the per-SDK README documents the trade-off.

## Future possibilities

- `transport/mtls/Watcher` companion: filesystem watcher that
  atomically swaps the loaded certificate when the source files
  change. Ships as v2 when a real consumer reports rotation pain.
- `transport/mtls/spiffe` companion: SPIFFE workload identity API
  integration for non-mesh consumers. Ships when surfaced.
- TPM / HSM-backed key support per platform. Different per OS;
  deferred until a real consumer asks.
- Cross-language conformance tests asserting each SDK rejects
  `InsecureSkipVerify`, accepts only TLS 1.3 by default, and applies
  the same magic-number sniff to a corrupted PEM file.
- A capability flag exposing whether the SDK was built with PKCS#12
  support (relevant in Rust and Go where it is a sub-module).
- Pre-shaped configuration profiles for common deployment scenarios
  (Kubernetes cert-manager, AWS Private CA, internal CA bundle from
  the company-wide root) so consumers do not re-derive the wiring
  per service.
