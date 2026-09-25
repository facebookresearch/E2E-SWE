"""Hidden test suite for the pytest-bdd reproduction task.

pytest-bdd is a pytest plugin, so every test drives the candidate's plugin
end-to-end through pytest's bundled ``pytester`` fixture: an inner test module
and ``.feature`` file are written into a throwaway project, an inner pytest
session is run, and we assert on its outcomes and output. Correctness contracts
are baked into the inner step functions (an assertion inside a step fails the
inner test), so a passing inner outcome means the behaviour was actually right.

``pytester`` is enabled with ``-p pytester`` on the command line (see test.sh).
"""

from __future__ import annotations

import json
import textwrap


def test_basic_given_when_then_scenario(pytester):
    """A user binds a feature's Given/When/Then to step functions with scenario(),
    shares state across steps via target_fixture, and the decorated test runs
    after all steps with the target fixture available."""
    pytester.makefile(
        ".feature",
        basic=textwrap.dedent(
            """\
            Feature: Wallet
                Scenario: Spend money
                    Given I have 100 in my wallet
                    When I spend 30
                    Then I should have 70 in my wallet
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when, then

            @given("I have 100 in my wallet", target_fixture="wallet")
            def _():
                return {"amount": 100}

            @when("I spend 30")
            def _(wallet):
                wallet["amount"] -= 30

            @then("I should have 70 in my wallet")
            def _(wallet):
                assert wallet["amount"] == 70

            @scenario("basic.feature", "Spend money")
            def test_spend(request):
                # body runs after the steps; the target fixture is reachable via request
                assert request.getfixturevalue("wallet")["amount"] == 70
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_scenarios_autocollects_all(pytester):
    """scenarios() collects every scenario found across the given feature files or
    directories and injects a test for each into the calling module."""
    pytester.makefile(
        ".feature",
        a=textwrap.dedent(
            """\
            Feature: A
                Scenario: one
                    Given setup
                    Then ok
                Scenario: two
                    Given setup
                    Then ok
            """
        ),
        b=textwrap.dedent(
            """\
            Feature: B
                Scenario: three
                    Given setup
                    Then ok
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, then

            @given("setup")
            def _():
                pass

            @then("ok")
            def _():
                pass

            scenarios(".")
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=3)


def test_step_parsers(pytester):
    """parsers.parse (typed fields + converters), parsers.re (named groups) and
    parsers.cfparse extract and convert step arguments; each parsed value is
    asserted for both value and type inside the steps."""
    pytester.makefile(
        ".feature",
        parsers=textwrap.dedent(
            """\
            Feature: Parsers
                Scenario: parse typed fields
                    Given there are 12 cucumbers
                    When I eat 5 cucumbers
                    Then I should have 7 cucumbers

                Scenario: converters
                    Given the price is 10 dollars

                Scenario: regex parser
                    When I refer to user bob

                Scenario: cfparse parser
                    Then the total is 42
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, when, then, parsers

            scenarios("parsers.feature")

            @given(parsers.parse("there are {start:d} cucumbers"), target_fixture="basket")
            def _(start):
                assert isinstance(start, int)
                return {"n": start}

            @when(parsers.parse("I eat {eat:d} cucumbers"))
            def _(basket, eat):
                assert isinstance(eat, int)
                basket["n"] -= eat

            @then(parsers.parse("I should have {left:d} cucumbers"))
            def _(basket, left):
                assert basket["n"] == left

            @given(parsers.parse("the price is {amount} dollars"), converters={"amount": int})
            def _(amount):
                assert amount == 10 and isinstance(amount, int)

            @when(parsers.re(r"I refer to user (?P<name>[a-z]+)"))
            def _(name):
                assert name == "bob"

            @then(parsers.cfparse("the total is {value:d}"))
            def _(value):
                assert value == 42 and isinstance(value, int)
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=4)


def test_step_fixtures_target_and_yield(pytester):
    """Steps can request existing pytest fixtures, a step can yield (so teardown
    runs after the scenario), and target_fixture rebinding chains a value across
    successive steps."""
    pytester.makefile(
        ".feature",
        fix=textwrap.dedent(
            """\
            Feature: Fixtures
                Scenario: chaining and fixtures
                    Given a base number
                    And the number doubled
                    When combined with the offset
                    Then the result is 25
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            import pytest
            from pytest_bdd import scenario, given, when, then

            teardown_log = []

            @pytest.fixture
            def offset():
                return 5

            @given("a base number", target_fixture="number")
            def _():
                yield 10
                teardown_log.append("torn down")

            @given("the number doubled", target_fixture="number")
            def _(number):
                return number * 2

            @when("combined with the offset", target_fixture="number")
            def _(number, offset):
                return number + offset

            @then("the result is 25")
            def _(number):
                assert number == 25

            @scenario("fix.feature", "chaining and fixtures")
            def test_chain():
                pass

            def test_teardown_ran_after_scenario():
                assert teardown_log == ["torn down"]
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)


def test_scenario_outline_examples(pytester):
    """A Scenario Outline expands its Examples table into one parametrized test per
    row, substituting <placeholders> into the steps; the parametrization id is the
    row's values joined with '-'."""
    pytester.makefile(
        ".feature",
        outline=textwrap.dedent(
            """\
            Feature: Outline
                Scenario Outline: eat cucumbers
                    Given there are <start> cucumbers
                    When I eat <eat> cucumbers
                    Then I should have <left> cucumbers

                    Examples:
                    | start | eat | left |
                    | 12    | 5   | 7    |
                    | 5     | 4   | 1    |
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when, then, parsers

            @given(parsers.parse("there are {start:d} cucumbers"), target_fixture="basket")
            def _(start):
                return {"n": start}

            @when(parsers.parse("I eat {eat:d} cucumbers"))
            def _(basket, eat):
                basket["n"] -= eat

            @then(parsers.parse("I should have {left:d} cucumbers"))
            def _(basket, left):
                assert basket["n"] == left

            @scenario("outline.feature", "eat cucumbers")
            def test_outline():
                pass
            """
        )
    )
    result = pytester.runpytest("-v")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*12-5-7*"])
    result.stdout.fnmatch_lines(["*5-4-1*"])


def test_background_steps(pytester):
    """Background steps run before every scenario's own steps in the feature."""
    pytester.makefile(
        ".feature",
        bg=textwrap.dedent(
            """\
            Feature: Background
                Background:
                    Given a starting balance of 50

                Scenario: deposit
                    When I deposit 10
                    Then the balance is 60

                Scenario: withdraw
                    When I withdraw 20
                    Then the balance is 30
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, when, then, parsers

            scenarios("bg.feature")

            @given(parsers.parse("a starting balance of {n:d}"), target_fixture="acct")
            def _(n):
                return {"bal": n}

            @when(parsers.parse("I deposit {n:d}"))
            def _(acct, n):
                acct["bal"] += n

            @when(parsers.parse("I withdraw {n:d}"))
            def _(acct, n):
                acct["bal"] -= n

            @then(parsers.parse("the balance is {n:d}"))
            def _(acct, n):
                assert acct["bal"] == n
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)


def test_tags_become_markers(pytester):
    """Feature- and scenario-level tags become pytest markers selectable with -m;
    a feature tag applies to all its scenarios."""
    pytester.makefile(
        ".ini",
        pytest=textwrap.dedent(
            """\
            [pytest]
            markers =
                web
                smoke
                slow
            """
        ),
    )
    pytester.makefile(
        ".feature",
        tags=textwrap.dedent(
            """\
            @web
            Feature: Tagged
                @smoke
                Scenario: fast one
                    Given a step

                @slow
                Scenario: slow one
                    Given a step
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given

            @given("a step")
            def _():
                pass

            scenarios("tags.feature")
            """
        )
    )
    # feature-level tag selects both scenarios
    result = pytester.runpytest("-m", "web", "-v")
    result.assert_outcomes(passed=2)
    # scenario-level tag selects exactly one and deselects the other
    outcomes = pytester.runpytest("-m", "smoke and not slow", "-v").parseoutcomes()
    assert outcomes["passed"] == 1
    assert outcomes["deselected"] == 1


def test_and_but_inherit_step_type(pytester):
    """And/But steps take the type of the preceding Given/When/Then, so they match
    step definitions of that inherited type and execute in order."""
    pytester.makefile(
        ".feature",
        andbut=textwrap.dedent(
            """\
            Feature: Continuation
                Scenario: mixed
                    Given an account
                    And it is funded
                    When a charge happens
                    And another charge happens
                    Then it is settled
                    But not overdrawn
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when, then

            log = []

            @given("an account")
            def _():
                log.append("g1")

            @given("it is funded")
            def _():
                log.append("g2")

            @when("a charge happens")
            def _():
                log.append("w1")

            @when("another charge happens")
            def _():
                log.append("w2")

            @then("it is settled")
            def _():
                log.append("t1")

            @then("not overdrawn")
            def _():
                log.append("t2")

            @scenario("andbut.feature", "mixed")
            def test_mixed():
                assert log == ["g1", "g2", "w1", "w2", "t1", "t2"]
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_missing_step_definition_error(pytester):
    """A scenario step with no matching definition raises StepDefinitionNotFoundError
    naming the step type, text, line number and scenario."""
    pytester.makefile(
        ".feature",
        missing=textwrap.dedent(
            """\
            Feature: Missing
                Scenario: no def
                    Given there is a defined step
                    When there is an undefined step
                    Then nothing
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, then

            @given("there is a defined step")
            def _():
                pass

            @then("nothing")
            def _():
                pass

            @scenario("missing.feature", "no def")
            def test_missing():
                pass
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines(
        [
            '*StepDefinitionNotFoundError: Step definition is not found: When "there is an undefined step". '
            'Line 4 in scenario "no def"*'
        ]
    )


def test_generic_step_decorator(pytester):
    """A step defined with step() (no type) matches Given, When and Then lines alike."""
    pytester.makefile(
        ".feature",
        generic=textwrap.dedent(
            """\
            Feature: Generic
                Scenario: any keyword
                    Given do the thing
                    When do the thing
                    Then do the thing
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, step

            count = []

            @step("do the thing")
            def _():
                count.append(1)

            @scenario("generic.feature", "any keyword")
            def test_generic():
                assert len(count) == 3
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_datatable_argument(pytester):
    """A step with a Gherkin data table receives it via the reserved `datatable`
    argument as a list of rows (header included), each cell a string."""
    pytester.makefile(
        ".feature",
        dt=textwrap.dedent(
            """\
            Feature: Datatable
                Scenario: users
                    Given the following users:
                        | name  | age |
                        | John  | 30  |
                        | Alice | 25  |
                    Then 2 users exist
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, then, parsers

            @given("the following users:", target_fixture="users")
            def _(datatable):
                assert datatable == [["name", "age"], ["John", "30"], ["Alice", "25"]]
                return datatable[1:]

            @then(parsers.parse("{n:d} users exist"))
            def _(users, n):
                assert len(users) == n

            @scenario("dt.feature", "users")
            def test_dt():
                pass
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_docstring_argument(pytester):
    """A step with a Gherkin docstring receives it via the reserved `docstring`
    argument, dedented to the docstring's own indentation."""
    pytester.makefile(
        ".feature",
        ds=textwrap.dedent(
            '''\
            Feature: Docstring
                Scenario: doc
                    Given a payload:
                        """
                        line one
                        line two
                        """
                    Then the payload has 2 lines
            '''
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            '''\
            from pytest_bdd import scenario, given, then, parsers

            @given("a payload:", target_fixture="payload")
            def _(docstring):
                assert docstring == "line one\\nline two"
                return docstring

            @then(parsers.parse("the payload has {n:d} lines"))
            def _(payload, n):
                assert len(payload.splitlines()) == n

            @scenario("ds.feature", "doc")
            def test_ds():
                pass
            '''
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_gherkin_terminal_reporter(pytester):
    """--gherkin-terminal-reporter renders Feature/Scenario lines at -v and the
    individual step lines at -vv."""
    pytester.makefile(
        ".feature",
        report=textwrap.dedent(
            """\
            Feature: Reporting feature
                Scenario: the scenario
                    Given there is a bar
                    When the bar is accessed
                    Then it works
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when, then

            @given("there is a bar")
            def _():
                pass

            @when("the bar is accessed")
            def _():
                pass

            @then("it works")
            def _():
                pass

            @scenario("report.feature", "the scenario")
            def test_report():
                pass
            """
        )
    )
    result = pytester.runpytest("--gherkin-terminal-reporter", "-v")
    result.assert_outcomes(passed=1)
    # the Feature header is one of the two lines the reporter emits per scenario, so it must
    # begin a line of its own (the scenario line below is the indented one)
    result.stdout.fnmatch_lines(["Feature: Reporting feature*"])
    result.stdout.fnmatch_lines(["*Scenario: the scenario PASSED"])

    result = pytester.runpytest("--gherkin-terminal-reporter", "-vv")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*Given there is a bar"])
    result.stdout.fnmatch_lines(["*When the bar is accessed"])
    result.stdout.fnmatch_lines(["*Then it works"])


def test_code_generation(pytester):
    """The `pytest-bdd generate` console script prints step-stub code for a feature,
    and `--generate-missing` reports scenarios not bound to tests and undefined steps."""
    pytester.makefile(
        ".feature",
        gen=textwrap.dedent(
            """\
            Feature: Generation
                Scenario: do something
                    Given I have a precondition
                    When I do an action
                    Then I observe an outcome
                Scenario: do another
                    Given I have a precondition
                    When I do another action
                    Then I observe an outcome
            """
        ),
    )
    # console script: prints a runnable test module skeleton
    result = pytester.run("pytest-bdd", "generate", "gen.feature")
    result.stdout.fnmatch_lines(['"""Generation feature tests."""'])
    result.stdout.fnmatch_lines(["from pytest_bdd import ("])
    result.stdout.fnmatch_lines(["@scenario('gen.feature', 'do something')"])
    result.stdout.fnmatch_lines(["@scenario('gen.feature', 'do another')"])
    result.stdout.fnmatch_lines(["*raise NotImplementedError*"])
    out = result.stdout.str()
    # steps are de-duplicated: the Given/Then shared by both scenarios appear once
    assert out.count("@given('I have a precondition')") == 1
    assert out.count("@then('I observe an outcome')") == 1
    # both distinct When stubs are generated
    assert "@when('I do an action')" in out
    assert "@when('I do another action')" in out
    # stubs are grouped by type in Given -> When -> Then order
    assert (
        out.index("@given('I have a precondition')")
        < out.index("@when('I do an action')")
        < out.index("@then('I observe an outcome')")
    )

    # --generate-missing: a bound scenario with one undefined step is reported,
    # followed by the generated stub code.
    pytester.makefile(
        ".feature",
        miss=textwrap.dedent(
            """\
            Feature: Missing
                Scenario: partly done
                    Given a known step
                    When an unknown step
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given

            @given("a known step")
            def _():
                pass

            @scenario("miss.feature", "partly done")
            def test_partly():
                pass
            """
        )
    )
    result = pytester.runpytest("--generate-missing", "--feature", "miss.feature")
    result.stdout.fnmatch_lines(['*Step When "an unknown step" is not defined in the scenario "partly done"*'])
    result.stdout.fnmatch_lines(["Please place the code above to the test file(s):"])
    result.stdout.fnmatch_lines(["@when('an unknown step')"])


def test_scenario_lookup_errors(pytester):
    """scenario() with an unknown scenario name raises ScenarioNotFound; scenarios()
    over a location containing no feature files raises NoScenariosFound."""
    pytester.makefile(
        ".feature",
        e=textwrap.dedent(
            """\
            Feature: Errors
                Scenario: real one
                    Given a step
            """
        ),
    )
    pytester.makepyfile(
        test_notfound=textwrap.dedent(
            """\
            from pytest_bdd import scenario, given

            @given("a step")
            def _():
                pass

            @scenario("e.feature", "does not exist")
            def test_x():
                pass
            """
        )
    )
    result = pytester.runpytest("test_notfound.py")
    # The spec pins only the observable exception class + message, not whether the
    # error surfaces at collection time (errors) or run time (failed); accept either.
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*ScenarioNotFound*does not exist*"])

    pytester.mkdir("empty")
    pytester.makepyfile(
        test_noscenarios=textwrap.dedent(
            """\
            from pytest_bdd import scenarios

            scenarios("empty")
            """
        )
    )
    result = pytester.runpytest("test_noscenarios.py")
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*NoScenariosFound*"])


def test_cucumber_json_report(pytester):
    """--cucumber-json=PATH writes a cucumber-style JSON report: a list of features,
    each carrying its scenarios as `elements`, each step carrying a `result.status`."""
    pytester.makefile(
        ".feature",
        cuke=textwrap.dedent(
            """\
            Feature: Reporting
                Scenario: passes
                    Given a good step
                Scenario: fails
                    Given a good step
                    When a bad step
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when

            @given("a good step")
            def _():
                pass

            @when("a bad step")
            def _():
                raise Exception("boom")

            @scenario("cuke.feature", "passes")
            def test_passes():
                pass

            @scenario("cuke.feature", "fails")
            def test_fails():
                pass
            """
        )
    )
    out = pytester.path / "cuke.json"
    result = pytester.runpytest(f"--cucumber-json={out}", "-s")
    result.assert_outcomes(passed=1, failed=1)

    data = json.loads(out.read_text())
    assert isinstance(data, list) and len(data) == 1
    feature = data[0]
    assert feature["name"] == "Reporting"
    elements = {e["name"]: e for e in feature["elements"]}
    assert set(elements) == {"passes", "fails"}
    # the passing scenario's single step is reported passed, with keyword + name
    passes_steps = elements["passes"]["steps"]
    assert [s["result"]["status"] for s in passes_steps] == ["passed"]
    assert passes_steps[0]["keyword"] == "Given"
    assert passes_steps[0]["name"] == "a good step"
    # the documented schema fields are populated: feature uri, scenario type/line,
    # step line, and a per-step result.duration. `line` is the 1-based source line in
    # the feature file: the `passes` scenario is on line 2 and its step on line 3.
    assert feature["uri"].endswith("cuke.feature")
    assert elements["passes"]["type"] == "scenario"
    assert elements["passes"]["line"] == 2
    assert passes_steps[0]["line"] == 3
    assert "duration" in passes_steps[0]["result"]
    # the failing scenario records a failed step
    assert "failed" in [s["result"]["status"] for s in elements["fails"]["steps"]]


def test_bdd_all_lifecycle_hooks(pytester):
    """All per-scenario/step BDD hooks fire: before_scenario, before_step,
    before_step_call, after_step (on success), after_scenario (even on failure),
    step_error (on a failing step), and step_func_lookup_error (on a missing step)."""
    pytester.makefile(
        ".feature",
        lc=textwrap.dedent(
            """\
            Feature: Lifecycle
                Scenario: ok
                    Given a good step
                Scenario: boom
                    Given a good step
                    When it explodes
                Scenario: missing
                    Given a good step
                    When undefined step here
            """
        ),
    )
    pytester.makeconftest(
        textwrap.dedent(
            """\
            ev = []
            def pytest_bdd_before_scenario(request, feature, scenario): ev.append("before_scenario:" + scenario.name)
            def pytest_bdd_after_scenario(request, feature, scenario): ev.append("after_scenario:" + scenario.name)
            def pytest_bdd_before_step(request, feature, scenario, step, step_func): ev.append("before_step:" + step.name)
            def pytest_bdd_before_step_call(request, feature, scenario, step, step_func, step_func_args): ev.append("before_step_call:" + step.name)
            def pytest_bdd_after_step(request, feature, scenario, step, step_func, step_func_args): ev.append("after_step:" + step.name)
            def pytest_bdd_step_error(request, feature, scenario, step, step_func, step_func_args, exception): ev.append("step_error:" + step.name + ":" + type(exception).__name__)
            def pytest_bdd_step_func_lookup_error(request, feature, scenario, step, exception): ev.append("lookup_error:" + step.name)
            def pytest_sessionfinish(session):
                import json
                (session.config.rootpath / "ev.json").write_text(json.dumps(ev))
            """
        )
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, when
            scenarios("lc.feature")
            @given("a good step")
            def _():
                pass
            @when("it explodes")
            def _():
                raise ValueError("boom")
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1, failed=2)
    ev = json.loads((pytester.path / "ev.json").read_text())
    assert "before_scenario:ok" in ev and "after_scenario:ok" in ev
    assert "before_step:a good step" in ev
    assert "before_step_call:a good step" in ev
    assert "after_step:a good step" in ev
    assert "step_error:it explodes:ValueError" in ev
    assert "after_scenario:boom" in ev
    assert "lookup_error:undefined step here" in ev


def test_apply_tag_hook(pytester):
    """pytest_bdd_apply_tag is invoked for each feature/scenario tag and can override
    tag handling (returning True suppresses the default marker)."""
    pytester.makefile(
        ".ini",
        pytest=textwrap.dedent(
            """\
            [pytest]
            markers =
                alpha
                beta
            """
        ),
    )
    pytester.makefile(
        ".feature",
        at=textwrap.dedent(
            """\
            @alpha
            Feature: ApplyTag
                @beta
                Scenario: s
                    Given a step
            """
        ),
    )
    pytester.makeconftest(
        textwrap.dedent(
            """\
            seen = []
            def pytest_bdd_apply_tag(tag, function):
                seen.append(tag)
                return True
            def pytest_sessionfinish(session):
                import json
                (session.config.rootpath / "tags.json").write_text(json.dumps(sorted(seen)))
            """
        )
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given
            scenarios("at.feature")
            @given("a step")
            def _():
                pass
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
    seen = json.loads((pytester.path / "tags.json").read_text())
    assert "alpha" in seen and "beta" in seen
    # The hook returned True, so the default markers were suppressed: neither the
    # feature tag (@alpha) nor the scenario tag (@beta) is registered on the test,
    # so -m selection on either deselects the single scenario rather than running it.
    outcomes = pytester.runpytest("-m", "beta").parseoutcomes()
    assert outcomes.get("passed", 0) == 0
    assert outcomes["deselected"] == 1


def test_features_base_dir_and_encoding(pytester):
    """scenario()/scenarios() honour the bdd_features_base_dir ini option (resolved
    from rootdir), and a non-default feature-file encoding is respected."""
    pytester.makefile(".ini", pytest="[pytest]\nbdd_features_base_dir = my_features\n")
    feats = pytester.mkdir("my_features")
    feats.joinpath("e.feature").write_text(
        "Feature: Enc\n    Scenario: s\n        Given a café exists\n", encoding="utf-8"
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given
            scenarios("e.feature")
            @given("a café exists")
            def _():
                pass
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_rule_blocks(pytester):
    """A Rule's scenarios run with BOTH feature-level and rule-level Background steps,
    and a tag on the Rule selects its scenarios via -m."""
    pytester.makefile(".ini", pytest="[pytest]\nmarkers =\n    deposits\n")
    pytester.makefile(
        ".feature",
        acct=textwrap.dedent(
            """\
            Feature: Account
                Background:
                    Given a feature base of 1

                @deposits
                Rule: deposit rule
                    Background:
                        Given a rule base of 10
                    Scenario: do a deposit
                        When I add 5
                        Then the total is 16
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, when, then, parsers

            scenarios("acct.feature")

            @given(parsers.parse("a feature base of {n:d}"), target_fixture="acc")
            def _(n):
                return {"total": n}

            @given(parsers.parse("a rule base of {n:d}"))
            def _(acc, n):
                acc["total"] += n

            @when(parsers.parse("I add {n:d}"))
            def _(acc, n):
                acc["total"] += n

            @then(parsers.parse("the total is {n:d}"))
            def _(acc, n):
                assert acc["total"] == n
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)
    # rule tag selects the scenario
    out = pytester.runpytest("-m", "deposits", "-v").parseoutcomes()
    assert out["passed"] == 1


def test_first_step_must_be_given_when_then(pytester):
    """A scenario whose first step is And/But (no preceding Given/When/Then) is a
    StepError naming the bad keyword."""
    pytester.makefile(
        ".feature",
        bad=textwrap.dedent(
            """\
            Feature: Bad
                Scenario: starts with and
                    And something
                    Then nothing
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, then

            @then("nothing")
            def _():
                pass

            @scenario("bad.feature", "starts with and")
            def test_bad():
                pass
            """
        )
    )
    result = pytester.runpytest()
    # The spec pins only the StepError class + message, not whether it surfaces at
    # collection time (errors) or run time (failed); accept either.
    assert result.ret != 0
    result.stdout.fnmatch_lines(["*StepError*"])
    result.stdout.fnmatch_lines(["*First step in a scenario or background must start with*"])


def test_outline_renders_datatable_and_docstring(pytester):
    """In a Scenario Outline, <placeholders> inside a step's data table and doc string
    are substituted per example row."""
    pytester.makefile(
        ".feature",
        ren=textwrap.dedent(
            '''\
            Feature: Render
                Scenario Outline: render into table and doc
                    Given rows:
                        | who   | amount |
                        | <who> | <amt>  |
                    And a note:
                        """
                        note for <who>
                        """
                    Then captured

                    Examples:
                    | who   | amt |
                    | alice | 5   |
            '''
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            '''\
            from pytest_bdd import scenarios, given, then
            import json, pathlib

            scenarios("ren.feature")

            @given("rows:", target_fixture="dt")
            def _(datatable):
                return datatable

            @given("a note:", target_fixture="doc")
            def _(docstring):
                return docstring

            @then("captured")
            def _(dt, doc):
                pathlib.Path("cap.json").write_text(json.dumps({"dt": dt, "doc": doc}))
            '''
        )
    )
    result = pytester.runpytest("-s")
    result.assert_outcomes(passed=1)
    cap = json.loads((pytester.path / "cap.json").read_text())
    assert cap["dt"] == [["who", "amount"], ["alice", "5"]]
    assert cap["doc"] == "note for alice"


def test_examples_table_tags_select_rows(pytester):
    """Tags on an Examples table become marks on the rows it produces, so -m selects
    only those rows."""
    pytester.makefile(".ini", pytest="[pytest]\nmarkers =\n    positive\n    negative\n")
    pytester.makefile(
        ".feature",
        ex=textwrap.dedent(
            """\
            Feature: Tagged examples
                Scenario Outline: add
                    Given start <a>
                    Then result <b>

                    @positive
                    Examples:
                    | a | b |
                    | 1 | 1 |
                    | 2 | 2 |

                    @negative
                    Examples:
                    | a  | b  |
                    | -1 | -1 |
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, then, parsers

            scenarios("ex.feature")

            @given(parsers.parse("start {a:d}"), target_fixture="s")
            def _(a):
                return a

            @then(parsers.parse("result {b:d}"))
            def _(s, b):
                assert s == b
            """
        )
    )
    result = pytester.runpytest().parseoutcomes()
    assert result["passed"] == 3
    sel = pytester.runpytest("-m", "positive").parseoutcomes()
    assert sel["passed"] == 2 and sel["deselected"] == 1


def test_step_fixture_evaluated_once_and_aliases(pytester):
    """A target_fixture step is evaluated once and reused by later steps; one step
    function can register multiple names via stacked decorators."""
    pytester.makefile(
        ".feature",
        once=textwrap.dedent(
            """\
            Feature: Once
                Scenario: reuse
                    Given a counter
                    When I read it as alpha
                    And I read it as beta
                    Then it was created once
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenario, given, when, then

            creations = []

            @given("a counter", target_fixture="counter")
            def _():
                creations.append(1)
                return {"reads": 0}

            @when("I read it as alpha")
            @when("I read it as beta")
            def _(counter):
                counter["reads"] += 1

            @then("it was created once")
            def _(counter):
                assert len(creations) == 1
                assert counter["reads"] == 2

            @scenario("once.feature", "reuse")
            def test_once():
                pass
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_gherkin_aliases_star_and_comments(pytester):
    """Gherkin keyword aliases (Example/Scenario Template/Scenarios) parse like their
    canonical forms, `#` comment lines are ignored, and the `*` step keyword inherits
    the previous step's type (so it matches a definition of that type)."""
    pytester.makefile(
        ".feature",
        alias=textwrap.dedent(
            """\
            # a leading comment line that must be ignored
            Feature: Aliases
                Example: via the Example keyword
                    Given a base
                    * also runs as a given
                    Then both givens ran

                Scenario Template: via the template keyword
                    Given start <a>
                    * bumped by one
                    Then total <b>

                    Scenarios:
                    | a | b |
                    | 1 | 2 |
            """
        ),
    )
    pytester.makepyfile(
        textwrap.dedent(
            """\
            from pytest_bdd import scenarios, given, then, parsers

            log = []
            scenarios("alias.feature")

            @given("a base")
            def _():
                log.append("base")

            @given("also runs as a given")
            def _():
                log.append("star")

            @then("both givens ran")
            def _():
                assert "base" in log and "star" in log

            @given(parsers.parse("start {a:d}"), target_fixture="acc")
            def _(a):
                return {"v": a}

            @given("bumped by one")
            def _(acc):
                acc["v"] += 1

            @then(parsers.parse("total {b:d}"))
            def _(acc, b):
                assert acc["v"] == b
            """
        )
    )
    result = pytester.runpytest()
    result.assert_outcomes(passed=2)
