"""Hidden test suite for the hojichar WRG task."""

import json
import os
import subprocess
import sys
import textwrap

import pytest

import hojichar
from hojichar import Compose, Document, Filter, Parallel, document_filters
from hojichar.filters.document_filters import (
    AcceptJapanese,
    CharRepetitionRatioFilter,
    DiscardAll,
    DiscardBBSComments,
    DiscardRareKuten,
    DiscardTooManyEndingEllipsis,
    DiscardTooShortLines,
    DocumentLengthFilter,
    DocumentNormalizer,
    ExampleHojiChar,
    Identity,
    JSONDumper,
    JSONLoader,
    MaskPersonalInformation,
    NgWordsFilterEn,
    NgWordsFilterJa,
    SingleCharacterRepetitionFilter,
)
from hojichar.filters.tokenization import (
    BlankCharTokenizer,
    MergeTokens,
    SentenceTokenizer,
)
from hojichar.utils.load_compose import (
    load_compose,
    load_filter_from_file,
    load_parametrized_filter_from_file,
)


class RaiseOnBomb(Filter):
    """Module-level filter that raises ValueError on the document text "bomb".

    Defined at module scope (not inside a test) so it is picklable into the
    Parallel worker processes, where it exercises the ignore_errors branch.
    """

    def apply(self, document: Document) -> Document:
        if document.text == "bomb":
            raise ValueError("boom")
        return document


# ---------------------------------------------------------------------------
# Test 1: Full JSON-in / JSON-out pipeline with filtering and statistics
# ---------------------------------------------------------------------------
class TestComposeJsonPipeline:
    def test_full_pipeline_accept_and_transform(self):
        """A realistic JSONL preprocessing workflow: load JSON, filter by
        language + length, normalize unicode, and dump back to JSON. Verifies
        the complete round-trip produces correct output and that per-filter
        statistics are tracked accurately."""
        cleaner = Compose(
            [
                JSONLoader(key="text"),
                AcceptJapanese(),
                DocumentLengthFilter(min_doc_len=1, max_doc_len=100),
                DocumentNormalizer(),
                JSONDumper(),
            ]
        )

        result = cleaner('{"text": "ﾃｽﾄ文章です"}')
        data = json.loads(result)
        assert data["text"] == "テスト文章です"

        stats = cleaner.get_total_statistics_map()
        total = stats[0]
        assert total["name"] == "Total"
        assert total["input_num"] == 1
        assert total["output_num"] == 1
        assert total["discard_num"] == 0

        loader_stat = stats[1]
        assert loader_stat["name"] == "0-JSONLoader"
        assert loader_stat["input_num"] == 1

    def test_pipeline_rejects_non_japanese(self):
        """Non-Japanese text is rejected and the pipeline returns empty string.
        Verifies discard tracking in statistics."""
        cleaner = Compose(
            [
                JSONLoader(key="text"),
                AcceptJapanese(),
                JSONDumper(),
            ]
        )

        result = cleaner('{"text": "This is English only"}')
        assert result == ""

        total = cleaner.get_total_statistics_map()[0]
        assert total["discard_num"] == 1

    def test_pipeline_rejects_by_length(self):
        """Documents exceeding max_doc_len or below min_doc_len are rejected."""
        cleaner_max = Compose(
            [
                JSONLoader(key="text"),
                DocumentLengthFilter(max_doc_len=10),
                JSONDumper(),
            ]
        )
        assert cleaner_max('{"text": "abcdefghijklmnop"}') == ""

        cleaner_min = Compose(
            [
                JSONLoader(key="text"),
                DocumentLengthFilter(min_doc_len=10),
                JSONDumper(),
            ]
        )
        assert cleaner_min('{"text": "hi"}') == ""


# ---------------------------------------------------------------------------
# Test 2: JSONLoader and JSONDumper metadata round-trip
# ---------------------------------------------------------------------------
class TestJsonMetadataRoundTrip:
    def test_extras_preserved_through_pipeline(self):
        """JSONLoader merges embedded 'extras' dict and extra_keys into
        Document.extras; JSONDumper with export_extras writes them back.
        Verifies the full metadata round-trip including key merging."""
        pipeline = Compose(
            [
                JSONLoader(extra_keys=["url"]),
                DocumentNormalizer(),
                JSONDumper(export_extras=True),
            ]
        )

        inp = json.dumps(
            {
                "text": " Hello ",
                "extras": {"source": "blog"},
                "url": "https://example.com",
            }
        )
        result = json.loads(pipeline(inp))

        assert result["text"] == " Hello "
        assert result["extras"]["source"] == "blog"
        assert result["extras"]["url"] == "https://example.com"

    def test_json_loader_custom_key(self):
        """JSONLoader extracts from a non-default key."""
        loader = JSONLoader(key="content")
        doc = loader.apply(Document('{"content": "abc", "other": 1}'))
        assert doc.text == "abc"

    def test_json_loader_error_handling(self):
        """JSONLoader with ignore=True rejects broken JSON; without ignore raises.
        Also raises KeyError on missing key."""
        loader_ignore = JSONLoader(ignore=True)
        doc = loader_ignore.apply(Document("{broken json"))
        assert doc.is_rejected is True

        loader_strict = JSONLoader(ignore=False)
        with pytest.raises(json.JSONDecodeError):
            loader_strict.apply(Document("{broken json"))

        loader_key = JSONLoader(key="text")
        with pytest.raises(KeyError):
            loader_key.apply(Document('{"other": "value"}'))

    def test_json_dumper_options(self):
        """JSONDumper with dump_reason and/or export_extras includes
        the appropriate fields in output."""
        # dump_reason only
        dumper_reason = JSONDumper(dump_reason=True)
        doc = Document("hello", is_rejected=True)
        doc.reject_reason = {"name": "SomeFilter"}
        result = dumper_reason.apply(doc)
        data = json.loads(result.text)
        assert data["is_rejected"] is True
        assert data["reason"]["name"] == "SomeFilter"

        # both dump_reason and export_extras
        dumper_both = JSONDumper(dump_reason=True, export_extras=True)
        doc2 = Document("hello")
        doc2.extras["tag"] = "test"
        doc2.reject_reason = {}
        result2 = dumper_both.apply(doc2)
        data2 = json.loads(result2.text)
        assert data2["extras"]["tag"] == "test"
        assert "is_rejected" in data2
        assert "reason" in data2


# ---------------------------------------------------------------------------
# Test 3: User-defined filter in Compose with rejection and statistics
# ---------------------------------------------------------------------------
class TestUserDefinedFilterWorkflow:
    def test_custom_filter_rejects_and_tracks_stats(self):
        """A user-defined filter that rejects documents containing a keyword.
        The Compose pipeline correctly returns '' for rejected docs,
        populates reject_reason, and tracks discard_num in stats."""

        class RejectIfContains(Filter):
            def __init__(self, keyword, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.keyword = keyword

            def apply(self, document):
                if self.keyword in document.text:
                    document.is_rejected = True
                return document

        pipeline = Compose(
            [
                JSONLoader(),
                RejectIfContains("spam"),
                JSONDumper(),
            ]
        )

        assert pipeline('{"text": "hello world"}') != ""
        assert pipeline('{"text": "this is spam"}') == ""

        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == 2
        assert total["discard_num"] == 1
        assert total["output_num"] == 1

    def test_custom_filter_modifies_text_and_extras(self):
        """A custom filter that transforms text and writes to extras.
        Verifies the pipeline correctly chains custom transformations."""

        class UpperAndTag(Filter):
            def apply(self, document):
                document.extras["original_len"] = len(document.text)
                document.text = document.text.upper()
                return document

        pipeline = Compose(
            [
                JSONLoader(),
                UpperAndTag(),
                JSONDumper(export_extras=True),
            ]
        )

        result = json.loads(pipeline('{"text": "hello"}'))
        assert result["text"] == "HELLO"
        assert result["extras"]["original_len"] == 5


# ---------------------------------------------------------------------------
# Test 4: Compose flattening, skip_rejected, and probabilistic p
# ---------------------------------------------------------------------------
class TestComposeAdvancedBehavior:
    def test_nested_compose_flattens(self):
        """When a Compose is included as a filter inside another Compose,
        the inner filters are flattened. Verify via filter count and naming."""
        inner = Compose([Identity(), ExampleHojiChar()])
        outer = Compose([JSONLoader(), inner, JSONDumper()])

        # get_total_statistics_map() returns [Total, filter0, filter1, ...];
        # the sub-filter entries (index 1 onward) reflect the flattened list.
        sub_filters = outer.get_total_statistics_map()[1:]
        assert len(sub_filters) == 4
        names = [f["name"] for f in sub_filters]
        assert "0-JSONLoader" in names
        assert "1-Identity" in names
        assert "2-ExampleHojiChar" in names
        assert "3-JSONDumper" in names

    def test_skip_rejected_prevents_downstream_processing(self):
        """Once a document is rejected, downstream filters with
        skip_rejected=True do not modify the text."""
        pipeline = Compose([DiscardAll(), ExampleHojiChar()])
        doc = pipeline.apply(Document("hello"))
        assert doc.is_rejected is True
        assert "<hojichar>" not in doc.text

    def test_filter_p_boundary_values(self):
        """A filter with p=0 never applies (identity); p=1 always applies."""
        pipeline_p0 = Compose([ExampleHojiChar(p=0.0, random_state=42)])
        assert pipeline_p0("test") == "test"

        pipeline_p1 = Compose([ExampleHojiChar(p=1.0)])
        assert pipeline_p1("test") == "test<hojichar>"


# ---------------------------------------------------------------------------
# Test 6: Stream and batch processing through Compose
# ---------------------------------------------------------------------------
class TestStreamAndBatchProcessing:
    def test_apply_stream_processes_generator(self):
        """Compose.apply_stream processes a generator of Documents,
        yielding results one by one with correct statistics."""
        pipeline = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3),
            ]
        )

        docs = (Document(t) for t in ["ﾃｽﾄ", "ab", "ﾃﾞｰﾀ"])
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 3
        accepted = [d for d in results if not d.is_rejected]
        assert len(accepted) == 2
        assert accepted[0].text == "テスト"
        assert accepted[1].text == "データ"

        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == 3
        assert total["discard_num"] == 1

    def test_apply_batch_processes_list(self):
        """Compose.apply_batch processes a list of Documents at once."""
        pipeline = Compose(
            [
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        batch = [Document("hello world"), Document("hi"), Document("testing123")]
        results = pipeline.apply_batch(batch)

        assert len(results) == 3
        assert results[0].is_rejected is False
        assert results[1].is_rejected is True
        assert results[2].is_rejected is False


# ---------------------------------------------------------------------------
# Test 7: Content quality filters (character repetition, ellipsis, short lines)
# ---------------------------------------------------------------------------
class TestContentQualityFilters:
    def test_char_repetition_filter(self):
        """CharRepetitionRatioFilter rejects text with high repetition ratio
        and accepts diverse text."""
        filt = CharRepetitionRatioFilter(threshold=0.3, ngram_size=3)
        doc_rep = filt.apply(Document("abcabcabcabcabcabcabcabc"))
        assert doc_rep.is_rejected is True

        filt2 = CharRepetitionRatioFilter(threshold=0.3, ngram_size=5)
        doc_div = filt2.apply(
            Document("The quick brown fox jumps over the lazy dog near the river bank")
        )
        assert doc_div.is_rejected is False

    def test_single_char_repetition_filter(self):
        """SingleCharacterRepetitionFilter rejects/accepts based on
        consecutive character repetition threshold."""
        filt = SingleCharacterRepetitionFilter(threshold=10)
        doc_rep = filt.apply(Document("hello" + "a" * 10 + "world"))
        assert doc_rep.is_rejected is True

        doc_norm = filt.apply(Document("hello world, this is normal text"))
        assert doc_norm.is_rejected is False

    def test_ellipsis_filter(self):
        """DiscardTooManyEndingEllipsis rejects documents where most lines
        end with '...' and accepts normal text."""
        filt = DiscardTooManyEndingEllipsis(threshold=0.5)
        doc_ell = filt.apply(
            Document("line one...\nline two...\nline three...\nline four\n")
        )
        assert doc_ell.is_rejected is True

        doc_norm = filt.apply(
            Document("This is normal.\nAnother line.\nAnd another.\n")
        )
        assert doc_norm.is_rejected is False

    def test_short_lines_filter(self):
        """DiscardTooShortLines rejects documents with many short lines
        and accepts documents with long lines."""
        filt = DiscardTooShortLines(threshold=0.5)
        doc_short = filt.apply(Document("a\nb\nc\nd\ne\nf\ng\nh\ni\nj\n"))
        assert doc_short.is_rejected is True

        doc_long = filt.apply(
            Document("This is a reasonably long line of text\nAnother long line here\n")
        )
        assert doc_long.is_rejected is False


# ---------------------------------------------------------------------------
# Test 8: Personal information masking
# ---------------------------------------------------------------------------
class TestPersonalInfoMasking:
    def test_mask_phone_and_email(self):
        """MaskPersonalInformation masks phone numbers and email addresses
        in various formats, including embedded in surrounding text."""
        filt = MaskPersonalInformation()
        # Basic phone formats
        assert filt("075-123-4567") == "075-123-XXXX"
        assert filt("090-1234-5678") == "090-1234-XXXX"
        assert filt("08012345678") == "0801234XXXX"
        # International phone
        assert filt("+81-80-1234-5678") == "+81-80-1234-XXXX"
        assert filt("+818012345678") == "+81801234XXXX"
        # Basic email
        assert filt("hogehoge@example.com") == "xxxx@yyy.com"
        # Email with multi-part TLD
        assert filt("hogehoge@example.ne.jp") == "xxxx@yyy.jp"
        # Embedded in text
        assert filt("連絡は075-123-4567 まで") == "連絡は075-123-XXXX まで"
        # No personal info: unchanged
        text = "This is normal text without any personal information."
        assert filt(text) == text
        # Multiple phones
        assert (
            filt("電話1: 075-123-4567 電話2: 090-1234-5678")
            == "電話1: 075-123-XXXX 電話2: 090-1234-XXXX"
        )
        # Multiple emails
        assert (
            filt("CC: alice@foo.com and bob@bar.org")
            == "CC: xxxx@yyy.com and xxxx@yyy.org"
        )
        # Mixed email and phone
        result = filt("連絡先: user@example.com / 075-123-4567")
        assert "xxxx@yyy.com" in result
        assert "075-123-XXXX" in result


# ---------------------------------------------------------------------------
# Test 9: Tokenization pipeline (tokenize -> filter -> merge)
# ---------------------------------------------------------------------------
class TestTokenizationPipeline:
    def test_blank_char_tokenizer_splits_on_whitespace(self):
        """BlankCharTokenizer splits text into tokens on whitespace characters."""
        tokenizer = BlankCharTokenizer()
        doc = Document("alpha beta gamma")
        result = tokenizer.apply(doc)
        assert len(result.tokens) == 3
        assert result.tokens[0].text == "alpha"
        assert result.tokens[1].text == "beta"
        assert result.tokens[2].text == "gamma"

    def test_sentence_tokenizer_splits_on_kuten(self):
        """SentenceTokenizer splits text into tokens on Japanese period."""
        tokenizer = SentenceTokenizer()
        doc = Document("おはよう。おやすみ。ありがとう。")
        result = tokenizer.apply(doc)
        assert len(result.tokens) == 3
        assert result.tokens[0].text == "おはよう。"
        assert result.tokens[1].text == "おやすみ。"
        assert result.tokens[2].text == "ありがとう。"

    def test_merge_tokens_joins_back(self):
        """MergeTokens joins document tokens back into text without separator."""
        pipeline = Compose(
            [
                BlankCharTokenizer(),
                MergeTokens(),
            ]
        )
        doc = pipeline.apply(Document("alpha beta gamma"))
        assert doc.text == "alphabetagamma"


# ---------------------------------------------------------------------------
# Test 10: Profile loading (FILTER and FACTORY patterns)
# ---------------------------------------------------------------------------
class TestProfileLoading:
    def test_load_filter_profile(self, tmp_path):
        """load_filter_from_file loads a profile defining FILTER as a Compose."""
        profile = tmp_path / "filter_profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import ExampleHojiChar

            FILTER = Compose([ExampleHojiChar()])
        """
            )
        )

        filt = load_filter_from_file(str(profile))
        assert isinstance(filt, Compose)
        assert filt("hello") == "hello<hojichar>"

    def test_load_factory_profile(self, tmp_path):
        """load_parametrised_filter_from_file loads a FACTORY profile
        that accepts arguments."""
        profile = tmp_path / "factory_profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose, Filter, Document

            class AddSuffix(Filter):
                def __init__(self, suffix, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.suffix = suffix
                def apply(self, document):
                    document.text += self.suffix
                    return document

            def create(suffix):
                return Compose([AddSuffix(suffix)])

            FACTORY = create
        """
            )
        )

        filt = load_parametrized_filter_from_file(str(profile), "!!!")
        assert filt("hello") == "hello!!!"

    def test_load_compose_autodetects(self, tmp_path):
        """load_compose auto-detects FILTER vs FACTORY pattern."""
        profile = tmp_path / "auto_profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import Identity

            FILTER = Compose([Identity()])
        """
            )
        )

        filt = load_compose(str(profile))
        assert filt("test") == "test"


# ---------------------------------------------------------------------------
# Test 11: CLI tool end-to-end (merged: TestCLI + TestCLIWithFactory + TestCLIStdin)
# ---------------------------------------------------------------------------
class TestCLI:
    def test_cli_processes_jsonl_with_profile(self, tmp_path):
        """The hojichar CLI reads JSONL from --input, applies a profile,
        and writes output to --output. Verifies the complete CLI workflow."""
        profile = tmp_path / "profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import JSONLoader, JSONDumper, DocumentNormalizer

            FILTER = Compose([
                JSONLoader(),
                DocumentNormalizer(),
                JSONDumper(),
            ])
        """
            )
        )

        input_file = tmp_path / "input.jsonl"
        lines = [
            json.dumps({"text": "ﾃｽﾄ"}),
            json.dumps({"text": "ﾃﾞｰﾀ"}),
        ]
        input_file.write_text("\n".join(lines) + "\n")

        output_file = tmp_path / "output.jsonl"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "-i",
                str(input_file),
                "-o",
                str(output_file),
                "-j",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output_lines = output_file.read_text().strip().split("\n")
        assert len(output_lines) == 2
        assert json.loads(output_lines[0])["text"] == "テスト"
        assert json.loads(output_lines[1])["text"] == "データ"

    def test_cli_rejects_filtered_docs(self, tmp_path):
        """The CLI excludes rejected documents from output by default."""
        profile = tmp_path / "reject_profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import (
                JSONLoader, JSONDumper, DocumentLengthFilter
            )

            FILTER = Compose([
                JSONLoader(),
                DocumentLengthFilter(min_doc_len=5),
                JSONDumper(),
            ])
        """
            )
        )

        input_file = tmp_path / "input.jsonl"
        lines = [
            json.dumps({"text": "hi"}),
            json.dumps({"text": "hello world"}),
        ]
        input_file.write_text("\n".join(lines) + "\n")

        output_file = tmp_path / "output.jsonl"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "-i",
                str(input_file),
                "-o",
                str(output_file),
                "-j",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output_lines = output_file.read_text().strip().split("\n")
        assert len(output_lines) == 1
        assert json.loads(output_lines[0])["text"] == "hello world"

    def test_cli_all_flag_includes_rejected(self, tmp_path):
        """The --all flag includes rejected documents in the output."""
        profile = tmp_path / "reject_profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import (
                JSONLoader, JSONDumper, DocumentLengthFilter
            )

            FILTER = Compose([
                JSONLoader(),
                DocumentLengthFilter(min_doc_len=5),
                JSONDumper(),
            ])
        """
            )
        )

        input_file = tmp_path / "input.jsonl"
        lines = [
            json.dumps({"text": "hi"}),
            json.dumps({"text": "hello world"}),
        ]
        input_file.write_text("\n".join(lines) + "\n")

        output_file = tmp_path / "output.jsonl"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "-i",
                str(input_file),
                "-o",
                str(output_file),
                "-j",
                "1",
                "--all",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output_lines = output_file.read_text().strip().split("\n")
        assert len(output_lines) == 2

    def test_cli_dump_stats(self, tmp_path):
        """--dump-stats writes pipeline statistics to a file."""
        profile = tmp_path / "profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import JSONLoader, JSONDumper

            FILTER = Compose([JSONLoader(), JSONDumper()])
        """
            )
        )

        input_file = tmp_path / "input.jsonl"
        input_file.write_text(json.dumps({"text": "hello"}) + "\n")

        output_file = tmp_path / "output.jsonl"
        stats_file = tmp_path / "stats.json"

        subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "-i",
                str(input_file),
                "-o",
                str(output_file),
                "-j",
                "1",
                "--dump-stats",
                str(stats_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert stats_file.exists()
        stats_data = json.loads(stats_file.read_text().strip())
        # One input document was processed end-to-end.
        assert stats_data["total_info"]["processed_num"] == 1

    def test_cli_factory_profile_with_args(self, tmp_path):
        """CLI loads a FACTORY profile and passes --args to it."""
        profile = tmp_path / "factory.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose, Filter, Document

            class AddSuffix(Filter):
                def __init__(self, suffix, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.suffix = suffix
                def apply(self, document):
                    document.text = document.text.rstrip("\\n") + self.suffix
                    return document

            def factory(suffix):
                return Compose([AddSuffix(suffix)])

            FACTORY = factory
        """
            )
        )

        input_file = tmp_path / "input.txt"
        input_file.write_text("hello\nworld\n")

        output_file = tmp_path / "output.txt"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "--args",
                "!!!",
                "-i",
                str(input_file),
                "-o",
                str(output_file),
                "-j",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        lines = output_file.read_text().strip().split("\n")
        assert lines[0] == "hello!!!"
        assert lines[1] == "world!!!"

    def test_cli_reads_from_stdin(self, tmp_path):
        """The hojichar CLI reads from stdin when no --input is specified,
        and writes to --output."""
        profile = tmp_path / "profile.py"
        profile.write_text(
            textwrap.dedent(
                """\
            from hojichar import Compose
            from hojichar.filters.document_filters import DocumentNormalizer

            FILTER = Compose([DocumentNormalizer()])
        """
            )
        )

        output_file = tmp_path / "output.txt"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hojichar.cli",
                "-p",
                str(profile),
                "-o",
                str(output_file),
                "-j",
                "1",
            ],
            input="ﾃｽﾄ\nﾃﾞｰﾀ\n",
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output_lines = output_file.read_text().strip().split("\n")
        assert len(output_lines) == 2
        assert output_lines[0] == "テスト"
        assert output_lines[1] == "データ"


# ---------------------------------------------------------------------------
# Test 12: Parallel processing (merged: TestParallelProcessing +
#   TestParallelWithErrors + TestParallelStatisticsProperties +
#   TestParallelCorrectOutput)
# ---------------------------------------------------------------------------
class TestParallelProcessing:
    def test_parallel_processes_documents(self):
        """Parallel.imap_apply processes documents across multiple workers
        and returns all results."""
        cleaner = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3),
            ]
        )

        docs = [Document(t) for t in ["ﾃｽﾄ", "ab", "ﾃﾞｰﾀ", "xy", "ﾃﾞｰﾀ処理"]]

        with Parallel(cleaner, num_jobs=1) as pfilter:
            results = list(pfilter.imap_apply(iter(docs)))

        assert len(results) == 5
        accepted = [d for d in results if not d.is_rejected]
        rejected = [d for d in results if d.is_rejected]
        assert len(accepted) == 3
        assert len(rejected) == 2

    def test_parallel_aggregates_statistics(self):
        """After processing a stream through Parallel, per-worker statistics are
        aggregated into a Total exposed both via get_total_statistics_map() and
        the statistics_obj StatsContainer, with input/output/discard accounted for.
        On context exit the same aggregate is merged back into the ORIGINAL
        Compose, whose own statistics then report the full parallel run."""
        from hojichar.core.inspection import StatsContainer

        cleaner = Compose([DocumentLengthFilter(min_doc_len=5)])

        docs = [Document(t) for t in ["hello world", "hi", "test data here"]]

        with Parallel(cleaner, num_jobs=1) as pfilter:
            list(pfilter.imap_apply(iter(docs)))
            stats_map = pfilter.get_total_statistics_map()
            stats_obj = pfilter.statistics_obj

        total = stats_map[0]
        assert total["name"] == "Total"
        assert total["input_num"] == 3
        assert total["discard_num"] == 1
        assert total["output_num"] == 2

        assert isinstance(stats_obj, StatsContainer)
        assert stats_obj.total_info.processed_num == 3
        assert stats_obj.total_info.discard_num == 1

        # The worker statistics are merged back on __exit__, so the original
        # Compose (which never processed a document in this process) now
        # reports the whole parallel run through its own public statistics.
        total_after = cleaner.get_total_statistics_map()[0]
        assert total_after["name"] == "Total"
        assert total_after["input_num"] == 3
        assert total_after["discard_num"] == 1
        assert total_after["output_num"] == 2

    def test_parallel_ignore_errors_continues(self):
        """Parallel with ignore_errors=True catches an exception raised in a
        worker for one document and still processes the remaining documents."""
        cleaner = Compose([RaiseOnBomb()])

        good_texts = ["alpha", "beta", "gamma", "delta"]
        docs = [Document(t) for t in good_texts[:2] + ["bomb"] + good_texts[2:]]

        with Parallel(cleaner, num_jobs=1, ignore_errors=True) as pfilter:
            results = list(pfilter.imap_apply(iter(docs)))

        # All 5 documents come back; only the one that raised is rejected.
        assert len(results) == 5
        rejected = [d for d in results if d.is_rejected]
        accepted = [d for d in results if not d.is_rejected]
        assert len(rejected) == 1
        assert sorted(d.text for d in accepted) == sorted(good_texts)

    def test_parallel_imap_outside_context_raises(self):
        """Calling imap_apply outside a 'with' block raises RuntimeError."""
        cleaner = Compose([Identity()])
        pfilter = Parallel(cleaner, num_jobs=1)

        with pytest.raises(RuntimeError):
            list(pfilter.imap_apply(iter([Document("test")])))

    def test_parallel_matches_sequential_output(self):
        """Verify that Parallel produces the SAME results as sequential
        processing (just potentially reordered). Process identical inputs
        both ways and compare."""
        pipeline = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3),
                ExampleHojiChar(),
            ]
        )

        inputs = ["ﾃｽﾄ", "ab", "ﾃﾞｰﾀ", "xy", "hello world"]

        # Sequential processing
        sequential_results = {}
        for t in inputs:
            result = pipeline(t)
            sequential_results[t] = result

        # Reset stats for parallel
        pipeline2 = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3),
                ExampleHojiChar(),
            ]
        )

        docs = [Document(t) for t in inputs]
        with Parallel(pipeline2, num_jobs=1) as pfilter:
            parallel_results_list = list(pfilter.imap_apply(iter(docs)))

        # Compare: each doc should have the same text and rejection status
        parallel_results = {}
        for doc in parallel_results_list:
            orig = doc.original
            if doc.is_rejected:
                parallel_results[orig] = ""
            else:
                parallel_results[orig] = doc.text

        for inp in inputs:
            assert sequential_results[inp] == parallel_results[inp], (
                f"Mismatch for input '{inp}': "
                f"sequential='{sequential_results[inp]}' vs "
                f"parallel='{parallel_results[inp]}'"
            )


# ---------------------------------------------------------------------------
# Test 13: NG words filtering
# ---------------------------------------------------------------------------
class TestNgWordsFiltering:
    def test_ng_words_ja(self, tmp_path):
        """NgWordsFilterJa rejects documents containing NG words and
        accepts clean documents."""
        dict_file = tmp_path / "ng_words.txt"
        dict_file.write_text("スパム\n悪質\n")

        filt_ja = NgWordsFilterJa(dict_path=str(dict_file))

        doc_match = filt_ja.apply(Document("この文章にはスパムが含まれます"))
        assert doc_match.is_rejected is True

        doc_clean = filt_ja.apply(Document("きれいな文章です"))
        assert doc_clean.is_rejected is False

    def test_ng_words_en(self, tmp_path):
        """NgWordsFilterEn rejects documents containing English NG words
        (word-boundary aware) and accepts clean documents."""
        dict_file = tmp_path / "ng_words_en.txt"
        dict_file.write_text("badword\nspam\n")

        filt = NgWordsFilterEn(dict_path=str(dict_file))
        doc_match = filt.apply(Document("this contains badword in it"))
        assert doc_match.is_rejected is True

        doc_clean = filt.apply(Document("this is a clean document"))
        assert doc_clean.is_rejected is False


# ---------------------------------------------------------------------------
# Test 14: Japanese-specific filters
# ---------------------------------------------------------------------------
class TestJapaneseFilters:
    def test_accept_japanese(self):
        """AcceptJapanese rejects non-Japanese text, accepts Japanese text,
        and only checks first lookup_size characters."""
        filt = AcceptJapanese(lookup_size=50)
        doc_en = filt.apply(Document("This is English text only"))
        assert doc_en.is_rejected is True

        filt2 = AcceptJapanese()
        doc_ja = filt2.apply(Document("これは日本語です"))
        assert doc_ja.is_rejected is False

        filt3 = AcceptJapanese(lookup_size=5)
        doc_beyond = filt3.apply(Document("abcde" + "あ"))
        assert doc_beyond.is_rejected is True

    def test_discard_rare_kuten(self):
        """DiscardRareKuten rejects text with too few sentence-ending periods
        and accepts text with sufficient periods."""
        filt_strict = DiscardRareKuten(max_average_sentence_length=5)
        doc_rare = filt_strict.apply(Document("これは長い文章で句点がない"))
        assert doc_rare.is_rejected is True

        filt_lenient = DiscardRareKuten(max_average_sentence_length=10)
        doc_ok = filt_lenient.apply(Document("短い。文。"))
        assert doc_ok.is_rejected is False

    def test_discard_bbs_comments(self):
        """DiscardBBSComments rejects text with many BBS-style patterns
        and accepts normal text."""
        text = "楽天市場 質問 投稿 コメント レビュー " * 4
        filt = DiscardBBSComments(max_allowed_num=5)
        doc_bbs = filt.apply(Document(text))
        assert doc_bbs.is_rejected is True

        filt2 = DiscardBBSComments()
        doc_norm = filt2.apply(Document("これは普通のテキストです"))
        assert doc_norm.is_rejected is False


# ---------------------------------------------------------------------------
# Test 15: Statistics aggregation across parallel workers
# ---------------------------------------------------------------------------
class TestStatisticsModel:
    def test_parallel_stats_merge_by_name_across_workers(self):
        """Process a stream through a multi-filter Compose under Parallel and
        verify that get_total_statistics_map() merges per-worker statistics by
        matching filter names: the aggregated Total and each per-filter entry
        report the summed input/output/discard counts over all documents. This
        is the real user scenario that drives the per-name statistics
        merge/aggregation, observed through the public statistics map, plus the
        documented Statistics.add / add_list_of_stats / get_filter contracts
        (including their error cases) that the reduction is specified to use."""
        from hojichar.core.models import Statistics

        cleaner = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        # 5 docs: "hello world" / "another doc" accepted; "hi" / "ab" / "x" rejected.
        texts = ["hello world", "hi", "another doc", "ab", "x"]
        docs = [Document(t) for t in texts]

        with Parallel(cleaner, num_jobs=2) as pfilter:
            list(pfilter.imap_apply(iter(docs)))
            stats_map = pfilter.get_total_statistics_map()

        by_name = {entry["name"]: entry for entry in stats_map}

        total = by_name["Total"]
        assert total["input_num"] == 5
        assert total["discard_num"] == 3
        assert total["output_num"] == 2

        # Per-filter entries are merged by name across all workers.
        normalizer = by_name["0-DocumentNormalizer"]
        assert normalizer["input_num"] == 5
        assert normalizer["discard_num"] == 0
        assert normalizer["output_num"] == 5

        length = by_name["1-DocumentLengthFilter"]
        assert length["input_num"] == 5
        assert length["discard_num"] == 3
        assert length["output_num"] == 2

        # The same merge-by-name contract at the documented public API level:
        # add() sums two same-named entries and rejects a name mismatch,
        # add_list_of_stats() merges two lists by matching name and rejects
        # mismatched name sets, and get_filter() looks an entry up by name.
        merged = Statistics.add(
            Statistics(name="0-Foo", input_num=5, output_num=4, discard_num=1),
            Statistics(name="0-Foo", input_num=3, output_num=3, discard_num=0),
        )
        assert merged.name == "0-Foo"
        assert merged.input_num == 8
        assert merged.output_num == 7
        assert merged.discard_num == 1

        with pytest.raises(AssertionError):
            Statistics.add(Statistics(name="0-Foo"), Statistics(name="1-Bar"))

        # Merged by NAME, not by position: the second list is deliberately
        # ordered differently from the first, so a positional merge would give
        # a=4 / b=6 instead of 5 / 5.
        by_name_merged = Statistics.add_list_of_stats(
            [Statistics(name="a", input_num=1), Statistics(name="b", input_num=2)],
            [Statistics(name="b", input_num=3), Statistics(name="a", input_num=4)],
        )
        assert len(by_name_merged) == 2
        assert {(s.name, s.input_num) for s in by_name_merged} == {("a", 5), ("b", 5)}

        with pytest.raises(ValueError):
            Statistics.add_list_of_stats(
                [Statistics(name="a")], [Statistics(name="b")]
            )

        stats = [Statistics(name="a"), Statistics(name="b")]
        assert Statistics.get_filter("b", stats).name == "b"
        with pytest.raises(KeyError):
            Statistics.get_filter("missing", stats)


# ---------------------------------------------------------------------------
# Test 16: Filter __call__ and context manager
# ---------------------------------------------------------------------------
class TestFilterInterface:
    def test_filter_call_forwards_kwargs_to_document(self):
        """Calling a Filter directly with a string returns the processed string,
        and extra keyword arguments are forwarded into the constructed Document
        so apply() can read them (e.g. via document.extras)."""

        class SuffixFromExtras(Filter):
            def apply(self, document):
                document.text = document.text + document.extras.get("suffix", "")
                return document

        filt = SuffixFromExtras()
        # **kwargs passed to __call__ reach the Document constructor, so the
        # suffix carried in extras is visible to apply().
        assert filt("hello", extras={"suffix": "!!!"}) == "hello!!!"
        # With no extras kwarg, the default empty extras leaves the text unchanged.
        assert filt("hello") == "hello"

    def test_filter_context_manager(self):
        """Using a Filter as a context manager invokes shutdown() on exit."""

        class TrackShutdown(Filter):
            def __init__(self):
                super().__init__()
                self.was_shutdown = False

            def apply(self, document):
                return document

            def shutdown(self):
                self.was_shutdown = True

        filt = TrackShutdown()
        assert filt.was_shutdown is False
        with filt:
            pass
        # __exit__ must cascade to shutdown().
        assert filt.was_shutdown is True

    def test_filter_get_jsonable_vars(self):
        """get_jsonable_vars returns only public primitive member variables: it
        keeps public primitives (with their exact values) and drops both
        underscore-prefixed names and non-primitive values."""

        class JsonableVarsFilter(Filter):
            def __init__(self):
                super().__init__()
                self.public_int = 5
                self._private_int = 99
                self.obj_attr = [1, 2, 3]

            def apply(self, document):
                return document

        vars_dict = JsonableVarsFilter().get_jsonable_vars()
        # Public primitive kept with its exact value.
        assert vars_dict["public_int"] == 5
        # Underscore-prefixed name excluded.
        assert "_private_int" not in vars_dict
        # Non-primitive value excluded (list), as is the built-in non-primitive `logger`.
        assert "obj_attr" not in vars_dict
        assert "logger" not in vars_dict
        # The inherited public primitives are still surfaced.
        assert vars_dict["p"] == 1.0
        assert vars_dict["skip_rejected"] is True


# ---------------------------------------------------------------------------
# Test 19: Compose statistics byte/char tracking accuracy
# ---------------------------------------------------------------------------
class TestComposeStatisticsAccuracy:
    def test_byte_and_char_diffs_and_accumulation(self):
        """Compose tracks byte/char differences for each filter accurately
        and statistics accumulate correctly across multiple documents."""
        pipeline = Compose([ExampleHojiChar()])
        pipeline("test")

        stats = pipeline.get_total_statistics_map()
        total = stats[0]
        assert total["diff_chars"] == len("<hojichar>")
        assert total["diff_bytes"] == len("<hojichar>".encode("utf-8"))

        # Process more documents and check accumulation
        pipeline2 = Compose([Identity()])
        for i in range(5):
            pipeline2(f"doc{i}")

        total2 = pipeline2.get_total_statistics_map()[0]
        assert total2["input_num"] == 5
        assert total2["output_num"] == 5
        assert total2["discard_num"] == 0


# ---------------------------------------------------------------------------
# Test 20: AsyncCompose pipeline (merged: TestAsyncCompose + TestAsyncBatchAndShutdown)
# ---------------------------------------------------------------------------
class TestAsyncCompose:
    def test_async_compose_with_sync_filters(self):
        """AsyncCompose wraps sync filters (JSONLoader, JSONDumper) and processes
        a document through the async pipeline. Verifies the complete async
        round-trip produces correct output."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        pipeline = AsyncCompose(
            [
                JSONLoader(key="text"),
                DocumentNormalizer(),
                JSONDumper(),
            ]
        )

        async def run():
            doc = Document('{"text": "ﾃｽﾄ文章"}')
            result = await pipeline.apply(doc)
            return result

        result = asyncio.run(run())
        data = json.loads(result.text)
        assert data["text"] == "テスト文章"

    def test_async_compose_with_native_async_filter(self):
        """AsyncCompose works with a custom AsyncFilter that performs async
        text transformation alongside sync filters."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose
        from hojichar.core.async_filter_interface import AsyncFilter as AsyncFilterBase

        class AsyncUppercase(AsyncFilterBase):
            async def apply(self, document):
                document.text = document.text.upper()
                return document

        pipeline = AsyncCompose(
            [
                JSONLoader(key="text"),
                AsyncUppercase(),
                JSONDumper(),
            ]
        )

        async def run():
            doc = Document('{"text": "hello world"}')
            result = await pipeline.apply(doc)
            return result

        result = asyncio.run(run())
        data = json.loads(result.text)
        assert data["text"] == "HELLO WORLD"

    def test_async_compose_apply_stream(self):
        """AsyncCompose.apply_stream processes a stream of documents and
        yields results one by one with correct statistics."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        pipeline = AsyncCompose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3),
            ]
        )

        async def run():
            docs = [Document(t) for t in ["ﾃｽﾄ", "ab", "ﾃﾞｰﾀ"]]
            results = []
            async for doc in pipeline.apply_stream(docs):
                results.append(doc)
            return results

        results = asyncio.run(run())
        assert len(results) == 3
        accepted = [d for d in results if not d.is_rejected]
        assert len(accepted) == 2
        assert accepted[0].text == "テスト"
        assert accepted[1].text == "データ"

    def test_async_compose_statistics(self):
        """AsyncCompose tracks statistics (get_total_statistics_map) correctly
        after processing multiple documents."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        pipeline = AsyncCompose(
            [
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        async def run():
            doc1 = Document("hello world")
            doc2 = Document("hi")
            await pipeline.apply(doc1)
            await pipeline.apply(doc2)

        asyncio.run(run())
        stats = pipeline.get_total_statistics_map()
        total = stats[0]
        assert total["name"] == "Total"
        assert total["input_num"] == 2
        assert total["discard_num"] == 1
        assert total["output_num"] == 1

    def test_async_compose_flattens_inner_compose(self):
        """AsyncCompose flattens an inner Compose, numbering sub-filters
        sequentially."""
        from hojichar.core.async_composition import AsyncCompose

        inner = Compose([Identity(), ExampleHojiChar()])
        outer = AsyncCompose([JSONLoader(), inner, JSONDumper()])

        # get_total_statistics_map() returns [Total, filter0, filter1, ...];
        # the sub-filter entries (index 1 onward) reflect the flattened list.
        sub_filters = outer.get_total_statistics_map()[1:]
        assert len(sub_filters) == 4
        names = [f["name"] for f in sub_filters]
        assert "0-JSONLoader" in names
        assert "1-Identity" in names
        assert "2-ExampleHojiChar" in names
        assert "3-JSONDumper" in names

    def test_async_compose_context_manager(self):
        """AsyncCompose works as an async context manager, calling shutdown
        on exit."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        async def run():
            async with AsyncCompose([Identity()]) as pipeline:
                doc = Document("test")
                result = await pipeline.apply(doc)
                assert result.text == "test"

        asyncio.run(run())

    def test_async_compose_apply_batch(self):
        """AsyncCompose.apply_batch processes a list of documents and
        returns results with correct accept/reject status."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        pipeline = AsyncCompose(
            [
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        async def run():
            batch = [
                Document("hello world"),
                Document("hi"),
                Document("testing123"),
            ]
            return await pipeline.apply_batch(batch)

        results = asyncio.run(run())
        assert len(results) == 3
        assert results[0].is_rejected is False
        assert results[1].is_rejected is True
        assert results[2].is_rejected is False

    def test_async_compose_shutdown_cascades(self):
        """AsyncCompose.shutdown() cascades to all sub-filters, cleaning
        up resources properly."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose
        from hojichar.core.async_filter_interface import AsyncFilter as AsyncFilterBase

        class TrackAsyncShutdown(AsyncFilterBase):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.was_shutdown = False

            async def apply(self, document):
                return document

            async def shutdown(self):
                self.was_shutdown = True

        f1 = TrackAsyncShutdown()
        pipeline = AsyncCompose([f1])

        # A native AsyncFilter is stored directly (no sync->async adapter wrapping),
        # so f1 is the same object held in the pipeline.
        async def run():
            await pipeline.apply(Document("test"))
            await pipeline.shutdown()

        assert f1.was_shutdown is False
        asyncio.run(run())
        # shutdown() must cascade to every sub-filter.
        assert f1.was_shutdown is True

    def test_async_compose_batch_statistics_accumulate_across_calls(self):
        """AsyncCompose statistics accumulate across repeated apply_batch calls,
        and the per-filter sub-entry mirrors the Total."""
        import asyncio

        from hojichar.core.async_composition import AsyncCompose

        pipeline = AsyncCompose(
            [
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        async def run():
            # First batch: 2 accepted, 1 rejected.
            await pipeline.apply_batch(
                [Document("hello world"), Document("hi"), Document("another long text")]
            )
            # Second batch: 1 accepted, 1 rejected -- totals must accumulate, not reset.
            await pipeline.apply_batch([Document("longenough"), Document("no")])

        asyncio.run(run())
        stats = pipeline.get_total_statistics_map()

        total = stats[0]
        assert total["name"] == "Total"
        assert total["input_num"] == 5
        assert total["discard_num"] == 2
        assert total["output_num"] == 3

        # The single DocumentLengthFilter sub-entry tracks the same cumulative counts.
        length = stats[1]
        assert length["name"] == "0-DocumentLengthFilter"
        assert length["input_num"] == 5
        assert length["discard_num"] == 2
        assert length["output_num"] == 3


# ---------------------------------------------------------------------------
# Test 22: Error handling and batch stream processing
# (merged: TestFilterErrorHandling + TestFilterBatchStream -> TestFilterStreamBehavior)
# ---------------------------------------------------------------------------
class TestFilterStreamBehavior:
    def test_stream_error_rejects_bad_doc_continues_others(self):
        """When a filter raises an exception for a specific document during
        stream processing, that document is rejected with an error reason,
        while other documents pass through normally."""

        class BombFilter(Filter):
            """Raises for any doc containing 'BOMB'."""

            def apply(self, document):
                if "BOMB" in document.text:
                    raise ValueError("Boom!")
                document.text = document.text.upper()
                return document

        pipeline = Compose([BombFilter()])
        docs = (Document(t) for t in ["hello", "BOMB", "world"])
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 3
        assert results[0].text == "HELLO"
        assert results[0].is_rejected is False

        # The BOMB doc should be rejected with an error
        assert results[1].is_rejected is True
        assert "error" in results[1].reject_reason

        assert results[2].text == "WORLD"
        assert results[2].is_rejected is False

        # Error should be tracked in the filter's statistics.
        # get_total_statistics() returns [Total, filter0, ...]; index 1 is filter0.
        bomb_stat = pipeline.get_total_statistics()[1]
        assert bomb_stat.errors == 1

    def test_stream_error_with_batch_processing(self):
        """When a filter using batch processing raises during apply_batch,
        all documents in the batch are rejected, but the pipeline continues."""

        class BatchBombFilter(Filter):
            """Raises on any batch containing a doc with 'BOMB'."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, use_batch=True, batch_size=3, **kwargs)

            def apply(self, document):
                return document

            def apply_batch(self, batch):
                for doc in batch:
                    if "BOMB" in doc.text:
                        raise ValueError("Batch boom!")
                return [doc for doc in batch]

        pipeline = Compose([BatchBombFilter()])
        # 3 docs fit in one batch (batch_size=3); all will be rejected because of BOMB
        docs = (Document(t) for t in ["good", "BOMB", "fine"])
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 3
        # All docs in the batch containing BOMB should be rejected
        for r in results:
            assert r.is_rejected is True

        # Errors are tracked in the filter's statistics.
        # get_total_statistics() returns [Total, filter0, ...]; index 1 is filter0.
        bomb_stat = pipeline.get_total_statistics()[1]
        assert bomb_stat.errors == 3

    def test_use_batch_stream_processes_in_batches(self):
        """A filter with use_batch=True processes documents through
        apply_batch in apply_stream, not individual apply calls."""

        class BatchCounter(Filter):
            """Counts how many times apply_batch is called vs apply."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, use_batch=True, batch_size=3, **kwargs)
                self.batch_call_count = 0
                self.single_call_count = 0

            def apply(self, document):
                self.single_call_count += 1
                document.text = document.text.upper()
                return document

            def apply_batch(self, batch):
                self.batch_call_count += 1
                return [self.apply(doc) for doc in batch]

        filt = BatchCounter()
        pipeline = Compose([filt])

        # 7 docs with batch_size=3: expect 2 full batches + 1 partial batch = 3 calls
        docs = (Document(f"doc{i}") for i in range(7))
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 7
        assert all(r.text.startswith("DOC") for r in results)
        # batch_call_count should be >= 2 (batches of 3 + remainder)
        assert filt.batch_call_count >= 2
        # All 7 docs should have been processed
        assert filt.single_call_count == 7

    def test_use_batch_false_processes_individually(self):
        """A filter with use_batch=False processes each document individually
        through _apply in apply_stream."""

        class IndividualTracker(Filter):
            """Tracks individual apply calls."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, use_batch=False, **kwargs)
                self.call_count = 0

            def apply(self, document):
                self.call_count += 1
                return document

        filt = IndividualTracker()
        pipeline = Compose([filt])

        docs = (Document(f"doc{i}") for i in range(5))
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 5
        assert filt.call_count == 5


# ---------------------------------------------------------------------------
# Test 26: DiscardAds filter
# ---------------------------------------------------------------------------
class TestDiscardAds:
    def test_discard_ads(self, tmp_path):
        """DiscardAds loads keywords from a dict file, counts regex matches,
        and rejects documents exceeding max_allowed_num."""
        from hojichar.filters.document_filters import DiscardAds

        dict_file = tmp_path / "ad_words.txt"
        dict_file.write_text("spam\nadvert\nclick here")

        filt = DiscardAds(dict_path=str(dict_file), max_allowed_num=3)
        ad_text = "spam advert click here spam advert click here"
        doc_ad = filt.apply(Document(ad_text))
        assert doc_ad.is_rejected is True

        doc_norm = filt.apply(Document("normal text without any keywords"))
        assert doc_norm.is_rejected is False


# ---------------------------------------------------------------------------
# Test 29: Compose apply_stream statistics tracking
# ---------------------------------------------------------------------------
class TestComposeStreamStats:
    def test_apply_stream_empty_stream_zero_stats(self):
        """Compose.apply_stream over an empty stream yields nothing and leaves
        the Total statistics at zero (no spurious input/output/discard counts)."""
        pipeline = Compose(
            [
                DocumentLengthFilter(min_doc_len=5),
            ]
        )

        docs = (Document(t) for t in [])
        results = list(pipeline.apply_stream(docs))

        assert results == []
        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == 0
        assert total["discard_num"] == 0
        assert total["output_num"] == 0


# ---------------------------------------------------------------------------
# Test 37: Compose with random_state produces deterministic p<1 results
# ---------------------------------------------------------------------------
class TestComposeRandomState:
    def test_random_state_deterministic_with_p(self):
        """When Compose is constructed with a fixed random_state, filters
        with p<1 produce deterministic results across repeated runs."""
        results_run1 = []
        results_run2 = []

        for results_list in [results_run1, results_run2]:
            pipeline = Compose(
                [ExampleHojiChar(p=0.5)],
                random_state=42,
            )
            for i in range(20):
                results_list.append(pipeline(f"doc{i}"))

        # Both runs with the same seed should produce identical results
        assert results_run1 == results_run2

    def test_random_state_propagates_to_subfilters(self):
        """The Compose-level random_state drives the per-document p<1 decisions of a
        sub-filter that has no random_state of its own, and a sub-filter that DOES carry
        its own random_state is left untouched.

        This is distinct from `test_random_state_deterministic_with_p` (which only proves
        same-seed reproducibility): here we prove the Compose seed actually flows into the
        seedless sub-filter by checking that two *different* Compose seeds yield two
        *different* applied-patterns -- an implementation that drew from the sub-filter's
        own (un-propagated) RNG would produce the same pattern regardless of the Compose
        seed."""

        def applied_pattern(compose_seed, filter_seed=None):
            # Per-document observable outcome: whether ExampleHojiChar appended "<hojichar>".
            pipeline = Compose(
                [ExampleHojiChar(p=0.5, random_state=filter_seed)],
                random_state=compose_seed,
            )
            return [pipeline(f"text{i}").endswith("<hojichar>") for i in range(30)]

        # A seedless sub-filter receives the Compose RNG: the pattern is deterministic per
        # seed and a real mix at p=0.5.
        pattern_123 = applied_pattern(123)
        assert pattern_123 == applied_pattern(123)
        assert any(pattern_123) and not all(pattern_123)

        # The Compose seed -- not some private sub-filter RNG -- determines the outcome, so
        # a different Compose seed produces a different pattern.
        assert applied_pattern(456) != pattern_123

        # A sub-filter with its OWN random_state is not overridden by the Compose seed:
        # the same filter seed gives the same pattern under different Compose seeds.
        assert applied_pattern(123, filter_seed=999) == applied_pattern(456, filter_seed=999)


# ---------------------------------------------------------------------------
# Test 42: Filter._apply_batch with p<1 probability skip
# ---------------------------------------------------------------------------
class TestFilterApplyBatchProbability:
    def test_apply_batch_with_p_boundary_values(self):
        """When a filter has p=0, batch processing skips it entirely;
        when p=1, all documents are processed."""
        pipeline_p0 = Compose([ExampleHojiChar(p=0.0, random_state=42)])
        batch0 = [Document("text1"), Document("text2"), Document("text3")]
        results0 = pipeline_p0.apply_batch(batch0)
        for r in results0:
            assert "<hojichar>" not in r.text

        pipeline_p1 = Compose([ExampleHojiChar(p=1.0)])
        batch1 = [Document("text1"), Document("text2")]
        results1 = pipeline_p1.apply_batch(batch1)
        for r in results1:
            assert r.text.endswith("<hojichar>")


# ---------------------------------------------------------------------------
# Test 43: Multi-document statistics accumulation across a Compose pipeline
# ---------------------------------------------------------------------------
class TestComposeMultiDocStatisticsAccumulation:
    def test_per_filter_stats_accumulate_across_many_docs(self):
        """Process many documents through a multi-filter Compose pipeline
        with some rejections, and verify that per-filter statistics
        (input_num, output_num, discard_num, diff_bytes, diff_chars)
        accumulate correctly across all documents."""
        pipeline = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=3, max_doc_len=50),
                ExampleHojiChar(),
            ]
        )

        inputs = [
            "ﾃｽﾄ",  # accepted: normalizes to テスト (3 chars), + <hojichar>
            "ab",  # rejected by length filter (2 < 3)
            "ﾃﾞｰﾀ",  # accepted: normalizes to データ (3 chars), + <hojichar>
            "hi",  # rejected by length filter (2 < 3)
            "hello world",  # accepted: no normalization change, + <hojichar>
            "x",  # rejected by length filter (1 < 3)
        ]

        for text in inputs:
            pipeline(text)

        stats_map = pipeline.get_total_statistics_map()
        total = stats_map[0]

        # Total pipeline: 6 inputs, 3 rejected, 3 output
        assert total["input_num"] == 6
        assert total["discard_num"] == 3
        assert total["output_num"] == 3

        # Per-filter stats
        normalizer_stat = stats_map[1]
        assert normalizer_stat["name"] == "0-DocumentNormalizer"
        assert normalizer_stat["input_num"] == 6
        # Normalizer doesn't reject anything
        assert normalizer_stat["discard_num"] == 0
        assert normalizer_stat["output_num"] == 6

        length_stat = stats_map[2]
        assert length_stat["name"] == "1-DocumentLengthFilter"
        assert length_stat["input_num"] == 6
        assert length_stat["discard_num"] == 3
        assert length_stat["output_num"] == 3

        hojichar_stat = stats_map[3]
        assert hojichar_stat["name"] == "2-ExampleHojiChar"
        assert hojichar_stat["input_num"] == 6
        assert hojichar_stat["discard_num"] == 0
        assert hojichar_stat["output_num"] == 6
        assert hojichar_stat["diff_chars"] == 10 * 3
        assert hojichar_stat["diff_bytes"] == 10 * 3


# ---------------------------------------------------------------------------
# Test 45: Compose stream with batch filters
# ---------------------------------------------------------------------------
class TestComposeStreamWithBatchFilters:
    def test_batch_filter_in_stream_produces_correct_results(self):
        """Build a Compose with a filter that has use_batch=True and
        a custom apply_batch. Process a stream and verify that batch
        processing is used AND statistics are accurate."""

        class BatchUppercase(Filter):
            """Uppercases text in batches."""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, use_batch=True, batch_size=3, **kwargs)
                self.batch_calls = 0

            def apply(self, document):
                document.text = document.text.upper()
                return document

            def apply_batch(self, batch):
                self.batch_calls += 1
                return [self.apply(doc) for doc in batch]

        filt = BatchUppercase()
        pipeline = Compose([filt])

        # Process 8 docs in stream: 3 + 3 + 2 = 3 batch calls
        docs = (Document(f"text{i}") for i in range(8))
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 8
        for i, r in enumerate(results):
            assert r.text == f"TEXT{i}"

        # Verify batch_calls: 3 batches (3 + 3 + 2)
        assert filt.batch_calls == 3

        # Verify statistics
        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == 8
        assert total["output_num"] == 8
        assert total["discard_num"] == 0

    def test_batch_filter_with_rejections_in_stream(self):
        """A batch filter that rejects some documents in a stream
        correctly tracks statistics including discards."""

        class BatchLengthFilter(Filter):
            """Rejects short docs in batch mode."""

            def __init__(self, min_len, *args, **kwargs):
                super().__init__(*args, use_batch=True, batch_size=4, **kwargs)
                self.min_len = min_len

            def apply(self, document):
                if len(document.text) < self.min_len:
                    document.is_rejected = True
                return document

            def apply_batch(self, batch):
                return [self.apply(doc) for doc in batch]

        filt = BatchLengthFilter(min_len=5)
        pipeline = Compose([filt])

        texts = ["hello world", "hi", "testing", "ab", "ok", "longer text"]
        docs = (Document(t) for t in texts)
        results = list(pipeline.apply_stream(docs))

        assert len(results) == 6
        accepted = [r for r in results if not r.is_rejected]
        rejected = [r for r in results if r.is_rejected]
        assert len(accepted) == 3  # "hello world", "testing", "longer text"
        assert len(rejected) == 3  # "hi", "ab", "ok"

        # Verify per-filter statistics
        filt_stats = filt.get_statistics()
        assert filt_stats.input_num == 6
        assert filt_stats.discard_num == 3
        assert filt_stats.output_num == 3


# ---------------------------------------------------------------------------
# Test 46: JSONLoader extra_keys edge cases (bundled: 5 -> 2)
# ---------------------------------------------------------------------------
class TestJsonLoaderExtraKeysMerging:
    def test_extra_keys_merging(self):
        """When extra_keys contains 'extras' key itself, it should merge
        that dict into document.extras without overwriting existing entries.
        When input has an embedded 'extras' dict AND extra_keys references
        additional fields, all are merged into document.extras."""
        # extras key merges as dict
        loader = JSONLoader(extra_keys=["extras"])
        inp = json.dumps(
            {
                "text": "hello",
                "extras": {"source": "web", "quality": "high"},
            }
        )
        doc = loader.apply(Document(inp))
        assert doc.text == "hello"
        assert doc.extras["source"] == "web"
        assert doc.extras["quality"] == "high"

        # multiple extra_keys combined with embedded extras
        loader2 = JSONLoader(extra_keys=["url", "score"])
        inp2 = json.dumps(
            {
                "text": "content",
                "extras": {"lang": "ja"},
                "url": "https://test.com",
                "score": 0.95,
            }
        )
        doc2 = loader2.apply(Document(inp2))
        assert doc2.text == "content"
        assert doc2.extras["lang"] == "ja"
        assert doc2.extras["url"] == "https://test.com"
        assert doc2.extras["score"] == 0.95

    def test_extra_keys_edge_cases(self):
        """When extra_keys references fields that don't exist in the
        input JSON, those fields are silently skipped. When 'extras'
        in extra_keys points to a non-dict value, it is stored directly.
        When extra_keys is an empty list, no extra keys are merged."""
        # missing fields skipped
        loader = JSONLoader(extra_keys=["url", "author", "nonexistent"])
        inp = json.dumps(
            {
                "text": "hello",
                "url": "https://example.com",
            }
        )
        doc = loader.apply(Document(inp))
        assert doc.text == "hello"
        assert doc.extras["url"] == "https://example.com"
        assert "author" not in doc.extras
        assert "nonexistent" not in doc.extras

        # non-dict extras stored as value
        loader2 = JSONLoader(extra_keys=["extras"])
        inp2 = json.dumps(
            {
                "text": "hello",
                "extras": "just_a_string",
            }
        )
        doc2 = loader2.apply(Document(inp2))
        assert doc2.text == "hello"
        assert doc2.extras["extras"] == "just_a_string"

        # empty list
        loader3 = JSONLoader(extra_keys=[])
        inp3 = json.dumps(
            {
                "text": "hello",
                "url": "https://example.com",
            }
        )
        doc3 = loader3.apply(Document(inp3))
        assert doc3.text == "hello"
        assert "url" not in doc3.extras


# ---------------------------------------------------------------------------
# Test 48: CharRepetitionRatio exact values for known inputs
# ---------------------------------------------------------------------------
class TestCharRepetitionExactValues:
    def test_char_repetition_ratio_threshold_boundary(self):
        """Exercise CharRepetitionRatioFilter's ratio computation through its
        public accept/reject surface, with thresholds placed so the known
        repetition ratio of each input straddles the boundary -- a wrong ratio
        computation flips the resulting doc.is_rejected.

        The filter rejects when ratio >= threshold. Known ratios:
        'abcabc' (ngram_size=2) -> 0.4, 'a'*10 (ngram_size=3) -> 1.0 (fully
        repetitive), 'abcdefghij' (ngram_size=3) -> 0.0 (all-unique), and any
        text shorter than ngram_size -> 0.0. The documented public static
        method must return those exact ratios as well.
        """
        # Ratio 0.4 straddled from both sides: threshold just above keeps it,
        # just below rejects it. Only a ratio in (0.3, 0.5] passes both.
        assert (
            CharRepetitionRatioFilter(threshold=0.5, ngram_size=2)
            .apply(Document("abcabc"))
            .is_rejected
            is False
        )
        assert (
            CharRepetitionRatioFilter(threshold=0.3, ngram_size=2)
            .apply(Document("abcabc"))
            .is_rejected
            is True
        )

        # Perfectly repetitive text (ratio 1.0) is rejected even at a threshold
        # just below 1.0.
        assert (
            CharRepetitionRatioFilter(threshold=0.99, ngram_size=3)
            .apply(Document("a" * 10))
            .is_rejected
            is True
        )

        # All-unique ngrams (ratio 0.0) are accepted even at a threshold just
        # above 0.0.
        assert (
            CharRepetitionRatioFilter(threshold=0.01, ngram_size=3)
            .apply(Document("abcdefghij"))
            .is_rejected
            is False
        )

        # Text shorter than ngram_size has ratio 0.0, so it is accepted even at
        # the lowest meaningful threshold.
        assert (
            CharRepetitionRatioFilter(threshold=0.01, ngram_size=5)
            .apply(Document("ab"))
            .is_rejected
            is False
        )

        # The same ratios read directly off the documented public static
        # method, which pins the value rather than just the side of the
        # threshold (and covers the short/empty-text branch).
        ratio_of = CharRepetitionRatioFilter.compute_character_repetition_ratio
        assert ratio_of("abcabc", 2) == pytest.approx(0.4)
        assert ratio_of("a" * 10, 3) == pytest.approx(1.0)
        assert ratio_of("abcdefghij", 3) == pytest.approx(0.0)
        assert ratio_of("ab", 5) == pytest.approx(0.0)
        assert ratio_of("", 5) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 50: Compose apply_stream with large dataset
# ---------------------------------------------------------------------------
class TestComposeApplyStreamLargeDataset:
    def test_large_stream_correct_stats(self):
        """Process 1000+ documents through apply_stream with a multi-filter
        pipeline and verify statistics are correct (no off-by-one, no
        missing documents)."""
        pipeline = Compose(
            [
                DocumentNormalizer(),
                DocumentLengthFilter(min_doc_len=5, max_doc_len=100),
                ExampleHojiChar(),
            ]
        )

        n_total = 1000
        n_short = 0
        texts = []
        for i in range(n_total):
            if i % 7 == 0:
                texts.append(f"s{i}")  # short, will be rejected
                n_short += 1
            else:
                texts.append(f"document_number_{i}")  # long enough

        docs = (Document(t) for t in texts)
        results = list(pipeline.apply_stream(docs))

        assert len(results) == n_total

        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == n_total
        assert total["discard_num"] == n_short
        assert total["output_num"] == n_total - n_short

        # Verify each result has correct rejection status
        accepted_count = sum(1 for r in results if not r.is_rejected)
        rejected_count = sum(1 for r in results if r.is_rejected)
        assert accepted_count == n_total - n_short
        assert rejected_count == n_short


# ---------------------------------------------------------------------------
# Test 52: Deduplication - GenerateDedupLSH (merged: TestDedupGenerateLSH +
#   TestDedupMinhashSignature + TestDedupSplitters, bundled: 10 -> 4)
# ---------------------------------------------------------------------------
class TestDedupGenerateLSH:
    def test_lsh_key_generation(self):
        """GenerateDedupLSH with default params produces LSH keys in the
        expected format and quantity, built on a MinHash signature of the
        documented shape and dtype. Identical texts produce identical
        signatures and keys. Very different texts produce at least some
        different keys."""
        import re as re_mod

        import numpy as np

        from hojichar.filters.deduplication import GenerateDedupLSH

        filt = GenerateDedupLSH()

        # basic lsh keys
        doc = filt.apply(Document("Hello world, this is a test document for dedup"))
        lsh_keys = doc.extras["dedup_lsh"]

        assert isinstance(lsh_keys, list)
        assert all(isinstance(k, str) for k in lsh_keys)
        assert len(lsh_keys) == filt.num_bands

        pattern = re_mod.compile(r"^\d+\+[0-9a-f]{32}$")
        for key in lsh_keys:
            assert pattern.match(key), f"Key '{key}' does not match expected format"

        # identical texts produce identical keys
        doc1 = filt.apply(Document("Identical text for testing dedup"))
        doc2 = filt.apply(Document("Identical text for testing dedup"))
        assert doc1.extras["dedup_lsh"] == doc2.extras["dedup_lsh"]

        # different texts produce different keys
        doc3 = filt.apply(Document("The quick brown fox jumps over the lazy dog"))
        doc4 = filt.apply(
            Document("Lorem ipsum dolor sit amet consectetur adipiscing elit")
        )
        keys3 = doc3.extras["dedup_lsh"]
        keys4 = doc4.extras["dedup_lsh"]
        assert keys3 != keys4

        # The keys are built from a public MinHash signature: one uint32 per
        # permutation (num_perm defaults to 500), deterministic for a given
        # text, and reducible to an integer digest per band.
        sig = filt.calculate_minhash_signature("Some text for signature testing")
        assert isinstance(sig, np.ndarray)
        assert sig.dtype == np.uint32
        assert sig.shape == (500,)
        assert np.array_equal(
            sig, filt.calculate_minhash_signature("Some text for signature testing")
        )

        band_size = 500 // filt.num_bands
        digest = filt.signature_to_lsh_digest(sig, band_size, 0)
        assert isinstance(digest, int)

    def test_tokenizer_variants(self):
        """The tokenizer is pluggable end-to-end: char_level_splitter and
        non_alpha_num_splitter tokenize the SAME text differently, so they must
        yield demonstrably different LSH keys (and both differ from the default
        tokenizer's keys for that text)."""
        from hojichar.filters.deduplication import GenerateDedupLSH, char_level_splitter
        from hojichar.filters.deduplication import non_alpha_num_splitter

        text = "Testing pluggable tokenizers for dedup keys"

        default_keys = GenerateDedupLSH().apply(Document(text)).extras["dedup_lsh"]
        char_keys = (
            GenerateDedupLSH(tokenizer=char_level_splitter).apply(Document(text)).extras["dedup_lsh"]
        )
        nonalpha_keys = (
            GenerateDedupLSH(tokenizer=non_alpha_num_splitter)
            .apply(Document(text))
            .extras["dedup_lsh"]
        )

        # Each tokenizer still produces num_bands LSH-key strings.
        for keys in (default_keys, char_keys, nonalpha_keys):
            assert isinstance(keys, list)
            assert all(isinstance(k, str) for k in keys)
            assert len(keys) == GenerateDedupLSH().num_bands

        # The default tokenizer IS char_level_splitter, so it reproduces char_keys exactly,
        # but the word-level non_alpha_num_splitter tokenizes the same text differently and
        # therefore yields a different set of LSH keys.
        assert char_keys == default_keys
        assert nonalpha_keys != char_keys


# ---------------------------------------------------------------------------
# Test 54+57: Deduplication - Deduplicators (merged: TestDedupInlineDeduplicator +
#   TestDedupRedisDeduplicator + TestDedupInlineDuplicateAnalyzer)
# ---------------------------------------------------------------------------
class TestDedupDeduplicators:
    def test_inline_dedup_rejects_duplicate(self):
        """InlineDeduplicator rejects duplicate documents sharing LSH keys."""
        from hojichar.filters.deduplication import GenerateDedupLSH, InlineDeduplicator

        pipeline = Compose([GenerateDedupLSH(), InlineDeduplicator()])

        doc1 = pipeline.apply(Document("Hello world"))
        doc2 = pipeline.apply(Document("Goodbye world"))
        doc3 = pipeline.apply(Document("Hello world"))

        assert doc1.is_rejected is False
        assert doc2.is_rejected is False
        assert doc3.is_rejected is True

    def test_inline_dedup_raises_without_lsh_keys(self):
        """InlineDeduplicator raises ValueError when document has no dedup_lsh."""
        from hojichar.filters.deduplication import InlineDeduplicator

        filt = InlineDeduplicator()
        with pytest.raises(ValueError):
            filt.apply(Document("no lsh keys"))

    @staticmethod
    def _redis_available():
        try:
            import redis as _redis

            r = _redis.Redis(host="localhost", port=6379, db=0)
            r.ping()
            return True
        except Exception:
            return False

    def test_redis_dedup_rejects_duplicate(self):
        """RedisDeduplicator rejects duplicate documents via Redis."""
        if not self._redis_available():
            pytest.skip("Redis server not available on localhost:6379")

        from uuid import uuid4

        from hojichar.filters.deduplication import GenerateDedupLSH, RedisDeduplicator

        prefix = f"test_{uuid4().hex[:8]}"
        pipeline = Compose(
            [
                GenerateDedupLSH(),
                RedisDeduplicator(host="localhost", port=6379, key_prefix=prefix),
            ]
        )

        doc1 = pipeline.apply(Document("Text A"))
        doc2 = pipeline.apply(Document("Text B"))
        doc3 = pipeline.apply(Document("Text A"))

        assert doc1.is_rejected is False
        assert doc2.is_rejected is False
        assert doc3.is_rejected is True

    def test_redis_dedup_raises_without_lsh_keys(self):
        """RedisDeduplicator raises ValueError when document has no dedup_lsh."""
        if not self._redis_available():
            pytest.skip("Redis server not available on localhost:6379")

        from uuid import uuid4

        from hojichar.filters.deduplication import RedisDeduplicator

        prefix = f"test_{uuid4().hex[:8]}"
        filt = RedisDeduplicator(host="localhost", port=6379, key_prefix=prefix)
        with pytest.raises(ValueError):
            filt.apply(Document("no lsh keys"))

    def test_analyzer_marks_similar_doc(self):
        """InlineDuplicateAnalyzer rejects duplicates and stores the
        similar_doc text in extras."""
        from hojichar.filters.deduplication import (
            GenerateDedupLSH,
            InlineDuplicateAnalyzer,
        )

        pipeline = Compose([GenerateDedupLSH(), InlineDuplicateAnalyzer()])

        doc1 = pipeline.apply(Document("Original text here"))
        doc2 = pipeline.apply(Document("Different text entirely"))
        doc3 = pipeline.apply(Document("Original text here"))

        assert doc1.is_rejected is False
        assert doc2.is_rejected is False
        assert doc3.is_rejected is True
        assert doc3.extras["similar_doc"] == "Original text here"


# ---------------------------------------------------------------------------
# Test 60: Deduplication - Compose end-to-end pipeline
# ---------------------------------------------------------------------------
class TestDedupComposePipeline:
    def test_realistic_dedup_pipeline(self):
        """End-to-end dedup workflow: JSONLoader -> GenerateDedupLSH ->
        InlineDeduplicator -> JSONDumper. Duplicates are rejected (return '')
        and statistics track discards."""
        from hojichar.filters.deduplication import GenerateDedupLSH, InlineDeduplicator

        pipeline = Compose(
            [
                JSONLoader(key="text"),
                GenerateDedupLSH(),
                InlineDeduplicator(),
                JSONDumper(),
            ]
        )

        inputs = [
            json.dumps({"text": "First unique document content"}),
            json.dumps({"text": "Second unique document content"}),
            json.dumps({"text": "First unique document content"}),  # duplicate
            json.dumps({"text": "A completely different sentence about weather patterns"}),
            json.dumps({"text": "Second unique document content"}),  # duplicate
        ]

        results = [pipeline(line) for line in inputs]

        assert results[0] != ""
        assert results[1] != ""
        assert results[2] == ""  # duplicate rejected
        assert results[3] != ""
        assert results[4] == ""  # duplicate rejected

        total = pipeline.get_total_statistics_map()[0]
        assert total["input_num"] == 5
        assert total["discard_num"] == 2
        assert total["output_num"] == 3


# ---------------------------------------------------------------------------
# SEOTokenRemover: decorative pattern removal with word-length gate
# ---------------------------------------------------------------------------
class TestSEOTokenRemover:
    def test_seo_token_remover(self):
        """SEOTokenRemover removes SEO-like decorative patterns when average
        word length exceeds threshold, and leaves normal text unchanged."""
        from hojichar.core.models import Token
        from hojichar.filters.token_filters import SEOTokenRemover

        filt = SEOTokenRemover(min_average_seo_char_length=1)
        token = Token("本文テキスト★━━━━━★ここから")
        result = filt.apply(token)
        # The star-bar run is excised and the surrounding text is kept verbatim.
        assert result.text == "本文テキストここから"

        filt2 = SEOTokenRemover()
        assert filt2("hello world") == "hello world"


# ---------------------------------------------------------------------------
# HeaderFooterTagsRemover: positional token inspection with keyword matching
# ---------------------------------------------------------------------------
class TestHeaderFooterTagsRemover:
    def test_header_footer_tags_remover(self):
        """In a realistic tokenize -> remove -> merge pipeline,
        HeaderFooterTagsRemover drops header/footer-like sentences (matched by
        keyword) so the merged document text no longer contains them, while
        body sentences are preserved. Text with no header/footer tags passes
        through unchanged."""
        from hojichar.filters.document_filters import HeaderFooterTagsRemover

        pipeline = Compose(
            [
                SentenceTokenizer(),
                HeaderFooterTagsRemover(),
                MergeTokens(),
            ]
        )

        # "トップページ" is a built-in header keyword; the leading sentence that
        # starts with it is dropped, leaving the body sentence in the output.
        result = pipeline("トップページ。これは本文です。")
        assert result == "これは本文です。"

        # Text without any header/footer keyword is returned unchanged.
        clean = pipeline("これは本文です。もう一行あります。")
        assert clean == "これは本文です。もう一行あります。"
