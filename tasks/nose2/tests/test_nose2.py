"""
End-to-end integration tests for the nose2 test framework.

Tests exercise complex multi-feature scenarios: discovery + running + result
verification, parameterized tests with multiple loaders, BDD-style DSL with
nested layers, JUnit XML report generation with mixed outcomes, configuration
interactions, and CLI integration.
"""

import os
import re
import subprocess
import sys
import shutil
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_project(tmpdir, files):
    """Create a temporary test project from a dict of {relative_path: content}."""
    for relpath, content in files.items():
        fpath = os.path.join(tmpdir, relpath)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, "w") as f:
            f.write(textwrap.dedent(content))
    return tmpdir


def _run_nose2(start_dir, argv=None, plugins=None, exclude_plugins=None):
    """Run nose2.discover() programmatically and return the PluggableTestProgram."""
    import nose2

    if argv is None:
        argv = ["nose2", "-s", start_dir, "-t", start_dir]
    else:
        argv = list(argv)

    kwargs = {
        "argv": argv,
        "exit": False,
        "plugins": plugins or [],
        "excludePlugins": exclude_plugins or [],
    }

    old_path = sys.path[:]
    old_cwd = os.getcwd()
    try:
        if start_dir not in sys.path:
            sys.path.insert(0, start_dir)
        os.chdir(start_dir)
        prog = nose2.discover(**kwargs)
        return prog
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path
        to_remove = [k for k in sys.modules if k.startswith("test_")]
        for k in to_remove:
            del sys.modules[k]


def _run_nose2_subprocess(tmpdir, extra_args=None):
    """Run nose2 via subprocess, return CompletedProcess."""
    args = [sys.executable, "-m", "nose2", "-s", tmpdir, "-t", tmpdir]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(
        args, capture_output=True, text=True, cwd=tmpdir,
    )


def _parse_summary(stderr):
    """Extract per-outcome counts from nose2's unittest-style summary in stderr.

    Accepts both `Ran N tests in T.TTTs` and a bare `Ran N tests` — the only
    contract the spec promises is the count, not the trailing duration.

    Anchors on the LAST `Ran N tests` line and reads the outcome counts from the
    status line after it, so report text a run quotes from elsewhere (e.g. a
    worker's own report echoed into a failure detail) cannot be mistaken for the
    run's own trailing summary.
    """
    ran_matches = list(re.finditer(r"Ran (\d+) tests?\b", stderr))
    m_total = ran_matches[-1] if ran_matches else None
    tail = stderr[m_total.end():] if m_total else stderr
    return {
        "total": int(m_total.group(1)) if m_total else None,
        "failures": int(m.group(1)) if (m := re.search(r"failures=(\d+)", tail)) else 0,
        "errors": int(m.group(1)) if (m := re.search(r"errors=(\d+)", tail)) else 0,
        "skipped": int(m.group(1)) if (m := re.search(r"skipped=(\d+)", tail)) else 0,
    }


# ===========================================================================
# 1. Discovery + run + result integration
# ===========================================================================

class TestDiscoveryAndRunIntegration(unittest.TestCase):
    """Complex discovery scenarios: mixed outcomes, multiple loaders,
    specific test selection, load_tests protocol, failfast."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_mixed_outcomes_via_cli(self):
        """Run tests with pass, fail, error, skip, and expectedFailure and
        verify the correct counts appear in the stderr summary."""
        _make_test_project(self.tmpdir, {
            "test_outcomes.py": """\
                import unittest

                class TestOutcomes(unittest.TestCase):
                    def test_pass(self):
                        self.assertTrue(True)

                    def test_fail(self):
                        self.assertEqual(1, 2)

                    def test_error(self):
                        raise RuntimeError("boom")

                    @unittest.skip("skipping this")
                    def test_skip(self):
                        pass

                    @unittest.expectedFailure
                    def test_expected_fail(self):
                        self.assertEqual(1, 2)
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ran 5 test", result.stderr)
        self.assertIn("failures=1", result.stderr)
        self.assertIn("errors=1", result.stderr)
        self.assertIn("skipped=1", result.stderr)
        self.assertIn("expected failures=1", result.stderr)

    def test_discover_functions_and_classes_together(self):
        """Discover both unittest classes and standalone functions when the
        functions loader is active."""
        _make_test_project(self.tmpdir, {
            "test_mixed_loaders.py": """\
                import unittest

                class TestClassBased(unittest.TestCase):
                    def test_from_class(self):
                        self.assertTrue(True)

                def test_standalone_function():
                    assert 1 + 1 == 2

                def test_another_function():
                    assert "hello".startswith("h")
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.loader.functions"],
        )
        self.assertEqual(result.returncode, 0)
        # 1 TestCase method + 2 standalone functions: an implementation whose
        # functions loader discovers zero functions would report "Ran 1 test".
        self.assertIn("Ran 3 test", result.stderr)

    def test_run_specific_test_by_name(self):
        """Run a single specific test method by its fully-qualified name,
        verifying only that test runs (not others)."""
        _make_test_project(self.tmpdir, {
            "test_named.py": """\
                import unittest

                class TestNamed(unittest.TestCase):
                    def test_alpha(self):
                        self.assertTrue(True)

                    def test_beta(self):
                        self.fail("should not run")
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["test_named.TestNamed.test_alpha"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 1 test", result.stderr)

    def test_load_tests_protocol(self):
        """Verify nose2 respects the load_tests protocol to customize
        which tests are loaded from a module."""
        _make_test_project(self.tmpdir, {
            "test_loadtests.py": """\
                import unittest

                class TestHidden(unittest.TestCase):
                    def test_should_not_run(self):
                        raise AssertionError("should not run")

                class TestVisible(unittest.TestCase):
                    def test_should_run(self):
                        assert True

                def load_tests(loader, tests, pattern):
                    suite = unittest.TestSuite()
                    suite.addTest(TestVisible('test_should_run'))
                    return suite
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir)
        # load_tests returned a suite holding exactly TestVisible.test_should_run, so the run must
        # succeed AND report precisely one test — not merely "no failure". An implementation that
        # ignored the protocol would also run TestHidden.test_should_not_run (an AssertionError →
        # non-zero exit, "Ran 2 tests"); one that loaded extra passing tests would inflate the count.
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(_parse_summary(result.stderr)["total"], 1)

    def test_failfast_stops_after_first_failure(self):
        """Failfast mode stops execution after the first failure."""
        _make_test_project(self.tmpdir, {
            "test_failfast.py": """\
                import unittest

                class TestFailFast(unittest.TestCase):
                    def test_a_fail(self):
                        self.assertEqual(1, 2)

                    def test_b_pass(self):
                        self.assertTrue(True)

                    def test_c_pass(self):
                        self.assertTrue(True)
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir, extra_args=["-F"])
        self.assertNotEqual(result.returncode, 0)
        # Should run fewer than 3 tests due to failfast
        self.assertIn("Ran 1 test", result.stderr)


# ===========================================================================
# 2. Parameterized testing integration
# ===========================================================================

class TestParameterizedIntegration(unittest.TestCase):
    """@params and @cartesian_params with count verification via subprocess."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_params_generates_multiple_test_cases(self):
        """@params generates one test case per parameter set. Failing
        parameter causes only that case to fail."""
        _make_test_project(self.tmpdir, {
            "test_params.py": """\
                import unittest
                from nose2.tools import params

                class TestParams(unittest.TestCase):
                    @params((1, 1, 2), (2, 3, 5), (10, 20, 30))
                    def test_add(self, a, b, expected):
                        self.assertEqual(a + b, expected)

                    @params((1, 2), (3, 3))
                    def test_equal(self, a, b):
                        self.assertEqual(a, b)
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ran 5 test", result.stderr)
        self.assertIn("failures=1", result.stderr)

    def test_params_on_standalone_functions(self):
        """@params works on standalone test functions with the functions loader."""
        _make_test_project(self.tmpdir, {
            "test_params_func.py": """\
                from nose2.tools import params

                @params("hello", "world", "test")
                def test_is_string(value):
                    assert isinstance(value, str)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.loader.functions"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 3 test", result.stderr)

    def test_cartesian_params_generates_all_combinations(self):
        """@cartesian_params generates the full Cartesian product."""
        _make_test_project(self.tmpdir, {
            "test_cartesian.py": """\
                import unittest
                from nose2.tools import cartesian_params

                class TestCartesian(unittest.TestCase):
                    @cartesian_params((1, 2, 3), ('a', 'b'))
                    def test_types(self, num, char):
                        self.assertIsInstance(num, int)
                        self.assertIsInstance(char, str)
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 6 test", result.stderr)


# ===========================================================================
# 3. BDD-style 'such' DSL integration
# ===========================================================================

class TestSuchDSLIntegration(unittest.TestCase):
    """Complex 'such' DSL: nested groups, fixtures, multiple tests."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_such_with_nested_groups_and_fixtures(self):
        """Full such scenario: top-level setup, nested 'having' groups,
        tests verifying fixture state at each level."""
        _make_test_project(self.tmpdir, {
            "test_such_full.py": """\
                from nose2.tools import such

                _state = {}

                with such.A('system') as it:
                    @it.has_setup
                    def setup():
                        _state['base'] = True

                    @it.has_teardown
                    def teardown():
                        _state.clear()

                    @it.should('have base setup')
                    def test_base(case):
                        case.assertTrue(_state.get('base'))

                    @it.should('not have subsystem yet')
                    def test_no_sub(case):
                        case.assertFalse(_state.get('sub'))

                    with it.having('a subsystem'):
                        @it.has_setup
                        def sub_setup():
                            _state['sub'] = True

                        @it.should('have both base and sub setup')
                        def test_sub(case):
                            case.assertTrue(_state.get('base'))
                            case.assertTrue(_state.get('sub'))

                        @it.should('verify sub is isolated')
                        def test_sub_isolated(case):
                            case.assertTrue(_state.get('sub'))

                    it.createTests(globals())
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.layers"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 4 test", result.stderr)


# ===========================================================================
# 4. Layers plugin integration
# ===========================================================================

class TestLayersIntegration(unittest.TestCase):
    """Layers: setup ordering with inheritance, multiple test classes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_layer_inheritance_ordering(self):
        """Child layers run parent setUp first. Tests verify accumulated state."""
        _make_test_project(self.tmpdir, {
            "test_layer_inherit.py": """\
                import unittest

                _log = []

                class BaseLayer:
                    @classmethod
                    def setUp(cls):
                        _log.append('base')

                    @classmethod
                    def tearDown(cls):
                        pass

                class ChildLayer(BaseLayer):
                    @classmethod
                    def setUp(cls):
                        _log.append('child')

                    @classmethod
                    def tearDown(cls):
                        pass

                class TestBase(unittest.TestCase):
                    layer = BaseLayer

                    def test_base_only(self):
                        self.assertIn('base', _log)

                class TestChild(unittest.TestCase):
                    layer = ChildLayer

                    def test_both_layers_setup(self):
                        self.assertIn('base', _log)
                        self.assertIn('child', _log)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.layers"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 2 test", result.stderr)


# ===========================================================================
# 5. JUnit XML integration
# ===========================================================================

class TestJUnitXmlIntegration(unittest.TestCase):
    """JUnit XML: comprehensive report with mixed outcomes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_junit_xml_comprehensive_report(self):
        """Generate JUnit XML with pass, fail, error, and skip. Verify
        testsuite attributes and child elements for each outcome type."""
        xml_path = os.path.join(self.tmpdir, "junit-report.xml")
        _make_test_project(self.tmpdir, {
            "test_forxml.py": """\
                import unittest

                class TestForXml(unittest.TestCase):
                    def test_pass(self):
                        self.assertTrue(True)

                    def test_fail(self):
                        self.assertEqual(1, 2, "intentional failure")

                    def test_error(self):
                        raise RuntimeError("intentional error")

                    @unittest.skip("not ready")
                    def test_skip(self):
                        pass
            """,
        })
        prog = _run_nose2(
            self.tmpdir,
            argv=["nose2", "-s", self.tmpdir, "-t", self.tmpdir,
                  "--plugin", "nose2.plugins.junitxml",
                  "-X", "--junit-xml-path", xml_path],
        )
        self.assertTrue(os.path.exists(xml_path))
        tree = ET.parse(xml_path)
        root = tree.getroot()
        self.assertEqual(root.tag, "testsuite")
        self.assertEqual(root.get("tests"), "4")
        self.assertEqual(root.get("failures"), "1")
        self.assertEqual(root.get("errors"), "1")
        self.assertEqual(root.get("skipped"), "1")

        testcases = root.findall("testcase")
        self.assertEqual(len(testcases), 4)

        failure_cases = [tc for tc in testcases if tc.find("failure") is not None]
        self.assertEqual(len(failure_cases), 1)

        error_cases = [tc for tc in testcases if tc.find("error") is not None]
        self.assertEqual(len(error_cases), 1)

        skipped_cases = [tc for tc in testcases if tc.find("skipped") is not None]
        self.assertEqual(len(skipped_cases), 1)


# ===========================================================================
# 6. Configuration integration
# ===========================================================================

class TestConfigIntegration(unittest.TestCase):
    """Config-driven verbosity via the [unittest] section."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_config_verbosity_shows_test_names_without_dash_v(self):
        """`[unittest] verbosity = 2` in config makes per-test names appear
        in stderr without passing -v on the command line."""
        _make_test_project(self.tmpdir, {
            "nose2.cfg": """\
                [unittest]
                verbosity = 2
            """,
            "test_verb_cfg.py": """\
                import unittest

                class TestVerbCfg(unittest.TestCase):
                    def test_gamma(self):
                        self.assertTrue(True)
            """,
        })
        # No -v flag — verbosity comes from the auto-loaded config.
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(_parse_summary(result.stderr)["total"], 1)
        # At verbosity 2 the per-test method name is printed.
        self.assertIn("test_gamma", result.stderr)


# ===========================================================================
# 7. CLI entry point integration
# ===========================================================================

class TestCLIIntegration(unittest.TestCase):
    """CLI: python -m nose2 with various flags."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_cli_buffer_captures_stdout(self):
        """With -B flag, stdout from failing tests appears in failure report."""
        _make_test_project(self.tmpdir, {
            "test_buf.py": """\
                import unittest

                class TestBuf(unittest.TestCase):
                    def test_with_output(self):
                        print("CAPTURED_OUTPUT_MARKER")
                        self.assertEqual(1, 2)
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir, extra_args=["-B"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CAPTURED_OUTPUT_MARKER", result.stderr)


# ===========================================================================
# 8. Generator tests
# ===========================================================================

class TestGeneratorTests(unittest.TestCase):
    """Generator test methods yield multiple test cases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_generator_yields_multiple_test_cases(self):
        """A generator test method yields multiple callable test cases."""
        _make_test_project(self.tmpdir, {
            "test_gen.py": """\
                import unittest

                class TestGenerator(unittest.TestCase):
                    def test_evens(self):
                        for val in [2, 4, 6, 8]:
                            yield self._check_even, val

                    def _check_even(self, val):
                        self.assertEqual(val % 2, 0)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.loader.generators"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 4 test", result.stderr)


# ===========================================================================
# 9. TestClasses loader — plain classes
# ===========================================================================

class TestTestClassLoader(unittest.TestCase):
    """Discover test methods in plain classes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_plain_class_tests(self):
        """Plain classes with test_ methods are discovered by testclasses plugin."""
        _make_test_project(self.tmpdir, {
            "test_plain.py": """\
                class TestPlainClass:
                    def test_one(self):
                        assert 1 + 1 == 2

                    def test_two(self):
                        assert "hello".upper() == "HELLO"
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.loader.testclasses"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 2 test", result.stderr)


# ===========================================================================
# 10. Attribute selection
# ===========================================================================

class TestAttributeSelection(unittest.TestCase):
    """Select tests by custom attributes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_select_by_attribute(self):
        """Only tests with the specified attribute (truthy value) are run."""
        _make_test_project(self.tmpdir, {
            "test_attrib.py": """\
                import unittest

                class TestAttrib(unittest.TestCase):
                    def test_slow(self):
                        self.assertTrue(True)
                    test_slow.slow = True

                    def test_fast(self):
                        self.fail("should not run when selecting slow")
                    test_fast.slow = False
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.attrib", "-A", "slow"],
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Ran 1 test", result.stderr)


# ===========================================================================
# 12. Log capture with verification
# ===========================================================================

class TestLogCaptureIntegration(unittest.TestCase):
    """Log capture plugin captures log messages in failure output."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_log_capture_shows_in_failure(self):
        """Log messages from failing tests appear in failure output."""
        _make_test_project(self.tmpdir, {
            "test_logs.py": """\
                import logging
                import unittest

                logger = logging.getLogger(__name__)

                class TestLogs(unittest.TestCase):
                    def test_with_logging(self):
                        logger.warning("LOG_CAPTURE_MARKER")
                        self.assertEqual(1, 2)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.logcapture", "--log-capture"],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LOG_CAPTURE_MARKER", result.stderr)


# ===========================================================================
# 14. Function decorators end-to-end
# ===========================================================================

class TestFunctionDecorators(unittest.TestCase):
    """with_setup and with_teardown decorators work end-to-end."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_with_setup_and_teardown_execute(self):
        """Functions decorated with @with_setup AND @with_teardown have both fixtures called.

        The setup side effect is observed inside the decorated function itself; the teardown side
        effect — which only happens *after* that function returns — is observed by a second
        function that runs afterwards. An implementation that wires up @with_setup but ignores
        @with_teardown leaves `_state` without 'teardown', failing the second function.

        Both functions are discovered by the functions loader (the spec-supported path) rather than
        selected by name; they are named so discovery order runs the decorated function first and
        the observer second.
        """
        _make_test_project(self.tmpdir, {
            "test_decorators.py": """\
                from nose2.tools.decorators import with_setup, with_teardown

                _state = []

                def my_setup():
                    _state.append('setup')

                def my_teardown():
                    _state.append('teardown')

                @with_setup(my_setup)
                @with_teardown(my_teardown)
                def test_1_with_fixtures():
                    assert 'setup' in _state

                def test_2_teardown_ran():
                    assert 'teardown' in _state
            """,
        })
        # Discover both functions (no positional names): the loader runs test_1_with_fixtures
        # first (firing its teardown), then test_2_teardown_ran observes the teardown side effect.
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.loader.functions"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Ran 2 test", result.stderr)


# ===========================================================================
# 16. Verbosity flags (-v / -q / --log-level)
# ===========================================================================

class TestVerbosityFlags(unittest.TestCase):
    """`-v` / `-q` / `--log-level` control output detail."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _make_test_project(self.tmpdir, {
            "test_verb.py": """\
                import unittest

                class TestVerb(unittest.TestCase):
                    def test_alpha(self):
                        self.assertTrue(True)

                    def test_beta(self):
                        self.assertTrue(True)
            """,
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_verbose_shows_test_names_and_quiet_hides_them(self):
        """At -v verbosity, per-test method names appear in stderr; at -q they don't."""
        result_v = _run_nose2_subprocess(self.tmpdir, extra_args=["-v"])
        result_q = _run_nose2_subprocess(self.tmpdir, extra_args=["-q"])
        self.assertEqual(result_v.returncode, 0, msg=result_v.stderr)
        self.assertEqual(result_q.returncode, 0, msg=result_q.stderr)
        v_summary = _parse_summary(result_v.stderr)
        q_summary = _parse_summary(result_q.stderr)
        self.assertEqual(v_summary["total"], 2)
        self.assertEqual(q_summary["total"], 2)
        # Verbose: per-test method names appear in stderr
        self.assertIn("test_alpha", result_v.stderr)
        self.assertIn("test_beta", result_v.stderr)
        # Quiet: per-test method names do NOT appear in stderr
        self.assertNotIn("test_alpha", result_q.stderr)
        self.assertNotIn("test_beta", result_q.stderr)

    def test_log_level_controls_console_log_verbosity(self):
        """--log-level sets the console logging threshold: DEBUG emits debug log lines that a
        higher level (WARNING) suppresses, and every standard level name is accepted with the
        run still completing."""
        # Every standard level name is accepted and the run completes with both tests.
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            result = _run_nose2_subprocess(
                self.tmpdir, extra_args=["--log-level", level]
            )
            self.assertEqual(
                result.returncode, 0,
                msg=f"--log-level {level} returned {result.returncode}: {result.stderr}",
            )
            self.assertEqual(_parse_summary(result.stderr)["total"], 2,
                             msg=f"--log-level {level} didn't run 2 tests: {result.stderr}")

        # Level-specific behavior: at DEBUG, debug-level log records reach the console; at WARNING
        # the same records are filtered out. This rewards real threshold handling, not mere flag
        # acceptance. The default logging format renders a record as "LEVELNAME:logger:message",
        # so a "DEBUG:" line is the user-observable signature of debug logging being enabled.
        debug_run = _run_nose2_subprocess(self.tmpdir, extra_args=["--log-level", "DEBUG"])
        warning_run = _run_nose2_subprocess(self.tmpdir, extra_args=["--log-level", "WARNING"])
        self.assertIn("DEBUG:", debug_run.stderr,
                      msg=f"--log-level DEBUG emitted no DEBUG log line: {debug_run.stderr!r}")
        self.assertNotIn("DEBUG:", warning_run.stderr,
                         msg=f"--log-level WARNING leaked a DEBUG log line: {warning_run.stderr!r}")


# ===========================================================================
# 17. Collect-only plugin
# ===========================================================================

class TestCollectOnlyPlugin(unittest.TestCase):
    """--collect-only lists discovered tests without executing them."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.marker = os.path.join(self.tmpdir, "executed.marker")
        _make_test_project(self.tmpdir, {
            "test_collect.py": f"""\
                import unittest

                class TestCol(unittest.TestCase):
                    def test_runs(self):
                        with open({self.marker!r}, "w") as f:
                            f.write("ran")
                        self.assertTrue(True)
            """,
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_collect_only_lists_tests_without_running(self):
        """Under --collect-only, the test body never executes (no marker file written)."""
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.collect", "--collect-only", "-v"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Side-effect marker must NOT exist — proves the test body did not run.
        self.assertFalse(
            os.path.exists(self.marker),
            msg=f"Marker exists; test body ran. stderr={result.stderr!r}",
        )
        # Discovery still happened: the test name appears in -v output.
        self.assertIn("test_runs", result.stderr)


# ===========================================================================
# 18. Doctests plugin
# ===========================================================================

class TestDoctestsPlugin(unittest.TestCase):
    """Doctests plugin discovers doctests in module function docstrings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_passing_doctest_in_module_docstring_runs(self):
        """A passing doctest in a function docstring is discovered and reported as success."""
        _make_test_project(self.tmpdir, {
            "mod_with_doctest.py": '''\
                def add(a, b):
                    """Return the sum.

                    >>> add(2, 3)
                    5
                    >>> add(-1, 1)
                    0
                    """
                    return a + b
            ''',
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.doctests", "--with-doctest"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # DocTestSuite yields exactly one test per docstring-with-examples, regardless of how
        # many >>> examples it contains; the single doctest-bearing function gives a count of 1.
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["failures"], 0)
        self.assertEqual(summary["errors"], 0)

    def test_failing_doctest_causes_nonzero_exit(self):
        """A doctest with the wrong expected output causes non-zero exit and a failure."""
        _make_test_project(self.tmpdir, {
            "mod_bad_doctest.py": '''\
                def bad(x):
                    """Wrong expected output below.

                    >>> bad(1)
                    99
                    """
                    return x
            ''',
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.doctests", "--with-doctest"],
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        summary = _parse_summary(result.stderr)
        # Either counted as a failure or an error — both indicate the doctest didn't pass.
        self.assertGreater(summary["failures"] + summary["errors"], 0)


# ===========================================================================
# 19. Coverage plugin
# ===========================================================================

class TestCoveragePlugin(unittest.TestCase):
    """Coverage plugin produces a coverage report that names measured files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_coverage_report_lists_measured_module(self):
        """`--with-coverage --coverage <pkg>` runs tests and emits a report mentioning the module."""
        _make_test_project(self.tmpdir, {
            "mymod.py": """\
                def my_function(x):
                    if x > 0:
                        return x * 2
                    return 0
            """,
            "test_cov.py": """\
                import unittest
                import mymod

                class TestCov(unittest.TestCase):
                    def test_pos(self):
                        self.assertEqual(mymod.my_function(5), 10)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=[
                "--plugin", "nose2.plugins.coverage",
                "--with-coverage",
                "--coverage", "mymod",
            ],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(_parse_summary(result.stderr)["total"], 1)
        # Coverage report names the measured module (it goes to stdout or stderr depending on impl).
        combined = result.stdout + result.stderr
        self.assertIn("mymod", combined)


# ===========================================================================
# 20. Profiler plugin
# ===========================================================================

class TestProfilerPlugin(unittest.TestCase):
    """Profiler plugin runs tests under cProfile and prints pstats output."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_profile_emits_profiling_output(self):
        """`--profile` produces a 'Profiling results' header and cProfile/pstats output."""
        _make_test_project(self.tmpdir, {
            "test_prof.py": """\
                import unittest

                def hot():
                    return sum(range(100))

                class TestProf(unittest.TestCase):
                    def test_calls_hot(self):
                        for _ in range(50):
                            hot()
                        self.assertEqual(hot(), 4950)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.prof", "--profile"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(_parse_summary(result.stderr)["total"], 1)
        combined = result.stdout + result.stderr
        # pstats output reliably contains the 'function calls' line; the
        # plugin emits a 'profile' header whose exact capitalization/
        # spelling ("Profile results" / "Profiling results") is not
        # specified, so match case-insensitively.
        self.assertRegex(combined, r"(?i)profil(e|ing)")
        self.assertIn("function calls", combined)


# ===========================================================================
# 21. unittest.cfg auto-load
# ===========================================================================

class TestUnittestCfgAutoLoad(unittest.TestCase):
    """nose2 auto-loads `unittest.cfg` from the start directory (no -c needed)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_unittest_cfg_changes_file_pattern_without_dash_c(self):
        """unittest.cfg's `test-file-pattern` is honored without an explicit -c flag."""
        _make_test_project(self.tmpdir, {
            "unittest.cfg": """\
                [unittest]
                test-file-pattern = check_*.py
            """,
            "check_ok.py": """\
                import unittest

                class TestOk(unittest.TestCase):
                    def test_one(self):
                        self.assertTrue(True)
            """,
            "test_ignored.py": """\
                import unittest

                class TestIgnored(unittest.TestCase):
                    def test_should_not_run(self):
                        self.fail("This file should not have been discovered")
            """,
        })
        # No -c flag — nose2 auto-loads unittest.cfg.
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Exactly 1 test must run (the check_ok.py one); test_ignored.py must NOT be picked up.
        self.assertEqual(_parse_summary(result.stderr)["total"], 1)


# ===========================================================================
# 22. Layer setUpTest / tearDownTest per-test hooks
# ===========================================================================

class TestLayerPerTestHooks(unittest.TestCase):
    """Layer classmethods testSetUp/testTearDown fire once per test in the layer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "hook_log.txt")

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_testSetUp_and_testTearDown_fire_once_per_test(self):
        """layer setUp/tearDown fire once each; testSetUp/testTearDown fire once per test."""
        _make_test_project(self.tmpdir, {
            "test_pertest_hook.py": f"""\
                import unittest

                _LOG = {self.log_path!r}

                def _log(msg):
                    with open(_LOG, "a") as f:
                        f.write(msg + "\\n")

                class HookLayer:
                    @classmethod
                    def setUp(cls):
                        _log("layer-setUp")

                    @classmethod
                    def tearDown(cls):
                        _log("layer-tearDown")

                    @classmethod
                    def testSetUp(cls, test):
                        _log("testSetUp")

                    @classmethod
                    def testTearDown(cls, test):
                        _log("testTearDown")

                class TestThree(unittest.TestCase):
                    layer = HookLayer

                    def test_a(self):
                        self.assertTrue(True)

                    def test_b(self):
                        self.assertTrue(True)

                    def test_c(self):
                        self.assertTrue(True)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.layers"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(_parse_summary(result.stderr)["total"], 3)
        with open(self.log_path) as f:
            events = f.read().splitlines()
        self.assertEqual(events.count("layer-setUp"), 1)
        self.assertEqual(events.count("layer-tearDown"), 1)
        self.assertEqual(events.count("testSetUp"), 3)
        self.assertEqual(events.count("testTearDown"), 3)


# ===========================================================================
# 23. Multiprocess failure isolation
# ===========================================================================

class TestMultiprocessFailureIsolation(unittest.TestCase):
    """A failing test in one mp worker does not prevent other tests from running."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_one_failure_does_not_skip_other_tests(self):
        """4 tests across 2 workers, 1 fails; all 4 still run, overall reports failure."""
        _make_test_project(self.tmpdir, {
            "test_mp_iso.py": """\
                import unittest

                class TestIso(unittest.TestCase):
                    def test_one(self):
                        self.assertTrue(True)

                    def test_two_fails(self):
                        self.assertEqual(1, 2)

                    def test_three(self):
                        self.assertTrue(True)

                    def test_four(self):
                        self.assertTrue(True)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.mp", "-N", "2"],
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["failures"], 1)


# ===========================================================================
# 24. DunderTest filter (__test__ = False excludes from discovery)
# ===========================================================================

class TestDunderTestFilter(unittest.TestCase):
    """Tests with __test__ = False are excluded by the always-on DunderTest filter."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_dundertest_false_excludes_class(self):
        """A test class with __test__ = False is silently dropped from the run."""
        _make_test_project(self.tmpdir, {
            "test_dunder.py": """\
                import unittest

                class TestIncluded(unittest.TestCase):
                    def test_a(self):
                        self.assertTrue(True)

                    def test_b(self):
                        self.assertTrue(True)

                class TestExcluded(unittest.TestCase):
                    __test__ = False

                    def test_should_not_run(self):
                        self.fail("DunderTest filter should have excluded this class")
            """,
        })
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Only TestIncluded's 2 methods must run; TestExcluded's method must be filtered.
        self.assertEqual(_parse_summary(result.stderr)["total"], 2)


# ===========================================================================
# 25. PrettyAssert plugin
# ===========================================================================

class TestPrettyAssertPlugin(unittest.TestCase):
    """PrettyAssert decorates bare `assert` failures with source + variable values."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_pretty_assert_includes_source_and_locals(self):
        """Failed `assert` from a bare statement shows the assertion source and value(s) in stderr."""
        _make_test_project(self.tmpdir, {
            "test_pretty.py": """\
                import unittest

                class TestPretty(unittest.TestCase):
                    def test_pretty_fail(self):
                        expected_value = 42
                        actual_value = 7
                        assert actual_value == expected_value
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.prettyassert", "--pretty-assert"],
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["failures"], 1)
        # PrettyAssert must include the variable names from the source assertion.
        self.assertIn("actual_value", result.stderr)
        self.assertIn("expected_value", result.stderr)


# ===========================================================================
# 26. TestID plugin (assigns IDs + supports rerun by ID)
# ===========================================================================

class TestIdPlugin(unittest.TestCase):
    """TestID assigns stable integer IDs and persists them in .noseids for rerun."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _make_test_project(self.tmpdir, {
            "test_ids.py": """\
                import unittest

                class TestIds(unittest.TestCase):
                    def test_first(self):
                        self.assertTrue(True)

                    def test_second(self):
                        self.assertTrue(True)

                    def test_third(self):
                        self.assertTrue(True)
            """,
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_with_id_emits_ids_and_supports_rerun_by_id(self):
        """First run assigns #1/#2/#3 ids and writes .noseids; second run with `1` arg reruns just test #1."""
        first = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.testid", "--with-id", "-v"],
        )
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        self.assertEqual(_parse_summary(first.stderr)["total"], 3)
        # ID markers must appear in the verbose stderr.
        self.assertIn("#1", first.stderr)
        self.assertIn("#2", first.stderr)
        self.assertIn("#3", first.stderr)
        # The .noseids persistence file must have been written.
        self.assertTrue(
            os.path.exists(os.path.join(self.tmpdir, ".noseids")),
            msg=f".noseids file missing. stderr={first.stderr!r}",
        )
        # Rerun using a numeric ID — only that one test should execute.
        second = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.testid", "--with-id", "1"],
        )
        self.assertEqual(second.returncode, 0, msg=second.stderr)
        self.assertEqual(_parse_summary(second.stderr)["total"], 1)


# ===========================================================================
# 27. Outcomes plugin (remap exception → skip)
# ===========================================================================

class TestOutcomesPlugin(unittest.TestCase):
    """Outcomes plugin remaps a configured exception class to 'skipped' instead of error."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_set_outcomes_treats_configured_exception_as_skip(self):
        """A NotImplementedError raised by a test is reported as skipped (not error) when configured."""
        _make_test_project(self.tmpdir, {
            "nose2.cfg": """\
                [outcomes]
                treat-as-skip = NotImplementedError
            """,
            "test_outcomes.py": """\
                import unittest

                class TestOutcomes(unittest.TestCase):
                    def test_raises_not_implemented(self):
                        raise NotImplementedError("not done yet")
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.outcomes", "--set-outcomes"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["errors"], 0)

    def test_set_outcomes_treats_configured_exception_as_fail(self):
        """A NotImplementedError raised by a test is reported as a failure (not error) when configured."""
        _make_test_project(self.tmpdir, {
            "nose2.cfg": """\
                [outcomes]
                treat-as-fail = NotImplementedError
            """,
            "test_outcomes_fail.py": """\
                import unittest

                class TestOutcomesFail(unittest.TestCase):
                    def test_raises_not_implemented(self):
                        raise NotImplementedError("not done yet")
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.outcomes", "--set-outcomes"],
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["failures"], 1)
        self.assertEqual(summary["errors"], 0)


# ===========================================================================
# 28. Doctests from .rst text file
# ===========================================================================

class TestDoctestsTextFile(unittest.TestCase):
    """Doctests plugin loads doctest examples from .rst/.txt text files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_doctest_in_rst_file_is_discovered_and_runs(self):
        """A passing doctest inside a standalone .rst file is found and runs to success."""
        _make_test_project(self.tmpdir, {
            "examples.rst": """\
                Some prose explaining a function::

                    >>> 1 + 1
                    2
                    >>> "abc".upper()
                    'ABC'
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.doctests", "--with-doctest"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # DocFileTest produces exactly one test case for the standalone text file, regardless of
        # how many >>> examples it contains, so the reported count must be exactly 1.
        summary = _parse_summary(result.stderr)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["failures"], 0)
        self.assertEqual(summary["errors"], 0)


# ===========================================================================
# 29. Buffer plugin via config (always-on, no -B flag)
# ===========================================================================

class TestBufferConfigAlwaysOn(unittest.TestCase):
    """Output buffer plugin can be enabled via config without the -B flag."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_buffer_activated_by_config_without_dash_b(self):
        """[output-buffer] always-on = True activates buffer; stdout from failing test still appears in failure report."""
        _make_test_project(self.tmpdir, {
            "nose2.cfg": """\
                [output-buffer]
                always-on = True
            """,
            "test_buf_cfg.py": """\
                import unittest

                class TestBufCfg(unittest.TestCase):
                    def test_with_output(self):
                        print("CFG_BUFFERED_MARKER")
                        self.assertEqual(1, 2)
            """,
        })
        # NOTE: no -B flag; buffering comes from the config file.
        result = _run_nose2_subprocess(self.tmpdir)
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        # Captured stdout appears in the failure report (buffer plugin was active).
        self.assertIn("CFG_BUFFERED_MARKER", result.stderr)


# ===========================================================================
# 30. PrintHooks plugin
# ===========================================================================

class TestPrintHooksPlugin(unittest.TestCase):
    """PrintHooks plugin prints plugin hook names in execution order."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_print_hooks_emits_known_hook_names(self):
        """--print-hooks prints common lifecycle hook names like startTestRun and startTest."""
        _make_test_project(self.tmpdir, {
            "test_ph.py": """\
                import unittest

                class TestPh(unittest.TestCase):
                    def test_one(self):
                        self.assertTrue(True)
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["--plugin", "nose2.plugins.printhooks", "--print-hooks"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Hook names from nose2's events module must appear in the output.
        combined = result.stdout + result.stderr
        self.assertIn("startTestRun", combined)
        self.assertIn("startTest", combined)
        self.assertIn("stopTest", combined)


# ===========================================================================
# 31. Positional test name at class granularity
# ===========================================================================

class TestPartialClassNameSelection(unittest.TestCase):
    """A positional argument of the form `module.TestClass` runs every test method in that class only."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_run_all_methods_of_one_class(self):
        """Selecting just `module.TestFoo` runs both TestFoo methods and zero TestBar methods."""
        _make_test_project(self.tmpdir, {
            "test_classes.py": """\
                import unittest

                class TestFoo(unittest.TestCase):
                    def test_foo_one(self):
                        self.assertTrue(True)

                    def test_foo_two(self):
                        self.assertTrue(True)

                class TestBar(unittest.TestCase):
                    def test_bar_one(self):
                        self.fail("TestBar should not run when selecting TestFoo")

                    def test_bar_two(self):
                        self.fail("TestBar should not run when selecting TestFoo")
            """,
        })
        result = _run_nose2_subprocess(
            self.tmpdir,
            extra_args=["test_classes.TestFoo"],
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        # Exactly 2 tests run (both TestFoo methods); TestBar's 2 methods must be excluded.
        self.assertEqual(_parse_summary(result.stderr)["total"], 2)


if __name__ == "__main__":
    unittest.main()
