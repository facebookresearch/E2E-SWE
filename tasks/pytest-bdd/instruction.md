# pytest-bdd

Build `pytest_bdd`, a Behaviour-Driven-Development plugin for pytest: users write
Gherkin `.feature` files and bind their steps to Python functions, so scenarios
run as ordinary pytest tests that reuse pytest fixtures.

Organise the internals however you like, as long as the public imports, the
pytest-plugin behaviour, the console script, and the observable outputs below all
resolve and match.

## Example use case

You describe behaviour in a Gherkin `.feature` file and implement each step in a Python module; binding the scenario turns it into an ordinary pytest test.

```gherkin
# thermostat.feature
Feature: Thermostat
    Scenario: Warm the room
        Given the thermostat is set to 18 degrees
        When I raise it by 4 degrees
        Then the thermostat reads 22 degrees
```

```python
# test_thermostat.py
from pytest_bdd import scenario, given, when, then

@given("the thermostat is set to 18 degrees", target_fixture="thermostat")
def _():
    return {"target": 18}

@when("I raise it by 4 degrees")
def _(thermostat):
    thermostat["target"] += 4

@then("the thermostat reads 22 degrees")
def _(thermostat):
    assert thermostat["target"] == 22

@scenario("thermostat.feature", "Warm the room")
def test_warm_the_room():
    pass
```

## Dependencies & packaging

The environment is **offline**: every dependency below is **already installed** — do not attempt to
install anything (there is no network). The project is built and installed for you by a `setup.sh`
that runs offline (`pip install -e . --no-build-isolation`, against the pre-baked build backend and
deps), so it must be installable that way from your `pyproject.toml` / `setup.py`.

Depends on `pytest` (>= 7). It must install and **auto-load as a pytest plugin** (so its fixtures,
command-line options and scenario behaviour are active whenever pytest runs, after the offline
`pip install -e .`), and provide a `pytest-bdd` console script. The following libraries are
pre-installed and available: `gherkin-official` (Gherkin parsing), `parse` / `parse-type`
(step-argument parsing), and `Mako` (code generation).

## Public API

```python
from pytest_bdd import given, when, then, step, scenario, scenarios, parsers
```

- `given` / `when` / `then` / `step` decorate step functions. The step name is a
  string (exact match) or a parser object. They accept optional `converters` (a
  `{arg: callable}` map applied to parsed arguments) and `target_fixture` (see
  *Step execution*). `step` also takes `type_` — `None` (default) matches a step
  of any type; `given`/`when`/`then` fix the type. A function may stack several
  decorators to answer to multiple step names.
- `parsers` provides step-name parsers: `parsers.parse` and `parsers.cfparse`
  (the `parse`/cfparse format with `{name}` / `{name:type}` fields),
  `parsers.re` (a regex that must fullmatch; arguments are its named groups), and
  `parsers.string` (exact match — what a bare string is wrapped in).
- `scenario(feature_name, scenario_name)` is a decorator binding one scenario of a
  feature file to a test function; the function body runs **after** the steps and
  may take fixtures (including target fixtures, retrieved via the `request`).
- `scenarios(*paths)` loads every scenario under the given files/directories
  (directories scanned recursively for `*.feature`) and injects one test per
  scenario into the calling module. Feature paths resolve relative to the calling
  test module's directory, unless `features_base_dir` is passed or the
  `bdd_features_base_dir` ini option is set (taken relative to the pytest rootdir);
  `scenario` also accepts an `encoding` (default `utf-8`).

## Gherkin

Support a `Feature` (with optional description and tags), an optional
`Background`, `Scenario` / `Scenario Outline` blocks, and `Rule:` blocks (a rule
may have its own `Background` and scenarios; a scenario under a rule runs the
feature background, then the rule background, then its own steps). Keyword
aliases: `Scenario`/`Example`, `Scenario Outline`/`Scenario Template`,
`Examples`/`Scenarios`. Also support `#` comments, `@tags`, step data tables, step
doc strings, and the step keywords `Given`/`When`/`Then`/`And`/`But`/`*`. The first
step of a scenario or background must be `Given`/`When`/`Then`; `And`/`But`/`*`
**inherit the previous step's type** and are matched as that type. Background
steps run before each scenario's own steps.

## Step execution

Each step is matched to a definition of a compatible type (or a generic `step`)
whose parser matches the text, and the step function is then called with:

- parsed arguments whose names appear in its signature (after `converters`);
- the reserved `datatable` argument — the step's data table as a list of rows
  **including the header row**, every cell a string — and/or the reserved
  `docstring` argument — the doc-string content, dedented — if declared;
- any other parameters resolved as ordinary **pytest fixtures**.

A step may `yield` instead of `return` (code after the `yield` runs as teardown
after the scenario). If `target_fixture="x"` is set, the return value becomes a
fixture named `x` available to later steps and the scenario's test body; reusing
the same name in successive steps chains the value through, and a target fixture
is evaluated once and reused.

## Scenario outlines

An outline with an `Examples` table yields **one parametrized test per row**;
each `<placeholder>` in a step's text (and in data-table cells / doc strings) is
replaced by that row's value (a placeholder with no column is left unchanged).
The **test id of a row is its cell values joined with `-`** (row `| 12 | 5 | 7 |`
→ id `12-5-7`). Multiple `Examples` tables under one outline are all expanded.

## Tags

Feature and scenario tags become pytest markers (the `@` stripped), so `-m`
selects scenarios. Tags inherit down the Gherkin nesting (feature → rule →
scenario → examples): a feature tag applies to every scenario in the feature, a
tag on a `Rule:` applies to every scenario under that rule, and a tag on an
`Examples` table becomes a mark on the rows that table produces.

## Hooks

Provide these pytest hook specifications (a project implements them in its
`conftest.py`); call each at the appropriate point:

- `pytest_bdd_before_scenario(request, feature, scenario)` and
  `pytest_bdd_after_scenario(request, feature, scenario)` — the latter runs even
  if a step failed.
- `pytest_bdd_before_step(request, feature, scenario, step, step_func)`,
  `pytest_bdd_before_step_call(request, feature, scenario, step, step_func, step_func_args)`,
  and `pytest_bdd_after_step(request, feature, scenario, step, step_func, step_func_args)`
  (after-step only on success).
- `pytest_bdd_step_error(request, feature, scenario, step, step_func, step_func_args, exception)`
  — a step raised an exception.
- `pytest_bdd_step_func_lookup_error(request, feature, scenario, step, exception)`
  — no step definition matched the step.
- `pytest_bdd_apply_tag(tag, function)` — apply one tag to the scenario's test
  (firstresult; the default does `getattr(pytest.mark, tag)(function)`, and an
  implementation returning `True` overrides that default).

The `scenario` exposes `.name`; a `step` exposes `.name`.

## Errors

Expose these exception classes (the class name and its message text are the
observable contract — they surface in the pytest traceback and the tests match
on them):

- **`StepDefinitionNotFoundError`** — a step has no matching definition. Message:
  `Step definition is not found: <Keyword> "<step text>". Line <n> in scenario "<scenario name>" in the feature "<feature file path>"` (`<Keyword>` = the step's
  type capitalised — `Given`/`When`/`Then`; `<n>` = the 1-based source line of the
  step within the feature file, as for `line` in the cucumber-json output).
- **`ScenarioNotFound`** — `scenario()` with an unknown scenario name:
  `Scenario "<name>" in feature "<feature name>" in <file> is not found.`
- **`NoScenariosFound`** — `scenarios()` finds no scenarios.
- **`StepError`** — a scenario or background whose first step is `And`/`But`/`*`
  (no preceding `Given`/`When`/`Then`); the message begins
  `First step in a scenario or background must start with 'Given', 'When' or 'Then'`.

## Command-line tools & reporters

- **`pytest-bdd generate FEATURE_FILE...`** prints a test-module skeleton: a
  module docstring `"""<feature name> feature tests."""`; the import block, exactly:

  ```
  from pytest_bdd import (
      given,
      scenario,
      then,
      when,
  )
  ```

  one `@scenario('<feature path>', '<scenario name>')` + `def test_...()` per
  scenario; and one stub per undefined step:

  ```
  @given('<step text>')
  def _():
      """<step text>."""
      raise NotImplementedError
  ```

  (using the step's type, step text as a single-quoted literal; steps de-duped and
  grouped by type then name — the type groups are emitted in `Given` → `When` →
  `Then` order, and the stubs within a group are ordered by step text).

- **`--generate-missing --feature FILE_OR_DIR`** (repeatable) — instead of running
  tests, print each scenario not bound to a test
  (`Scenario "<name>" is not bound to any test in the feature "<feature name>" in the file <file>:<line>`)
  and each undefined step
  (`Step <Keyword> "<step text>" is not defined in the scenario "<scenario name>" in the feature "<feature name>" in the file <file>:<line>`),
  then the line `Please place the code above to the test file(s):` followed by the
  generated code.

- **`--gherkin-terminal-reporter`** — at `-v`, two lines per scenario:
  `<Feature keyword>: <feature name>` and an indented
  `<Scenario keyword>: <scenario name> <STATUS>` (e.g. `Scenario: the scenario PASSED`);
  at `-vv`, additionally one indented line per step (`<Keyword> <step text>`) then
  the status.

- **`--cucumber-json=PATH`** (alias `--cucumberjson`) — write a JSON **list of
  feature objects**, each `{keyword, name, uri, description, tags, elements}`,
  where each element (scenario) is `{keyword, name, line, type, tags, steps}`
  (each element's `type` is the literal string `"scenario"`) and
  each step is `{keyword, name, line, result}` with `result` =
  `{status, duration}` (status `"passed"`/`"failed"`/`"skipped"`). Every `line` is
  the **1-based source line** of that scenario or step within its `.feature` file.
  Each step's `keyword` is the canonical Gherkin keyword with **no trailing
  whitespace** — i.e. `"Given"` / `"When"` / `"Then"` (an `And`/`But`/`*` step
  surfaces its own source keyword the same way, trimmed); do not carry the
  trailing space the Gherkin parser emits.
