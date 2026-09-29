"""
Tests for the invoke task execution library.

Tests cover user-facing APIs: @task decorator, Collection, Context,
MockContext, Config, Parser/Argument, Executor, Result, watchers,
FilesystemLoader, and exceptions.
"""

import os
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


# =============================================================================
# TestTaskDecorator - @task decorator and Task class
# =============================================================================


class TestTaskDecorator:
    """Tests for the @task decorator which marks functions as invoke tasks."""

    def test_task_collection_executor_pipeline(self):
        """Full pipeline: create tasks with @task, verify properties, organize into
        nested subcollections, verify dotted name resolution, execute via Executor,
        verify return values and called tracking."""
        from invoke import task, Context, Collection, Config, Executor

        @task
        def build(c):
            return "built"

        @task
        def test_code(c):
            return "tested"

        @task
        def deploy(c):
            return "deployed"

        # Step 1: Verify task name and called properties
        assert build.name == "build"
        assert build.called is False

        # Step 2: Direct call to verify basic task execution
        ctx = Context()
        result = build(ctx)
        assert result == "built"
        assert build.called is True

        # Step 3: Organize into nested subcollections
        dev = Collection("dev", build, test_code)
        ops = Collection("ops", deploy)
        root = Collection(dev, ops)

        # Step 4: Verify dotted name resolution in task_names
        names = root.task_names
        assert "dev.build" in names
        assert "dev.test-code" in names
        assert "ops.deploy" in names

        # Step 5: Execute tasks via Executor and verify return values
        # Need fresh tasks since build.called is already True
        @task
        def get_version(c):
            return "1.0.0"

        @task
        def get_name(c):
            return "myapp"

        exec_coll = Collection(get_version, get_name)
        executor = Executor(exec_coll, config=Config())
        results = executor.execute("get-version", "get-name")
        values = list(results.values())
        assert "1.0.0" in values
        assert "myapp" in values

        # Step 6: Verify task.called is True after execution
        assert get_version.called is True
        assert get_name.called is True

    def test_task_get_arguments_reflects_signature(self):
        """get_arguments returns Argument objects matching function signature with correct types."""
        from invoke import task

        @task(
            positional=["target"],
            iterable=["tags"],
            incrementable=["verbose"],
        )
        def deploy(c, target, version="1.0", verbose=0, force=False, tags=[]):
            pass

        args = {a.name: a for a in deploy.get_arguments()}
        assert "target" in args
        assert args["version"].kind == str
        assert args["force"].kind == bool
        assert args["tags"].kind == list
        assert args["verbose"].incrementable is True
        assert args["target"].positional is True

    def test_task_pre_order_follows_declaration(self):
        """Pre-tasks within one `pre=[...]` list run in left-to-right declaration order.

        Distinct from test_depth_first_dependency_chain (which only asserts each pre-task runs
        before the main task, never the relative order of siblings declared in the same list):
        this pins that the order of names inside a single `pre=` list is honored, by running the
        same two pre-tasks in both declaration orders and asserting execution tracks each.
        """
        from invoke import task, Collection, Config, Executor

        def run_with_pre(first_name, second_name):
            order = []

            @task
            def clean(c):
                order.append("clean")

            @task
            def lint(c):
                order.append("lint")

            pre = [clean, lint] if first_name == "clean" else [lint, clean]

            @task(pre=pre)
            def build(c):
                order.append("build")

            Executor(Collection(clean, lint, build), config=Config()).execute("build")
            return order

        # Declaring pre=[clean, lint] runs clean then lint; reversing the list reverses execution.
        assert run_with_pre("clean", "lint") == ["clean", "lint", "build"]
        assert run_with_pre("lint", "clean") == ["lint", "clean", "build"]

    def test_task_aliases_and_default(self):
        """Tasks with aliases and default flag integrate into collections correctly."""
        from invoke import task, Collection

        @task(aliases=["compile", "make"], default=True)
        def build(c):
            return "built"

        coll = Collection(build)
        # task_names maps canonical names to alias lists
        names = coll.task_names
        assert "build" in names
        assert "compile" in names["build"]
        assert coll.default == "build"

    def test_task_iterable_and_incrementable_args(self):
        """Tasks with iterable and incrementable params accumulate values correctly."""
        from invoke import task, Context

        @task(iterable=["hosts"], incrementable=["verbose"])
        def deploy(c, hosts=[], verbose=0):
            return hosts, verbose

        ctx = Context()
        h, v = deploy(ctx, hosts=["web1", "web2"], verbose=3)
        assert h == ["web1", "web2"]
        assert v == 3

    def test_task_autoprint_returns_value(self):
        """Task with autoprint=True prints return value when executed via Executor."""
        from invoke import task, Collection, Config, Executor
        import io
        import sys

        @task(autoprint=True)
        def version(c):
            return "1.2.3"

        coll = Collection(version)
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        try:
            Executor(coll, config=Config()).execute("version")
        finally:
            sys.stdout = old_stdout
        assert "1.2.3" in captured.getvalue()


# =============================================================================
# TestCollection - Task organization and namespaces
# =============================================================================


class TestCollection:
    """Tests for Collection which organizes tasks into namespaces."""

    def test_collection_configure_propagates_to_subcollection(self):
        """Collection.configure data propagates through subcollection hierarchy."""
        from invoke import task, Collection

        @task
        def show_config(c):
            return c

        inner = Collection("inner", show_config)
        inner.configure({"db_host": "localhost"})

        outer = Collection(inner)
        outer.configure({"app_name": "myapp"})

        # The merged view for a task that lives in the subcollection must combine
        # the inner-set value with the value inherited from the outer collection.
        merged = outer.configuration("inner.show-config")
        assert merged["db_host"] == "localhost"
        assert merged["app_name"] == "myapp"

    def test_collection_auto_dash_names_with_subcollections(self):
        """auto_dash_names transforms propagate through subcollection task names."""
        from invoke import task, Collection

        @task
        def my_long_task(c):
            pass

        @task
        def another_task(c):
            pass

        sub = Collection("my_sub", my_long_task)
        root = Collection(sub)
        root.add_task(another_task)

        names = root.task_names
        # Underscored names become dashed
        assert "another-task" in names
        assert "my-sub.my-long-task" in names

    def test_collection_no_auto_dash_names(self):
        """auto_dash_names=False preserves underscored names."""
        from invoke import task, Collection

        @task
        def my_task(c):
            pass

        coll = Collection(my_task, auto_dash_names=False)
        assert "my_task" in coll.task_names

    def test_collection_task_replacement(self):
        """Adding a task with the same name replaces the previous one."""
        from invoke import task, Collection, Executor, Config

        @task
        def build(c):
            return "v1"

        @task
        def build_v2(c):
            return "v2"

        coll = Collection(build)
        coll.add_task(build_v2, name="build")
        results = Executor(coll, config=Config()).execute("build")
        assert "v2" in results.values()

    def test_collection_serialized_nested(self):
        """serialized() returns complete dict representation of nested collection."""
        from invoke import task, Collection

        @task
        def build(c, target="all"):
            pass

        @task(aliases=["t"])
        def test_code(c):
            pass

        sub = Collection("sub", test_code)
        root = Collection("root", build)
        root.add_collection(sub)

        data = root.serialized()
        # serialized returns a dict with name, default, tasks, collections keys
        assert data["name"] == "root"
        assert data["default"] is None
        # The root's own task is listed under its transformed name.
        task_names = [t["name"] for t in data["tasks"]]
        assert "build" in task_names
        # The nested collection is serialized recursively under its own name.
        sub_data = next(c for c in data["collections"] if c["name"] == "sub")
        # The nested collection's task carries the transformed name AND the
        # transformed alias list that serialized() actually computes.
        sub_task = next(t for t in sub_data["tasks"] if t["name"] == "test-code")
        assert sub_task["aliases"] == ["t"]

    def test_collection_from_module_with_config(self):
        """from_module loads tasks from module and supports name override."""
        from invoke import task, Collection
        import types

        mod = types.ModuleType("mytasks")

        @task
        def hello(c):
            pass

        @task
        def world(c):
            pass

        mod.hello = hello
        mod.world = world

        coll = Collection.from_module(mod, name="custom")
        assert coll.name == "custom"
        assert "hello" in coll.task_names
        assert "world" in coll.task_names

    def test_collection_default_task_execution(self):
        """Default task can be invoked by collection name."""
        from invoke import task, Collection, Executor, Config

        @task(default=True)
        def main_task(c):
            return "default executed"

        @task
        def other(c):
            return "other"

        sub = Collection("sub", main_task, other)
        root = Collection(sub)
        executor = Executor(root, config=Config())
        results = executor.execute("sub")
        assert "default executed" in results.values()


# =============================================================================
# TestArgument - CLI argument parsing components
# =============================================================================


class TestArgument:
    """Tests for Argument and its interactions with ParserContext."""

    def test_argument_types_and_casting(self):
        """Argument values are cast to the correct type when set."""
        from invoke import Argument

        # String arg
        s = Argument(name="host")
        s.value = "web1"
        assert s.value == "web1"
        assert s.got_value is True

        # Bool arg - toggling
        b = Argument(name="verbose", kind=bool, default=False)
        assert b.takes_value is False
        b.value = True
        assert b.value is True

        # Int arg - string casting
        i = Argument(name="count", kind=int, default=0)
        i.value = "5"
        assert i.value == 5

        # List arg - accumulation
        l = Argument(name="items", kind=list, default=[])
        l.value = "first"
        l.value = "second"
        assert l.value == ["first", "second"]

        # Incrementable
        inc = Argument(name="verbose", kind=int, default=0, incrementable=True)
        inc.value = None  # increment
        inc.value = None  # increment
        inc.value = None  # increment
        assert inc.value == 3

    def test_argument_names_and_flags(self):
        """Arguments with multiple names generate correct flag mappings."""
        from invoke import Argument
        from invoke.parser import ParserContext

        arg = Argument(names=("verbose", "v"), kind=bool, default=False)
        ctx = ParserContext(name="build", args=[arg])

        # Both long and short forms should be in flags
        assert "--verbose" in ctx.flags
        assert "-v" in ctx.flags

        # Inverse flag for bools defaulting to True
        arg2 = Argument(name="color", kind=bool, default=True)
        ctx2 = ParserContext(name="test", args=[arg2])
        assert "--no-color" in ctx2.inverse_flags

        # Underscores in argument names translate to dashes in the long flag,
        # and single-char names render as short flags -- observable via flags.
        arg3 = Argument(name="my_task_name", kind=bool, default=False)
        ctx3 = ParserContext(name="run", args=[arg3])
        assert "--my-task-name" in ctx3.flags

        arg4 = Argument(name="x", kind=bool, default=False)
        ctx4 = ParserContext(name="run", args=[arg4])
        assert "-x" in ctx4.flags


# =============================================================================
# TestParserContext - Parser context for flag registration
# =============================================================================


class TestParserContext:
    """Tests for ParserContext flag management and kwargs extraction."""

    def test_parser_context_full_workflow(self):
        """Build a context, add args, set values, extract kwargs."""
        from invoke.parser import ParserContext
        from invoke import Argument

        ctx = ParserContext(name="deploy", aliases=("d",))
        ctx.add_arg(Argument(name="target", positional=True))
        ctx.add_arg(Argument(name="force", kind=bool, default=False))
        ctx.add_arg(Argument(names=("verbose", "v"), kind=bool, default=False))

        # Check structure
        assert ctx.name == "deploy"
        assert "d" in ctx.aliases
        assert len(ctx.positional_args) == 1
        assert "--force" in ctx.flags
        assert "-v" in ctx.flags
        assert ctx.missing_positional_args == [ctx.args["target"]]

        # Set values
        ctx.args["target"].value = "prod"
        ctx.args["force"].value = True

        # Extract kwargs
        kwargs = dict(ctx.as_kwargs)
        assert kwargs["target"] == "prod"
        assert kwargs["force"] is True
        assert kwargs["verbose"] is False
        assert len(ctx.missing_positional_args) == 0

    def test_help_tuples_formatting(self):
        """help_tuples returns formatted flag names with help text."""
        from invoke.parser import ParserContext
        from invoke import Argument

        ctx = ParserContext(name="build", args=[
            Argument(name="clean", kind=bool, default=False, help="Remove artifacts"),
        ])
        tuples = ctx.help_tuples()
        assert len(tuples) >= 1
        flag_spec, help_str = tuples[0]
        assert "clean" in flag_spec
        assert help_str == "Remove artifacts"


# =============================================================================
# TestParser - CLI argument parser (integration-heavy)
# =============================================================================


class TestParser:
    """Tests for the Parser which parses argv-style token lists."""

    def test_parse_multi_task_with_flags(self):
        """Parse multiple tasks each with their own flags in one argv."""
        from invoke import Parser, Argument
        from invoke.parser import ParserContext

        build_ctx = ParserContext(name="build", args=[
            Argument(name="clean", kind=bool, default=False),
            Argument(name="target", default="all"),
        ])
        test_ctx = ParserContext(name="test", args=[
            Argument(name="verbose", kind=bool, default=False),
            Argument(name="suite", default="unit"),
        ])
        parser = Parser(contexts=[build_ctx, test_ctx])
        result = parser.parse_argv([
            "build", "--clean", "--target", "release",
            "test", "--verbose", "--suite", "integration",
        ])

        assert len(result) == 2
        assert result[0].name == "build"
        assert result[0].args["clean"].value is True
        assert result[0].args["target"].value == "release"
        assert result[1].name == "test"
        assert result[1].args["verbose"].value is True
        assert result[1].args["suite"].value == "integration"

    def test_parse_comprehensive_flag_features(self):
        """Exercises equals syntax, inverse booleans, positional args mixed with flags,
        incrementable flags, task aliases, task repetition, remainder, and unknown handling
        in a single integrated flow."""
        from invoke import Parser, Argument, ParseError
        from invoke.parser import ParserContext

        # -- Equals syntax --
        deploy_ctx = ParserContext(name="deploy", aliases=["dep"], args=[
            Argument(name="target", positional=True),
            Argument(name="env", positional=True),
            Argument(name="region", default="us-east"),
            Argument(name="color", kind=bool, default=True),
            Argument(names=("verbose", "v"), kind=int, default=0, incrementable=True),
            Argument(name="force", kind=bool, default=False),
        ])
        parser = Parser(contexts=[deploy_ctx])

        # Test equals syntax + inverse boolean + incrementable + positional mixed with flags
        result = parser.parse_argv([
            "deploy", "--region=eu-west", "--no-color", "-v", "-v", "--force", "prod", "staging",
        ])
        ctx = result[0]
        kwargs = dict(ctx.as_kwargs)
        assert kwargs["region"] == "eu-west"
        assert kwargs["color"] is False
        assert kwargs["verbose"] == 2
        assert kwargs["force"] is True
        assert kwargs["target"] == "prod"
        assert kwargs["env"] == "staging"

        # -- Task aliases --
        result2 = parser.parse_argv(["dep", "--region=ap-south", "myapp", "dev"])
        assert result2[0].name == "deploy"
        assert result2[0].args["region"].value == "ap-south"

        # -- Task repetition with different args --
        task_ctx = ParserContext(name="run-job", args=[Argument(name="id")])
        parser2 = Parser(contexts=[task_ctx])
        result3 = parser2.parse_argv([
            "run-job", "--id", "abc", "run-job", "--id", "xyz",
        ])
        assert len(result3) == 2
        assert result3[0].args["id"].value == "abc"
        assert result3[1].args["id"].value == "xyz"

        # -- Remainder after -- --
        simple_ctx = ParserContext(name="build")
        parser3 = Parser(contexts=[simple_ctx])
        result4 = parser3.parse_argv(["build", "--", "extra", "stuff", "--flag"])
        assert "extra" in result4.remainder
        assert "stuff" in result4.remainder
        assert "--flag" in result4.remainder

        # -- Unknown raises ParseError by default --
        parser4 = Parser(contexts=[simple_ctx])
        with pytest.raises(ParseError):
            parser4.parse_argv(["nonexistent"])

        # -- ignore_unknown captures unparsed --
        parser5 = Parser(contexts=[simple_ctx], ignore_unknown=True)
        result5 = parser5.parse_argv(["nonexistent", "--foo", "bar"])
        assert "nonexistent" in result5.unparsed

    def test_parse_list_flag_stops_at_task_boundary(self):
        """List-type flag accumulation stops when a new task name is encountered."""
        from invoke import Parser, Argument
        from invoke.parser import ParserContext

        c1 = ParserContext(name="mytask", args=[
            Argument(name="mylist", kind=list),
        ])
        c2 = ParserContext(name="othertask")
        result = Parser([c1, c2]).parse_argv([
            "mytask", "--mylist", "val1", "--mylist", "val2", "othertask",
        ])
        # List should contain only val1 and val2, not "othertask"
        assert result[0].args["mylist"].value == ["val1", "val2"]
        assert len(result) == 2
        assert result[1].name == "othertask"

    def test_parse_with_initial_context(self):
        """Initial context captures core flags before task names."""
        from invoke import Parser, Argument
        from invoke.parser import ParserContext

        initial = ParserContext(args=[
            Argument(name="debug", kind=bool, default=False),
        ])
        task_ctx = ParserContext(name="build")
        parser = Parser(contexts=[task_ctx], initial=initial)
        result = parser.parse_argv(["--debug", "build"])
        # Initial context is first result with name=None
        assert result[0].name is None
        assert dict(result[0].as_kwargs)["debug"] is True
        assert result[1].name == "build"

    def test_parse_core_vs_task_flag_conflict(self):
        """When core and task contexts share a flag name, the task's flag wins
        and determines parsing behavior — even across different types."""
        from invoke import Parser, Argument
        from invoke.parser import ParserContext

        # Same-type conflict: both bool
        initial = ParserContext(args=[
            Argument(name="echo", kind=bool, default=False),
        ])
        task_ctx = ParserContext(name="mytask", args=[
            Argument(name="echo", kind=bool, default=False),
        ])
        parser = Parser(initial=initial, contexts=[task_ctx])
        result = parser.parse_argv(["mytask", "--echo"])
        assert dict(result[0].as_kwargs)["echo"] is False
        assert dict(result[1].as_kwargs)["echo"] is True

        # Cross-type conflict: core is bool, task is string
        initial2 = ParserContext(args=[
            Argument(name="hide", kind=bool, default=False),
        ])
        task_ctx2 = ParserContext(name="mytask", args=[
            Argument(name="hide"),  # string type
        ])
        parser2 = Parser(initial=initial2, contexts=[task_ctx2])
        result2 = parser2.parse_argv(["mytask", "--hide", "both"])
        assert dict(result2[0].as_kwargs)["hide"] is False
        assert dict(result2[1].as_kwargs)["hide"] == "both"


# =============================================================================
# TestConfig - Hierarchical configuration
# =============================================================================


class TestConfig:
    """Tests for Config and DataProxy hierarchical configuration."""

    def test_config_hierarchy_end_to_end(self):
        """Full config lifecycle: overrides win, deep merge preserves nested values,
        clone is independent, and separate Config instances don't leak references."""
        from invoke import Config

        # Step 1: Create Config with nested defaults + overrides, verify overrides win
        config = Config(
            defaults={"debug": False, "level": 1, "db": {"host": "localhost", "port": 5432, "name": "mydb"}},
            overrides={"debug": True, "db": {"host": "production-server"}},
        )
        assert config.debug is True  # override wins
        assert config.level == 1  # default preserved

        # Step 2: Verify deep merge - override only replaces host, not port/name
        assert config.db.host == "production-server"
        assert config.db.port == 5432
        assert config.db.name == "mydb"

        # Step 3: Clone the config
        cloned = config.clone()

        # Step 4: Modify the clone
        cloned.debug = False
        cloned.db.host = "clone-host"

        # Step 5: Verify clone has modified value
        assert cloned.debug is False
        assert cloned.db.host == "clone-host"

        # Step 6: Verify original is unchanged (independence)
        assert config.debug is True
        assert config.db.host == "production-server"

        # Step 7: Create a second Config, modify it, verify first unaffected (no reference leaking)
        config2 = Config(overrides={"db": {"host": "host2", "port": 5432, "name": "mydb"}})
        config2.db.host = "modified"
        assert config.db.host == "production-server"

    def test_config_nested_proxy_access(self):
        """Nested dicts become DataProxy objects with attribute access."""
        from invoke import Config

        config = Config(overrides={
            "run": {"echo": True, "shell": "/bin/zsh"},
            "deploy": {"target": {"host": "web1", "port": 8080}},
        })
        assert config.run.echo is True
        assert config.run.shell == "/bin/zsh"
        assert config.deploy.target.host == "web1"
        assert config.deploy.target.port == 8080

    def test_config_modification_and_dict_protocol(self):
        """Config supports dict protocol and runtime modifications."""
        from invoke import Config

        config = Config(overrides={"key1": "val1"})

        # Dict protocol
        assert "key1" in config
        assert config["key1"] == "val1"
        config["key2"] = "val2"
        assert config.key2 == "val2"

        # Iteration
        keys = list(config.keys())
        assert "key1" in keys

    def test_config_env_vars(self):
        """Config loads environment variables with INVOKE_ prefix, casting to existing type."""
        from invoke import Config

        config = Config()  # has default run.echo = False (bool)
        with patch.dict(os.environ, {"INVOKE_RUN_ECHO": "1"}):
            config.load_shell_env()
        # Value is cast to the type of the existing config value (bool)
        assert config.run.echo is True

    def test_config_load_collection(self):
        """load_collection merges collection-level config."""
        from invoke import Config

        config = Config(overrides={"existing": "value"})
        config.load_collection({"collection_key": "coll_value"})
        assert config.collection_key == "coll_value"
        assert config.existing == "value"

    def test_config_set_runtime_values(self):
        """Runtime attribute writes take top precedence and survive a later merge.

        A nested value set at runtime must outrank collection-level config loaded
        afterwards -- i.e. it is reapplied last when the config re-merges.
        """
        from invoke import Config

        config = Config(defaults={"run": {"echo": False}})
        config.run.echo = True
        # A collection loaded afterwards tries to set echo back to False, which
        # re-merges the config; the runtime write must still win.
        config.load_collection({"run": {"echo": False}})
        assert config.run.echo is True

    def test_config_load_project_from_yaml(self):
        """Config loads project-level settings from invoke.yaml in the project directory."""
        from invoke import Config

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create an invoke.yaml config file in the project directory
            config_path = Path(tmpdir) / "invoke.yaml"
            config_path.write_text(
                "run:\n"
                "  echo: true\n"
                "my_setting: custom_value\n",
                encoding="utf-8",
            )

            # Create a Config pointing at this project directory and load it
            config = Config(project_location=tmpdir)
            config.load_project()

            # Verify the loaded values override defaults and are accessible
            assert config.run.echo is True
            assert config.my_setting == "custom_value"


# =============================================================================
# TestDataProxy - Dict wrapper with attribute access
# =============================================================================


class TestDataProxy:
    """Tests for DataProxy which provides attribute access to dicts."""

# =============================================================================
# TestContext - Command execution with cd/prefix
# =============================================================================


class TestContext:
    """Tests for Context command execution and context managers."""

    def test_context_config_proxy(self):
        """Context proxies attribute access to its config."""
        from invoke import Context, Config

        config = Config(overrides={"my_setting": "value", "nested": {"key": "deep"}})
        ctx = Context(config=config)
        assert ctx.my_setting == "value"
        assert ctx.nested.key == "deep"

    def test_context_run_with_various_options(self):
        """Run commands with hide, warn, exit code checking."""
        from invoke import Context, UnexpectedExit

        ctx = Context()

        # Basic run
        result = ctx.run("echo hello", hide=True, in_stream=False)
        assert "hello" in result.stdout
        assert result.exited == 0
        assert result.ok is True
        assert result.command == "echo hello"

        # Stderr capture
        result2 = ctx.run("echo error >&2", hide=True, pty=False, in_stream=False)
        assert "error" in result2.stderr

        # Non-zero exit raises
        with pytest.raises(UnexpectedExit):
            ctx.run("false", hide=True, in_stream=False)

        # warn mode
        result3 = ctx.run("false", hide=True, warn=True, in_stream=False)
        assert result3.failed is True

    def test_context_cd_prefix_composition(self):
        """cd and prefix context managers compose correctly in nested scenarios."""
        from invoke import Context

        ctx = Context()

        # Basic cd
        with ctx.cd("/tmp"):
            result = ctx.run("pwd", hide=True, in_stream=False)
            assert "/tmp" in result.stdout

        # Nested cd composes paths
        with ctx.cd("/tmp"):
            with ctx.cd("subdir"):
                assert "subdir" in ctx.cwd

        # Basic prefix
        with ctx.prefix("export MY_VAR=hello"):
            result = ctx.run("echo $MY_VAR", hide=True, in_stream=False)
            assert "hello" in result.stdout

        # Nested prefixes compose with &&
        with ctx.prefix("export A=1"):
            with ctx.prefix("export B=2"):
                result = ctx.run("echo $A $B", hide=True, in_stream=False)
                assert "1" in result.stdout
                assert "2" in result.stdout

    def test_context_cd_with_prefix_ordering(self):
        """cd occurs before prefix in the composed command string."""
        from invoke import Context

        ctx = Context()
        # When cd and prefix are nested, cd should come first
        with ctx.prefix("export VAR=1"):
            with ctx.cd("/tmp"):
                result = ctx.run("pwd && echo $VAR", hide=True, in_stream=False)
                assert "/tmp" in result.stdout
                assert "1" in result.stdout

    def test_context_run_with_env_and_timeout(self):
        """Run with custom env vars and timeout."""
        from invoke import Context

        ctx = Context()
        result = ctx.run(
            "echo $MY_TEST_VAR",
            hide=True,
            env={"MY_TEST_VAR": "custom_value"},
            in_stream=False,
        )
        assert "custom_value" in result.stdout

        # Timeout that completes
        result2 = ctx.run("echo fast", hide=True, timeout=10, in_stream=False)
        assert "fast" in result2.stdout

    def test_context_run_multiline_and_hide(self):
        """Capture multiline output and verify hide behavior."""
        from invoke import Context

        ctx = Context()
        result = ctx.run(
            "echo line1 && echo line2 && echo line3",
            hide=True,
            in_stream=False,
        )
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 3

        # Hide specific streams
        result2 = ctx.run("echo out && echo err >&2", hide="both", pty=False, in_stream=False)
        assert "stdout" in result2.hide
        assert "stderr" in result2.hide

    def test_context_run_timeout_raises(self):
        """Run with a timeout that triggers raises CommandTimedOut."""
        from invoke import Context
        from invoke.exceptions import CommandTimedOut

        ctx = Context()
        with pytest.raises(CommandTimedOut) as exc_info:
            ctx.run("sleep 10", hide=True, in_stream=False, timeout=1)
        assert exc_info.value.timeout == 1

    def test_context_run_pty_mode(self):
        """Run with pty=True uses pseudo-terminal when available."""
        import subprocess
        # Run in a subprocess to avoid pytest's stdin capture interfering
        code = (
            "from invoke import Context; "
            "ctx = Context(); "
            "r = ctx.run('echo hello', hide=True, in_stream=False, pty=True); "
            "print(r.pty); print(repr(r.stdout))"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15,
        )
        assert proc.returncode == 0
        lines = proc.stdout.strip().split("\n")
        assert lines[0] == "True"
        assert "hello" in lines[1]

    def test_context_run_encoding(self):
        """Run with explicit encoding sets result encoding."""
        from invoke import Context

        ctx = Context()
        result = ctx.run("echo hello", hide=True, in_stream=False, encoding="latin-1")
        assert result.encoding == "latin-1"
        assert "hello" in result.stdout

    def test_context_sudo_wraps_command(self):
        """sudo() composes a sudo-prefixed command with password auto-response watcher."""
        from invoke import Context, Config

        ctx = Context(config=Config(overrides={"sudo": {"password": "testpass"}}))
        # Use warn=True so we don't crash if sudo auth fails (likely in test env)
        result = ctx.sudo("echo hello", hide=True, warn=True, in_stream=False, pty=False)
        # The executed command string must contain "sudo" - proves sudo() wraps
        # the command rather than just delegating to run()
        assert "sudo" in result.command
        # The command should also contain the original command
        assert "echo hello" in result.command
        # sudo() adds -S flag (for stdin password) and -p flag (for prompt)
        assert "-S" in result.command
        assert "-p" in result.command


# =============================================================================
# TestMockContext - Testing utility with complex patterns
# =============================================================================


class TestMockContext:
    """Tests for MockContext with complex result mapping patterns."""

    def test_mock_context_basic_patterns(self):
        """MockContext supports Result, bool, and string values."""
        from invoke import MockContext, Result

        # Result object
        mc = MockContext(run=Result("output"))
        assert mc.run("cmd").stdout == "output"

        # Boolean shorthand
        mc2 = MockContext(run=True)
        assert mc2.run("cmd").exited == 0
        mc3 = MockContext(run=False)
        assert mc3.run("cmd").exited == 1

        # String shorthand
        mc4 = MockContext(run="string output")
        assert mc4.run("cmd").stdout == "string output"

    def test_mock_context_dict_and_regex_mapping(self):
        """MockContext maps commands to results via exact match and regex."""
        from invoke import MockContext, Result

        mc = MockContext(run={
            "whoami": Result("testuser"),
            "hostname": Result("testhost"),
            "check": True,
            "version": "1.0.0",
            "fail-cmd": False,
            re.compile(r"echo .*"): Result("echoed"),
        })
        assert mc.run("whoami").stdout == "testuser"
        assert mc.run("hostname").stdout == "testhost"
        assert mc.run("echo hello world").stdout == "echoed"

        # Bool/string shorthands are also accepted as dict values
        assert mc.run("check").exited == 0
        assert mc.run("version").stdout == "1.0.0"
        assert mc.run("fail-cmd").exited == 1

        # Unmatched command raises NotImplementedError
        with pytest.raises(NotImplementedError):
            mc.run("unknown command")

    def test_mock_context_iterable_and_repeat(self):
        """MockContext iterates results and supports repeat mode."""
        from invoke import MockContext, Result

        # Iterable: different results per call
        mc = MockContext(
            run=[Result("first"), Result("second"), Result("third")],
            repeat=False,
        )
        assert mc.run("cmd").stdout == "first"
        assert mc.run("cmd").stdout == "second"
        assert mc.run("cmd").stdout == "third"

        # Repeat mode: same result every time
        mc2 = MockContext(run=Result("always"), repeat=True)
        assert mc2.run("cmd1").stdout == "always"
        assert mc2.run("cmd2").stdout == "always"
        assert mc2.run("cmd3").stdout == "always"

    def test_mock_context_sudo_and_set_result_for(self):
        """MockContext supports sudo and dynamic result modification."""
        from invoke import MockContext, Result

        mc = MockContext(
            run={"cmd1": Result("original")},
            sudo=Result("sudo output"),
        )
        assert mc.sudo("whoami").stdout == "sudo output"

        # Add results dynamically
        mc.set_result_for("run", "cmd2", Result("added"))
        assert mc.run("cmd2").stdout == "added"

    def test_mock_context_mock_wrapped(self):
        """MockContext methods are Mock-wrapped for assertion checking."""
        from invoke import MockContext, Result

        mc = MockContext(run=Result("out"))
        mc.run("test command")
        mc.run.assert_called_once_with("test command")


# =============================================================================
# TestResult - Command execution results
# =============================================================================


class TestResult:
    """Tests for Result container."""

    def test_result_full_interface(self):
        """Result provides ok/failed, bool conversion, tail, and return_code."""
        from invoke import Result

        r = Result(
            stdout="line1\nline2\nline3\nline4\nline5\n",
            stderr="err1\nerr2\n",
            encoding="utf-8",
            command="test cmd",
            shell="/bin/bash",
            exited=0,
            pty=False,
            hide=("stdout",),
        )

        assert r.ok is True
        assert r.failed is False
        assert bool(r) is True
        assert r.command == "test cmd"
        assert r.encoding == "utf-8"
        assert r.return_code == 0
        assert r.return_code == r.exited
        assert "stdout" in r.hide
        assert "test cmd" in repr(r)

        # tail
        tail = r.tail("stdout", 3)
        assert "line3" in tail and "line4" in tail and "line5" in tail

        # Failed result
        r2 = Result(command="bad", exited=1)
        assert r2.ok is False
        assert r2.failed is True
        assert bool(r2) is False


# =============================================================================
# TestExecutor - Task dependency execution (integration-heavy)
# =============================================================================


class TestExecutor:
    """Tests for Executor with dependency resolution and config propagation."""

    def test_execute_with_pre_post_deduplication(self):
        """Executor resolves pre/post dependencies with deduplication."""
        from invoke import Executor, Collection, Config, task

        order = []

        @task
        def setup(c):
            order.append("setup")

        @task(pre=[setup])
        def build(c):
            order.append("build")

        @task(pre=[setup])
        def test_cmd(c):
            order.append("test")

        coll = Collection(setup, build, test_cmd)
        executor = Executor(coll, config=Config())
        executor.execute("build", "test-cmd")
        # setup should only run once due to deduplication
        assert order.count("setup") == 1
        assert "build" in order
        assert "test" in order

    def test_execute_subcollection_config_per_task(self):
        """Each subcollection's config is passed to its tasks' contexts."""
        from invoke import Executor, Collection, Config, task

        @task
        def task_a(c):
            return c.my_key

        @task
        def task_b(c):
            return c.my_key

        inner1 = Collection("inner1", task_a)
        inner1.configure({"my_key": "value_a"})
        inner2 = Collection("inner2", task_b)
        inner2.configure({"my_key": "value_b"})
        root = Collection(inner1, inner2)

        executor = Executor(root, config=Config())
        results = executor.execute("inner1.task-a", "inner2.task-b")
        values = list(results.values())
        assert "value_a" in values
        assert "value_b" in values

    def test_execute_config_shared_between_tasks(self):
        """Tasks in the same execute() call share the same config object."""
        from invoke import Executor, Collection, Config, task

        @task
        def task1(c):
            c.config.shared_data = "from_task1"
            return c

        @task
        def task2(c):
            return c

        coll = Collection(task1, task2)
        results = Executor(coll, config=Config()).execute("task1", "task2")
        contexts = list(results.values())
        c1, c2 = contexts[0], contexts[1]
        # Config is shared, so task2 sees task1's mutation
        assert c1.config is c2.config

    def test_execute_with_call_kwargs(self):
        """Executor passes kwargs from call() to tasks."""
        from invoke import Executor, Collection, Config, task, call

        @task
        def greet(c, name="world"):
            return f"hello {name}"

        @task(pre=[call(greet, name="invoke")])
        def main(c):
            return "done"

        coll = Collection(greet, main)
        executor = Executor(coll, config=Config())
        results = executor.execute("main")
        values = list(results.values())
        assert "hello invoke" in values

    def test_execute_root_default_task_when_no_name_given(self):
        """Executor runs the collection's own default task when execute() is called with no task name."""
        from invoke import Executor, Collection, Config, task

        @task(default=True)
        def primary(c):
            return "root_default_ran"

        @task
        def secondary(c):
            return "secondary"

        root = Collection(primary, secondary)

        executor = Executor(root, config=Config())
        results = executor.execute()
        assert "root_default_ran" in results.values()
        # Only the default task ran -- the non-default task is not invoked.
        assert "secondary" not in results.values()

    def test_execute_post_task_ordering(self):
        """Executor runs post-tasks AFTER the main task in correct order."""
        from invoke import Executor, Collection, Config, task

        order = []

        @task
        def notify(c):
            order.append("notify")

        @task
        def cleanup(c):
            order.append("cleanup")

        @task(post=[notify, cleanup])
        def deploy(c):
            order.append("deploy")

        @task
        def setup(c):
            order.append("setup")

        @task(pre=[setup], post=[cleanup])
        def build(c):
            order.append("build")

        coll = Collection(notify, cleanup, deploy, setup, build)
        executor = Executor(coll, config=Config())

        # Execute deploy: should run deploy THEN notify THEN cleanup
        executor.execute("deploy")
        assert order.index("deploy") < order.index("notify")
        assert order.index("deploy") < order.index("cleanup")
        assert order == ["deploy", "notify", "cleanup"]

        # Reset and test build with both pre and post
        order.clear()
        executor2 = Executor(coll, config=Config())
        executor2.execute("build")
        # pre tasks first, then main, then post
        assert order.index("setup") < order.index("build")
        assert order.index("build") < order.index("cleanup")


# =============================================================================
# TestWatchers - Stream watching and auto-responding
# =============================================================================


class TestWatchers:
    """Tests for watcher classes that monitor and respond to streams."""

    def test_responder_pattern_matching(self):
        """Responder matches patterns and tracks index to avoid duplicates."""
        from invoke import Responder

        r = Responder(pattern=r"password:", response="secret\n")

        # First match
        responses = list(r.submit("Enter password:"))
        assert len(responses) == 1
        assert responses[0] == "secret\n"

        # Same stream, no new content past index
        responses = list(r.submit("Enter password:"))
        assert len(responses) == 0

        # New content with pattern
        responses = list(r.submit("Enter password: again password:"))
        assert len(responses) == 1

    def test_failing_responder_detects_sentinel(self):
        """FailingResponder raises ResponseNotAccepted when sentinel detected."""
        from invoke import FailingResponder
        from invoke.exceptions import ResponseNotAccepted

        fr = FailingResponder(
            pattern=r"password:",
            response="wrong_password\n",
            sentinel="Sorry, try again",
        )
        # First: see prompt and respond
        list(fr.submit("password:"))
        # Then: see failure sentinel
        with pytest.raises(ResponseNotAccepted):
            list(fr.submit("password: Sorry, try again"))

    def test_watchers_integration_with_run(self):
        """Responder watcher auto-responds to prompts during real command execution."""
        from invoke import Context, Responder

        ctx = Context()
        # Run a shell command that prints a prompt and reads stdin, then echoes
        # what it received. The Responder watches for the prompt pattern and
        # sends the response automatically.
        cmd = """bash -c 'echo "Enter value:" && read val && echo "Got: $val"'"""
        responder = Responder(
            pattern=r"Enter value:",
            response="test_input\n",
        )
        result = ctx.run(
            cmd,
            watchers=[responder],
            hide=True,
            in_stream=False,
            pty=False,
        )
        # The responder should have sent "test_input" which the script reads
        # and echoes back
        assert "Got: test_input" in result.stdout
        assert result.ok is True

    def test_watchers_multi_prompt_interaction(self):
        """Two Responders handle multiple distinct prompts in sequence during a single command."""
        from invoke import Context, Responder

        ctx = Context()
        # Shell command that prompts twice and uses both inputs
        cmd = """bash -c 'echo "Username:" && read u && echo "Password:" && read p && echo "Logged in as $u"'"""
        username_responder = Responder(
            pattern=r"Username:",
            response="admin\n",
        )
        password_responder = Responder(
            pattern=r"Password:",
            response="secret\n",
        )
        result = ctx.run(
            cmd,
            watchers=[username_responder, password_responder],
            hide=True,
            in_stream=False,
            pty=False,
        )
        assert "Logged in as admin" in result.stdout
        assert result.ok is True


# =============================================================================
# TestFilesystemLoader - Task module loading
# =============================================================================


class TestFilesystemLoader:
    """Tests for FilesystemLoader which finds and loads task modules."""

    def test_load_tasks_module_and_build_collection(self):
        """Load tasks.py, build collection, and verify task resolution."""
        from invoke import FilesystemLoader, Collection

        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_py = Path(tmpdir) / "tasks.py"
            tasks_py.write_text(textwrap.dedent("""
                from invoke import task

                @task
                def hello(c):
                    return "hello"

                @task(aliases=["bye"])
                def goodbye(c):
                    return "goodbye"
            """))

            loader = FilesystemLoader(start=tmpdir)
            mod, path = loader.load("tasks")
            coll = Collection.from_module(mod)
            names = coll.task_names
            assert "hello" in names
            assert "goodbye" in names
            # "bye" should be an alias of "goodbye"
            assert "bye" in names.get("goodbye", [])

    def test_load_nonexistent_raises(self):
        """Loading a non-existent task module raises CollectionNotFound."""
        from invoke import FilesystemLoader
        from invoke.exceptions import CollectionNotFound

        with tempfile.TemporaryDirectory() as tmpdir:
            loader = FilesystemLoader(start=tmpdir)
            with pytest.raises((CollectionNotFound, ImportError)):
                loader.load("nonexistent")

    def test_load_tasks_package(self):
        """Load tasks from a package directory (tasks/__init__.py)."""
        from invoke import FilesystemLoader, Collection

        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir) / "tasks"
            pkg_dir.mkdir()
            init_py = pkg_dir / "__init__.py"
            init_py.write_text(textwrap.dedent("""
                from invoke import task

                @task
                def build(c):
                    pass

                @task
                def test_code(c):
                    pass
            """))

            loader = FilesystemLoader(start=tmpdir)
            mod, path = loader.load("tasks")
            coll = Collection.from_module(mod)
            assert "build" in coll.task_names

    def test_loader_full_workflow_with_namespace(self):
        """Full workflow: load module, build collection, execute tasks with config."""
        from invoke import FilesystemLoader, Collection, Executor, Config

        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_py = Path(tmpdir) / "tasks.py"
            tasks_py.write_text(textwrap.dedent("""
                from invoke import task, Collection

                @task
                def clean(c):
                    return "cleaned"

                @task
                def build(c, target="all"):
                    return f"built {target}"

                ns = Collection(clean, build)
                ns.configure({"project": "myapp"})
            """))

            loader = FilesystemLoader(start=tmpdir)
            mod, path = loader.load("tasks")
            coll = Collection.from_module(mod)
            assert "clean" in coll.task_names
            assert "build" in coll.task_names


# =============================================================================
# TestExceptions - Exception hierarchy
# =============================================================================


class TestExceptions:
    """Tests for invoke's exception classes in realistic scenarios."""

    def test_unexpected_exit_contains_result_info(self):
        """UnexpectedExit wraps a Result with command and exit code details."""
        from invoke import UnexpectedExit, Result

        r = Result(
            command="deploy --target=prod",
            exited=1,
            stdout="deploying...",
            stderr="Error: permission denied",
            hide=("stdout", "stderr"),
        )
        exc = UnexpectedExit(r)
        assert exc.result is r
        assert "deploy" in str(exc)
        assert "1" in str(exc)

    def test_failure_chain_with_watcher_error(self):
        """Failure can carry a WatcherError reason from stream watchers."""
        from invoke import Result
        from invoke.exceptions import Failure, WatcherError, AuthFailure

        # WatcherError as reason
        reason = WatcherError("bad response from watcher")
        r = Result(command="sudo cmd", exited=1)
        f = Failure(result=r, reason=reason)
        assert f.reason is reason
        assert f.result.command == "sudo cmd"

        # AuthFailure
        r2 = Result(command="sudo cmd")
        af = AuthFailure(result=r2, prompt="[sudo] password:")
        assert af.prompt == "[sudo] password:"
        assert "rejected" in str(af).lower()

    def test_exit_and_parse_error(self):
        """Exit for clean termination, ParseError for CLI issues."""
        from invoke import Exit, ParseError

        # Default exit
        e = Exit()
        assert e.code == 0
        assert e.message is None

        # Exit with message defaults to code 1
        e2 = Exit(message="Something went wrong")
        assert e2.code == 1

        # Custom code
        e3 = Exit(message="Custom", code=42)
        assert e3.code == 42

        # ParseError
        pe = ParseError("Invalid flag --bogus")
        assert "Invalid flag" in str(pe)

    def test_collection_not_found_and_command_timed_out(self):
        """CollectionNotFound and CommandTimedOut carry context information."""
        from invoke import Result
        from invoke.exceptions import CollectionNotFound, CommandTimedOut

        cnf = CollectionNotFound(name="tasks", start="/home/user/project")
        assert cnf.name == "tasks"
        assert cnf.start == "/home/user/project"

        r = Result(command="sleep 100", hide=("stdout", "stderr"))
        cto = CommandTimedOut(result=r, timeout=30)
        assert cto.timeout == 30
        assert "30" in str(cto)


# =============================================================================
# TestTopLevelAPI - Convenience functions and imports
# =============================================================================


class TestTopLevelAPI:
    """Tests for top-level convenience functions."""

    def test_invoke_run(self):
        """invoke.run() executes commands without explicit Context."""
        import invoke

        result = invoke.run("echo hello", hide=True, in_stream=False)
        assert "hello" in result.stdout

    def test_invoke_sudo(self):
        """invoke.sudo() threads password through to the documented sudo command structure.

        Distinct from TestContext.test_context_sudo_wraps_command (which only checks that
        ``sudo``/``-S``/``-p`` appear as substrings under an explicit Config): this exercises the
        top-level convenience wrapper building its OWN default Context and asserts the *ordered*
        composed structure ``sudo -S -p '<prompt>' ... <command>`` documented in the spec, so a
        wrapper that delegates but mis-orders the flags would be caught.
        """
        import re
        import invoke

        # Use warn=True so it doesn't crash in test environment without real sudo
        result = invoke.sudo(
            "echo hello", hide=True, warn=True, in_stream=False, pty=False,
            password="testpass",
        )
        # The documented command form is `sudo -S -p '<prompt>' <command>`: the -S (stdin
        # password) and -p (quoted prompt) flags lead, in order, and the original command trails.
        assert re.match(r"^sudo -S -p '[^']*' ", result.command), \
            f"expected leading `sudo -S -p '<prompt>' `, got: {result.command!r}"
        assert result.command.endswith("echo hello")


# =============================================================================
# TestProgram - CLI entry point (Program class)
# =============================================================================


class TestProgram:
    """Tests for Program which provides the CLI entry point for invoke."""

    def test_program_help_output(self):
        """Program --help prints usage info with core options and exits cleanly."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            code = textwrap.dedent("""
                import sys
                from invoke import Program, Collection, task

                @task
                def hello(c):
                    \"\"\"Say hello.\"\"\"
                    print("hello world")

                program = Program(namespace=Collection(hello))
                try:
                    program.run(argv=["inv", "--help"])
                except SystemExit as e:
                    sys.exit(0 if e.code is None or e.code == 0 else 1)
            """)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=15,
                cwd=tmpdir,
            )
            assert proc.returncode == 0
            combined = proc.stdout + proc.stderr
            assert "hello" in combined, \
                f"Expected 'hello' task in help output, got: {combined!r}"

    def test_program_list_tasks(self):
        """Program --list displays available tasks with their names."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            code = textwrap.dedent("""
                import sys
                from invoke import Program, Collection, task

                @task
                def build(c):
                    \"\"\"Build the project.\"\"\"
                    pass

                @task(aliases=["t"])
                def test_code(c):
                    \"\"\"Run tests.\"\"\"
                    pass

                @task
                def deploy(c):
                    \"\"\"Deploy to server.\"\"\"
                    pass

                program = Program(namespace=Collection(build, test_code, deploy))
                try:
                    program.run(argv=["inv", "--list"])
                except SystemExit as e:
                    sys.exit(0 if e.code is None or e.code == 0 else 1)
            """)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=15,
                cwd=tmpdir,
            )
            assert proc.returncode == 0
            combined = proc.stdout + proc.stderr
            # All three tasks should be listed
            assert "build" in combined, f"Expected 'build' in task listing, got: {combined!r}"
            assert "deploy" in combined, f"Expected 'deploy' in task listing, got: {combined!r}"
            # test-code or test_code (depending on auto_dash_names)
            assert "test-code" in combined or "test_code" in combined, \
                f"Expected 'test-code' or 'test_code' in task listing, got: {combined!r}"

    def test_program_execute_task(self):
        """Program runs a named task with arguments through the full CLI pipeline."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            code = textwrap.dedent("""
                import sys
                from invoke import Program, Collection, task

                @task
                def greet(c, name="world"):
                    print(f"Hello, {name}!")

                program = Program(namespace=Collection(greet))
                try:
                    program.run(argv=["inv", "greet", "--name", "invoke"])
                except SystemExit as e:
                    sys.exit(0 if e.code is None or e.code == 0 else 1)
            """)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=15,
                cwd=tmpdir,
            )
            assert proc.returncode == 0
            combined = proc.stdout + proc.stderr
            assert "Hello, invoke!" in combined, \
                f"Expected 'Hello, invoke!' in output, got: {combined!r}"

    def test_program_unknown_task_error(self):
        """Program exits with error when an unknown task name is given."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            code = textwrap.dedent("""
                import sys
                from invoke import Program, Collection, task

                @task
                def build(c):
                    pass

                program = Program(namespace=Collection(build))
                try:
                    program.run(argv=["inv", "nonexistent_task"])
                except SystemExit as e:
                    sys.exit(e.code if e.code is not None and e.code != 0 else 1)
            """)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=15,
                cwd=tmpdir,
            )
            # Should exit with non-zero code
            assert proc.returncode != 0, \
                f"Expected non-zero exit for unknown task, got rc={proc.returncode}"
            # The error must actually identify the offending token, not merely produce *some*
            # output (a generic traceback / unrelated error would otherwise pass).
            combined = proc.stdout + proc.stderr
            assert "nonexistent_task" in combined, \
                f"Expected the unknown task name to be reported, got: {combined!r}"


# =============================================================================
# Integration Tests - Complex multi-component workflows
# =============================================================================


class TestIntegrationWorkflows:
    """End-to-end integration tests composing multiple invoke components."""

    def test_full_pipeline_loader_to_execution(self):
        """Load tasks from file, parse CLI args, execute with config."""
        from invoke import (
            FilesystemLoader, Collection, Config, Executor,
            Parser, Argument, task,
        )
        from invoke.parser import ParserContext

        # Create task module
        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_py = Path(tmpdir) / "tasks.py"
            tasks_py.write_text(textwrap.dedent("""
                from invoke import task

                @task
                def clean(c):
                    return "cleaned"

                @task
                def build(c, target="debug"):
                    return f"built-{target}"
            """))

            # Load
            loader = FilesystemLoader(start=tmpdir)
            mod, _ = loader.load("tasks")
            coll = Collection.from_module(mod)

            # Parse
            contexts = coll.to_contexts()
            parser = Parser(contexts=contexts)
            result = parser.parse_argv(["build", "--target", "release"])

            # Execute with parsed kwargs
            executor = Executor(coll, config=Config())
            kwargs = dict(result[0].as_kwargs)
            results = executor.execute(("build", kwargs))
            assert "built-release" in results.values()

    def test_mock_context_driven_test_workflow(self):
        """Use MockContext to test task logic without real command execution."""
        from invoke import task, MockContext, Result

        @task
        def deploy(c, target="staging"):
            # Check current branch
            branch = c.run("git branch --show-current").stdout.strip()
            if branch != "main":
                raise ValueError("Can only deploy from main")

            # Build
            build_result = c.run(f"make build TARGET={target}")
            if build_result.failed:
                raise RuntimeError("Build failed")

            # Deploy
            c.run(f"deploy.sh {target}")
            return f"deployed to {target}"

        # Test the happy path
        mc = MockContext(run={
            "git branch --show-current": Result("main\n"),
            re.compile(r"make build.*"): Result("build success"),
            re.compile(r"deploy\.sh.*"): Result("deployed"),
        })
        result = deploy(mc, target="production")
        assert result == "deployed to production"

        # Test the error path
        mc2 = MockContext(run={
            "git branch --show-current": Result("feature-branch\n"),
        })
        with pytest.raises(ValueError, match="Can only deploy from main"):
            deploy(mc2)

    def test_nested_collection_with_parser_and_executor(self):
        """Build nested collections, parse dotted task names, execute with config."""
        from invoke import task, Collection, Config, Executor

        results_log = []

        @task
        def db_migrate(c):
            results_log.append(f"migrated-{c.db_host}")
            return f"migrated-{c.db_host}"

        @task
        def db_seed(c):
            results_log.append(f"seeded-{c.db_host}")
            return f"seeded-{c.db_host}"

        @task
        def app_build(c):
            results_log.append("built")
            return "built"

        db = Collection("db", db_migrate, db_seed)
        db.configure({"db_host": "localhost:5432"})

        app = Collection("app", app_build)
        root = Collection(db, app)

        executor = Executor(root, config=Config())
        results = executor.execute("db.db-migrate", "app.app-build")
        values = list(results.values())
        assert "migrated-localhost:5432" in values
        assert "built" in values

    def test_task_argument_introspection_to_parser(self):
        """Task.get_arguments() produces Argument objects usable by the parser."""
        from invoke import task, Collection, Parser

        @task(
            positional=["name"],
            iterable=["tags"],
            help={"name": "Project name", "verbose": "Increase verbosity"},
        )
        def create(c, name, template="default", verbose=False, tags=[]):
            pass

        coll = Collection(create)
        contexts = coll.to_contexts()
        parser = Parser(contexts=contexts)

        # Parse with various arg styles
        result = parser.parse_argv([
            "create", "myproject",
            "--template", "flask",
            "--verbose",
            "--tags", "web",
            "--tags", "python",
        ])

        kwargs = dict(result[0].as_kwargs)
        assert kwargs["name"] == "myproject"
        assert kwargs["template"] == "flask"
        assert kwargs["verbose"] is True
        assert kwargs["tags"] == ["web", "python"]

    def test_config_hierarchy_through_executor(self):
        """Config flows correctly from collection configure through executor to task context."""
        from invoke import task, Collection, Config, Executor

        @task
        def check_config(c):
            return {
                "app": c.app_name,
                "env": c.environment,
                "db": c.db.host,
            }

        coll = Collection(check_config)
        coll.configure({
            "app_name": "myapp",
            "environment": "production",
            "db": {"host": "db.example.com", "port": 5432},
        })

        config = Config(defaults={"app_name": "default_app", "environment": "dev"})
        executor = Executor(coll, config=config)
        results = executor.execute("check-config")
        config_dict = list(results.values())[0]
        # Collection config overrides defaults
        assert config_dict["app"] == "myapp"
        assert config_dict["env"] == "production"
        assert config_dict["db"] == "db.example.com"

    def test_depth_first_dependency_chain(self):
        """Complex dependency chain executes in correct depth-first order."""
        from invoke import task, call, Collection, Config, Executor

        order = []

        @task
        def clean(c):
            order.append("clean")

        @task
        def makedirs(c):
            order.append("makedirs")

        @task(pre=[clean, makedirs])
        def build(c):
            order.append("build")

        @task(pre=[build])
        def test_suite(c):
            order.append("test")

        @task(pre=[build])
        def package(c):
            order.append("package")

        @task(pre=[test_suite, package])
        def release(c):
            order.append("release")

        coll = Collection(clean, makedirs, build, test_suite, package, release)
        executor = Executor(coll, config=Config())
        executor.execute("release")

        # clean and makedirs should appear before build
        assert order.index("clean") < order.index("build")
        assert order.index("makedirs") < order.index("build")
        # build should appear before test and package
        assert order.index("build") < order.index("test")
        assert order.index("build") < order.index("package")
        # test and package before release
        assert order.index("test") < order.index("release")
        assert order.index("package") < order.index("release")
        # build should only run once (dedup)
        assert order.count("build") == 1


# =============================================================================
# TestCrossFeatureIntegration - Cross-cutting integration tests
# =============================================================================


class TestCrossFeatureIntegration:
    """Integration tests that exercise multiple subsystems simultaneously."""

    def test_subcollection_parser_executor_pipeline(self):
        """Nested subcollections flow through Parser and Executor with per-subcollection config."""
        from invoke import task, Collection, Config, Executor, Parser
        from invoke.parser import ParserContext

        results_log = []

        @task
        def migrate(c, version="latest"):
            results_log.append(f"migrate-{c.db_host}-{version}")
            return f"migrate-{c.db_host}-{version}"

        @task
        def seed(c):
            results_log.append(f"seed-{c.db_host}")
            return f"seed-{c.db_host}"

        @task
        def build(c, target="debug"):
            results_log.append(f"build-{target}")
            return f"build-{target}"

        @task
        def deploy(c):
            results_log.append("deploy")
            return "deploy"

        # Build nested subcollections with different configs
        db = Collection("db", migrate, seed)
        db.configure({"db_host": "postgres:5432"})
        app = Collection("app", build, deploy)
        app.configure({"app_env": "production"})
        root = Collection(db, app)

        # Use to_contexts -> Parser -> parse_argv for dotted task resolution
        contexts = root.to_contexts()
        parser = Parser(contexts=contexts)
        result = parser.parse_argv(["db.migrate", "--version", "v3.2"])

        assert result[0].name == "db.migrate"
        kwargs = dict(result[0].as_kwargs)
        assert kwargs["version"] == "v3.2"

        # Execute via Executor with the parsed kwargs
        executor = Executor(root, config=Config())
        exec_results = executor.execute(("db.migrate", kwargs))
        values = list(exec_results.values())
        assert "migrate-postgres:5432-v3.2" in values

    def test_program_nested_subcollections_cli(self):
        """Program resolves nested subcollection tasks via CLI argv pipeline."""
        import subprocess

        with tempfile.TemporaryDirectory() as tmpdir:
            code = textwrap.dedent("""
                import sys
                from invoke import Program, Collection, task

                @task
                def migrate(c, version="latest"):
                    print(f"migrated-{version}")

                @task
                def build(c, target="debug"):
                    print(f"built-{target}")

                db = Collection("db", migrate)
                app = Collection("app", build)
                root = Collection(db, app)

                program = Program(namespace=root)
                try:
                    program.run(argv=["inv", "db.migrate", "--version", "v5"])
                except SystemExit as e:
                    sys.exit(0 if e.code is None or e.code == 0 else 1)
            """)
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, timeout=15,
                cwd=tmpdir,
            )
            assert proc.returncode == 0
            combined = proc.stdout + proc.stderr
            assert "migrated-v5" in combined, \
                f"Expected 'migrated-v5' in output, got: {combined!r}"

    def test_config_multi_source_merge(self):
        """Config merges defaults < collection < project file, with env vars on default keys."""
        from invoke import task, Collection, Config, Executor

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create project config file (invoke.yaml)
            # NOTE: avoid "run" key — Context.run() method shadows config proxy access
            config_path = Path(tmpdir) / "invoke.yaml"
            config_path.write_text(
                "deploy:\n"
                "  verbose: true\n"
                "db:\n"
                "  host: yaml-host\n"
                "  port: 5432\n",
                encoding="utf-8",
            )

            @task
            def check(c):
                return {
                    "verbose": c.deploy.verbose,
                    "db_host": c.db.host,
                    "db_port": c.db.port,
                    "app_name": c.app_name,
                }

            coll = Collection(check)
            # Collection-level config: lower priority than project file
            coll.configure({"app_name": "myapp", "db": {"host": "collection-host"}})

            # Merge order: defaults < collection < project file
            config = Config(
                defaults={"db": {"host": "default-host", "port": 3306}},
                project_location=tmpdir,
            )
            config.load_project()

            executor = Executor(coll, config=config)
            results = executor.execute("check")
            result_dict = list(results.values())[0]

            # project file overrides both default and collection for db.host
            assert result_dict["db_host"] == "yaml-host"
            # project file overrides defaults for db.port
            assert result_dict["db_port"] == 5432
            # collection config provides app_name (not in project file so survives)
            assert result_dict["app_name"] == "myapp"
            # project file sets deploy.verbose
            assert result_dict["verbose"] is True

    def test_pre_post_dedup_with_call_kwargs(self):
        """call() kwargs flow, dedup keyed on (task, kwargs), and post ordering.

        Deduplication compares a Call by its task AND its bound kwargs, so two
        identical call()s collapse to one, while a call() carrying kwargs and a
        plain reference to the same task (default kwargs) are distinct and both
        run. This is orthogonal to the pure-pre depth-first chain covered
        elsewhere.
        """
        from invoke import task, call, Collection, Config, Executor

        order = []

        @task
        def build(c, target="debug"):
            order.append(f"build-{target}")

        @task
        def cleanup(c):
            order.append("cleanup")

        # `package` depends on a plain build (default kwargs -> "build-debug").
        @task(pre=[build])
        def package(c):
            order.append("package")

        # `release` requests build twice via call(target="release") plus the
        # `package` pre (which pulls in the plain build), and a post cleanup.
        @task(
            pre=[call(build, target="release"), call(build, target="release"), package],
            post=[cleanup],
        )
        def release(c):
            order.append("release")

        coll = Collection(build, cleanup, package, release)
        Executor(coll, config=Config()).execute("release")

        # The two identical call(build, target="release") dedupe to ONE run.
        assert order.count("build-release") == 1
        # call() kwargs reached the task body.
        assert "build-release" in order
        # The plain `build` (default target) is a DISTINCT call (different
        # kwargs), so it is NOT deduped against the call() variant -- both run.
        assert "build-debug" in order
        # Pre-tasks precede the main task; the post task follows it.
        assert order.index("build-release") < order.index("release")
        assert order.index("package") < order.index("release")
        assert order.index("release") < order.index("cleanup")
