# HojiChar: Text Processing Pipeline Library

Implement `hojichar`, a Python library for composing text processing pipelines. The library lets users define text-processing steps as `Filter` subclasses and chain them with `Compose` into a single pipeline. It tracks per-filter statistics, supports parallel execution, and provides a CLI tool.

## Installation

The package must be installable via `pip install -e .` with a `pyproject.toml` using `hatchling` as the build backend. The package name is `hojichar`. Required runtime dependencies: `numpy>=1.26,<2.0` and `tqdm>=4.65.0,<5`.

Register a console script entry point: `hojichar = "hojichar.cli:main"`.

**Environment is offline — do not install anything.** All dependencies are already installed in the environment and there is no network access. The runtime dependencies (`numpy`, `tqdm`), the deduplication dependencies (`datasketch`, `rensa`, `xxhash`, `nltk`, `redis`), a running `redis-server`, the build backend (`hatchling` with `uv-dynamic-versioning`), and the test harness are all pre-installed. Your project is installed offline by a `setup.sh` that runs `pip install -e . --no-build-isolation` against these pre-installed packages, so make sure `pyproject.toml` builds an editable install without fetching anything from the network.

## Module Layout

The public API is organized into these import paths:

- `hojichar` — top-level re-exports: `Compose`, `Filter`, `Document`, `Token`, `Parallel`, `AsyncCompose`, `AsyncFilterAdapter`, `AsyncFilter`
- `hojichar.core.models` — `Document`, `Token`, `Statistics`
- `hojichar.core.filter_interface` — `Filter`
- `hojichar.core.composition` — `Compose`
- `hojichar.core.async_filter_interface` — `AsyncFilter`
- `hojichar.core.async_composition` — `AsyncCompose`, `AsyncFilterAdapter`
- `hojichar.core.parallel` — `Parallel`
- `hojichar.core.inspection` — `StatsContainer`
- `hojichar.filters.document_filters` — all built-in document filters (see below)
- `hojichar.filters.token_filters` — `SEOTokenRemover`
- `hojichar.filters.tokenization` — `BlankCharTokenizer`, `SentenceTokenizer`, `MergeTokens`
- `hojichar.filters.deduplication` — `GenerateDedupLSH`, `InlineDeduplicator`, `RedisDeduplicator`, `InlineDuplicateAnalyzer`, `char_level_splitter`, `non_alpha_num_splitter`
- `hojichar.utils.load_compose` — `load_compose`, `load_filter_from_file`, `load_factory_from_file`, `load_parametrized_filter_from_file`
- `hojichar.cli` — CLI entry point (`main`)

The NG word filters load keyword files from a `dict/` directory inside the package (e.g., `adult_keywords_ja.txt`, `adult_keywords_en.txt`, `advertisement_keywords_ja.txt`, `discrimination_keywords_ja.txt`, `violence_keywords_ja.txt`, `header_footer_keywords_ja.txt`). Each file contains test sentinel strings like `<TEST_STRING_OF_ADULT_KEYWORD>` for validation.

## Core API

### `hojichar.Document`

A container for text being processed through the pipeline.

- Constructor: `Document(text: str, is_rejected: bool = False, tokens=None, extras=None)`
- `text` (str): Mutable text content.
- `original` (property, str): The initial text at construction time. Immutable.
- `is_rejected` (bool): When `True`, downstream filters with `skip_rejected=True` skip this document, and `Compose.__call__` returns `""`.
- `extras` (dict): Arbitrary metadata dictionary. Defaults to `{}`.
- `reject_reason` (dict): When a filter rejects a document (transitions `is_rejected` from False to True), this is set to the filter's `get_jsonable_vars()` — a dict containing `name`, `p`, `skip_rejected`, and all filter-specific public primitive attributes (e.g., `min_doc_len`, `max_doc_len`). Not overwritten by downstream filters. Defaults to `{}`.
- `tokens` (list): List of `Token` objects (deprecated).
- `set_tokens(tokens: List[str])`: Deprecated. Creates Token objects from strings.
- `get_tokens() -> List[str]`: Deprecated. Returns token texts.
- `__str__()`: Returns `self.text`.
- `__repr__()`: Returns `Document(text=..., is_rejected=..., extras=...)`.

### `hojichar.Token` (deprecated)

- Constructor: `Token(text: str, is_rejected: bool = False)`
- `text`: Mutable text content.
- `original` (property): Immutable initial text.
- `is_rejected`: Flag for token-level filtering.

### `hojichar.core.models.Statistics`

A dataclass tracking per-filter processing statistics.

**Fields:** `name`, `input_num`, `input_bytes`, `input_chars`, `output_num`, `output_bytes`, `output_chars`, `discard_num`, `diff_bytes`, `diff_chars`, `cumulative_time_ns`, `errors`. All integers, default 0.

**Counting contract (per-filter and `"Total"` entries alike):** `input_num` counts every document fed in; `discard_num` counts the documents this filter/pipeline rejected (transitioned `is_rejected` from `False` to `True`); and `output_num` counts only the documents that were **not** discarded (the accepted/surviving documents). So the identity `input_num == output_num + discard_num` holds (equivalently `output_num == input_num - discard_num`), and `output_bytes`/`output_chars` likewise accumulate only over the surviving documents. This same relationship holds for `Compose`, `AsyncCompose`, and `Parallel`-aggregated `"Total"` entries.

**Skipped documents still count.** Every document presented to a filter stage increments that filter's `input_num`, **including** a document the filter skips because it arrived already rejected (`skip_rejected=True`) or because a `p<1` draw made the filter a no-op for it. A skipped document is not discarded *by this filter* (this filter did not transition its `is_rejected` from `False` to `True`), so it counts toward that filter's `output_num` as a pass-through survivor and contributes zero to `discard_num` and zero to `diff_bytes`/`diff_chars`.

`diff_bytes` and `diff_chars` are the per-filter size change measured as **output minus input** (`after - before`), so a filter that lengthens text reports positive diffs and one that shrinks text reports negative diffs; for a rejected document the input size is subtracted (the output is discarded). These diffs accumulate additively across documents.

**Methods:**
- `to_dict() -> dict`: Returns all fields as a dictionary.
- `update(other: Statistics)`: Adds another Statistics' values in-place.
- `reset() -> Statistics`: Zeros all counters. Returns self.
- `Statistics.add(x, y) -> Statistics` (static): Adds two with matching names. Raises `AssertionError` if names differ.
- `Statistics.add_list_of_stats(x, y) -> List[Statistics]` (static): Merges two lists by matching names. Raises `ValueError` if name sets don't match.
- `Statistics.get_filter(name, stats) -> Statistics` (static): Finds a stat by name. Raises `KeyError` if not found.

### `hojichar.Filter`

Base class for document-level filters. Users subclass it and implement `apply(document) -> Document`.

**Constructor params:** `p=1.0` (probability of applying, 0=identity), `skip_rejected=True`, `random_state=None` (int or `np.random.Generator`; `None` means receives Compose's shared RNG), `use_batch=False`, `batch_size=128`.

**Behaviors:**
- `__call__(text: str, **kwargs) -> str`: Processes a string through the filter and returns the resulting text. Any keyword arguments are forwarded to the `Document` constructor (e.g. `filt(text, extras={...})`), so `apply` can read them off the document.
- `get_statistics() -> Statistics`: Returns accumulated statistics for this filter.
- `get_jsonable_vars(exclude_keys=None) -> dict`: Returns primitive-typed public member variables (excludes those starting with `_`).
- `shutdown()`: Cleanup hook. Called by `__exit__`.
- Context manager support (`with` statement calls `shutdown` on exit).
- When used inside `Compose`, the pipeline tracks per-filter statistics (input/output counts, byte diffs, discard counts) automatically.
- `apply_stream(stream) -> Iterable[Document]`: Processes documents lazily. When `use_batch=True`, accumulates documents into chunks of `batch_size` and processes each chunk via `apply_batch`. Remaining documents at end-of-stream are processed as a partial batch. When `use_batch=False`, processes individually. Streaming updates the **same** per-filter statistics as `__call__`: each document that flows through `apply_stream` increments this filter's `input_num`/`output_num`/`discard_num` (per the counting contract above) and its byte/char counts and diffs, so `get_statistics()` after consuming the stream reports the same accounting as if the documents had gone through `apply`/`__call__`.
- Error handling in `apply_stream`: exceptions set `is_rejected=True`, `reject_reason={"error": <message>}`, increment `statistics.errors`, and continue processing. When `use_batch=True` and `apply_batch` raises for a chunk, the failure is handled at batch granularity: **every** document in that chunk is marked `is_rejected=True` with `reject_reason={"error": <message>}`, and `statistics.errors` is incremented **once per document in the chunk** (so a single exception on a 3-document chunk yields `errors == 3`). Processing then continues with the next chunk.

### `hojichar.Compose`

Chains multiple filters into a single pipeline.

**Constructor:** `Compose(filters, random_state=None)`

**Behaviors:**
- `__call__(text) -> str`: Returns processed text, or `""` if rejected.
- `apply(document: Document) -> Document`: The `Document`-level counterpart of `__call__`. Runs the document through every sub-filter in order (honoring `skip_rejected` and each filter's `p`), updates per-filter and `"Total"` statistics, and returns the resulting `Document` (with `is_rejected` set accordingly). `__call__(text)` is `apply(Document(text))` with the rejected-to-`""` shortcut applied to the result.
- Nested `Compose` objects in the filter list are **flattened** — inner filters are extracted and indexed sequentially.
- Filter names are set to `"{index}-{ClassName}"` (e.g., `"0-JSONLoader"`, `"1-Identity"`).
- The Compose's own statistics entry is named `"Total"`.
- **RNG propagation:** Sub-filters with `random_state=None` receive the Compose's shared RNG (seeded from `Compose`'s `random_state`), so the Compose seed drives their `p<1` apply/skip decisions — a fixed Compose seed yields a deterministic per-document outcome, and two different Compose seeds yield different outcomes. A sub-filter that was given its own `random_state` keeps it and is **not** overridden by the Compose seed.
- `apply_batch(batch) -> List[Document]`
- `apply_stream(stream) -> Iterable[Document]`: Chains each sub-filter's `apply_stream` in sequence, preserving each filter's batching behavior. It accumulates the **same** per-filter and `"Total"` statistics as `apply`/`apply_batch`: as documents flow through the stream, each sub-filter entry and the `"Total"` entry are updated with `input_num`/`output_num`/`discard_num`, byte/char counts, and diffs, so `get_total_statistics()`/`get_total_statistics_map()` after consuming an `apply_stream` reports the same accounting the equivalent `apply`/`__call__` sequence would.
- `get_total_statistics() -> List[Statistics]`: Returns `[Total, filter0, filter1, ...]`.
- `get_total_statistics_map() -> List[dict]`: Dict version.
- `shutdown()`: Cascades to all sub-filters. Also invoked via context manager `__exit__`.

### `hojichar.Parallel`

Applies a `Compose` filter in parallel across worker processes. Must be used as a context manager.

- Constructor: `Parallel(filter, num_jobs=None, ignore_errors=False)`. `ignore_errors` controls worker-exception handling: when `ignore_errors=True`, an exception raised while processing a document is caught and logged, that document is replaced by a rejected empty document (`Document("", is_rejected=True)`) that is still yielded back, and processing continues with the remaining documents; when `ignore_errors=False` the first such exception propagates out of `imap_apply` and terminates the whole parallel run.
- `imap_apply(docs) -> Iterator[Document]`: Processes documents via multiprocessing pool. Each worker runs its own independent copy of the pipeline. Workers return both the processed document and their accumulated statistics with each result. The Parallel class collects per-worker (per-PID) statistics as documents are yielded. Raises `RuntimeError` if called outside `with` block.
- `get_total_statistics_map() -> List[dict]`: Returns aggregated per-worker stats (reduces collected per-PID stats via `Statistics.add_list_of_stats`). Can be called inside the `with` block.
- `statistics_obj` (property): Returns `StatsContainer` from aggregated stats.
- On context exit, the per-worker statistics are aggregated across all workers and merged back so that the original filter's public statistics (`get_total_statistics_map()` / `statistics_obj`) reflect the full parallel run.

### Async Pipeline

**`AsyncFilter`**: Async equivalent of `Filter`. Constructor: `AsyncFilter(*, p=1.0, skip_rejected=True, random_state=None, use_batch=True, batch_size=128)`. Users implement `async apply(document) -> Document`. Supports `async __call__`, `async apply_batch`, `async apply_stream`, `async shutdown`, and async context manager.

**`AsyncFilterAdapter`**: Wraps a sync `Filter` for use inside `AsyncCompose`. Constructor: `AsyncFilterAdapter(sync_filter, *, executor=None, use_batch=True)`.

**`AsyncCompose`**: Async equivalent of `Compose`. Constructor: `AsyncCompose(filters, random_state=None, executor=None)`. Sync `Filter` objects are automatically wrapped in `AsyncFilterAdapter`. When naming filters, uses `"{index}-{OriginalClassName}"` (the original class name before wrapping, e.g., `"0-JSONLoader"` not `"0-AsyncFilterAdapter"`). The `async apply(doc)` method tracks "Total" statistics (input/output/discard counts) around the full pipeline. `async apply_batch(batch)` also tracks per-document statistics via a finalize step. Supports `async apply_stream`, flattening, `get_total_statistics_map`, `async shutdown`, and async context manager.

- **Flattening contract:** a nested `Compose` (sync) **or** `AsyncCompose` in the filter list is flattened — its sub-filters are extracted into the parent and indexed sequentially alongside the rest. Each extracted sync `Filter` sub-filter is wrapped in `AsyncFilterAdapter` (a native `AsyncFilter` sub-filter is kept as-is), and every sub-filter is named `"{index}-{OriginalClassName}"` using its original (pre-wrapping) class name.
- **`async apply_stream` input contract:** accepts an iterable of `Document`s that may be **either** synchronous (a list or generator) **or** asynchronous (an async iterable); a synchronous iterable is adapted into the async stream internally. It is itself an async generator (consume it with `async for`).

### Inspection Module (`hojichar.core.inspection`)

**`StatsContainer`**: Dataclass with `total_info` and `layers_info`, summarizing a run's `Statistics`. Used by `Parallel.statistics_obj`.

- `total_info` is an **attribute-bearing object** (not a plain dict): its members are read by attribute, e.g. `stats_obj.total_info.processed_num`. It carries `processed_num` — the number of documents processed, equal to the Total entry's `input_num` — and `discard_num` — the Total `discard_num` — among other roll-up fields.
- `layers_info` holds the per-filter summaries keyed by filter name.
- When serialized to JSON (see CLI `--dump-stats`), the same data is rendered as `{"total_info": {...}, "layers_info": [...]}`, where `total_info` becomes a plain dict carrying the same keys (`processed_num`, `discard_num`, …) accessed by key, and `layers_info` becomes a list of per-filter dicts. So `processed_num` is reachable as `total_info.processed_num` in memory and as `total_info["processed_num"]` in the dumped JSON.

## Built-in Filters (`hojichar.filters.document_filters`)

### Text I/O
- **`JSONLoader(key="text", ignore=False, extra_keys=None)`**: Parses `document.text` as JSON and extracts `key`. Merges embedded `"extras"` dict into `document.extras`. `extra_keys` copies additional fields; missing fields are silently skipped; if `extra_keys` includes `"extras"` and the value is a dict it is merged, otherwise stored as-is; empty list copies nothing. Raises `json.JSONDecodeError` on parse failure (unless `ignore=True` which sets `is_rejected`). Raises `KeyError` on missing key.
- **`JSONDumper(dump_reason=False, export_extras=False, skip_rejected=False)`**: Wraps text into `{"text": ...}` JSON. `dump_reason=True` adds `"is_rejected"` and `"reason"`. `export_extras=True` adds `"extras"`. `skip_rejected=False` means rejected docs are still processed.

### Text Normalization
- **`DocumentNormalizer()`**: Applies `unicodedata.normalize("NFKC", text)`.

### Filtering
- **`DocumentLengthFilter(min_doc_len=None, max_doc_len=None)`**: Rejects by character count.
- **`AcceptJapanese(lookup_size=50)`**: Rejects if no hiragana/katakana in first `lookup_size` chars. Regex: `[ぁ-んァ-ン]`.
- **`DiscardRareKuten(max_average_sentence_length=100)`**: Splits on `。`, rejects if avg segment too long.
- **`DiscardBBSComments(max_allowed_num=14)`**: Counts matches of a regex targeting BBS-style content — dates in various formats (`\d{4}[年.\-/]\d{1,2}[月.\-/]\d{1,2}[日]*`), plus keywords: `コメント`, `SOLD OUT`, `レビュー`, `投稿`, `ページ`, day-of-week patterns (`(月)` through `(日)`), `質問`, `\d+話`, `楽天市場`, `-`. Rejects if match count > `max_allowed_num`.

### Personal Information Masking
- **`MaskPersonalInformation()`**: Masks phone numbers and email addresses, supporting Japanese and international formats.
  - **Phone numbers**: A phone number is a run of 10–11 digits, optionally grouped by `-` or space separators, with either a leading `0` or a leading `+` followed by a 1–3 digit country code (optionally separated). Exactly the **trailing 4 digits** are replaced with `XXXX`; the rest of the number (including the prefix and any separators) is preserved verbatim. The recognized digit groupings before the final 4 digits are the common Japanese landline/mobile shapes (`\d{2}-\d{4}`, `\d-\d{4}`, `\d{2}-\d{3}`, `\d{3}-\d{2}`, `\d{4}-\d`), each with optional separators.
  - **Emails**: An email (local part `@` domain with at least one `.label`) is replaced with `xxxx@yyy.{last_label}`, where `{last_label}` is **only the final dot-separated label** of the domain (the rest of the domain is dropped).
  - Substrings without personal information are left unchanged, and multiple matches in one document are each masked.

### Content Quality
- **`CharRepetitionRatioFilter(threshold=0.33, ngram_size=5)`**: Computes character n-gram repetition ratio. Rejects if >= threshold. Static method `compute_character_repetition_ratio(text, n)` returns 0.0 for short/empty text (fewer chars than `n`). Algorithm: build a frequency dict of all character n-grams; let `freq_list` be the sorted (descending) list of frequencies; let `val_one` = count of n-grams with frequency 1; let `num_rep = min(int(numpy.sqrt(num_unique_ngrams)), num_unique_ngrams - val_one)`; ratio = `sum(freq_list[:num_rep]) / sum(freq_list)`. Returns 0.0 when frequency dict is empty.
- **`SingleCharacterRepetitionFilter(threshold=200)`**: Rejects if any character repeated >= threshold times consecutively.
- **`DiscardTooManyEndingEllipsis(threshold=0.7)`**: Regex `(\.{3}|…)\n`. Rejects if ratio > threshold.
- **`DiscardTooShortLines(threshold=0.5)`**: Lines <= 10 chars. Rejects if ratio > threshold.

### NG Word Filters
- **`NgWordsFilterJa(dict_path)`**: Newline-separated keywords.
- **`NgWordsFilterEn(dict_path)`**: Word-boundary matching, case-insensitive. Regex: `(?:^| )({words})(?:( |,|\.)|$)`.
- **`DiscardAds(dict_path=<built-in>, max_allowed_num=14)`**: Counts keyword matches, rejects if > threshold.

### Header/Footer Removal
- **`HeaderFooterTagsRemover(dict_path=<built-in>)`**: Inspects the tokens nearest the start and end of the document (more positions are inspected for longer documents) and rejects any such token whose text **starts with** one of the built-in header/footer keywords (an anchored prefix match, so a token like `"トップページ。"` matches the keyword `"トップページ"`). A matched token has its `is_rejected` set to `True`; the filter is a no-op when the document has no tokens. The built-in keyword file contains common Japanese header/footer strings (e.g., "トップページ", "ホーム>", "前の記事", "次の記事", "お名前", "検索", "アーカイブ", etc.) plus the test sentinel `<TEST_STRING_OF_KEYWORD>`.

### Utility Filters
- **`ExampleHojiChar()`**: Appends `"<hojichar>"`.
- **`Identity()`**: No-op.
- **`DiscardAll()`**: Rejects everything.

## Token Filters (`hojichar.filters.token_filters`)

- **`SEOTokenRemover(min_average_seo_char_length=5)`**: A **token-level** filter — its `apply(token: Token) -> Token` operates on a single `Token` (reading and rewriting `token.text`) and returns that same `Token`, in contrast to the document-level `apply(document) -> Document` of an ordinary document filter. It is nonetheless a `hojichar.Filter` subclass and so supports the same string-call convention as `hojichar.Filter`: `__call__(text: str) -> str` wraps the input string in a `Token`, runs `apply`, and returns the resulting `token.text`. It splits the token text (after stripping) on ` `, `-`, `・`, `,` to get words, then computes the average characters per word as `len(text) / n_words`. The removal branch runs only when that average is **strictly greater than** `min_average_seo_char_length` (so `min_average_seo_char_length=1` forces removal on essentially any multi-character single token); otherwise the token is returned unchanged. When removal runs, it searches for a decorative separator run and deletes the **first** match only, leaving all surrounding text intact. A decorative run is a star-delimited bar: a `★`, followed by one or more of the characters `…` (horizontal ellipsis, U+2026) or `━` (heavy horizontal bar, U+2501), followed by a closing `★` — i.e. the pattern `★[…━]+★`. (Several other long-dash / hash / dollar / percent separator runs may also be recognized; the star-bar form above is the one exercised here.) Normal text with no such run is unchanged.

## Tokenization (`hojichar.filters.tokenization`)

- **`BlankCharTokenizer()`**: Splits on whitespace (`text.split()`), stores as tokens. Has `tokenize(text) -> List[str]`.
- **`SentenceTokenizer()`**: Splits on `。`, preserving it on each segment (last segment has no `。` unless text ends with one). Has `tokenize(text) -> List[str]`.
- **`MergeTokens()`**: Joins non-rejected tokens with `"".join()` (no separator). Has `merge(tokens) -> str`.

## Deduplication (`hojichar.filters.deduplication`)

Requires: `datasketch`, `rensa`, `xxhash`, `nltk`, `redis`.

**Free functions:**
- `char_level_splitter(text)` -> list of individual characters.
- `non_alpha_num_splitter(text)` -> list of alphanumeric tokens.

**`GenerateDedupLSH(num_perm=500, threshold=0.8, tokenizer=char_level_splitter, n_grams=5, seed=42)`**: Computes MinHash + LSH keys. `num_bands` and `band_size` are derived from `threshold` and `num_perm` (choosing a band/row split appropriate for the similarity threshold), and `num_bands` is exposed as a public attribute equal to the number of LSH keys produced. Methods: `calculate_minhash_signature(text) -> NDArray[np.uint32]` (shape `(num_perm,)`), `signature_to_lsh_digest(sig, band_size, band_idx) -> int` (xxhash-128), `apply(doc)` stores `extras["dedup_lsh"]` as list of `"{band_idx}+{digest:032x}"` strings.

**`InlineDeduplicator()`**: Stores LSH keys in a local set. Rejects if any key seen before. Raises `ValueError` if `dedup_lsh` missing.

**`RedisDeduplicator(host, port, db=0, key_prefix="dedup")`**: Same logic via Redis `SET NX` pipeline. Raises `ValueError` if `dedup_lsh` missing.

**`InlineDuplicateAnalyzer()`**: Like InlineDeduplicator but also stores `extras["similar_doc"]` with matching document's text.

## Profile Loading (`hojichar.utils.load_compose`)

- **FILTER pattern**: File defines `FILTER = Compose([...])`. Loaded by `load_filter_from_file(path)`. Raises `TypeError` / `NotImplementedError`.
- **FACTORY pattern**: File defines `FACTORY = callable`. Loaded by `load_factory_from_file(path)` or `load_parametrized_filter_from_file(path, *args)`.
- **`load_compose(path, *args)`**: Auto-detects FILTER vs FACTORY.

All functions add the profile's parent directory to `sys.path`.

## CLI (`hojichar.cli`)

Entry point: `hojichar` (or `python -m hojichar.cli`).

Flags: `-p/--profile` (required), `-i/--input`, `-o/--output`, `-j/--jobs`, `--args`, `--dump-stats`, `--all`, `--exit-on-error`.

Behavior: reads lines from input, wraps each line in a `Document`, and processes it at the `Document` level through the loaded Compose (so each output line is the resulting `Document.text` after the pipeline runs — for a profile ending in `JSONDumper`, the dumped JSON line). By default only non-rejected documents are written to output. `--all` additionally writes the rejected documents, and each rejected document is emitted with the **same** pipeline-processed `Document.text` a non-rejected document would receive (e.g. its `JSONDumper` JSON line) — it is **not** collapsed to an empty string or a blank line. Stats printed to stderr. `--dump-stats` appends stats JSON (`{"total_info": {...}, "layers_info": [...]}`) to file. Progress bar via `tqdm`.

## Public Re-exports (`hojichar.__init__`)

Exports: `Compose`, `Filter`, `Document`, `Token`, `Parallel`, `StatsContainer`, `AsyncCompose`, `AsyncFilterAdapter`, `AsyncFilter`, and sub-modules `document_filters`, `deduplication`, `language_identification`, `tokenization`.
