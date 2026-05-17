# RFC 0009: Pagination API shape

- Status: Accepted
- Date: 2026-05-17
- Affects: every `sdk-core-*` repo's `pagination` helper module.
- Depends on: RFC 0001 (multi-language parity baseline),
  RFC 0002 (layered SDK architecture).

## Summary

Pin the shape of the pagination helper every SDK ships. Token-paginated
RPCs (`List`, `Search`, etc. returning `items + next_page_token`) are
near-universal in protobuf-defined services, and rolling the iteration
loop by hand in every consumer is wasteful. The helper is consumer-side
only: not an interceptor, but ships in the core package as a Layer 2
utility. Each SDK exposes the same three operations under the language's
native fallible-async-iteration idiom, with a sequential variant, an
opt-in parallel-prefetch variant, and a materialising collector. The
first SDK (Go) shipped this as a local ADR; pinning it across SDKs
prevents the next implementer from picking a different shape and
breaking cross-language behaviour parity.

## Motivation

A consumer paginating a List RPC writes the same loop everywhere:

```
token = ""
loop:
    resp = client.List(req with page_token=token)
    for item in resp.items: handle(item)
    if resp.next_page_token == "": break
    token = resp.next_page_token
```

Repeating this in every consumer is wasteful and bug-prone (forgotten
cancellation, dropped errors, mishandled empty pages). A shared helper
turns the loop into a one-liner per language.

The interesting question is the shape of the helper. Each target
language has a native fallible-async-iteration primitive
(`iter.Seq2[T, error]` in Go, `IAsyncEnumerable<T>` in .NET,
`AsyncIterator<T>` in TS, `Stream<Item = Result<T, E>>` in Rust,
`Stream` in Dart, async generator in Python, `Flow` in Kotlin, an
`Iterator`-with-error model in Java). The shape must map cleanly to
each so the helper feels idiomatic without forcing callers to learn a
new convention.

## Guide-level explanation

### Surface

Every SDK exposes three operations on its `pagination` module:

| Operation       | Behaviour                                                 |
|-----------------|-----------------------------------------------------------|
| `Iter`          | Sequential iteration. One outstanding fetch at a time.    |
| `IterParallel`  | Producer fetches ahead of consumer up to N pages.         |
| `Collect`       | Materialises every item into a list. Partial on error.    |

Names follow each ecosystem's casing convention (`Iter` in Go,
`IterAsync` in .NET, `iter` in Rust, etc.). The contract is the
behaviour, not the spelling.

### Fetch closure, not interface

The caller supplies a `FetchPage` closure that takes a page token and
returns `(items, next_token, error)`. Each SDK uses its native function
type, not a one-method interface. Closures over the consumer's
generated client are simpler than wrapping the client in a wrapper
class and play better with type inference.

### Invariants every SDK must hold

1. **Empty next-token terminates iteration.** When `next_token` is the
   empty string (proto default), iteration ends after yielding the
   current page's items.
2. **Cancellation is honoured promptly.** A cancelled context /
   cancellation token / abort signal stops the next fetch before it
   starts and surfaces a cancellation error to the consumer. The
   language's native cancellation type is used; the SDK does not invent
   its own.
3. **Errors terminate iteration.** A non-nil error from `FetchPage`
   yields once (alongside no item) and ends the iteration. Subsequent
   calls to the iterator return EOF / done.
4. **Page order is preserved.** Items appear in the order they came
   from the server. `IterParallel` does not reorder pages; the
   parallelism is producer-runs-ahead-of-consumer, not N concurrent
   fetches (page N depends on page N-1's token, so concurrent fetching
   is impossible without speculative tokens).
5. **`Collect` returns partial-on-error.** When an error stops
   iteration mid-way, `Collect` returns the items gathered so far plus
   the error. All-or-nothing semantics are easy to layer on top
   (`if err != nil { return nil, err }`); the inverse is not.

### Layer placement

Pagination is a Layer 2 helper, not a Layer 2 interceptor. It runs in
consumer code wrapping the generated RPC stubs. Each underlying RPC
still goes through the full interceptor stack (OTel, breaker,
idempotency, retry, auth) as RFC 0008 specifies. The helper is not in
the interceptor chain.

This placement matters because:

- Retries on a paginated fetch are per-page. A transient failure on
  page 3 retries page 3 with the same token; it does not restart at
  page 0.
- Idempotency keys are per-RPC. Each page fetch generates its own key.
- OTel spans wrap each underlying RPC; the helper does not add a span
  of its own (consumers who want a span around the whole iteration
  wire it explicitly).

## Reference-level explanation

### Parallel-prefetch semantics

`IterParallel(fetch, lookahead)` (or the language equivalent) starts a
producer task that fetches pages sequentially and pushes them onto a
bounded buffer of size `lookahead`. The consumer pulls items from the
buffer; the producer keeps fetching as long as the buffer has space.
When the producer hits a non-empty `next_token` and the buffer is full,
the producer blocks until the consumer drains.

- `lookahead < 1` degrades to sequential `Iter`.
- The recommended default for unspecified `lookahead` is 2. Two pages
  of headroom amortises typical per-fetch latency without ballooning
  memory for large pages.
- Errors from page N are yielded after all items from pages 0..N-1.

### Per-language idiom mapping

| Language | Iteration primitive                | Cancellation primitive          | Method names                              |
|----------|------------------------------------|---------------------------------|-------------------------------------------|
| Go       | `iter.Seq2[T, error]`              | `context.Context`               | `Iter`, `IterParallel`, `Collect`         |
| .NET     | `IAsyncEnumerable<T>`              | `CancellationToken`             | `IterAsync`, `IterParallelAsync`, `CollectAsync` |
| TS / Node| `AsyncIterableIterator<T>`         | `AbortSignal`                   | `iter`, `iterParallel`, `collect`         |
| Rust     | `Stream<Item = Result<T, Error>>`  | drop / `CancellationToken`      | `iter`, `iter_parallel`, `collect`        |
| Java     | `Iterator<T>` + checked exception  | `Thread.interrupt` / explicit   | `iter`, `iterParallel`, `collect`         |
| Kotlin   | `Flow<T>`                          | structured concurrency / job    | `iter`, `iterParallel`, `collect`         |
| Python   | `AsyncIterator[T]`                 | `asyncio.CancelledError`        | `iter`, `iter_parallel`, `collect`        |
| Dart     | `Stream<T>`                        | stream subscription cancel      | `iter`, `iterParallel`, `collect`         |
| Swift    | `AsyncThrowingStream<T, Error>`    | task cancellation               | `iter`, `iterParallel`, `collect`         |

Error surfacing follows the language idiom: a separate yield slot
(`iter.Seq2`'s second value) where available, an exception otherwise,
a `Result` type for languages that prefer it.

### Streaming over server-streaming RPC

Pagination as defined here is unary RPC with a token. Server-streaming
RPCs (`stream Foo` in proto) are a different shape and out of scope for
this RFC. A future RFC may define a `pagination/streaming` companion
once a real consumer needs it; the unary-with-token pattern remains the
default because it composes with HTTP-level CDN caching, retries, and
hedged requests, while server streams do not.

### What pagination does NOT do

- **No reflection-based "iterate any List* method".** Brittle, hides
  schema, breaks under method renames. The explicit `FetchPage` closure
  is one extra line but obvious in code review.
- **No automatic re-fetch on stale token.** If the server rejects a
  token (e.g. with `InvalidArgument`), the iteration ends with that
  error. Re-issuing from scratch is the consumer's choice.
- **No global page-token cache.** Tokens are per-iteration. Caching
  tokens across iterations is a consumer concern, not the SDK's.
- **No deduplication across pages.** Some APIs return overlapping
  pages (sliding-window pagination, e.g. when items change between
  fetches). Deduping is consumer-side; the helper yields whatever the
  server returns.

## Drawbacks

- Nine languages, nine slightly different surfaces. The contract is
  the behaviour, but the spellings differ enough that cross-language
  code review needs a per-language reviewer to catch shape drift.
- `Collect`'s partial-on-error semantics is a footgun for callers who
  do not check the returned error. Documented; static analysis tools
  in each language flag unchecked errors anyway.
- `IterParallel`'s `lookahead` parameter is a knob most consumers will
  not understand or tune. The default of 2 covers the typical case;
  consumers who care can read the doc comment.
- The recommended default `lookahead = 2` is picked, not measured
  against any specific service.

## Rationale and alternatives

- **Channel-based / unbounded queue.** Rejected: callers must remember
  to drain on early exit to avoid resource leaks. The language native
  iteration primitive solves early-exit cleanly.
- **Callback-based API: `forEach(fetch, callback)`.** Rejected:
  closures-with-state in the callback push complexity to the call site.
  The native iteration primitive lets the consumer keep per-iteration
  state in plain locals.
- **Materialise always: return `List<T>` only.** Rejected: forces every
  consumer to load the full result set into memory. Streaming
  iteration matters for large lists. `Collect` is opt-in.
- **All-or-nothing `Collect` (discard partial on error).** Considered.
  Rejected: the inverse is harder to recover. Callers who want
  all-or-nothing wrap the partial result themselves; callers who want
  partial cannot recover it from an all-or-nothing API.
- **N concurrent fetches.** Impossible: page N depends on page N-1's
  token. `IterParallel` only buys producer-consumer concurrency.
- **One unified name across all languages (e.g. always `paginate`).**
  Rejected: language ecosystems have strong naming conventions and
  forcing one breaks the "feels native" criterion from RFC 0001.

## Prior art

- Stripe SDKs auto-paginating iterators
  (Ruby, Python, Node, Go, Java, .NET):
  https://stripe.com/docs/api/pagination
- AWS SDK paginators (boto3, aws-sdk-go-v2):
  https://docs.aws.amazon.com/sdk-for-go/v2/developer-guide/sdk-utilities.html#paginators
- Google Cloud client libraries iterators
  (per-language helpers that wrap List + pageToken):
  https://cloud.google.com/apis/design/design_patterns#list_pagination
- Go 1.23 range-over-func proposal and `iter` package:
  https://go.dev/blog/range-functions
- .NET `IAsyncEnumerable<T>` and `await foreach`:
  https://learn.microsoft.com/dotnet/csharp/asynchronous-programming/generate-consume-asynchronous-stream
- sdk-core-go/docs/adr/0008 (pagination API shape): Go-side reference
  implementation.

## Unresolved questions

- Whether languages without a native fallible-iteration primitive (Java
  pre-records, older Python) need a wrapper type to carry
  `(item, error)` tuples, or whether the language's exception model
  suffices. The default position is "use the exception model"; revisit
  if a Java consumer reports confusion.
- Server-streaming pagination as a separate companion module. Wait for
  a real consumer ask.
- `CollectAll` (all-or-nothing) as a sibling of `Collect`, for
  consumers who want the friendlier default. Wait until consumer
  feedback shows confusion around partial-on-error.
- Whether `IterParallel`'s default `lookahead` should be tuneable per
  service via the schema (proto option), or whether per-call override
  is sufficient. Today's answer is per-call.

## Future possibilities

- Cross-language conformance tests that hit a shared fixture server
  returning a known list of items across known page boundaries and
  assert each SDK's `Iter` and `Collect` yield identical sequences
  in identical order under identical cancellation conditions.
- A schema annotation (`option (pinguteca.pagination.default_lookahead)`)
  that lets the service author hint at a per-method default. Out of
  scope until a real consumer hits the limit.
- Auto-generated typed wrappers from buf / protoc-gen that emit a
  `Client.ListUsersIter()` shortcut per List method, eliminating the
  `FetchPage` closure for the common case. A separate code-generation
  RFC if pursued.
