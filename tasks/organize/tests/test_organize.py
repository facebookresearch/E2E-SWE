"""WRG test suite for organize — file management automation tool.

Tests the core pipeline: YAML config → rule execution → walker →
filter pipeline → action pipeline, including template rendering,
conflict resolution, filter combination modes, and multi-rule workflows.
"""

import os
import time
from collections import Counter
from pathlib import Path
import pytest

from organize import Config, ConfigError
from organize.output import SavingOutput


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def testoutput():
    return SavingOutput()


def make_files(structure, path="."):
    if isinstance(path, str):
        path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if isinstance(structure, list):
        for name in structure:
            (path / name).touch()
        return
    for name, content in structure.items():
        resource = path / name
        if isinstance(content, dict):
            make_files(structure=content, path=resource)
        elif content is None:
            resource.touch()
        elif isinstance(content, bytes):
            resource.write_bytes(content)
        elif isinstance(content, str):
            resource.write_text(content)
        else:
            raise ValueError(f"Unknown file data {content}")


def read_files(path="."):
    if isinstance(path, str):
        path = Path(path)
    result = dict()
    for x in path.glob("*"):
        if x.is_file():
            result[x.name] = x.read_text()
        if x.is_dir():
            result[x.name] = read_files(x)
    return result


# ---------------------------------------------------------------------------
# Config parsing and validation
# ---------------------------------------------------------------------------


def test_config_yaml_anchors_and_execution(fs, testoutput):
    """User DRYs up config with YAML anchors and runs it to organize files."""
    make_files({"a.txt": "hello", "b.log": "world"}, "/src")
    config = """
    my_locations: &loc
      - /src

    rules:
      - locations: *loc
        filters:
          - extension: txt
        actions:
          - echo: "found {path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["found a.txt"]


def test_config_error_on_invalid_structure(fs):
    """User gets ConfigError when filters are a dict instead of a list."""
    config = """
    rules:
      - locations: /src
        filters:
          extension: jpg
          name: test
        actions:
          - echo: "hello"
    """
    with pytest.raises(ConfigError):
        Config.from_string(config)


# ---------------------------------------------------------------------------
# Walker and location
# ---------------------------------------------------------------------------


def test_recursive_walking_with_subfolders(fs, testoutput):
    """User scans nested directories with subfolders: true."""
    make_files({
        "a.txt": "",
        "sub1": {
            "b.txt": "",
            "sub2": {"c.txt": ""},
        },
    }, "/src")
    config = """
    rules:
      - locations: /src
        subfolders: true
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["a.txt", "b.txt", "c.txt"])


def test_walker_exclude_directories(fs, testoutput):
    """User excludes specific directories from recursive scanning."""
    make_files({
        "root.txt": "",
        "build": {"output.txt": ""},
        "src": {"code.txt": ""},
    }, "/project")
    config = """
    rules:
      - locations:
          - path: /project
            exclude_dirs:
              - build
        subfolders: true
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["root.txt", "code.txt"])


def test_multiple_locations_in_one_rule(fs, testoutput):
    """User scans multiple directories in a single rule."""
    make_files({"a.txt": ""}, "/loc1")
    make_files({"b.txt": ""}, "/loc2")
    config = """
    rules:
      - locations:
          - /loc1
          - /loc2
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["a.txt", "b.txt"])


def test_targets_dirs(fs, testoutput):
    """User operates on directories instead of files with targets: dirs."""
    make_files({
        "file.txt": "",
        "empty_dir": {},
        "full_dir": {"x.txt": ""},
    }, "/src")
    config = """
    rules:
      - locations: /src
        targets: dirs
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["empty_dir", "full_dir"])


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_name_filter_simplematch_groups(fs, testoutput):
    """User captures named groups from filename patterns and uses them in actions."""
    make_files([
        "Invoice_ACME_2024_03_15.pdf",
        "Invoice_GLOBEX_2024_07_22.pdf",
        "README.md",
    ], "/docs")
    config = """
    rules:
      - locations: /docs
        filters:
          - name: "Invoice_{company}_{year}_{month}_{day}"
        actions:
          - echo: "{name.company} {name.year}-{name.month}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter([
        "ACME 2024-03",
        "GLOBEX 2024-07",
    ])


def test_name_filter_criteria_with_case_insensitive(fs, testoutput):
    """User filters by startswith + contains with case-insensitive matching (AND logic)."""
    make_files([
        "report_2024_final.txt",
        "report_2023_draft.txt",
        "REPORT_2024_v2.txt",
        "notes_2024.txt",
    ], "/docs")
    config = """
    rules:
      - locations: /docs
        filters:
          - name:
              startswith: report
              contains: "2024"
              case_sensitive: false
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter([
        "report_2024_final.txt",
        "REPORT_2024_v2.txt",
    ])


def test_extension_filter_case_insensitive(fs, testoutput):
    """User filters files by extension list with case-insensitive matching."""
    make_files([
        "photo.jpg",
        "photo.JPG",
        "photo.PNG",
        "document.pdf",
        "notes.txt",
    ], "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - extension:
              - jpg
              - png
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter([
        "photo.jpg",
        "photo.JPG",
        "photo.PNG",
    ])


def test_regex_filter_named_groups_in_rename(fs):
    """User extracts structured data from filenames with regex and renames based on captured groups."""
    make_files(["IMG_20240315_001.jpg", "IMG_20240722_002.jpg", "notes.txt"], "/photos")
    config = r"""
    rules:
      - locations: /photos
        filters:
          - regex: 'IMG_(?P<date>\d{8})_(?P<seq>\d+)\.jpg'
        actions:
          - rename: "photo_{regex.date}_{regex.seq}.jpg"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/photos") == {
        "photo_20240315_001.jpg": "",
        "photo_20240722_002.jpg": "",
        "notes.txt": "",
    }


def test_size_filter_with_conditions(fs, testoutput):
    """User filters files by size ranges using operators and units."""
    make_files({
        "tiny.txt": "",
        "small.txt": "hello",
        "medium.txt": "x" * 500,
        "large.txt": "x" * 2000,
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - size: ">= 100b, < 1000b"
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["medium.txt"]


def test_duplicate_filter_detection(fs):
    """User detects and deletes duplicate files, keeping the first seen original."""
    make_files({
        "a_original.txt": "same content",
        "b_duplicate.txt": "same content",
        "c_unique.txt": "different content",
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - duplicate
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/files")
    assert result == {
        "a_original.txt": "same content",
        "c_unique.txt": "different content",
    }


def test_empty_filter_files_and_dirs(fs):
    """User deletes empty files and empty directories in a two-rule config."""
    make_files({
        "keep.txt": "content",
        "empty.txt": "",
        "empty_dir": {},
        "full_dir": {"notempty.txt": "data"},
    }, "/cleanup")
    config = """
    rules:
      - locations: /cleanup
        filters:
          - empty
        actions:
          - delete
      - locations: /cleanup
        targets: dirs
        filters:
          - empty
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/cleanup")
    assert result == {
        "keep.txt": "content",
        "full_dir": {"notempty.txt": "data"},
    }


def test_filecontent_filter_regex_extraction(fs, testoutput):
    """User extracts data from file contents with regex named groups."""
    make_files({
        "invoice1.txt": "Invoice Number: INV-2024-001\nTotal: $500.00",
        "invoice2.txt": "Invoice Number: INV-2024-002\nTotal: $1200.50",
        "readme.txt": "This is a readme file.",
    }, "/docs")
    config = r"""
    rules:
      - locations: /docs
        filters:
          - filecontent: 'Invoice Number: (?P<inv_num>INV-\d{4}-\d{3})'
        actions:
          - echo: "{filecontent.inv_num}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["INV-2024-001", "INV-2024-002"])


def test_python_filter_with_return_value(fs, testoutput):
    """User writes custom Python filter code that computes values and filters files."""
    make_files(["001.txt", "002.txt", "003.txt", "010.txt"], "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - python: |
              num = int(path.stem)
              if num > 5:
                  return {"value": num}
        actions:
          - echo: "{python.value}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["10"]


def test_lastmodified_filter_older_mode(fs, testoutput):
    """User filters files modified more than a week ago."""
    make_files({"old.txt": "old", "new.txt": "new"}, "/files")
    old_time = time.time() - 30 * 86400
    os.utime("/files/old.txt", (old_time, old_time))
    config = """
    rules:
      - locations: /files
        filters:
          - lastmodified:
              days: 7
              mode: older
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["old.txt"]


def test_lastmodified_filter_newer_mode(fs, testoutput):
    """User filters files modified within the last week using mode: newer (distinct branch)."""
    make_files({"old.txt": "old", "fresh.txt": "fresh"}, "/files")
    old_time = time.time() - 30 * 86400
    os.utime("/files/old.txt", (old_time, old_time))
    config = """
    rules:
      - locations: /files
        filters:
          - lastmodified:
              days: 7
              mode: newer
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["fresh.txt"]


def test_multiple_filters_with_template_vars(fs, testoutput):
    """User combines multiple filters and accesses all their template vars in one action."""
    make_files({"report_2024.pdf": "x" * 1500}, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - name: "report_{year}"
          - extension: pdf
          - size: ">= 1000b"
        actions:
          - echo: "Year:{name.year} Ext:{extension} Size:{size.bytes}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["Year:2024 Ext:pdf Size:1500"]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_copy_into_directory(fs):
    """User copies matching files into a new directory, keeping originals."""
    make_files({
        "report.pdf": "pdf content",
        "data.csv": "csv content",
        "notes.txt": "text content",
    }, "/src")
    config = """
    rules:
      - locations: /src
        filters:
          - extension: pdf
        actions:
          - copy: /dest/pdfs/
    """
    Config.from_string(config).execute(simulate=False)
    assert Path("/src/report.pdf").exists()
    assert Path("/dest/pdfs/report.pdf").exists()
    assert Path("/dest/pdfs/report.pdf").read_text() == "pdf content"
    assert not Path("/dest/pdfs/data.csv").exists()


def _run_copy_conflict_mode(mode, expected):
    """Shared body: copy src.txt onto an existing dst.txt with the given on_conflict mode."""
    make_files({"src.txt": "src", "dst.txt": "dst"}, "/test")
    config = f"""
    rules:
      - locations: /test
        filters:
          - name: src
        actions:
          - copy:
              dest: /test/dst.txt
              on_conflict: {mode}
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/test") == expected


def test_copy_conflict_skip(fs):
    """User resolves a copy conflict with skip: both files left untouched."""
    _run_copy_conflict_mode("skip", {"src.txt": "src", "dst.txt": "dst"})


def test_copy_conflict_overwrite(fs):
    """User resolves a copy conflict with overwrite: the destination is replaced."""
    _run_copy_conflict_mode("overwrite", {"src.txt": "src", "dst.txt": "src"})


def test_copy_conflict_rename_new(fs):
    """User resolves a copy conflict with rename_new: the incoming file gets a counter suffix."""
    _run_copy_conflict_mode("rename_new", {"src.txt": "src", "dst.txt": "dst", "dst 2.txt": "src"})


def test_copy_conflict_rename_existing(fs):
    """User resolves a copy conflict with rename_existing: the existing file is renamed aside."""
    _run_copy_conflict_mode("rename_existing", {"src.txt": "src", "dst.txt": "src", "dst 2.txt": "dst"})


def test_copy_deduplicate_conflict(fs):
    """User copies with deduplicate mode: identical files skipped, different files renamed."""
    make_files({
        "a.txt": "content_a",
        "sub": {"a.txt": "content_a"},
        "other": {"a.txt": "content_b"},
    }, "/test")
    config = """
    rules:
      - locations: /test
        subfolders: true
        filters:
          - name: a
        actions:
          - copy:
              dest: /output/a.txt
              on_conflict: deduplicate
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/output")
    assert result == {"a.txt": "content_a", "a 2.txt": "content_b"}


def test_move_with_template_destination(fs):
    """User moves files into folders based on file extension using templates."""
    make_files({
        "report.pdf": "pdf",
        "photo.jpg": "jpg",
        "notes.txt": "txt",
    }, "/inbox")
    config = """
    rules:
      - locations: /inbox
        filters:
          - extension
        actions:
          - move: "/sorted/{extension.upper()}/"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/sorted") == {
        "PDF": {"report.pdf": "pdf"},
        "JPG": {"photo.jpg": "jpg"},
        "TXT": {"notes.txt": "txt"},
    }
    assert read_files("/inbox") == {}


def test_move_conflict_removes_source(fs):
    """Move shares the conflict matrix with copy; its only delta is that the source is removed.

    The full skip/overwrite/rename_new/rename_existing/deduplicate matrix is exercised through
    copy (test_copy_conflict_*); this test asserts only the move-specific behavior: under a
    representative conflict mode the incoming source no longer exists at its original location.
    """
    make_files({"src.txt": "src", "dst.txt": "dst"}, "/test")
    config = """
    rules:
      - locations: /test
        filters:
          - name: src
        actions:
          - move:
              dest: /test/dst.txt
              on_conflict: rename_new
    """
    Config.from_string(config).execute(simulate=False)
    # rename_new keeps the existing dst.txt and places the moved file at dst 2.txt;
    # the move-specific delta over copy is that the original src.txt is gone.
    assert read_files("/test") == {"dst.txt": "dst", "dst 2.txt": "src"}
    assert not Path("/test/src.txt").exists()


def test_move_conflict_overwrite_replaces_and_removes_source(fs):
    """Move + overwrite must BOTH replace the destination and remove the source.

    test_copy_conflict_overwrite pins only the destination side of `overwrite`; an
    implementation that resolves the conflict in a shared pre-step and then short-circuits
    the move (leaving src.txt behind, or unlinking the source without writing the
    destination) satisfies that case but not this conjunction.
    """
    make_files({"src.txt": "src", "dst.txt": "dst"}, "/test")
    config = """
    rules:
      - locations: /test
        filters:
          - name: src
        actions:
          - move:
              dest: /test/dst.txt
              on_conflict: overwrite
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/test") == {"dst.txt": "src"}


def test_size_traditional_template_var(fs, testoutput):
    """User echoes human-readable sizes via the size filter's {size.traditional} string variable."""
    make_files({"two_kb.bin": "x" * 2048, "one_mb.bin": "x" * (1024 * 1024)}, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - size
        actions:
          - echo: "{path.name} = {size.traditional}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter([
        "two_kb.bin = 2.0 KB",
        "one_mb.bin = 1.0 MB",
    ])


def test_echo_with_template_vars(fs, testoutput):
    """User echoes file info using built-in and filter template variables."""
    make_files({"hello.txt": ""}, "/test")
    config = """
    rules:
      - locations: /test
        actions:
          - echo: "stem={path.stem} name={path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["stem=hello name=hello.txt"]


def test_shell_action_output_capture(tmp_path, testoutput):
    """User runs shell commands and accesses return code in downstream actions."""
    (tmp_path / "test.txt").touch()
    config = f"""
    rules:
      - locations: "{tmp_path}"
        actions:
          - shell: "echo done"
          - echo: "rc={{shell.returncode}}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert any(m == "rc=0" for m in testoutput.messages)


def test_python_action_with_return_dict(fs, testoutput):
    """User executes custom Python code and uses returned values in downstream echo."""
    make_files({"report.txt": "Hello World"}, "/test")
    config = """
    rules:
      - locations: /test
        actions:
          - python: |
              content = path.read_text()
              return {"word_count": len(content.split())}
          - echo: "words={python.word_count}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert any(m == "words=2" for m in testoutput.messages)


def test_write_action_all_modes(fs):
    """User writes file paths using append, prepend, and overwrite modes."""
    make_files(["a.txt", "b.txt", "c.txt"], "/files")

    for mode, expected in [
        ("append", "a.txt\nb.txt\nc.txt\n"),
        ("prepend", "c.txt\nb.txt\na.txt\n"),
        ("overwrite", "c.txt\n"),
    ]:
        config = f"""
        rules:
          - locations: /files
            actions:
              - write:
                  text: "{{path.name}}"
                  outfile: /output/{mode}.txt
                  mode: {mode}
        """
        Config.from_string(config).execute(simulate=False)
        content = Path(f"/output/{mode}.txt").read_text()
        assert content == expected, f"mode={mode}: expected {expected!r}, got {content!r}"


# ---------------------------------------------------------------------------
# Filter modes and negation
# ---------------------------------------------------------------------------


def test_filter_mode_any(fs, testoutput):
    """User matches files with OR logic using filter_mode: any."""
    make_files(["photo.jpg", "document.pdf", "song.mp3", "notes.txt"], "/files")
    config = """
    rules:
      - locations: /files
        filter_mode: any
        filters:
          - extension: jpg
          - extension: pdf
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["photo.jpg", "document.pdf"])


def test_filter_mode_none(fs, testoutput):
    """User matches files that satisfy NO filter using filter_mode: none."""
    make_files(["photo.jpg", "document.pdf", "notes.txt"], "/files")
    config = """
    rules:
      - locations: /files
        filter_mode: none
        filters:
          - extension: jpg
          - extension: pdf
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["notes.txt"]


def test_not_filter_prefix(fs, testoutput):
    """User excludes files matching a pattern using the not prefix."""
    make_files(["keep.txt", "keep2.txt", "ignore.txt", "ignore2.txt"], "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - not name:
              startswith: ignore
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["keep.txt", "keep2.txt"])


# ---------------------------------------------------------------------------
# Tags, simulation, and integration
# ---------------------------------------------------------------------------


def test_tag_filtering_with_always_and_never(fs):
    """User selectively runs rules with tags, including always and never special tags."""
    make_files(["a.txt"], "/files")

    config = """
    rules:
      - locations: /files
        tags: [always]
        actions:
          - echo: "always runs"
      - locations: /files
        tags: [daily]
        actions:
          - echo: "daily"
      - locations: /files
        tags: [weekly]
        actions:
          - echo: "weekly"
      - locations: /files
        tags: [never]
        actions:
          - echo: "dangerous"
      - locations: /files
        actions:
          - echo: "untagged"
    """
    out1 = SavingOutput()
    Config.from_string(config).execute(simulate=False, output=out1, tags={"daily"})
    assert Counter(out1.messages) == Counter(["always runs", "daily"])

    out2 = SavingOutput()
    Config.from_string(config).execute(simulate=False, output=out2)
    assert "dangerous" not in out2.messages
    assert "always runs" in out2.messages
    assert "untagged" in out2.messages


def test_simulation_does_not_modify_files(fs):
    """User previews changes with simulate=True and filesystem stays untouched."""
    files = {
        "report.pdf": "content",
        "photo.jpg": "image",
    }
    make_files(files, "/test")
    config = """
    rules:
      - locations: /test
        actions:
          - move: /dest/
          - copy: /backup/
    """
    Config.from_string(config).execute(simulate=True)
    assert read_files("/test") == files
    assert not Path("/dest").exists()
    assert not Path("/backup").exists()


def test_multi_rule_dependent_pipeline(fs):
    """User runs dependent rules: rule 1 copies files, rule 2 renames copies."""
    make_files({"original.txt": "data"}, "/src")
    config = """
    rules:
      - locations: /src
        actions:
          - copy: /staging/
      - locations: /staging
        filters:
          - extension
        actions:
          - rename: "processed_{path.stem}.{extension}"
    """
    Config.from_string(config).execute(simulate=False)
    assert Path("/src/original.txt").exists()
    assert Path("/staging/processed_original.txt").exists()
    assert not Path("/staging/original.txt").exists()


def test_standalone_echo_without_locations(fs, testoutput):
    """User runs an echo action without locations (standalone mode)."""
    config = """
    rules:
      - actions:
          - echo: "Hello from standalone"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["Hello from standalone"]


def test_copy_preserving_folder_structure(fs):
    """User copies files while preserving directory hierarchy using relative_path."""
    make_files({
        "file1.txt": "",
        "sub1": {
            "file2.txt": "",
            "sub2": {"file3.txt": ""},
        },
    }, "/src")
    config = """
    rules:
      - locations: /src
        subfolders: true
        filters:
          - name:
              startswith: file
        actions:
          - copy: "/dest/{relative_path}"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/dest") == {
        "file1.txt": "",
        "sub1": {
            "file2.txt": "",
            "sub2": {"file3.txt": ""},
        },
    }


# ---------------------------------------------------------------------------
# Harder tests — edge cases, complex pipelines, subtle behaviors
# ---------------------------------------------------------------------------


def test_move_prevents_reprocessing_via_walker_skip(fs):
    """Moving a file into the same scanned location does not cause it to be reprocessed."""
    make_files({
        "a.txt": "aaa",
        "b.txt": "bbb",
    }, "/data")
    config = """
    rules:
      - locations: /data
        filters:
          - extension: txt
        actions:
          - move: "/data/archive/"
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/data")
    assert result == {
        "archive": {
            "a.txt": "aaa",
            "b.txt": "bbb",
        },
    }


def test_copy_continue_with_original(fs, testoutput):
    """Copy with continue_with: original keeps the pipeline working on the source file."""
    make_files({"src.txt": "data"}, "/test")
    config = """
    rules:
      - locations: /test
        actions:
          - copy:
              dest: /backup/
              continue_with: original
          - echo: "{path}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Path("/backup/src.txt").exists()
    assert any(m == str(Path("/test/src.txt")) for m in testoutput.messages)


def test_multiple_regex_filters_deep_merge(fs, testoutput):
    """Two regex filters in one rule deep-merge their named groups into {regex}."""
    make_files(["report-2024-Q3.pdf"], "/docs")
    config = r"""
    rules:
      - locations: /docs
        filters:
          - regex: '(?P<type>\w+)-(?P<year>\d{4})'
          - regex: '(?P<quarter>Q\d)'
        actions:
          - echo: "{regex.type} {regex.year} {regex.quarter}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["report 2024 Q3"]


def test_duplicate_detect_original_by_name(fs):
    """Duplicate filter with detect_original_by: name uses alphabetical order to pick the original."""
    make_files({
        "zzz_copy.txt": "same",
        "aaa_original.txt": "same",
        "unique.txt": "different",
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - duplicate:
              detect_original_by: name
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/files")
    assert result == {
        "aaa_original.txt": "same",
        "unique.txt": "different",
    }


def test_write_clear_before_first_write(fs):
    """Write with clear_before_first_write clears existing content on first append only."""
    make_files({"existing.log": "old content\n"}, "/output")
    make_files(["a.txt", "b.txt"], "/files")
    config = """
    rules:
      - locations: /files
        actions:
          - write:
              text: "{path.name}"
              outfile: /output/existing.log
              mode: append
              clear_before_first_write: true
    """
    Config.from_string(config).execute(simulate=False)
    content = Path("/output/existing.log").read_text()
    assert content == "a.txt\nb.txt\n"


def test_size_filter_on_directories(fs, testoutput):
    """Size filter on directories computes the recursive sum of all contained files."""
    make_files({
        "small_dir": {"a.txt": "x" * 100},
        "large_dir": {"b.txt": "x" * 500, "c.txt": "x" * 600},
        "empty_dir": {},
    }, "/data")
    config = """
    rules:
      - locations: /data
        targets: dirs
        filters:
          - size: "> 200b"
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["large_dir"])


def test_python_filter_with_import_and_nested_dict(fs, testoutput):
    """Python filter can import modules and return nested dicts accessible via dot notation."""
    make_files({"test.txt": "Hello World\nSecond Line\nThird Line"}, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - python: |
              import os
              content = path.read_text()
              lines = content.strip().split('\\n')
              return {"stats": {"line_count": len(lines), "first_word": lines[0].split()[0]}}
        actions:
          - echo: "{python.stats.line_count} lines, starts with {python.stats.first_word}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["3 lines, starts with Hello"]


def test_complex_multi_filter_action_pipeline(fs, testoutput):
    """Complex pipeline: name + regex + extension filters chain, all vars available in echo."""
    make_files(["report_2024-Q3_final.pdf"], "/docs")
    config = r"""
    rules:
      - locations: /docs
        filters:
          - name: "report_{year}-{quarter}_{status}"
          - regex: '(?P<full_stem>.+)\.pdf'
          - extension: pdf
        actions:
          - echo: "Y:{name.year} Q:{name.quarter} S:{name.status} E:{extension} R:{regex.full_stem}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == [
        "Y:2024 Q:Q3 S:final E:pdf R:report_2024-Q3_final"
    ]


def test_not_combined_with_filter_mode_any(fs, testoutput):
    """Negated filters combined with filter_mode: any — file passes if any negated filter is true."""
    make_files(["photo.jpg", "doc.pdf", "notes.txt", "data.csv"], "/files")
    config = """
    rules:
      - locations: /files
        filter_mode: any
        filters:
          - not extension: jpg
          - not extension: pdf
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    # "not jpg" OR "not pdf" — everything passes except... actually:
    # photo.jpg: not jpg = False, not pdf = True → passes (any mode, one is True)
    # doc.pdf: not jpg = True, not pdf = False → passes
    # notes.txt: not jpg = True, not pdf = True → passes
    # data.csv: not jpg = True, not pdf = True → passes
    # All files pass because for any file, at least one negated filter is True
    assert Counter(testoutput.messages) == Counter([
        "photo.jpg", "doc.pdf", "notes.txt", "data.csv"
    ])


def test_move_then_echo_shows_updated_path(fs, testoutput):
    """Move updates res.path; downstream echo sees the new location."""
    make_files({"report.txt": "data"}, "/inbox")
    config = """
    rules:
      - locations: /inbox
        actions:
          - move: /processed/
          - echo: "{path}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert any(m == str(Path("/processed/report.txt")) for m in testoutput.messages)
    assert not Path("/inbox/report.txt").exists()
    assert Path("/processed/report.txt").exists()


def test_lastmodified_strftime_in_move_destination(fs):
    """User sorts files into date-based folders using lastmodified.strftime in move dest."""
    make_files({"photo.jpg": "img"}, "/unsorted")
    # Set mtime to a known date: 2024-06-15
    import datetime
    target_time = datetime.datetime(2024, 6, 15, 12, 0, 0).timestamp()
    os.utime("/unsorted/photo.jpg", (target_time, target_time))
    config = """
    rules:
      - locations: /unsorted
        filters:
          - lastmodified
        actions:
          - move: "/sorted/{lastmodified.strftime('%Y/%m')}/"
    """
    Config.from_string(config).execute(simulate=False)
    assert Path("/sorted/2024/06/photo.jpg").exists()
    assert Path("/sorted/2024/06/photo.jpg").read_text() == "img"


def test_cascading_conflict_rename_multiple_files(fs):
    """Multiple files copied to the same destination cascade through rename_new counters."""
    make_files({
        "a": {"file.txt": "from_a"},
        "b": {"file.txt": "from_b"},
        "c": {"file.txt": "from_c"},
    }, "/src")
    config = """
    rules:
      - locations: /src
        subfolders: true
        filters:
          - name: file
        actions:
          - copy: /dest/file.txt
    """
    Config.from_string(config).execute(simulate=False)
    # The rename_new counter increments in walk order (natsort over subfolders a, b, c), so the
    # mapping of content to suffix is fully determined: assert it exactly, not just the sets.
    assert read_files("/dest") == {
        "file.txt": "from_a",
        "file 2.txt": "from_b",
        "file 3.txt": "from_c",
    }


def test_natsort_ordering_in_walker(fs, testoutput):
    """Walker yields files in natural sort order: file1, file2, file10 — not lexicographic."""
    make_files(["file10.txt", "file1.txt", "file2.txt", "file20.txt"], "/data")
    config = """
    rules:
      - locations: /data
        actions:
          - write:
              text: "{path.name}"
              outfile: /output/order.txt
              mode: append
    """
    Config.from_string(config).execute(simulate=False)
    content = Path("/output/order.txt").read_text()
    assert content == "file1.txt\nfile2.txt\nfile10.txt\nfile20.txt\n"


def test_copy_onto_itself_is_noop(fs):
    """Copying a file to the same location where it already exists is a no-op."""
    files = {
        "test.txt": "content",
        "other.txt": "other",
    }
    make_files(files, "/test")
    config = """
    rules:
      - locations: /test
        actions:
          - copy: /test
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/test") == files


def test_name_filter_list_criteria_or_within_and_across(fs, testoutput):
    """Name filter: list values within a criterion use OR; across criteria use AND."""
    make_files([
        "report_draft.txt",
        "report_final.txt",
        "invoice_draft.txt",
        "invoice_final.txt",
        "notes_draft.txt",
    ], "/docs")
    config = """
    rules:
      - locations: /docs
        filters:
          - name:
              startswith:
                - report
                - invoice
              endswith: final
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter([
        "report_final.txt",
        "invoice_final.txt",
    ])


def test_duplicate_across_multiple_locations(fs):
    """Duplicate filter maintains state across multiple locations in one rule."""
    make_files({"file.txt": "same content"}, "/loc1")
    make_files({"file.txt": "same content"}, "/loc2")
    make_files({"unique.txt": "different"}, "/loc1")
    config = """
    rules:
      - locations:
          - /loc1
          - /loc2
        filters:
          - duplicate
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    assert Path("/loc1/file.txt").exists()
    assert not Path("/loc2/file.txt").exists()
    assert Path("/loc1/unique.txt").exists()


def test_write_with_per_file_templated_outfile(fs):
    """Write action with templated outfile creates separate output files per input."""
    make_files({
        "alpha.txt": "content_a",
        "beta.txt": "content_b",
    }, "/input")
    config = """
    rules:
      - locations: /input
        actions:
          - write:
              text: "processed"
              outfile: "/output/{path.stem}.log"
              mode: overwrite
    """
    Config.from_string(config).execute(simulate=False)
    assert Path("/output/alpha.log").read_text() == "processed\n"
    assert Path("/output/beta.log").read_text() == "processed\n"


def test_shell_ignore_errors_continues_pipeline(tmp_path, testoutput):
    """Shell with ignore_errors=true continues pipeline even when command fails."""
    (tmp_path / "test.txt").touch()
    config = f"""
    rules:
      - locations: "{tmp_path}"
        actions:
          - shell:
              cmd: "exit 1"
              ignore_errors: true
          - echo: "rc={{shell.returncode}}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert any(m == "rc=1" for m in testoutput.messages)


def test_empty_filters_matches_all_files(fs, testoutput):
    """Rule with empty filters list (or no filters) matches all files."""
    make_files(["a.txt", "b.pdf", "c.jpg"], "/files")
    config = """
    rules:
      - locations: /files
        filters:
        actions:
          - echo: "{path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert Counter(testoutput.messages) == Counter(["a.txt", "b.pdf", "c.jpg"])


def test_duplicate_large_files_full_hash(fs):
    """Duplicate detection on large files (>1024 bytes) requires full hash comparison."""
    chunk = "x" * 1024
    make_files({
        "a.txt": chunk + "AAAA",
        "b.txt": chunk + "BBBB",
        "c.txt": chunk + "AAAA",
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - duplicate
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/files") == {
        "a.txt": chunk + "AAAA",
        "b.txt": chunk + "BBBB",
    }


def test_python_action_print_routes_to_output(fs, testoutput):
    """Python action's print() function routes output through the output handler."""
    make_files(["test.txt"], "/files")
    config = """
    rules:
      - locations: /files
        actions:
          - python: |
              print("hello from python")
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert "hello from python" in testoutput.messages


def test_filecontent_multiline_dotall(fs, testoutput):
    """Filecontent regex with DOTALL matches across line boundaries."""
    make_files({
        "multi.txt": "START\nsome data\nEND",
        "nomatch.txt": "no markers here",
    }, "/files")
    config = r"""
    rules:
      - locations: /files
        filters:
          - filecontent: 'START(?P<body>.+)END'
        actions:
          - echo: "matched {path.name}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["matched multi.txt"]


def test_duplicate_original_template_var(fs, testoutput):
    """Duplicate filter exposes {duplicate.original} pointing to the original file."""
    make_files({
        "aaa_original.txt": "same",
        "zzz_duplicate.txt": "same",
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - duplicate
        actions:
          - echo: "dup={path.name} orig={duplicate.original}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert len(testoutput.messages) == 1
    msg = testoutput.messages[0]
    assert "dup=zzz_duplicate.txt" in msg
    assert "aaa_original.txt" in msg


def test_move_deduplicate_conflict(fs):
    """Move + deduplicate: the move-specific delta over copy is the source disposition.

    Copy+deduplicate is covered by test_copy_deduplicate_conflict; this test asserts ONLY
    what move adds: when a source is byte-identical to the destination the move is *skipped*
    so that source stays in place, while a source whose content differs is moved away (its
    original location is emptied). Walk order is the documented case-insensitive natsort,
    breadth-first (root files before subfolders): /test/a.txt lands at /output/a.txt first,
    then /test/other/a.txt (different) is moved to /output/a 2.txt, and /test/sub/a.txt
    (identical) is skipped.
    """
    make_files({
        "a.txt": "content_a",
        "other": {"a.txt": "content_b"},
        "sub": {"a.txt": "content_a"},
    }, "/test")
    config = """
    rules:
      - locations: /test
        subfolders: true
        filters:
          - name: a
        actions:
          - move:
              dest: /output/a.txt
              on_conflict: deduplicate
    """
    Config.from_string(config).execute(simulate=False)
    # Source disposition is the move-specific behavior copy cannot exhibit:
    # the identical duplicate's source remains, the different and first files were moved away.
    assert not Path("/test/a.txt").exists()
    assert not Path("/test/other/a.txt").exists()
    assert read_files("/test/sub") == {"a.txt": "content_a"}


def test_rename_conflict_rename_new(fs):
    """Rename onto an existing name uses rename_new to give the incoming file a counter suffix."""
    make_files({"old.txt": "data", "new.txt": "existing"}, "/test")
    config = """
    rules:
      - locations: /test
        filters:
          - name: old
        actions:
          - rename:
              new_name: new.txt
              on_conflict: rename_new
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/test") == {"new.txt": "existing", "new 2.txt": "data"}


def test_python_filter_uses_prior_filter_variables(fs, testoutput):
    """A python filter reads variables set by an earlier filter in the same rule."""
    make_files(["item_042.txt", "item_007.txt", "note.txt"], "/files")
    config = r'''
    rules:
      - locations: /files
        filters:
          - regex: 'item_(?P<num>\d+)'
          - python: |
              return int(regex["num"]) > 10
        actions:
          - echo: "{regex.num}"
    '''
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["042"]


def test_invoice_processing_workflow(fs):
    """End-to-end: regex groups + python filter (reads path & prior regex var, returns
    dict conditionally) + rename consuming both {regex.id} and {python.amount}. Fails as
    a unit — the agent must get the whole chain right."""
    make_files({
        "invoice_1001.txt": "AMOUNT: 250",
        "invoice_1002.txt": "AMOUNT: 75",
        "note.txt": "not an invoice",
    }, "/inbox")
    config = r'''
    rules:
      - locations: /inbox
        filters:
          - regex: 'invoice_(?P<id>\d+)'
          - python: |
              import re
              amount = int(re.search(r'AMOUNT: (\d+)', path.read_text()).group(1))
              if amount >= 100:
                  return {"amount": amount}
        actions:
          - rename: "INV{regex.id}_{python.amount}.txt"
    '''
    Config.from_string(config).execute(simulate=False)
    assert read_files("/inbox") == {
        "INV1001_250.txt": "AMOUNT: 250",
        "invoice_1002.txt": "AMOUNT: 75",
        "note.txt": "not an invoice",
    }


def test_dedup_then_manifest_workflow(fs):
    """Multi-rule end-to-end: duplicate detection + delete, then a natsort-ordered manifest
    written via append. Compounds the dedup pipeline, walk order, multi-rule sequencing,
    and the write action."""
    make_files({
        "a_report.txt": "DATA",
        "b_copy.txt": "DATA",
        "c_other.txt": "UNIQUE",
    }, "/docs")
    config = """
    rules:
      - locations: /docs
        filters:
          - duplicate
        actions:
          - delete
      - locations: /docs
        filters:
          - extension: txt
        actions:
          - write:
              text: "{path.name}"
              outfile: /docs/manifest.log
              mode: append
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/docs")
    assert "b_copy.txt" not in result
    assert result["a_report.txt"] == "DATA"
    assert result["c_other.txt"] == "UNIQUE"
    assert result["manifest.log"] == "a_report.txt\nc_other.txt\n"


def test_download_sorter_workflow(fs):
    """Recursively sort files into per-extension folders, cascading name conflicts.
    Compounds the subfolders walk, extension filter, templated move destination, and
    rename_new conflict resolution."""
    make_files({
        "report.pdf": "p1",
        "photo.jpg": "j1",
        "notes.txt": "t1",
        "sub": {"report.pdf": "p2"},
    }, "/downloads")
    config = """
    rules:
      - locations: /downloads
        subfolders: true
        filters:
          - extension:
              - pdf
              - jpg
        actions:
          - move: "/sorted/{extension}/"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/sorted") == {
        "jpg": {"photo.jpg": "j1"},
        "pdf": {"report.pdf": "p1", "report 2.pdf": "p2"},
    }


def test_content_router_workflow(fs):
    """Route documents by a category extracted from their content: filecontent named
    group feeds a rename template."""
    make_files({
        "doc1.txt": "Category: FINANCE\nbody",
        "doc2.txt": "Category: LEGAL\nbody",
        "doc3.txt": "no category here",
    }, "/inbox")
    config = r'''
    rules:
      - locations: /inbox
        filters:
          - filecontent: 'Category: (?P<cat>\w+)'
        actions:
          - rename: "{filecontent.cat}_{path.name}"
    '''
    Config.from_string(config).execute(simulate=False)
    assert read_files("/inbox") == {
        "FINANCE_doc1.txt": "Category: FINANCE\nbody",
        "LEGAL_doc2.txt": "Category: LEGAL\nbody",
        "doc3.txt": "no category here",
    }


def test_action_chaining_workflow(fs, testoutput):
    """A single rule chains rename -> copy -> echo, with res.path flowing through each
    action so the copy and echo see the renamed path."""
    make_files({"IMG_001.heic": "img"}, "/inbox")
    config = r'''
    rules:
      - locations: /inbox
        filters:
          - regex: 'IMG_(?P<n>\d+)'
        actions:
          - rename: "photo_{regex.n}.heic"
          - copy: /processed/
          - echo: "{path.name}"
    '''
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert read_files("/inbox") == {"photo_001.heic": "img"}
    assert read_files("/processed") == {"photo_001.heic": "img"}
    assert "photo_001.heic" in testoutput.messages


def test_python_action_categorize_then_move_workflow(fs):
    """A python action returns a dict whose value drives a downstream move destination —
    a distinct usage scenario (python action -> move) from the filter -> rename workflow."""
    make_files({
        "score_90.txt": "a",
        "score_30.txt": "b",
    }, "/inbox")
    config = """
    rules:
      - locations: /inbox
        actions:
          - python: |
              n = int(path.stem.split('_')[1])
              return {"bucket": "high" if n >= 50 else "low"}
          - move: "/sorted/{python.bucket}/"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/sorted") == {
        "high": {"score_90.txt": "a"},
        "low": {"score_30.txt": "b"},
    }


def test_cleanup_pipeline_workflow(fs):
    """Large end-to-end three-rule cleanup: cross-directory dedup + delete, then empty-file
    removal, then empty-directory removal (targets dirs). The second/third rules depend on
    the side effects of the earlier ones."""
    make_files({
        "a.log": "DATA",
        "b.log": "DATA",
        "big.log": "x" * 2000,
        "empty.log": "",
        "emptydir": {},
        "sub": {"c.log": "DATA"},
    }, "/workspace")
    config = """
    rules:
      - locations: /workspace
        subfolders: true
        filters:
          - duplicate
        actions:
          - delete
      - locations: /workspace
        filters:
          - empty
        actions:
          - delete
      - locations: /workspace
        targets: dirs
        filters:
          - empty
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/workspace") == {"a.log": "DATA", "big.log": "x" * 2000}


# ---------------------------------------------------------------------------
# Template engine depth (real Jinja2, not naive substitution)
# ---------------------------------------------------------------------------


def test_template_conditional_expression(fs):
    """A Jinja conditional in a move destination routes by a computed condition. Only a
    real Jinja engine (not naive {var} substitution) satisfies this."""
    make_files({
        "big.txt": "x" * 2000,
        "small.txt": "x" * 50,
    }, "/files")
    config = """
    rules:
      - locations: /files
        filters:
          - size
        actions:
          - move: "/sorted/{ 'large' if size.bytes > 1000 else 'small' }/"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/sorted") == {
        "large": {"big.txt": "x" * 2000},
        "small": {"small.txt": "x" * 50},
    }


def test_template_slicing_and_methods(fs, testoutput):
    """Templates support Python slicing and chained method calls on attributes."""
    make_files(["Report_Final.TXT"], "/docs")
    config = """
    rules:
      - locations: /docs
        actions:
          - echo: "{path.stem[:6].lower()}-{path.suffix.lstrip('.').lower()}"
    """
    Config.from_string(config).execute(simulate=False, output=testoutput)
    assert testoutput.messages == ["report-txt"]


# ---------------------------------------------------------------------------
# Conflict-resolution edge cases
# ---------------------------------------------------------------------------


def test_rename_existing_cascade(fs):
    """rename_existing renames the EXISTING file out of the way (not the incoming one),
    placing the incoming file at the original destination — easy to implement backwards."""
    make_files({
        "a": {"doc.txt": "incoming1"},
        "b": {"doc.txt": "incoming2"},
        "dest": {"doc.txt": "original"},
    }, "/test")
    config = """
    rules:
      - locations:
          - /test/a
          - /test/b
        filters:
          - name: doc
        actions:
          - move:
              dest: /test/dest/doc.txt
              on_conflict: rename_existing
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/test/dest") == {
        "doc.txt": "incoming2",
        "doc 2.txt": "original",
        "doc 3.txt": "incoming1",
    }


def test_custom_rename_template(fs):
    """A custom rename_template controls the conflict-renamed filename."""
    make_files({
        "src": {"file.txt": "new"},
        "file.txt": "existing",
    }, "/test")
    config = """
    rules:
      - locations: /test/src
        actions:
          - copy:
              dest: /test/file.txt
              on_conflict: rename_new
              rename_template: "{name}_copy{counter}{extension}"
    """
    Config.from_string(config).execute(simulate=False)
    result = read_files("/test")
    assert result["file.txt"] == "existing"
    assert result["file_copy2.txt"] == "new"


# ---------------------------------------------------------------------------
# Mega workflows — long multi-feature chains, fail as a unit
# ---------------------------------------------------------------------------


def test_mega_photo_library_reorg(fs):
    """Three-rule reorg chaining exclude_dirs + recursive walk + cross-dir dedup +
    extension + regex date groups + templated move + empty-dir cleanup."""
    make_files({
        "IMG_2023-12-31_001.jpg": "a",
        "IMG_2024-03-15_001.jpg": "b",
        "IMG_2024-03-15_002.jpg": "b",
        "notes.txt": "x",
        "raw": {"IMG_2024-03-15_009.jpg": "b"},
        "exports": {"IMG_2024-01-01_001.jpg": "z"},
    }, "/camera")
    config = r'''
    rules:
      - locations:
          - path: /camera
            exclude_dirs: [exports]
        subfolders: true
        filters:
          - duplicate
        actions:
          - delete
      - locations:
          - path: /camera
            exclude_dirs: [exports]
        subfolders: true
        filters:
          - extension: jpg
          - regex: 'IMG_(?P<date>\d{4}-\d{2})'
        actions:
          - move: "/camera/sorted/{regex.date}/"
      - locations: /camera
        targets: dirs
        filters:
          - empty
        actions:
          - delete
    '''
    Config.from_string(config).execute(simulate=False)
    assert read_files("/camera") == {
        "exports": {"IMG_2024-01-01_001.jpg": "z"},
        "notes.txt": "x",
        "sorted": {
            "2023-12": {"IMG_2023-12-31_001.jpg": "a"},
            "2024-03": {"IMG_2024-03-15_001.jpg": "b"},
        },
    }


def test_mega_document_intake(fs):
    """Two-rule intake chaining name criterion + filecontent two-group extraction +
    python filter (conditional on a prior filter's dict) + rename + copy, then a manifest
    of all remaining text files."""
    make_files({
        "doc_1.txt": "Dept: ENG\nPriority: 5",
        "doc_2.txt": "Dept: HR\nPriority: 1",
        "doc_3.txt": "Dept: ENG\nPriority: 9",
        "skip.txt": "no header",
    }, "/inbox")
    config = r'''
    rules:
      - locations: /inbox
        filters:
          - name:
              startswith: doc
          - filecontent: 'Dept: (?P<dept>\w+)\nPriority: (?P<pri>\d+)'
          - python: |
              return int(filecontent["pri"]) >= 5
        actions:
          - rename: "{filecontent.dept}_{filecontent.pri}.txt"
          - copy: "/inbox/archive/"
      - locations: /inbox
        filters:
          - extension: txt
        actions:
          - write:
              text: "{path.name}"
              outfile: "/inbox/manifest.log"
              mode: append
    '''
    Config.from_string(config).execute(simulate=False)
    assert read_files("/inbox") == {
        "ENG_5.txt": "Dept: ENG\nPriority: 5",
        "ENG_9.txt": "Dept: ENG\nPriority: 9",
        "doc_2.txt": "Dept: HR\nPriority: 1",
        "skip.txt": "no header",
        "manifest.log": "doc_2.txt\nENG_5.txt\nENG_9.txt\nskip.txt\n",
        "archive": {
            "ENG_5.txt": "Dept: ENG\nPriority: 5",
            "ENG_9.txt": "Dept: ENG\nPriority: 9",
        },
    }


def test_mega_size_tiering_with_conflict(fs):
    """Size-threshold tiering into an archive that already holds a same-named file, forcing
    a rename_new conflict, while sub-threshold files are only reported."""
    make_files({
        "big1.dat": "x" * 2000,
        "big2.dat": "y" * 1500,
        "small.dat": "z" * 100,
        "archive": {"big1.dat": "OLD"},
    }, "/data")
    config = """
    rules:
      - locations: /data
        filters:
          - size: ">= 1kb"
        actions:
          - move:
              dest: /data/archive/
              on_conflict: rename_new
      - locations: /data
        filters:
          - size: "< 1kb"
        actions:
          - echo: "small: {path.name}"
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/data") == {
        "small.dat": "z" * 100,
        "archive": {
            "big1.dat": "OLD",
            "big1 2.dat": "x" * 2000,
            "big2.dat": "y" * 1500,
        },
    }


def test_mega_backup_then_dedup(fs):
    """Backup all non-empty files into a sibling tree preserving directory structure
    (relative_path), then dedup the source. Chains negated filter + recursive walk +
    structure-preserving copy + multi-rule + content dedup + delete."""
    make_files({
        "a.txt": "DATA",
        "docs": {"b.txt": "DATA", "c.txt": "UNIQUE"},
        "empty.txt": "",
    }, "/src")
    config = """
    rules:
      - locations: /src
        subfolders: true
        filters:
          - not empty
        actions:
          - copy: "/backup/{relative_path}"
      - locations: /src
        subfolders: true
        filters:
          - duplicate
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False)
    assert read_files("/src") == {
        "a.txt": "DATA",
        "docs": {"c.txt": "UNIQUE"},
        "empty.txt": "",
    }
    assert read_files("/backup") == {
        "a.txt": "DATA",
        "docs": {"b.txt": "DATA", "c.txt": "UNIQUE"},
    }


def test_mega_filename_normalization(fs):
    """Normalize report filenames recursively: extension (case-insensitive on .PDF) +
    regex groups + rename + move into one archive, with a same-normalized-name collision
    resolved by rename_new."""
    make_files({
        "Report-2024-001.PDF": "p1",
        "notes.txt": "x",
        "sub": {"Report-2024-001.PDF": "p2"},
    }, "/incoming")
    config = r'''
    rules:
      - locations: /incoming
        subfolders: true
        filters:
          - extension: pdf
          - regex: 'Report-(?P<y>\d{4})-(?P<n>\d+)'
        actions:
          - rename: "{regex.y}_{regex.n}.pdf"
          - move:
              dest: /archive/
              on_conflict: rename_new
    '''
    Config.from_string(config).execute(simulate=False)
    assert read_files("/archive") == {
        "2024_001.pdf": "p1",
        "2024_001 2.pdf": "p2",
    }
    assert read_files("/incoming") == {"notes.txt": "x", "sub": {}}


def test_mega_tag_driven_batch(fs, testoutput):
    """Tag-driven multi-rule batch: an `always` rule (filter_mode any) reports media, a
    requested `cleanup` rule deletes temp files, and a `never` rule is skipped."""
    make_files({
        "report.pdf": "p",
        "photo.jpg": "j",
        "temp.tmp": "t",
        "draft.txt": "d",
    }, "/files")
    config = """
    rules:
      - tags: [always]
        locations: /files
        filter_mode: any
        filters:
          - extension: pdf
          - extension: jpg
        actions:
          - echo: "media: {path.name}"
      - tags: [cleanup]
        locations: /files
        filters:
          - extension: tmp
        actions:
          - delete
      - tags: [never]
        locations: /files
        actions:
          - delete
    """
    Config.from_string(config).execute(simulate=False, output=testoutput, tags={"cleanup"})
    assert read_files("/files") == {
        "report.pdf": "p",
        "photo.jpg": "j",
        "draft.txt": "d",
    }
    assert "media: photo.jpg" in testoutput.messages
    assert "media: report.pdf" in testoutput.messages


