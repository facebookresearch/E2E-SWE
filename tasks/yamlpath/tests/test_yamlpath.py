"""E2E tests for the yamlpath library and CLI tools."""

import json
import os
import subprocess
import tempfile
import textwrap

import pytest


def run_cmd(args, input_data=None, expect_fail=False):
    """Run a CLI command and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        input=input_data,
        timeout=30,
    )
    if not expect_fail:
        assert (
            result.returncode == 0
        ), f"Command failed: {args}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return result.stdout, result.stderr, result.returncode


def write_yaml(content, suffix=".yaml"):
    """Write YAML content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False)
    f.write(textwrap.dedent(content))
    f.flush()
    f.close()
    return f.name


# ===========================================================================
# yaml-get: basic value retrieval (Group 1: 18 -> 3)
# ===========================================================================
class TestYamlGet:
    def test_get_basic_ops(self):
        """Bundle: scalar, nested fslash, array, boolean, null, stdin."""
        # Scalar
        path = write_yaml(
            """\
            database:
              host: localhost
              port: 5432
              name: mydb
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "database.host", path])
        assert stdout.strip() == "localhost"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "database.port", path])
        assert stdout.strip() == "5432"
        os.unlink(path)

        # Nested fslash
        path = write_yaml(
            """\
            a:
              b:
                c: deep_value
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "/a/b/c", path])
        assert stdout.strip() == "deep_value"
        os.unlink(path)

        # Array element
        path = write_yaml(
            """\
            fruits:
              - apple
              - banana
              - cherry
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "fruits[1]", path])
        assert stdout.strip() == "banana"
        os.unlink(path)

        # Boolean
        path = write_yaml(
            """\
            flags:
              enabled: true
              disabled: false
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "flags.enabled", path])
        assert stdout.strip().lower() == "true"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "flags.disabled", path])
        assert stdout.strip().lower() == "false"
        os.unlink(path)

        # Null
        path = write_yaml(
            """\
            empty: null
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "empty", path])
        assert stdout.strip() == "\x00"
        os.unlink(path)

        # Stdin
        yaml_content = "greeting: hello\n"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "greeting"], input_data=yaml_content)
        assert stdout.strip() == "hello"

    def test_get_complex_and_json_output(self):
        """Bundle: complex node JSON, array JSON, nested complex, !!set, deeply nested, empty string."""
        # Complex node returns JSON
        path = write_yaml(
            """\
            config:
              settings:
                debug: true
                level: 3
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config.settings", path])
        data = json.loads(stdout.strip())
        assert data["debug"] is True
        assert data["level"] == 3
        os.unlink(path)

        # Array returns JSON array
        path = write_yaml(
            """\
            items:
              - 10
              - 20
              - 30
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", path])
        data = json.loads(stdout.strip())
        assert data == [10, 20, 30]
        os.unlink(path)

        # Nested complex node
        path = write_yaml(
            """\
            outer:
              inner:
                list:
                  - a
                  - b
                map:
                  x: 1
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "outer.inner", path])
        data = json.loads(stdout.strip())
        assert data["list"] == ["a", "b"]
        assert data["map"]["x"] == 1
        os.unlink(path)

        # !!set returns JSON dict
        path = write_yaml("tags: !!set\n  python: null\n  java: null\n  rust: null\n")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "tags", path])
        data = json.loads(stdout.strip())
        assert isinstance(data, dict)
        assert sorted(data.keys()) == ["java", "python", "rust"]
        for v in data.values():
            assert v is None
        os.unlink(path)

        # Deeply nested (5+ levels)
        path = write_yaml(
            """\
            l1:
              l2:
                l3:
                  l4:
                    l5: deepvalue
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "l1.l2.l3.l4.l5", path])
        assert stdout.strip() == "deepvalue"
        os.unlink(path)

        path2 = write_yaml(
            "a:\n  b:\n    c:\n      d:\n        e:\n          f: very_deep\n"
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a.b.c.d.e.f", path2])
        assert stdout.strip() == "very_deep"
        os.unlink(path2)

        path3 = write_yaml(
            """\
            root:
              config:
                env:
                  production:
                    replicas: 3
                    memory: 4096
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "root.config.env.production", path3])
        data = json.loads(stdout.strip())
        assert data["replicas"] == 3
        assert data["memory"] == 4096
        os.unlink(path3)

        # Empty string value
        path = write_yaml(
            """\
            empty_str: ""
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "empty_str", path])
        assert stdout.strip() == ""
        os.unlink(path)

    def test_get_output_formats(self):
        """Bundle: date, timestamp, timezone, literal, folded, null byte."""
        # Date ISO format
        path = write_yaml(
            """\
            birthday: 2023-06-15
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "birthday", path])
        assert stdout.strip() == "2023-06-15"
        os.unlink(path)

        # Timestamp ISO format
        path = write_yaml(
            """\
            event_time: 2023-06-15T10:30:00
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "event_time", path])
        assert stdout.strip() == "2023-06-15T10:30:00"
        os.unlink(path)

        # Timestamp with timezone
        path = write_yaml(
            """\
            event: 2023-06-15T10:30:00+05:30
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "event", path])
        assert "+05:30" in stdout.strip()
        assert "2023-06-15" in stdout.strip()
        os.unlink(path)

        # Literal multiline
        path = write_yaml("msg: |\n  line1\n  line2\n  line3\n")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "msg", path])
        assert r"line1\nline2\nline3" in stdout
        os.unlink(path)

        # Folded multiline
        path = write_yaml("msg: >\n  line1\n  line2\n  line3\n")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "msg", path])
        assert "line1 line2 line3" in stdout
        os.unlink(path)

        # Null outputs NUL byte
        path = write_yaml(
            """\
            empty: null
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "empty", path])
        assert stdout.strip() == "\x00"
        os.unlink(path)

    def test_get_nonexistent_path_fails(self):
        path = write_yaml(
            """\
            key: value
        """
        )
        _, _, rc = run_cmd(["yaml-get", "-p", "nonexistent", path], expect_fail=True)
        assert rc != 0
        os.unlink(path)

    def test_get_on_empty_yaml_returns_no_output(self):
        """yaml-get on an empty YAML file returns no output (no data to read)."""
        path = write_yaml("")
        stdout, _, rc = run_cmd(["yaml-get", "-p", "any.key", path])
        # Empty file has no data, so no output is produced
        assert stdout.strip() == ""
        os.unlink(path)


# ===========================================================================
# yaml-set: basic value mutation (Group 2: 15 -> 3)
# ===========================================================================
class TestYamlSet:
    def test_set_basic_ops(self):
        """Bundle: scalar set, create new path, null, backup, delete, dquote, check old, deeply nested delete, empty string."""
        # Set scalar
        path = write_yaml(
            """\
            database:
              host: localhost
        """
        )
        run_cmd(["yaml-set", "-g", "database.host", "-a", "remotehost", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "database.host", path])
        assert stdout.strip() == "remotehost"
        os.unlink(path)

        # Creates new path
        path = write_yaml(
            """\
            existing: value
        """
        )
        run_cmd(["yaml-set", "-g", "new.nested.key", "-a", "created", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "new.nested.key", path])
        assert stdout.strip() == "created"
        os.unlink(path)

        # Null value
        path = write_yaml(
            """\
            key: something
        """
        )
        run_cmd(["yaml-set", "-g", "key", "-N", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path])
        assert stdout.strip() == "\x00"
        os.unlink(path)

        # Backup
        path = write_yaml(
            """\
            key: original
        """
        )
        run_cmd(["yaml-set", "-g", "key", "-a", "changed", "-b", path])
        assert os.path.exists(path + ".bak")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path])
        assert stdout.strip() == "changed"
        os.unlink(path)
        os.unlink(path + ".bak")

        # Delete node
        path = write_yaml(
            """\
            keep: yes
            remove: me
        """
        )
        run_cmd(["yaml-set", "-g", "remove", "-D", path])
        _, _, rc = run_cmd(["yaml-get", "-p", "remove", path], expect_fail=True)
        assert rc != 0
        stdout, _, _ = run_cmd(["yaml-get", "-p", "keep", path])
        assert stdout.strip() == "yes"
        os.unlink(path)

        # Format dquote
        path = write_yaml(
            """\
            key: value
        """
        )
        run_cmd(["yaml-set", "-g", "key", "-a", "quoted", "-F", "dquote", path])
        with open(path) as f:
            content = f.read()
        assert '"quoted"' in content
        os.unlink(path)

        # Check old value
        path = write_yaml(
            """\
            key: original
        """
        )
        run_cmd(["yaml-set", "-g", "key", "-a", "new", "-c", "original", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path])
        assert stdout.strip() == "new"
        os.unlink(path)

        # Delete deeply nested path
        path = write_yaml(
            """\
            root:
              level1:
                level2:
                  keep: important
                  remove: unneeded
                  also_keep: valuable
                sibling_key: yes
        """
        )
        run_cmd(["yaml-set", "-g", "root.level1.level2.remove", "-D", path])
        _, _, rc = run_cmd(
            ["yaml-get", "-p", "root.level1.level2.remove", path], expect_fail=True
        )
        assert rc != 0
        stdout, _, _ = run_cmd(["yaml-get", "-p", "root.level1.level2.keep", path])
        assert stdout.strip() == "important"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "root.level1.level2.also_keep", path])
        assert stdout.strip() == "valuable"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "root.level1.sibling_key", path])
        assert stdout.strip() == "yes"
        os.unlink(path)

        # Empty string value
        path = write_yaml(
            """\
            key: notempty
        """
        )
        run_cmd(["yaml-set", "-g", "key", "-a", "", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path])
        assert stdout.strip() == ""
        os.unlink(path)

    def test_set_input_modes(self):
        """Bundle: set value from file (single+multi), stdin (single+multi), random (default+custom)."""
        # From file - single-line
        val_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        val_file.write("value_from_file\n\n")
        val_file.close()
        path = write_yaml("key: placeholder\n")
        run_cmd(["yaml-set", "-g", "key", "-f", val_file.name, path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path])
        assert stdout.strip() == "value_from_file"
        os.unlink(path)
        os.unlink(val_file.name)

        # From file - multiline
        val_file2 = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        val_file2.write("line1\nline2\nline3\n")
        val_file2.close()
        path2 = write_yaml("key: placeholder\n")
        run_cmd(["yaml-set", "-g", "key", "-f", val_file2.name, path2])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", path2])
        assert "line1" in stdout
        assert "line2" in stdout
        assert "line3" in stdout
        os.unlink(path2)
        os.unlink(val_file2.name)

        # From stdin - single-line
        path = write_yaml(
            """\
            secret: placeholder
        """
        )
        run_cmd(
            ["yaml-set", "-g", "secret", "-i", path],
            input_data="stdin_secret_value",
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "secret", path])
        assert stdout.strip() == "stdin_secret_value"
        os.unlink(path)

        # From stdin - multiline
        path2 = write_yaml("content: placeholder\n")
        run_cmd(
            ["yaml-set", "-g", "content", "-i", path2],
            input_data="line1\nline2\nline3",
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "content", path2])
        assert "line1" in stdout
        assert "line2" in stdout
        assert "line3" in stdout
        os.unlink(path2)

        # Random - default
        path = write_yaml(
            """\
            secret: placeholder
        """
        )
        run_cmd(["yaml-set", "-g", "secret", "-R", "16", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "secret", path])
        val = stdout.strip()
        assert len(val) == 16
        assert val != "placeholder"
        os.unlink(path)

        # Random - custom charset (AB only)
        path2 = write_yaml("token: placeholder\n")
        run_cmd(["yaml-set", "-g", "token", "-R", "20", "-M", "AB", path2])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "token", path2])
        val2 = stdout.strip()
        assert len(val2) == 20
        assert set(val2).issubset({"A", "B"})
        os.unlink(path2)

        # Random - digits only
        path3 = write_yaml("code: placeholder\n")
        run_cmd(["yaml-set", "-g", "code", "-R", "12", "-M", "0123456789", path3])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "code", path3])
        val3 = stdout.strip()
        assert len(val3) == 12
        assert val3.isdigit()
        os.unlink(path3)

    def test_set_format_and_saveto(self):
        """Bundle: squote/folded/literal formats, saveto preserves old, saveto nested source."""
        # squote
        path_sq = write_yaml("key: value\n")
        run_cmd(["yaml-set", "-g", "key", "-a", "quoted", "-F", "squote", path_sq])
        with open(path_sq) as f:
            assert "'quoted'" in f.read()
        os.unlink(path_sq)

        # folded (>)
        path_f = write_yaml("message: hello\n")
        run_cmd(
            [
                "yaml-set",
                "-g",
                "message",
                "-a",
                "this is a long folded value",
                "-F",
                "folded",
                path_f,
            ]
        )
        with open(path_f) as f:
            assert ">" in f.read()
        os.unlink(path_f)

        # literal (|)
        path_l = write_yaml("script: echo hi\n")
        run_cmd(
            [
                "yaml-set",
                "-g",
                "script",
                "-a",
                "echo hello\\necho world",
                "-F",
                "literal",
                path_l,
            ]
        )
        with open(path_l) as f:
            assert "|" in f.read()
        os.unlink(path_l)

        # saveto preserves old value
        path = write_yaml(
            """\
            current: old_val
            backup_slot: placeholder
        """
        )
        run_cmd(
            [
                "yaml-set",
                "-g",
                "current",
                "-a",
                "new_val",
                "-s",
                "backup_slot",
                path,
            ]
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "current", path])
        assert stdout.strip() == "new_val"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "backup_slot", path])
        assert stdout.strip() == "old_val"
        os.unlink(path)

        # saveto with nested source path
        path = write_yaml(
            """\
            config:
              db:
                host: prod-server
                port: 5432
            backup_host: placeholder
        """
        )
        run_cmd(
            [
                "yaml-set",
                "-g",
                "config.db.host",
                "-a",
                "new-server",
                "-s",
                "backup_host",
                path,
            ]
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config.db.host", path])
        assert stdout.strip() == "new-server"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "backup_host", path])
        assert stdout.strip() == "prod-server"
        os.unlink(path)

    def test_set_with_mustexist_fails_on_missing(self):
        path = write_yaml(
            """\
            key: value
        """
        )
        _, _, rc = run_cmd(
            ["yaml-set", "-g", "nonexistent", "-a", "val", "-m", path],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)

    def test_set_check_wrong_value_fails(self):
        path = write_yaml(
            """\
            key: actual
        """
        )
        _, _, rc = run_cmd(
            ["yaml-set", "-g", "key", "-a", "new", "-c", "wrong", path],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)


# ===========================================================================
# yaml-paths: search for paths matching expressions
# ===========================================================================
class TestYamlPaths:
    def test_search_exact_match(self):
        path = write_yaml(
            """\
            users:
              - name: alice
                role: admin
              - name: bob
                role: user
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=alice", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the alice value matches the `=` exact-match operator; bob does not.
        assert lines == ["users[0].name"]
        os.unlink(path)

    def test_search_contains(self):
        path = write_yaml(
            """\
            items:
              - description: red car
              - description: blue truck
              - description: red bike
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "%red", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two "red" descriptions match; the "blue truck" at items[1] does not.
        assert lines == ["items[0].description", "items[2].description"]
        os.unlink(path)

    def test_search_starts_with(self):
        path = write_yaml(
            """\
            words:
              - prefix_one
              - prefix_two
              - other
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "^prefix", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two "prefix_*" values match; "other" at words[2] does not.
        assert lines == ["words[0]", "words[1]"]
        os.unlink(path)

    def test_search_key_names(self):
        path = write_yaml(
            """\
            config:
              database_host: localhost
              database_port: 5432
              cache_host: redis
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "^database", "-K", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two "database_*" keys match; "cache_host" is excluded.
        assert lines == ["config.database_host", "config.database_port"]
        os.unlink(path)

    def test_search_regex(self):
        path = write_yaml(
            """\
            entries:
              - code: AB-123
              - code: CD-456
              - code: AB-789
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=~/^AB-/", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two "AB-*" codes match; "CD-456" at entries[1] is excluded.
        assert lines == ["entries[0].code", "entries[2].code"]
        os.unlink(path)

    def test_search_with_except(self):
        path = write_yaml(
            """\
            items:
              - name: apple
              - name: apricot
              - name: banana
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "^ap", "-c", "=apricot", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # `^ap` matches apple and apricot; `-c =apricot` excepts apricot, leaving
        # exactly the apple element. banana never matched. The except must not
        # over-remove (apple stays) nor under-remove (apricot gone).
        assert lines == ["items[0].name"]
        assert "apricot" not in stdout
        os.unlink(path)

    def test_search_empty_result_no_error(self):
        """Search that matches nothing returns empty, not error (via yaml-paths CLI)."""
        path = write_yaml(
            """\
            items:
              - name: alpha
              - name: beta
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=nonexistent", path])
        lines = [l for l in stdout.strip().splitlines() if l.strip()]
        assert len(lines) == 0
        os.unlink(path)


# ===========================================================================
# yaml-validate: file validation (Group 15: 3 happy-path -> 1)
# ===========================================================================
class TestYamlValidate:
    def test_validate_happy_paths(self):
        """Bundle: valid yaml, valid json, empty file, deeply nested."""
        # Valid YAML
        path = write_yaml(
            """\
            key: value
            list:
              - one
              - two
        """
        )
        _, _, rc = run_cmd(["yaml-validate", path])
        assert rc == 0
        os.unlink(path)

        # Valid JSON
        path = write_yaml('{"key": "value", "list": [1, 2, 3]}', suffix=".json")
        _, _, rc = run_cmd(["yaml-validate", path])
        assert rc == 0
        os.unlink(path)

        # Empty file
        path_empty = write_yaml("")
        _, _, rc = run_cmd(["yaml-validate", path_empty])
        assert rc == 0
        os.unlink(path_empty)

        # Deeply nested
        path_deep = write_yaml(
            """\
            a:
              b:
                c:
                  d:
                    e:
                      f: value
                      list:
                        - 1
                        - 2
        """
        )
        _, _, rc = run_cmd(["yaml-validate", path_deep])
        assert rc == 0
        os.unlink(path_deep)

    def test_invalid_yaml_fails(self):
        path = write_yaml(
            """\
            key: value
              bad indent: here
            another: key
        """
        )
        _, _, rc = run_cmd(["yaml-validate", path], expect_fail=True)
        assert rc != 0
        os.unlink(path)


# ===========================================================================
# yaml-merge: merging documents (Group 7: 10 -> 3, Group 8: 5 -> 2)
# ===========================================================================
class TestYamlMerge:
    def test_merge_basic_and_hashes(self):
        """Bundle: merge two files, hashes left, hashes right, to stdout, overwrite with backup."""
        # Merge two files
        lhs = write_yaml(
            """\
            base:
              host: localhost
              port: 3000
        """
        )
        rhs = write_yaml(
            """\
            base:
              port: 8080
              debug: true
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "base.port", out])
        assert stdout.strip() == "8080"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "base.host", out])
        assert stdout.strip() == "localhost"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "base.debug", out])
        assert stdout.strip().lower() == "true"
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Hashes left
        lhs = write_yaml(
            """\
            config:
              a: 1
              b: 2
        """
        )
        rhs = write_yaml(
            """\
            config:
              b: 99
              c: 3
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-H", "left", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config.b", out])
        assert stdout.strip() == "2"
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Hashes right
        lhs = write_yaml(
            """\
            config:
              a: 1
              b: 2
        """
        )
        rhs = write_yaml(
            """\
            config:
              b: 99
              c: 3
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-H", "right", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config.b", out])
        assert stdout.strip() == "99"
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # To stdout
        lhs = write_yaml(
            """\
            a: 1
        """
        )
        rhs = write_yaml(
            """\
            b: 2
        """
        )
        stdout, _, _ = run_cmd(["yaml-merge", "-S", lhs, rhs])
        # `a`/`b` are the merged key NAMES, so substring presence alone does not
        # prove the values survived the merge. Round-trip the stdout YAML through
        # yaml-get to confirm the mapping is {a: 1, b: 2} (matching how the other
        # sub-cases above verify merged values).
        merged = write_yaml(stdout)
        val_a, _, _ = run_cmd(["yaml-get", "-p", "a", merged])
        assert val_a.strip() == "1"
        val_b, _, _ = run_cmd(["yaml-get", "-p", "b", merged])
        assert val_b.strip() == "2"
        os.unlink(merged)
        os.unlink(lhs)
        os.unlink(rhs)

        # Overwrite with backup
        lhs = write_yaml(
            """\
            key: original
        """
        )
        rhs = write_yaml(
            """\
            key: changed
        """
        )
        run_cmd(["yaml-merge", "-S", "-w", lhs, "-b", lhs, rhs])
        assert os.path.exists(lhs + ".bak")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", lhs])
        assert stdout.strip() == "changed"
        os.unlink(lhs)
        os.unlink(lhs + ".bak")
        os.unlink(rhs)

    def test_merge_array_modes(self):
        """Bundle: arrays all, arrays unique, arrays left and right."""
        # Arrays all
        lhs = write_yaml(
            """\
            items:
              - one
              - two
        """
        )
        rhs = write_yaml(
            """\
            items:
              - three
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-A", "all", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        data = json.loads(stdout.strip())
        assert "one" in data
        assert "two" in data
        assert "three" in data
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Arrays unique
        lhs = write_yaml(
            """\
            items:
              - one
              - two
        """
        )
        rhs = write_yaml(
            """\
            items:
              - two
              - three
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-A", "unique", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        data = json.loads(stdout.strip())
        assert data.count("two") == 1
        assert "three" in data
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Arrays left and right
        lhs = write_yaml("items:\n  - a\n  - b\n")
        rhs = write_yaml("items:\n  - c\n  - d\n")
        out_l = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out_l)
        run_cmd(["yaml-merge", "-S", "-A", "left", "-o", out_l, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out_l])
        assert json.loads(stdout.strip()) == ["a", "b"]
        out_r = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out_r)
        run_cmd(["yaml-merge", "-S", "-A", "right", "-o", out_r, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out_r])
        assert json.loads(stdout.strip()) == ["c", "d"]
        for f in [lhs, rhs, out_l, out_r]:
            os.unlink(f)

    def test_merge_format_and_comments(self):
        """Bundle: force JSON output, preserve LHS comments."""
        # Force JSON output
        lhs = write_yaml(
            """\
            key: value
        """
        )
        rhs = write_yaml(
            """\
            other: data
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-D", "json", "-o", out, lhs, rhs])
        with open(out) as f:
            data = json.load(f)
        assert data["key"] == "value"
        assert data["other"] == "data"
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Preserve LHS comments
        lhs = write_yaml(
            """\
            # This is a comment
            key: original
        """
        )
        rhs = write_yaml(
            """\
            key: updated
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-l", "-o", out, lhs, rhs])
        with open(out) as f:
            content = f.read()
        # -l preserves the LHS comment verbatim; without it the comment is dropped.
        assert "# This is a comment" in content
        stdout, _, _ = run_cmd(["yaml-get", "-p", "key", out])
        assert stdout.strip() == "updated"
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_multi_file(self):
        """Bundle: three files sequential, four files cascading, yaml sets."""
        # Three files
        f1 = write_yaml(
            """\
            a: 1
            b: 2
        """
        )
        f2 = write_yaml(
            """\
            b: 20
            c: 3
        """
        )
        f3 = write_yaml(
            """\
            c: 30
            d: 4
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-o", out, f1, f2, f3])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a", out])
        assert stdout.strip() == "1"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "b", out])
        assert stdout.strip() == "20"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "c", out])
        assert stdout.strip() == "30"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "d", out])
        assert stdout.strip() == "4"
        for f in [f1, f2, f3, out]:
            os.unlink(f)

        # Four files cascading
        f1 = write_yaml("a: 1\nb: 2\nc: 3\nd: 4\n")
        f2 = write_yaml("b: 20\n")
        f3 = write_yaml("c: 300\n")
        f4 = write_yaml("d: 4000\ne: 5\n")
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-o", out, f1, f2, f3, f4])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a", out])
        assert stdout.strip() == "1"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "b", out])
        assert stdout.strip() == "20"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "c", out])
        assert stdout.strip() == "300"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "d", out])
        assert stdout.strip() == "4000"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "e", out])
        assert stdout.strip() == "5"
        for f in [f1, f2, f3, f4, out]:
            os.unlink(f)

        # Merge yaml sets
        lhs = write_yaml("tags: !!set\n  python: null\n  java: null\n")
        rhs = write_yaml("tags: !!set\n  java: null\n  rust: null\n")
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-o", out, lhs, rhs])
        with open(out) as f:
            content = f.read()
        assert "python" in content
        assert "java" in content
        assert "rust" in content
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_anchor_conflicts(self):
        """Bundle: anchors rename, anchors left."""
        # Rename
        lhs = write_yaml(
            """\
            defaults: &shared
              key: lhs_value
            use_lhs:
              <<: *shared
        """
        )
        rhs = write_yaml(
            """\
            overrides: &shared
              key: rhs_value
            use_rhs:
              <<: *shared
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-a", "rename", "-o", out, lhs, rhs])
        with open(out) as f:
            content = f.read()
        assert "lhs_value" in content
        assert "rhs_value" in content
        for f in [lhs, rhs, out]:
            os.unlink(f)

        # Left
        lhs = write_yaml(
            """\
            a: &dup
              val: left
        """
        )
        rhs = write_yaml(
            """\
            b: &dup
              val: right
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-a", "left", "-o", out, lhs, rhs])
        # Both anchored mapping bodies must survive intact. With anchor mode "left",
        # the LHS `&dup` wins the name clash and the RHS occurrence resolves to it,
        # so both `a.val` and `b.val` read back as the LHS value.
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a.val", out])
        assert stdout.strip() == "left"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "b.val", out])
        assert stdout.strip() == "left"
        for f in [lhs, rhs, out]:
            os.unlink(f)


# ===========================================================================
# yaml-diff: comparing documents (Group 3: 5 -> 1)
# ===========================================================================
class TestYamlDiff:
    def test_diff_basic(self):
        """Bundle: identical, different, additions, deletions, same/onlysame flags."""
        # Identical
        content = """\
            key: value
            list:
              - one
        """
        f1 = write_yaml(content)
        f2 = write_yaml(content)
        _, _, rc = run_cmd(["yaml-diff", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)

        # Different
        f1 = write_yaml(
            """\
            key: value1
        """
        )
        f2 = write_yaml(
            """\
            key: value2
        """
        )
        _, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        os.unlink(f1)
        os.unlink(f2)

        # Additions
        f1 = write_yaml(
            """\
            a: 1
        """
        )
        f2 = write_yaml(
            """\
            a: 1
            b: 2
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        # yaml-diff prefixes each line with an action marker ('a' add, 'd' delete,
        # 'c' change, 's' same). Merely finding `b` in the output re-checks the key
        # name, not the computed classification, so assert the ADD marker: the new
        # key `b` is reported on a line starting with `a `.
        assert any(
            line.startswith("a ") and line.split()[1] == "b"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

        # Deletions
        f1 = write_yaml(
            """\
            a: 1
            b: 2
        """
        )
        f2 = write_yaml(
            """\
            a: 1
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        # Symmetric to Additions: the removed key `b` must be reported as a DELETE,
        # i.e. on a line starting with `d ` (not the same marker as the add case).
        assert any(
            line.startswith("d ") and line.split()[1] == "b"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

        # --same and --onlysame flags
        f1 = write_yaml(
            """\
            same_key: same_val
            diff_key: old_val
            another_same: 42
        """
        )
        f2 = write_yaml(
            """\
            same_key: same_val
            diff_key: new_val
            another_same: 42
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", "-s", f1, f2], expect_fail=True)
        assert rc == 1
        assert "same_key" in stdout
        assert "diff_key" in stdout
        stdout_o, _, rc_o = run_cmd(["yaml-diff", "-o", f1, f2], expect_fail=True)
        assert rc_o == 1
        # --onlysame reports ONLY the unchanged nodes: both `same_key` and
        # `another_same` appear, while the changed `diff_key` must be absent.
        assert "same_key" in stdout_o
        assert "another_same" in stdout_o
        assert "diff_key" not in stdout_o
        os.unlink(f1)
        os.unlink(f2)


# ===========================================================================
# Diff CLI modes
# ===========================================================================
class TestDiffCLIModes:
    def test_array_and_aoh_modes(self):
        """Bundle: aoh deep, aoh value, aoh key, arrays by position, arrays by value."""
        # AoH deep
        f1 = write_yaml(
            """\
            users:
              - name: alice
                role: user
              - name: bob
                role: admin
        """
        )
        f2 = write_yaml(
            """\
            users:
              - name: alice
                role: admin
              - name: bob
                role: admin
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", "-O", "deep", f1, f2], expect_fail=True)
        assert rc == 1
        # AoH deep matches records by identity key (default: first key `name`) and
        # diffs their fields, so alice's flipped role surfaces as a CHANGE on her
        # role path. Substring presence of `alice`/`role` (both are fixture names)
        # would pass a misclassifying differ; assert the concrete `c <path>` marker.
        assert any(
            line.startswith("c ") and line.split()[1] == "users[0].role"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

        # AoH value mode
        f1 = write_yaml(
            """\
            items:
              - name: a
                val: 1
              - name: b
                val: 2
        """
        )
        f2 = write_yaml(
            """\
            items:
              - name: b
                val: 2
              - name: a
                val: 1
        """
        )
        _, _, rc = run_cmd(["yaml-diff", "-O", "value", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)

        # AoH key mode
        f1 = write_yaml(
            """\
            users:
              - name: alice
                score: 10
              - name: bob
                score: 20
        """
        )
        f2 = write_yaml(
            """\
            users:
              - name: bob
                score: 30
              - name: alice
                score: 10
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", "-O", "key", f1, f2], expect_fail=True)
        assert rc == 1
        # AoH key mode pairs records by identity key (default: first key `name`)
        # regardless of their order, so alice's unchanged record is NOT reported and
        # bob's record (score 20 -> 30) is the sole CHANGE, reported on its index
        # path. Substring presence of `bob`/`score` (fixture names present in both
        # docs) would pass a wrong-shaped differ; assert the concrete `c <path>`.
        assert any(
            line.startswith("c ") and line.split()[1] == "users[1]"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

        # Arrays by position
        f1 = write_yaml(
            """\
            items:
              - a
              - b
        """
        )
        f2 = write_yaml(
            """\
            items:
              - b
              - a
        """
        )
        _, _, rc = run_cmd(["yaml-diff", "-A", "position", f1, f2], expect_fail=True)
        assert rc == 1
        os.unlink(f1)
        os.unlink(f2)

        # Arrays by value
        f1 = write_yaml(
            """\
            items:
              - a
              - b
              - c
        """
        )
        f2 = write_yaml(
            """\
            items:
              - b
              - c
              - a
        """
        )
        _, _, rc = run_cmd(["yaml-diff", "-A", "value", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)

    def test_nested_structures(self):
        """Bundle: nested hash change, nested array change."""
        # Nested hash change
        f1 = write_yaml(
            """\
            config:
              database:
                host: localhost
                port: 5432
        """
        )
        f2 = write_yaml(
            """\
            config:
              database:
                host: remotehost
                port: 5432
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        # Only the leaf scalar `config.database.host` changed; `host`/`database`/
        # `config` are fixture key names, so substring presence re-checks the input
        # rather than the classification. Assert the exact CHANGE line so a differ
        # that misclassifies the leaf (or reports the wrong path) is caught.
        assert any(
            line.startswith("c ") and line.split()[1] == "config.database.host"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

        # Nested array change
        f1 = write_yaml(
            """\
            servers:
              production:
                - web1
                - web2
        """
        )
        f2 = write_yaml(
            """\
            servers:
              production:
                - web1
                - web3
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        # The changed element is the second array item; default position array mode
        # reports it as a CHANGE on its index path. Assert the concrete marker
        # rather than only rc==1 so the element-wise classification is verified.
        assert any(
            line.startswith("c ") and line.split()[1] == "servers.production[1]"
            for line in stdout.splitlines()
        )
        os.unlink(f1)
        os.unlink(f2)

    def test_multidoc_and_ini(self):
        """Bundle: select subdocument, specific subdocs different, diff INI config."""
        # Select subdocument
        f1 = write_yaml(
            """\
            doc0_key: val0
            ---
            doc1_key: val1
        """
        )
        f2 = write_yaml(
            """\
            doc0_key: val0
        """
        )
        _, _, rc = run_cmd(["yaml-diff", "-L", "0", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)

        # Specific subdocs different
        f1 = write_yaml("doc0: val0\n---\ndoc1: val1\n---\ndoc2: val2\n")
        f2 = write_yaml("doc0: val0\n---\ndoc1: changed\n---\ndoc2: val2\n")
        stdout, _, rc = run_cmd(
            ["yaml-diff", "-L", "1", "-R", "1", f1, f2], expect_fail=True
        )
        assert rc == 1
        assert "doc1" in stdout
        _, _, rc = run_cmd(["yaml-diff", "-L", "2", "-R", "2", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)

        # Diff INI config value mode per path
        f1 = write_yaml(
            """\
            items:
              - a
              - b
            config:
              x: 1
        """
        )
        f2 = write_yaml(
            """\
            items:
              - b
              - a
            config:
              x: 2
        """
        )
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False)
        cfg.write("[rules]\nitems = value\n")
        cfg.close()
        stdout, _, rc = run_cmd(["yaml-diff", "-c", cfg.name, f1, f2], expect_fail=True)
        assert rc == 1
        # The `items = value` rule makes the reordered `items` array compare equal
        # (order-insensitive), so the only difference is `config.x` (1 -> 2), reported
        # as a single `c config.x` change line. Assert that concrete marker rather than
        # a near-vacuous substring disjunct.
        assert any(
            line.startswith("c ") and line.split()[1] == "config.x"
            for line in stdout.splitlines()
        )
        for f in [f1, f2, cfg.name]:
            os.unlink(f)


# ===========================================================================
# Diff type changes (converted from API TestDifferTypeChanges)
# ===========================================================================
class TestDiffTypeChanges:
    def test_diff_type_changes_reported_as_delete_add(self):
        """A node whose type changes is reported as DELETE of the old + ADD of the new.

        Covers both scalar->hash and hash->array transitions in one test: each is a
        type change (not a CHANGE), so the old node is removed (`d` line) and the
        new node's leaves are added (`a` lines). Asserting these distinct markers —
        rather than only `rc == 1` or mere key-name presence — verifies the differ
        actually classifies the type change correctly instead of just noticing that
        the two documents differ at all.
        """
        # Scalar -> hash: the scalar `key` is deleted, the new nested leaf is added.
        f1 = write_yaml("key: simple_value\n")
        f2 = write_yaml("key:\n  nested: value\n")
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        lines = stdout.splitlines()
        assert any(line.startswith("d ") and line.split()[1] == "key" for line in lines)
        assert any(line.startswith("a ") and line.split()[1] == "key.nested" for line in lines)
        os.unlink(f1)
        os.unlink(f2)

        # Hash -> array: the hash `key` is deleted, the new array elements are added.
        f1 = write_yaml("key:\n  a: 1\n")
        f2 = write_yaml("key:\n  - item1\n  - item2\n")
        stdout, _, rc = run_cmd(["yaml-diff", f1, f2], expect_fail=True)
        assert rc == 1
        lines = stdout.splitlines()
        assert any(line.startswith("d ") and line.split()[1] == "key.a" for line in lines)
        assert any(line.startswith("a ") and line.split()[1] == "key[0]" for line in lines)
        assert any(line.startswith("a ") and line.split()[1] == "key[1]" for line in lines)
        os.unlink(f1)
        os.unlink(f2)

    def test_diff_deeply_nested_mixed(self):
        """Deeply nested diffs are detected correctly."""
        f1 = write_yaml(
            """\
            root:
              a:
                deep:
                  same: unchanged
                  diff: old
              b:
                deep:
                  same: unchanged
                  diff: also_old
        """
        )
        f2 = write_yaml(
            """\
            root:
              a:
                deep:
                  same: unchanged
                  diff: new
              b:
                deep:
                  same: unchanged
                  diff: also_new
        """
        )
        stdout, _, rc = run_cmd(["yaml-diff", "-s", f1, f2], expect_fail=True)
        assert rc == 1
        # The two scalar leaves named `diff` changed and the two named `same` did
        # not. `"diff"`/`"same"` are fixture key names, so substring presence alone
        # does not verify the classification; assert the changed leaves carry the
        # CHANGE marker (`c <path>.diff`) and the unchanged ones the SAME marker
        # (`s <path>.same`, emitted only because of `-s`).
        lines = stdout.splitlines()
        assert any(line.startswith("c ") and line.split()[1].endswith(".diff") for line in lines)
        assert any(line.startswith("s ") and line.split()[1].endswith(".same") for line in lines)
        os.unlink(f1)
        os.unlink(f2)

    def test_diff_arrays_with_mixed_types(self):
        """Per-element scalar changes in an array, plus -s emitting unchanged elements.

        Distinct from the container type-change test: here every element stays a
        scalar, so each differing index is a CHANGE (`c items[i]`), and `-s` makes
        the unchanged `items[0]` surface as a SAME (`s items[0]`) line. Asserting
        both markers verifies element-wise change detection AND that `-s` actually
        emits unchanged nodes, rather than only that the documents differ.
        """
        f1 = write_yaml("items:\n  - 1\n  - two\n  - true\n")
        f2 = write_yaml("items:\n  - 1\n  - TWO\n  - false\n")
        stdout, _, rc = run_cmd(["yaml-diff", "-s", f1, f2], expect_fail=True)
        assert rc == 1
        lines = stdout.splitlines()
        # items[0] (value 1) is unchanged -> SAME line, present only because of -s.
        assert any(line.startswith("s ") and line.split()[1] == "items[0]" for line in lines)
        # items[1] (two -> TWO) changed -> CHANGE line.
        assert any(line.startswith("c ") and line.split()[1] == "items[1]" for line in lines)
        os.unlink(f1)
        os.unlink(f2)


# ===========================================================================
# Path expressions via CLI
# ===========================================================================
class TestComplexPathExpressions:
    def test_complex_paths(self):
        """Bundle: quoted key, wildcard in nested hash, deep traversal with wildcard."""
        # Quoted key
        path = write_yaml('"dotted.key": value1\nnormal_key: value2\n')
        stdout, _, _ = run_cmd(["yaml-get", "-p", "'dotted.key'", path])
        assert stdout.strip() == "value1"
        os.unlink(path)

        # Wildcard in nested hash
        path = write_yaml(
            """\
            services:
              web:
                port: 80
              api:
                port: 8080
              admin:
                port: 9090
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "services.*.port", path])
        # Wildcard with yaml-get produces multiple lines
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        values = sorted([int(l) for l in lines])
        assert values == [80, 8080, 9090]
        os.unlink(path)

        # Deep traversal
        path = write_yaml(
            """\
            level1:
              level2a:
                level3:
                  target: deep1
              level2b:
                target: deep2
            another:
              nested:
                deeply:
                  target: deep3
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "**.target", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        values = sorted(lines)
        assert values == ["deep1", "deep2", "deep3"]
        os.unlink(path)

    def test_separators(self):
        """Bundle: explicit dot and fslash separators, fslash with array index."""
        # Dot and fslash
        path = write_yaml(
            """\
            a:
              b: val
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a.b", "-t", "dot", path])
        assert stdout.strip() == "val"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "/a/b", "-t", "fslash", path])
        assert stdout.strip() == "val"
        os.unlink(path)

        # Fslash with array index
        path = write_yaml(
            """\
            data:
              items:
                - first
                - second
        """
        )
        stdout, _, _ = run_cmd(
            ["yaml-get", "-p", "/data/items[0]", "-t", "fslash", path]
        )
        assert stdout.strip() == "first"
        os.unlink(path)


# ===========================================================================
# Multi-doc (Group 16: 3 -> 1)
# ===========================================================================
class TestMultiDocAdvanced:
    def test_multidoc_ops(self):
        """Bundle: get from specific doc via paths, validate multi-doc, validate multiple files."""
        # Get from specific doc
        path = write_yaml(
            """\
            key1: findme
            ---
            key2: findme
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=findme", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        # Both documents match `=findme`, each path qualified by its source document
        # index (`<file>/0` for key1 in doc 0, `<file>/1` for key2 in doc 1). Assert
        # the exact set of two matches rather than a `>= 2` lower bound, which would
        # also pass duplicated or wrong-document results.
        assert len(lines) == 2
        assert any(l.endswith("/0: key1") for l in lines)
        assert any(l.endswith("/1: key2") for l in lines)
        os.unlink(path)

        # Validate multi-doc
        path = write_yaml(
            """\
            doc1: value1
            ---
            doc2: value2
            ---
            doc3: value3
        """
        )
        _, _, rc = run_cmd(["yaml-validate", path])
        assert rc == 0
        os.unlink(path)

        # Validate multiple files
        f1 = write_yaml(
            """\
            valid: yes
        """
        )
        f2 = write_yaml(
            """\
            also_valid: true
        """
        )
        _, _, rc = run_cmd(["yaml-validate", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)


# ===========================================================================
# CLI: yaml-set with --tag
# ===========================================================================
class TestYamlSetTag:
    def test_set_tag_alone_and_with_value(self):
        """--tag applies custom YAML tag, with or without --value."""
        path = write_yaml(
            """\
            data: value
        """
        )
        run_cmd(["yaml-set", "-g", "data", "-a", "tagged", "-T", "!custom", path])
        with open(path) as f:
            content = f.read()
        assert "!custom" in content
        os.unlink(path)

        path2 = write_yaml("data: old\n")
        run_cmd(["yaml-set", "-g", "data", "-a", "new_val", "-T", "!mytype", path2])
        with open(path2) as f:
            content2 = f.read()
        assert "!mytype" in content2
        stdout, _, _ = run_cmd(["yaml-get", "-p", "data", path2])
        assert stdout.strip() == "new_val"
        os.unlink(path2)


# ===========================================================================
# CLI: yaml-merge with merge-at
# ===========================================================================
class TestMergeAt:
    def test_merge_at_specific_path(self):
        lhs = write_yaml(
            """\
            outer:
              inner:
                keep: yes
        """
        )
        rhs = write_yaml(
            """\
            added: value
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-m", "outer.inner", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "outer.inner.added", out])
        assert stdout.strip() == "value"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "outer.inner.keep", out])
        assert stdout.strip() == "yes"
        for f in [lhs, rhs, out]:
            os.unlink(f)


# ===========================================================================
# CLI: Keyword searches (converted from API TestKeywordSearches/TestProcessorKeywords)
# ===========================================================================
class TestKeywordSearchesCLI:
    def test_has_child_keyword(self):
        """has_child(attr) filters to nodes with that child key."""
        path = write_yaml(
            """\
            items:
              - name: a
                extra: yes
              - name: b
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[has_child(extra)]", path])
        data = json.loads(stdout.strip())
        assert data["name"] == "a"
        assert data["extra"] == "yes"
        os.unlink(path)

    def test_max_keyword(self):
        """max(attr) selects the node with the maximum value of attr."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 90
              - val: 50
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "scores[max(val)]", path])
        data = json.loads(stdout.strip())
        assert data["val"] == 90
        os.unlink(path)

    def test_min_keyword(self):
        """min(attr) selects the node with the minimum value of attr."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 90
              - val: 50
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "scores[min(val)]", path])
        data = json.loads(stdout.strip())
        assert data["val"] == 10
        os.unlink(path)

    def test_name_keyword(self):
        """name() returns the key name itself."""
        path = write_yaml(
            """\
            config:
              database: postgres
              cache: redis
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config.database[name()]", path])
        assert stdout.strip() == "database"
        os.unlink(path)

    def test_parent_keyword(self):
        """parent() steps up to the parent node."""
        path = write_yaml(
            """\
            root:
              child:
                grandchild: value
        """
        )
        stdout, _, _ = run_cmd(
            ["yaml-get", "-p", "root.child.grandchild[parent()]", path]
        )
        data = json.loads(stdout.strip())
        # parent() of root.child.grandchild is the `child` node, whose full value
        # is the single-key mapping {"grandchild": "value"}.
        assert data == {"grandchild": "value"}
        os.unlink(path)

    def test_distinct_keyword(self):
        """distinct(attr) returns one record per unique value of attr."""
        path = write_yaml(
            """\
            records:
              - status: active
                name: a
              - status: inactive
                name: b
              - status: active
                name: c
              - status: pending
                name: d
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "records[distinct(status)]", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        # Should get 3 distinct status values
        statuses = []
        for line in lines:
            data = json.loads(line)
            statuses.append(data["status"])
        assert len(statuses) == 3
        assert set(statuses) == {"active", "inactive", "pending"}
        os.unlink(path)

    def test_unique_keyword(self):
        """unique(attr) returns only records whose attr value appears exactly once."""
        path = write_yaml(
            """\
            records:
              - status: active
                name: a
              - status: inactive
                name: b
              - status: active
                name: c
              - status: pending
                name: d
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "records[unique(status)]", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        statuses = []
        for line in lines:
            data = json.loads(line)
            statuses.append(data["status"])
        assert "active" not in statuses
        assert "inactive" in statuses
        assert "pending" in statuses
        assert len(statuses) == 2
        os.unlink(path)

    def test_has_child_inverted(self):
        """!has_child(attr) filters to nodes WITHOUT that child key."""
        path = write_yaml(
            """\
            items:
              - name: a
                optional: yes
              - name: b
              - name: c
                optional: no
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[!has_child(optional)]", path])
        data = json.loads(stdout.strip())
        assert data["name"] == "b"
        os.unlink(path)


# ===========================================================================
# CLI: Array slicing (converted from API TestArraySlicing)
# ===========================================================================
class TestArraySlicingCLI:
    def test_array_slice(self):
        """Array slice returns the half-open [start:stop) range, including a from-start slice."""
        path = write_yaml(
            """\
            items:
              - a
              - b
              - c
              - d
              - e
        """
        )
        # Mid-range slice.
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[1:3]", path])
        assert json.loads(stdout.strip()) == ["b", "c"]
        # From-start slice.
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[0:2]", path])
        assert json.loads(stdout.strip()) == ["a", "b"]
        os.unlink(path)


# ===========================================================================
# CLI: Search operators (converted from API TestSearchOperators/TestProcessorComplexSearches)
# ===========================================================================
class TestSearchOperatorsCLI:
    def test_ends_with_search(self):
        """$ operator finds values ending with a suffix."""
        path = write_yaml(
            """\
            items:
              - ext: file.txt
              - ext: file.yaml
              - ext: readme.txt
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "$txt", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two ".txt" values match; "file.yaml" at items[1] does not.
        assert lines == ["items[0].ext", "items[2].ext"]
        os.unlink(path)

    def test_greater_than_search(self):
        """> operator finds values strictly greater than threshold."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 50
              - val: 90
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", ">40", "-F", "-X", "-L", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # 50 and 90 exceed 40; 10 does not.
        assert lines == ["scores[1].val: 50", "scores[2].val: 90"]
        os.unlink(path)

    def test_less_than_search(self):
        """< operator finds values strictly less than threshold."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 50
              - val: 90
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "<60", "-F", "-X", "-L", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # 10 and 50 are below 60; 90 is not.
        assert lines == ["scores[0].val: 10", "scores[1].val: 50"]
        os.unlink(path)

    def test_greater_equal_search(self):
        """>= operator finds values greater than or equal to threshold (boundary included)."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 50
              - val: 50
              - val: 90
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", ">=50", "-F", "-X", "-L", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Both 50s (boundary) and the 90 match; 10 does not. A >-instead-of->= bug would drop the 50s.
        assert lines == ["scores[1].val: 50", "scores[2].val: 50", "scores[3].val: 90"]
        os.unlink(path)

    def test_less_equal_search(self):
        """<= operator finds values less than or equal to threshold (boundary included)."""
        path = write_yaml(
            """\
            scores:
              - val: 10
              - val: 50
              - val: 90
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "<=50", "-F", "-X", "-L", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # 10 and the boundary 50 match; 90 does not.
        assert lines == ["scores[0].val: 10", "scores[1].val: 50"]
        os.unlink(path)

    def test_inverted_search(self):
        """!= operator inverts the match."""
        path = write_yaml(
            """\
            users:
              - role: admin
              - role: user
              - role: user
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "!=admin", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only the two non-admin "user" roles match; the "admin" at users[0] is excluded.
        assert lines == ["users[1].role", "users[2].role"]
        os.unlink(path)

    def test_search_with_chained_aoh(self):
        """Search expression on AoH filters correctly via yaml-get."""
        path = write_yaml(
            """\
            users:
              - name: alice
                role: admin
                level: 5
              - name: bob
                role: user
                level: 3
              - name: carol
                role: admin
                level: 4
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "users[role=admin].name", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        names = sorted(lines)
        assert names == ["alice", "carol"]
        os.unlink(path)

    def test_dot_match_in_array(self):
        """[.=value] matches element values directly in arrays."""
        path = write_yaml(
            """\
            tags:
              - python
              - java
              - rust
              - python
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=python", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Both "python" elements match; "java"/"rust" do not.
        assert lines == ["tags[0]", "tags[3]"]
        os.unlink(path)


# ===========================================================================
# CLI: Negative array index
# ===========================================================================
class TestNegativeArrayIndex:
    def test_negative_index_resolves_last_element(self):
        """A negative index `[-1]` resolves to the last element, as a bare scalar and via AoH child access."""
        # Bare scalar array: items[-1] is the last element.
        path = write_yaml(
            """\
            items:
              - first
              - second
              - third
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[-1]", path])
        assert stdout.strip() == "third"
        os.unlink(path)

        # Array-of-hashes: records[-1].value reads a child of the last record.
        path = write_yaml(
            """\
            records:
              - id: 1
                value: first
              - id: 2
                value: second
              - id: 3
                value: third
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "records[-1].value", path])
        assert stdout.strip() == "third"
        os.unlink(path)


# ===========================================================================
# CLI: AoH passthrough
# ===========================================================================
class TestAoHPassthrough:
    def test_aoh_passthrough_all_names(self):
        """users.name without selector passes through all hashes."""
        path = write_yaml(
            """\
            users:
              - name: alice
              - name: bob
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "users.name", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        names = sorted(lines)
        assert names == ["alice", "bob"]
        os.unlink(path)


# ===========================================================================
# CLI: Collector expressions (converted from API TestCollectorExpressions/R3)
# ===========================================================================
class TestCollectorExpressionsCLI:
    def test_collector_addition_two_arrays(self):
        """+ collects across whole arrays and across specific indexed elements."""
        path = write_yaml(
            """\
            list_a:
              - 1
              - 2
            list_b:
              - 3
              - 4
        """
        )
        # Whole-array addition.
        stdout, _, _ = run_cmd(["yaml-get", "-p", "(list_a)+(list_b)", path])
        assert sorted(json.loads(stdout.strip())) == [1, 2, 3, 4]
        os.unlink(path)

        # Specific-element addition (indexed collectors).
        path = write_yaml(
            """\
            items:
              - apple
              - banana
              - cherry
              - date
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "(items[0])+(items[2])", path])
        assert json.loads(stdout.strip()) == ["apple", "cherry"]
        os.unlink(path)

    def test_collector_subtraction_removes_matching(self):
        """(all_items)-(remove_items) removes matching elements."""
        path = write_yaml(
            """\
            all_items:
              - alpha
              - beta
              - gamma
              - delta
            remove_items:
              - beta
              - delta
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "(all_items)-(remove_items)", path])
        data = json.loads(stdout.strip())
        assert sorted(data) == ["alpha", "gamma"]
        os.unlink(path)

    def test_collector_intersection(self):
        """(set_a)&(set_b) returns only common elements."""
        path = write_yaml(
            """\
            set_a:
              - red
              - green
              - blue
            set_b:
              - green
              - blue
              - yellow
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "(set_a)&(set_b)", path])
        data = json.loads(stdout.strip())
        assert sorted(data) == ["blue", "green"]
        os.unlink(path)

    def test_collector_chained_addition_subtraction(self):
        """(a)+(b)-(c) chains addition then subtraction."""
        path = write_yaml(
            """\
            a:
              - 1
              - 2
            b:
              - 3
              - 4
            c:
              - 2
              - 3
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "(a)+(b)-(c)", path])
        data = json.loads(stdout.strip())
        assert sorted(data) == [1, 4]
        os.unlink(path)

    def test_collector_intersection_no_overlap_fails(self):
        """Intersection with no common elements produces an error."""
        path = write_yaml(
            """\
            set_a:
              - 1
              - 2
            set_b:
              - 3
              - 4
        """
        )
        _, _, rc = run_cmd(
            ["yaml-get", "-p", "(set_a)&(set_b)", path], expect_fail=True
        )
        assert rc != 0
        os.unlink(path)

    def test_collector_subtraction_complete_removal_fails(self):
        """Subtracting all elements produces an error."""
        path = write_yaml(
            """\
            all:
              - a
              - b
            remove:
              - a
              - b
        """
        )
        _, _, rc = run_cmd(["yaml-get", "-p", "(all)-(remove)", path], expect_fail=True)
        assert rc != 0
        os.unlink(path)


# ===========================================================================
# CLI: Anchors and aliases
# ===========================================================================
class TestAnchorsAndAliasesCLI:
    def test_anchor_lookup(self):
        """&anchor_name retrieves the anchored node."""
        path = write_yaml(
            """\
            defaults: &defaults
              adapter: postgres
              host: localhost
            production:
              <<: *defaults
              host: prod-server
        """
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "&defaults", path])
        data = json.loads(stdout.strip())
        assert data["adapter"] == "postgres"
        assert data["host"] == "localhost"
        os.unlink(path)


# ===========================================================================
# CLI: yaml-set --aliasof
# ===========================================================================
class TestYamlSetAliasOf:
    def test_aliasof_creates_yaml_alias(self):
        """--aliasof makes target an alias of the anchored source."""
        path = write_yaml(
            """\
            defaults: &defaults
              adapter: postgres
              host: localhost
            production:
              adapter: sqlite
        """
        )
        run_cmd(["yaml-set", "-g", "production", "-A", "&defaults", path])
        with open(path) as f:
            content = f.read()
        assert "*defaults" in content
        stdout, _, _ = run_cmd(["yaml-get", "-p", "production.adapter", path])
        assert stdout.strip() == "postgres"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "production.host", path])
        assert stdout.strip() == "localhost"
        os.unlink(path)

    def test_aliasof_with_anchor_name(self):
        """--aliasof with -H creates/renames the anchor."""
        path = write_yaml(
            """\
            source:
              db: mysql
            target: placeholder
        """
        )
        run_cmd(["yaml-set", "-g", "target", "-A", "source", "-H", "mysrc", path])
        with open(path) as f:
            content = f.read()
        assert "&mysrc" in content
        assert "*mysrc" in content
        stdout, _, _ = run_cmd(["yaml-get", "-p", "target.db", path])
        assert stdout.strip() == "mysql"
        os.unlink(path)


# ===========================================================================
# CLI: yaml-paths --expand
# ===========================================================================
class TestYamlPathsExpand:
    def test_expand_parent_matches(self):
        """--expand expands matching parent nodes to leaf children."""
        path = write_yaml(
            """\
            config:
              database:
                host: localhost
                port: 5432
              cache:
                host: redis
                port: 6379
        """
        )
        # --expand (-m) turns the matched `database` parent into its leaf-child paths;
        # -F strips the filename decorator. The result must be the expanded leaves, not
        # the unexpanded parent `config.database`.
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "^database", "-K", "-m", "-F", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        assert lines == ["config.database.host", "config.database.port"]
        os.unlink(path)


# ===========================================================================
# CLI: yaml-paths multiple search expressions
# ===========================================================================
class TestYamlPathsMultiSearch:
    def test_multiple_search_expressions(self):
        """Multiple -s flags search for each expression independently."""
        path = write_yaml(
            """\
            users:
              - name: alice
              - name: bob
              - name: carol
        """
        )
        # -F -X strips the filename and expression decorators, leaving bare paths.
        # Each independent -s expression must resolve to its own element.
        stdout, _, _ = run_cmd(
            ["yaml-paths", "-s", "=alice", "-s", "=carol", "-F", "-X", path]
        )
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        assert lines == ["users[0].name", "users[2].name"]
        os.unlink(path)


# ===========================================================================
# CLI: yaml-paths NDJSON mode
# ===========================================================================
class TestYamlPathsNDJSON:
    def test_ndjson_multi_doc(self):
        """--json-multi-doc parses NDJSON as multiple documents."""
        path = write_yaml(
            '{"name": "alice"}\n{"name": "bob"}\n',
            suffix=".jsonl",
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=alice", "-j", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        # Only the alice record (document index 0) matches `=alice`; the path is
        # qualified by its source document index (`<file>/0`). The bob record
        # (document index 1) must NOT be returned, proving NDJSON is parsed as
        # separate documents and the value search is applied per document.
        assert len(lines) == 1
        assert lines[0].endswith("/0: name")
        assert "/1" not in stdout
        os.unlink(path)


# ===========================================================================
# CLI: yaml-merge AoH modes
# ===========================================================================
class TestMergeAoH:
    def test_merge_aoh_deep_by_identity_key(self):
        """AoH deep merge matches records by identity key and merges fields."""
        lhs = write_yaml(
            """\
            users:
              - name: alice
                role: user
              - name: bob
                role: user
        """
        )
        rhs = write_yaml(
            """\
            users:
              - name: alice
                role: admin
                email: alice@example.com
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-O", "deep", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "users", out])
        data = json.loads(stdout.strip())
        alice = [u for u in data if u["name"] == "alice"][0]
        assert alice["role"] == "admin"
        assert alice["email"] == "alice@example.com"
        bob = [u for u in data if u["name"] == "bob"][0]
        assert bob["role"] == "user"
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_aoh_unique(self):
        """AoH unique merge deduplicates records."""
        lhs = write_yaml(
            """\
            items:
              - name: a
                val: 1
              - name: b
                val: 2
        """
        )
        rhs = write_yaml(
            """\
            items:
              - name: b
                val: 2
              - name: c
                val: 3
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-O", "unique", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        data = json.loads(stdout.strip())
        names = [i["name"] for i in data]
        assert names.count("b") == 1
        assert "c" in names
        assert "a" in names
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_aoh_left(self):
        """AoH left merge keeps only LHS records."""
        lhs = write_yaml(
            """\
            items:
              - name: a
              - name: b
        """
        )
        rhs = write_yaml(
            """\
            items:
              - name: c
              - name: d
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-O", "left", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        data = json.loads(stdout.strip())
        names = [i["name"] for i in data]
        assert names == ["a", "b"]
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_aoh_right(self):
        """AoH right merge replaces with RHS records."""
        lhs = write_yaml(
            """\
            items:
              - name: a
              - name: b
        """
        )
        rhs = write_yaml(
            """\
            items:
              - name: c
              - name: d
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-O", "right", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        data = json.loads(stdout.strip())
        names = [i["name"] for i in data]
        assert names == ["c", "d"]
        for f in [lhs, rhs, out]:
            os.unlink(f)


# ===========================================================================
# CLI: yaml-merge multi-doc modes
# ===========================================================================
class TestMergeMultiDocModes:
    def test_merge_across_multi_doc(self):
        """merge_across merges corresponding subdocuments by index."""
        lhs = write_yaml(
            """\
            a: 1
            ---
            b: 2
        """
        )
        rhs = write_yaml(
            """\
            x: 10
            ---
            y: 20
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-M", "merge_across", "-o", out, lhs, rhs])
        with open(out) as f:
            content = f.read()
        # merge_across pairs subdocuments by index into SEPARATE output documents:
        # doc 0 = LHS doc 0 (a) merged with RHS doc 0 (x); doc 1 = b merged with y.
        # condense_all would instead collapse all four keys into one document, so
        # asserting the per-document key groupings (not just key presence) is what
        # distinguishes merge_across from condense_all.
        docs = [
            d
            for d in (block.strip() for block in content.replace("...", "---").split("---"))
            if d
        ]
        assert len(docs) == 2
        keys_per_doc = [
            {line.split(":", 1)[0].strip() for line in doc.splitlines() if ":" in line}
            for doc in docs
        ]
        assert {"a", "x"} in keys_per_doc
        assert {"b", "y"} in keys_per_doc
        for f in [lhs, rhs, out]:
            os.unlink(f)

    def test_merge_matrix_multi_doc(self):
        """matrix_merge merges every RHS doc into every LHS doc."""
        lhs = write_yaml(
            """\
            base: value
            ---
            other: data
        """
        )
        rhs = write_yaml(
            """\
            injected: yes
        """
        )
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-M", "matrix_merge", "-o", out, lhs, rhs])
        with open(out) as f:
            content = f.read()
        # matrix_merge injects the single RHS doc into EVERY LHS doc, producing 2
        # output documents. A shape-only `count("injected") >= 2` check would also
        # pass an implementation that wrote both `injected` keys into one document,
        # so split on the document markers and assert each output doc keeps its own
        # original LHS key together with the injected one: {base, injected} and
        # {other, injected}.
        docs = [
            d
            for d in (block.strip() for block in content.replace("...", "---").split("---"))
            if d
        ]
        assert len(docs) == 2
        keys_per_doc = [
            {line.split(":", 1)[0].strip() for line in doc.splitlines() if ":" in line}
            for doc in docs
        ]
        assert {"base", "injected"} in keys_per_doc
        assert {"other", "injected"} in keys_per_doc
        for f in [lhs, rhs, out]:
            os.unlink(f)


# ===========================================================================
# CLI: JSON file handling
# ===========================================================================
class TestJsonHandling:
    def test_get_from_json_file(self):
        path = write_yaml('{"database": {"host": "localhost"}}', suffix=".json")
        stdout, _, _ = run_cmd(["yaml-get", "-p", "database.host", path])
        assert stdout.strip() == "localhost"
        os.unlink(path)

    def test_set_in_json_file(self):
        path = write_yaml('{"key": "old"}', suffix=".json")
        run_cmd(["yaml-set", "-g", "key", "-a", "new", path])
        with open(path) as f:
            data = json.load(f)
        assert data["key"] == "new"
        os.unlink(path)

    def test_merge_json_files(self):
        f1 = write_yaml('{"a": 1}', suffix=".json")
        f2 = write_yaml('{"b": 2}', suffix=".json")
        out = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-o", out, f1, f2])
        with open(out) as f:
            data = json.load(f)
        assert data["a"] == 1
        assert data["b"] == 2
        for f in [f1, f2, out]:
            os.unlink(f)


# ===========================================================================
# CLI: yaml-set --delete array elements
# ===========================================================================
class TestDeleteArrayElements:
    def test_delete_array_element_by_index(self):
        path = write_yaml(
            """\
            items:
              - keep
              - remove
              - also_keep
        """
        )
        run_cmd(["yaml-set", "-g", "items[1]", "-D", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", path])
        data = json.loads(stdout.strip())
        assert "remove" not in data
        assert "keep" in data
        assert "also_keep" in data
        os.unlink(path)


# ===========================================================================
# CLI: yaml-paths with --line
# ===========================================================================
class TestYamlPathsLine:
    def test_search_by_line_number(self):
        path = write_yaml(
            """\
            first: value1
            second: value2
            third: value3
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "--line", "2", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # The only top-level key on line 2 is `second`; the keys on lines 1 and 3
        # (`first`, `third`) must NOT be reported.
        assert lines == ["second"]
        assert "first" not in stdout and "third" not in stdout
        os.unlink(path)


# ===========================================================================
# CLI: Frontmatter
# ===========================================================================
class TestFrontmatter:
    def test_get_frontmatter_via_cli(self):
        path = write_yaml(
            "---\ntitle: Test\nauthor: Me\n---\n\nBody text here.\n",
            suffix=".md",
        )
        stdout, _, _ = run_cmd(["yaml-get", "-p", "title", "--frontmatter", path])
        assert stdout.strip() == "Test"
        os.unlink(path)


# ===========================================================================
# CLI: Frontmatter advanced
# ===========================================================================
class TestFrontmatterAdvanced:
    def test_set_frontmatter_value(self):
        path = write_yaml(
            "---\ntitle: Original\nauthor: Me\n---\n\n# Content\n\nBody.\n",
            suffix=".md",
        )
        run_cmd(["yaml-set", "-g", "title", "-a", "Updated", "--frontmatter", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "title", "--frontmatter", path])
        assert stdout.strip() == "Updated"
        with open(path) as f:
            content = f.read()
        assert "Body." in content
        os.unlink(path)


# ===========================================================================
# Delete multiple elements
# ===========================================================================
class TestDeleteMultipleElements:
    def test_delete_multiple_matching_array_elements(self):
        path = write_yaml(
            """\
            tasks:
              - status: done
                name: t1
              - status: pending
                name: t2
              - status: done
                name: t3
              - status: active
                name: t4
        """
        )
        run_cmd(["yaml-set", "-g", "tasks[status=done]", "-D", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "tasks", path])
        data = json.loads(stdout.strip())
        names = [t["name"] for t in data]
        assert "t1" not in names
        assert "t3" not in names
        assert "t2" in names
        assert "t4" in names
        assert len(data) == 2
        os.unlink(path)


# ===========================================================================
# CLI: yaml-set via wildcard and search match
# ===========================================================================
class TestYamlSetAdvancedCLI:
    def test_set_value_overwrites_at_search_match(self):
        """yaml-set can overwrite a value matched by search expression."""
        path = write_yaml(
            """\
            users:
              - name: alice
                score: 10
              - name: bob
                score: 20
        """
        )
        run_cmd(["yaml-set", "-g", "users[name=bob].score", "-a", "99", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "users", path])
        data = json.loads(stdout.strip())
        bob = [u for u in data if u["name"] == "bob"][0]
        assert bob["score"] == 99
        alice = [u for u in data if u["name"] == "alice"][0]
        assert alice["score"] == 10
        os.unlink(path)

    def test_set_value_via_wildcard(self):
        """yaml-set with wildcard sets all matching values."""
        path = write_yaml(
            """\
            servers:
              web:
                enabled: false
              api:
                enabled: false
              admin:
                enabled: false
        """
        )
        run_cmd(
            ["yaml-set", "-g", "servers.*.enabled", "-a", "true", "-F", "boolean", path]
        )
        for key in ["web", "api", "admin"]:
            stdout, _, _ = run_cmd(["yaml-get", "-p", f"servers.{key}.enabled", path])
            assert stdout.strip().lower() == "true"
        os.unlink(path)

    def test_set_array_element_by_index(self):
        """yaml-set replaces a specific array element by positive or negative index."""
        path = write_yaml(
            """\
            items:
              - a
              - b
              - c
        """
        )
        # Positive index: only items[1] changes.
        run_cmd(["yaml-set", "-g", "items[1]", "-a", "replaced", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[1]", path])
        assert stdout.strip() == "replaced"
        # Negative index: items[-1] (the last element) changes, items[0] untouched.
        run_cmd(["yaml-set", "-g", "items[-1]", "-a", "last_replaced", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[-1]", path])
        assert stdout.strip() == "last_replaced"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[0]", path])
        assert stdout.strip() == "a"
        os.unlink(path)


# ===========================================================================
# CLI: yaml-set --mergekey
# ===========================================================================
class TestYamlSetMergeKey:
    def test_mergekey_creates_yaml_merge_key(self):
        path = write_yaml(
            """\
            defaults: &defaults
              adapter: postgres
              host: localhost
            target:
              name: mydb
        """
        )
        run_cmd(["yaml-set", "-g", "target", "-K", "&defaults", path])
        with open(path) as f:
            content = f.read()
        assert "*defaults" in content
        stdout, _, _ = run_cmd(["yaml-get", "-p", "target.adapter", path])
        assert stdout.strip() == "postgres"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "target.name", path])
        assert stdout.strip() == "mydb"
        os.unlink(path)


# ===========================================================================
# yaml-paths flag combinations
# ===========================================================================
class TestYamlPathsFlagCombinations:
    def test_paths_keynames_with_regex(self):
        path = write_yaml(
            """\
            config:
              database_host: localhost
              database_port: 5432
              cache_host: redis
              cache_port: 6379
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=~/^database/", "-K", "-F", "-X", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # The key-name regex `^database` matches exactly the two `database_*` keys;
        # `cache_host`/`cache_port` must NOT be matched (no over-matching).
        assert lines == ["config.database_host", "config.database_port"]
        os.unlink(path)

    def test_paths_noexpression_flag(self):
        path = write_yaml(
            """\
            data:
              x: findme
              y: keepme
        """
        )
        # With more than one search expression, each result line is decorated with
        # the matching expression unless -X/--noexpression is given.
        stdout_with, _, _ = run_cmd(
            ["yaml-paths", "-s", "=findme", "-s", "=keepme", "-F", path]
        )
        stdout_without, _, _ = run_cmd(
            ["yaml-paths", "-s", "=findme", "-s", "=keepme", "-F", "-X", path]
        )
        # Default output carries the [=findme] expression decorator.
        assert "[=findme]" in stdout_with
        # -X strips every expression decorator, leaving only the bare paths.
        assert "[" not in stdout_without
        lines_without = sorted(
            l.strip() for l in stdout_without.strip().splitlines() if l.strip()
        )
        assert lines_without == ["data.x", "data.y"]
        os.unlink(path)

    def test_paths_noyamlpath_with_values(self):
        path = write_yaml(
            """\
            items:
              - name: test_value
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=test_value", "-L", "-P", path])
        stripped = stdout.strip()
        # -P suppresses the YAML Path, so the matched path `items[0].name` must NOT
        # appear; with -L the value is still printed after the file decorator, so the
        # line ends with `: test_value` and the path segment `items[0].name` is gone.
        assert "items[0].name" not in stdout
        assert "name" not in stripped
        assert stripped.endswith(": test_value")
        os.unlink(path)


# ===========================================================================
# Diff nested array order
# ===========================================================================
class TestDiffNestedArrayOrder:
    def test_diff_nested_array_order_value_mode(self):
        f1 = write_yaml(
            """\
            config:
              servers:
                - name: web
                  ports:
                    - 80
                    - 443
                    - 8080
        """
        )
        f2 = write_yaml(
            """\
            config:
              servers:
                - name: web
                  ports:
                    - 8080
                    - 80
                    - 443
        """
        )
        _, _, rc = run_cmd(["yaml-diff", "-A", "position", f1, f2], expect_fail=True)
        assert rc == 1
        _, _, rc = run_cmd(["yaml-diff", "-O", "deep", "-A", "value", f1, f2])
        assert rc == 0
        os.unlink(f1)
        os.unlink(f2)


# ===========================================================================
# yaml-set --check numeric
# ===========================================================================
class TestYamlSetCheckNumeric:
    def test_check_match_mismatch_and_type_mismatch(self):
        path = write_yaml('port: "5432"\n')
        run_cmd(["yaml-set", "-g", "port", "-a", "3306", "-c", "5432", path])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "port", path])
        assert stdout.strip() == "3306"
        os.unlink(path)

        path2 = write_yaml('port: "5432"\n')
        _, _, rc = run_cmd(
            ["yaml-set", "-g", "port", "-a", "3306", "-c", "9999", path2],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path2)

        path3 = write_yaml("port: 5432\n")
        _, _, rc = run_cmd(
            ["yaml-set", "-g", "port", "-a", "3306", "-c", "5432", path3],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path3)


# ===========================================================================
# Merge with config
# ===========================================================================
class TestMergeWithConfig:
    def test_merge_with_ini_config(self):
        lhs = write_yaml(
            """\
            settings:
              debug: false
              items:
                - a
                - b
        """
        )
        rhs = write_yaml(
            """\
            settings:
              debug: true
              items:
                - c
        """
        )
        config_file = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False)
        config_file.write("[defaults]\nhashes = left\narrays = left\n")
        config_file.close()
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-c", config_file.name, "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "settings.debug", out])
        assert stdout.strip().lower() == "false"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "settings.items", out])
        data = json.loads(stdout.strip())
        assert data == ["a", "b"]
        for f in [lhs, rhs, out, config_file.name]:
            os.unlink(f)


# ===========================================================================
# Merge INI config
# ===========================================================================
class TestMergeINIConfig:
    def test_merge_ini_config_per_path_rules(self):
        lhs = write_yaml(
            """\
            items:
              - a
              - b
            config:
              x: 1
              y: 2
        """
        )
        rhs = write_yaml(
            """\
            items:
              - c
            config:
              x: 10
              z: 3
        """
        )
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False)
        cfg.write("[rules]\nitems = left\nconfig = right\n")
        cfg.close()
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-c", cfg.name, "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items", out])
        items = json.loads(stdout.strip())
        assert items == ["a", "b"]
        stdout, _, _ = run_cmd(["yaml-get", "-p", "config", out])
        config = json.loads(stdout.strip())
        assert config == {"x": 10, "z": 3}
        for f in [lhs, rhs, cfg.name, out]:
            os.unlink(f)

    def test_merge_ini_config_keys_section_identity(self):
        lhs = write_yaml(
            """\
            users:
              - id: 1
                name: alice
                role: user
              - id: 2
                name: bob
                role: user
        """
        )
        rhs = write_yaml(
            """\
            users:
              - id: 2
                name: bob
                role: admin
        """
        )
        cfg = tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False)
        cfg.write("[keys]\nusers = id\n")
        cfg.close()
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-O", "deep", "-c", cfg.name, "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "users", out])
        data = json.loads(stdout.strip())
        bob = [u for u in data if u["id"] == 2][0]
        assert bob["role"] == "admin"
        alice = [u for u in data if u["id"] == 1][0]
        assert alice["role"] == "user"
        for f in [lhs, rhs, cfg.name, out]:
            os.unlink(f)


# ===========================================================================
# Merge condense all
# ===========================================================================
class TestMergeCondenseAll:
    def test_condense_all_merges_all_docs_into_one(self):
        lhs = write_yaml("a: 1\n---\nb: 2\n")
        rhs = write_yaml("c: 3\n")
        out = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False).name
        os.unlink(out)
        run_cmd(["yaml-merge", "-S", "-M", "condense_all", "-o", out, lhs, rhs])
        stdout, _, _ = run_cmd(["yaml-get", "-p", "a", out])
        assert stdout.strip() == "1"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "b", out])
        assert stdout.strip() == "2"
        stdout, _, _ = run_cmd(["yaml-get", "-p", "c", out])
        assert stdout.strip() == "3"
        for f in [lhs, rhs, out]:
            os.unlink(f)


# ===========================================================================
# yaml-paths anchor flags
# ===========================================================================
class TestYamlPathsAnchorFlags:
    def test_default_and_anchorsonly_exclude_alias_matches(self):
        # Both the default mode and --anchorsonly exclude value-alias matches: the
        # anchored origin and the plain scalar match, but the `*myval` alias does not.
        path = write_yaml(
            "anchored: &myval findme\nalias_copy: *myval\nplain: findme\n"
        )
        for extra_args in ([], ["--anchorsonly"]):
            stdout, _, _ = run_cmd(["yaml-paths", "-s", "=findme", *extra_args, path])
            lines = [l for l in stdout.strip().splitlines() if l.strip()]
            matched_paths = " ".join(lines)
            assert "anchored" in matched_paths
            assert "plain" in matched_paths
            assert "alias_copy" not in matched_paths
        os.unlink(path)

    def test_allowaliases_includes_alias_matches(self):
        path = write_yaml(
            "anchored: &myval findme\nalias_copy: *myval\nplain: findme\n"
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", "=findme", "--allowaliases", path])
        lines = [l for l in stdout.strip().splitlines() if l.strip()]
        matched_paths = " ".join(lines)
        assert "anchored" in matched_paths
        assert "alias_copy" in matched_paths
        assert "plain" in matched_paths
        os.unlink(path)


# ===========================================================================
# CLI: Deep traversal chains
# ===========================================================================
class TestDeepTraversalChains:
    def test_wildcard_plus_search(self):
        """servers.*.ports[.>8000] finds ports > 8000 across all servers."""
        path = write_yaml(
            """\
            servers:
              web:
                ports:
                  - 80
                  - 443
                  - 8080
              api:
                ports:
                  - 3000
                  - 9090
        """
        )
        stdout, _, _ = run_cmd(["yaml-paths", "-s", ">8000", "-F", "-X", "-L", path])
        lines = sorted(l.strip() for l in stdout.strip().splitlines() if l.strip())
        # Only ports 8080 and 9090 exceed 8000; 80/443/3000 do not.
        assert lines == ["servers.api.ports[1]: 9090", "servers.web.ports[2]: 8080"]
        os.unlink(path)

    def test_deep_traversal_plus_search(self):
        """root.**.items[status=active].id finds deeply nested matches."""
        path = write_yaml(
            """\
            root:
              section_a:
                items:
                  - status: active
                    id: 1
                  - status: inactive
                    id: 2
              section_b:
                nested:
                  items:
                    - status: active
                      id: 3
                    - status: active
                      id: 4
        """
        )
        stdout, _, _ = run_cmd(
            ["yaml-get", "-p", "root.**.items[status=active].id", path]
        )
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        values = sorted([int(l) for l in lines])
        assert values == [1, 3, 4]
        os.unlink(path)

    def test_multi_level_chaining(self):
        """Multi-level search chaining: items[type=config].settings[enabled=true].name."""
        path = write_yaml(
            """\
            items:
              - type: config
                settings:
                  - enabled: true
                    name: setting_A
                  - enabled: false
                    name: setting_B
                  - enabled: true
                    name: setting_C
              - type: data
                settings:
                  - enabled: true
                    name: setting_D
        """
        )
        stdout, _, _ = run_cmd(
            ["yaml-get", "-p", "items[type=config].settings[enabled=true].name", path]
        )
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        names = sorted(lines)
        assert names == ["setting_A", "setting_C"]
        os.unlink(path)

    def test_index_then_search(self):
        """items[0].tags[.=important] composes a leading array index with a value search."""
        path = write_yaml(
            """\
            items:
              - name: first
                tags:
                  - important
                  - low
                  - important
              - name: second
                tags:
                  - important
        """
        )
        # The leading `[0]` scopes the subsequent `[.=important]` value search to the
        # FIRST item only, so the two "important" tags in items[0] are returned and the
        # "important" tag in items[1] is excluded. Resolving through yaml-get returns the
        # matched values (one per line); a differ that ignored the leading index would
        # also surface items[1]'s tag. This exercises index+search composition, which a
        # plain `[.=value]` array search (test_dot_match_in_array) does not cover.
        stdout, _, _ = run_cmd(["yaml-get", "-p", "items[0].tags[.=important]", path])
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        assert lines == ["important", "important"]
        os.unlink(path)

    def test_aoh_passthrough_with_search(self):
        """users.addresses[city=NYC].street passes through AoH then searches."""
        path = write_yaml(
            """\
            users:
              - name: alice
                addresses:
                  - city: NYC
                    street: Broadway
                  - city: LA
                    street: Sunset
              - name: bob
                addresses:
                  - city: NYC
                    street: Wall St
        """
        )
        stdout, _, _ = run_cmd(
            ["yaml-get", "-p", "users.addresses[city=NYC].street", path]
        )
        lines = [l.strip() for l in stdout.strip().splitlines() if l.strip()]
        streets = sorted(lines)
        assert streets == ["Broadway", "Wall St"]
        os.unlink(path)


# ===========================================================================
# CLI: Repeated traversal error
# ===========================================================================
class TestRepeatedTraversalError:
    def test_repeated_double_star_fails(self):
        """root.**.**.leaf should fail (repeated traversal)."""
        path = write_yaml("root:\n  child:\n    leaf: val\n")
        _, _, rc = run_cmd(
            ["yaml-get", "-p", "root.**.**.leaf", path], expect_fail=True
        )
        assert rc != 0
        os.unlink(path)


# ===========================================================================
# Failure conditions (CLI-only)
# ===========================================================================
class TestFailureConditions:
    """Tests that exercise error handling paths the model usually misses."""

    def test_yaml_set_saveto_with_multiple_matches_fails(self):
        """yaml-set --saveto with multiple matching nodes should fail."""
        path = write_yaml(
            """\
            items:
              - name: alice
              - name: bob
        """
        )
        _, stderr, rc = run_cmd(
            [
                "yaml-set",
                "-g",
                "items.name",
                "-a",
                "new_name",
                "-s",
                "backup_name",
                path,
            ],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)

    def test_yaml_set_aliasof_nonexistent_anchor_fails(self):
        """yaml-set --aliasof with a nonexistent anchor path should fail."""
        path = write_yaml(
            """\
            target: placeholder
        """
        )
        _, stderr, rc = run_cmd(
            [
                "yaml-set",
                "-g",
                "target",
                "-A",
                "nonexistent.anchor.path",
                path,
            ],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)

    def test_yaml_set_delete_nonexistent_path_fails(self):
        """yaml-set --delete on a nonexistent path should error."""
        path = write_yaml(
            """\
            existing: value
        """
        )
        _, stderr, rc = run_cmd(
            ["yaml-set", "-g", "nonexistent.path", "-D", path],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)

    def test_yaml_merge_output_to_existing_file_fails(self):
        """yaml-merge -o to an existing file should error."""
        lhs = write_yaml("a: 1\n")
        rhs = write_yaml("b: 2\n")
        existing_out = write_yaml("already: here\n")
        _, _, rc = run_cmd(
            ["yaml-merge", "-S", "-o", existing_out, lhs, rhs],
            expect_fail=True,
        )
        # The exact error wording is an implementation detail; only the refusal (non-zero exit) matters.
        assert rc != 0
        for f in [lhs, rhs, existing_out]:
            os.unlink(f)

    def test_yaml_merge_anchor_conflict_stop_mode_fails(self):
        """yaml-merge with --anchors=stop (default) should error on conflict."""
        lhs = write_yaml(
            """\
            defaults: &shared
              key: lhs_value
        """
        )
        rhs = write_yaml(
            """\
            overrides: &shared
              key: rhs_value
        """
        )
        _, stderr, rc = run_cmd(
            ["yaml-merge", "-S", "-a", "stop", lhs, rhs],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(lhs)
        os.unlink(rhs)

    def test_yaml_diff_with_only_one_file_fails(self):
        """yaml-diff requires exactly 2 files; 1 file should error."""
        f1 = write_yaml("key: value\n")
        _, stderr, rc = run_cmd(
            ["yaml-diff", f1],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(f1)

    def test_yaml_validate_nonexistent_file_fails(self):
        """yaml-validate with a nonexistent file should produce error output."""
        _, _, rc = run_cmd(
            ["yaml-validate", "-S", "/tmp/nonexistent_file_12345.yaml"],
            expect_fail=True,
        )
        assert rc != 0

    def test_yaml_get_no_query_flag_fails(self):
        """yaml-get with no -p flag should error."""
        path = write_yaml("key: value\n")
        _, stderr, rc = run_cmd(
            ["yaml-get", path],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)

    def test_yaml_set_no_change_flag_fails(self):
        """yaml-set with no -g flag should error."""
        path = write_yaml("key: value\n")
        _, stderr, rc = run_cmd(
            ["yaml-set", "-a", "newval", path],
            expect_fail=True,
        )
        assert rc != 0
        os.unlink(path)
