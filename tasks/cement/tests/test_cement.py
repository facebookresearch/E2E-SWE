"""
Integration tests for the Cement CLI application framework.
Tests exercise realistic usage patterns composing App, Controller, Handler,
Interface, Hook, Config, and utility components together.
"""

import os
import json
import tempfile
from io import StringIO

import pytest


def _assert_smtp_connection(smtp_cls, host, port, timeout):
    """Assert how ``smtplib.SMTP`` was constructed without pinning the calling convention.

    The framework may pass ``host``/``port``/``timeout`` positionally
    (``SMTP(host, port, timeout)``) or with ``timeout`` as a keyword
    (``SMTP(host, port, timeout=...)``). Both are correct, so check the effective
    values from ``call_args`` rather than requiring an exact positional tuple.
    """
    call = smtp_cls.call_args
    args, kwargs = call.args, call.kwargs
    assert args[0] == host
    assert args[1] == port
    effective_timeout = kwargs["timeout"] if "timeout" in kwargs else args[2]
    assert effective_timeout == timeout


# =============================================================================
# App Lifecycle
# =============================================================================


class TestAppLifecycle:
    """Tests for App creation, setup, run, close lifecycle."""

    def test_app_context_manager_full_lifecycle(self):
        """Create an App with context manager, setup+close happen automatically."""
        from cement import TestApp

        with TestApp() as app:
            # Setup ran automatically on __enter__: the app's own config section (named after
            # its label) was created and the log handler defaults to the INFO level.
            assert app.config.has_section(app.label)
            assert app.log.get_level() == "INFO"

    def test_app_with_custom_meta_and_debug(self):
        """App with custom label and debug mode via argv."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                label = "myapp"

        with MyApp(argv=["--debug"]) as app:
            app.run()
            assert app.label == "myapp"
            assert app.debug is True

    def test_app_config_defaults_and_access(self):
        """App merges config_defaults and provides attribute access."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "database")
        defaults["myapp"]["debug"] = False
        defaults["database"]["host"] = "localhost"
        defaults["database"]["port"] = "5432"

        with TestApp(config_defaults=defaults) as app:
            assert app.config.has_section("database")
            assert app.config.get("database", "host") == "localhost"
            assert app.config.get("database", "port") == "5432"

    def test_app_extend_and_render(self):
        """App.extend adds attributes; render sends data through output handler."""
        from cement import TestApp, FrameworkError

        class MyApp(TestApp):
            class Meta:
                extensions = ["json"]
                output_handler = "json"

        with MyApp() as app:
            # extend
            app.extend("custom_data", {"key": "value"})
            assert app.custom_data == {"key": "value"}
            with pytest.raises(FrameworkError):
                app.extend("custom_data", "other")

            # render with JSON output
            out = StringIO()
            app.render({"name": "test", "value": 42}, out=out)
            rendered = json.loads(out.getvalue())
            assert rendered["name"] == "test"
            assert rendered["value"] == 42
            assert app.last_rendered is not None

    def test_app_quiet_mode(self, capsys):
        """App in quiet mode suppresses render output to stdout while still returning it."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["json"]
                output_handler = "json"

        with MyApp(argv=["--quiet"]) as app:
            app.run()
            assert app.quiet is True
            out_text = app.render({"data": "test"})
            data, text = app.last_rendered

        # Quiet mode suppresses the stdout write: nothing is emitted to stdout.
        assert capsys.readouterr().out == ""
        # render still computes and returns the rendered text (and records it in last_rendered).
        assert data == {"data": "test"}
        assert text == out_text == '{"data": "test"}'

    def test_app_lifecycle_hooks_fire_in_order(self):
        """App setup, run, render, and close hooks fire around a full app workflow."""
        from cement import TestApp

        events = []

        def mark(name):
            def _hook(app):
                events.append(name)
            return _hook

        class MyApp(TestApp):
            class Meta:
                hooks = [
                    ("pre_setup", mark("pre_setup")),
                    ("post_setup", mark("post_setup")),
                    ("pre_run", mark("pre_run")),
                    ("post_run", mark("post_run")),
                    ("pre_close", mark("pre_close")),
                    ("post_close", mark("post_close")),
                ]

        with MyApp() as app:
            assert events[:2] == ["pre_setup", "post_setup"]
            app.run()
            assert events[2:4] == ["pre_run", "post_run"]

        assert events == [
            "pre_setup",
            "post_setup",
            "pre_run",
            "post_run",
            "pre_close",
            "post_close",
        ]

    def test_default_dummy_output_records_last_render_without_writing(self):
        """Default dummy output records rendered data while producing no text object."""
        from cement import TestApp

        with TestApp() as app:
            out = StringIO()
            app.render({"silent": True, "count": 3}, out=out)
            assert out.getvalue() == ""
            data, rendered = app.last_rendered
            assert data == {"silent": True, "count": 3}
            assert rendered is None


# =============================================================================
# Controller + @ex Decorator
# =============================================================================


class TestControllerCommands:
    """Tests for Controller with @ex-decorated commands."""

    def test_controller_with_arguments(self):
        """Controller commands with CLI arguments and dispatch."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(
                help="greet someone",
                arguments=[
                    (["-n", "--name"], dict(dest="name", default="world")),
                    (["-l", "--loud"], dict(dest="loud", action="store_true")),
                ],
            )
            def greet(self):
                name = self.app.pargs.name
                loud = self.app.pargs.loud
                msg = f"Hello {name}!"
                if loud:
                    msg = msg.upper()
                self.app.extend("greeting", msg)

        with TestApp(handlers=[Base], argv=["greet", "-n", "Alice", "--loud"]) as app:
            app.run()
            assert app.greeting == "HELLO ALICE!"

    def test_nested_controller_stacking(self):
        """Nested controllers create sub-command namespaces."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

        class DbController(Controller):
            class Meta:
                label = "db"
                stacked_on = "base"
                stacked_type = "nested"
                help = "database commands"

            @ex(help="run migrations")
            def migrate(self):
                self.app.extend("db_result", "migrated")

        with TestApp(handlers=[Base, DbController], argv=["db", "migrate"]) as app:
            app.run()
            assert app.db_result == "migrated"

    def test_embedded_controller_stacking(self):
        """Embedded controllers add commands to parent namespace."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

        class Extra(Controller):
            class Meta:
                label = "extra"
                stacked_on = "base"
                stacked_type = "embedded"

            @ex(help="extra command")
            def bonus(self):
                self.app.extend("bonus_result", "done")

        with TestApp(handlers=[Base, Extra], argv=["bonus"]) as app:
            app.run()
            assert app.bonus_result == "done"

    def test_controller_meta_arguments(self):
        """Controller Meta.arguments adds global args to the controller."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"
                arguments = [
                    (["-v", "--verbose"], dict(dest="verbose", action="store_true")),
                ]

            @ex(help="run task")
            def run_task(self):
                self.app.extend("verbose", self.app.pargs.verbose)

        with TestApp(handlers=[Base], argv=["--verbose", "run-task"]) as app:
            app.run()
            assert app.verbose is True

    def test_controller_command_label_override_and_positional_args(self):
        """A command can expose a custom CLI label and parse positional arguments."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(label="copy-file", arguments=[(["src"], {}), (["dest"], {})])
            def copy_impl(self):
                self.app.extend("copy_result", f"{self.app.pargs.src}->{self.app.pargs.dest}")

        with TestApp(handlers=[Base], argv=["copy-file", "input.txt", "output.txt"]) as app:
            app.run()
            assert app.copy_result == "input.txt->output.txt"

    def test_controller_hidden_command_omits_help_description(self, capsys):
        """Hidden controller commands dispatch but omit their help description."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(help="visible command")
            def visible(self):
                self.app.extend("visible_result", "shown")

            @ex(hide=True, help="secret command")
            def hidden(self):
                self.app.extend("hidden_result", "ran")

        with TestApp(handlers=[Base], argv=["hidden"]) as app:
            app.run()
            assert app.hidden_result == "ran"

        with pytest.raises(SystemExit):
            with TestApp(handlers=[Base], argv=["--help"]) as app:
                app.run()

        help_text = capsys.readouterr().out
        assert "visible" in help_text
        assert "visible command" in help_text
        assert "secret command" not in help_text

    def test_nested_controller_combines_parent_and_child_arguments(self):
        """Nested controllers preserve parent options while parsing child command args."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"
                arguments = [(["--tenant"], dict(default="default"))]

        class Reports(Controller):
            class Meta:
                label = "reports"
                stacked_on = "base"
                stacked_type = "nested"

            @ex(arguments=[(["name"], {}), (["--limit"], dict(type=int, default=10))])
            def show(self):
                self.app.extend(
                    "report_result",
                    (self.app.pargs.tenant, self.app.pargs.name, self.app.pargs.limit),
                )

        with TestApp(
            handlers=[Base, Reports],
            argv=["--tenant", "analytics", "reports", "show", "daily", "--limit", "2"],
        ) as app:
            app.run()
            assert app.report_result == ("analytics", "daily", 2)


# =============================================================================
# Hook System
# =============================================================================


class TestHookSystem:
    """Tests for the Hook system with lifecycle integration."""

    def test_hooks_with_weight_ordering_and_lifecycle(self):
        """Define hooks, register with weights, verify ordering. Framework hooks fire during lifecycle."""
        from cement import TestApp

        order = []
        events = []

        def third(app):
            order.append("third")

        def first(app):
            order.append("first")

        def second(app):
            order.append("second")

        def on_pre_run(app):
            events.append("pre_run")

        def on_post_run(app):
            events.append("post_run")

        with TestApp(
            define_hooks=["ordered"],
            hooks=[("pre_run", on_pre_run), ("post_run", on_post_run)],
        ) as app:
            app.hook.register("ordered", third, weight=30)
            app.hook.register("ordered", first, weight=10)
            app.hook.register("ordered", second, weight=20)

            results = list(app.hook.run("ordered", app))
            assert order == ["first", "second", "third"]

            # Framework hooks
            assert app.hook.defined("ordered")
            assert app.hook.defined("pre_setup")
            assert "ordered" in app.hook.list()
            assert "pre_run" in app.hook.list()

            app.run()
            assert "pre_run" in events
            assert "post_run" in events


# =============================================================================
# Handler + Interface System
# =============================================================================


class TestHandlerInterface:
    """Tests for custom Interfaces and Handlers."""

    def test_register_custom_interface_and_handler(self):
        """Define a custom interface, register handler, resolve by label and class."""
        from cement import TestApp, Interface, Handler

        class MyInterface(Interface):
            class Meta:
                interface = "my_service"

        class MyHandler(MyInterface, Handler):
            class Meta:
                label = "default"

            def do_work(self):
                return "work_done"

        with TestApp(interfaces=[MyInterface], handlers=[MyHandler]) as app:
            assert app.interface.defined("my_service")
            assert app.handler.registered("my_service", "default")

            handler_cls = app.handler.get("my_service", "default")
            assert handler_cls is MyHandler
            assert MyHandler in app.handler.list("my_service")

            # Resolve by label
            resolved = app.handler.resolve("my_service", "default")
            assert isinstance(resolved, MyHandler)

            # Resolve by class
            resolved2 = app.handler.resolve("my_service", MyHandler)
            assert isinstance(resolved2, MyHandler)

    def test_handler_config_defaults_merged(self):
        """Handler config_defaults are merged into App config during setup."""
        from cement import TestApp, Interface, Handler

        class CacheInterface(Interface):
            class Meta:
                interface = "custom_cache"

        class CacheHandler(CacheInterface, Handler):
            class Meta:
                label = "memory"
                config_defaults = dict(max_size=1000, ttl=300)

        with TestApp(interfaces=[CacheInterface], handlers=[CacheHandler]) as app:
            h = app.handler.setup(CacheHandler)
            section = "custom_cache.memory"
            assert app.config.has_section(section)
            assert str(app.config.get(section, "max_size")) == "1000"

    def test_handler_force_registration_replaces_existing_label(self):
        """A handler can be force-registered to replace an existing label."""
        from cement import TestApp, Interface, Handler

        class StoreInterface(Interface):
            class Meta:
                interface = "store"

        class OldStore(StoreInterface, Handler):
            class Meta:
                label = "default"

            def value(self):
                return "old"

        class NewStore(StoreInterface, Handler):
            class Meta:
                label = "default"

            def value(self):
                return "new"

        with TestApp(interfaces=[StoreInterface], handlers=[OldStore]) as app:
            assert app.handler.resolve("store", "default", setup=True).value() == "old"
            app.handler.register(NewStore, force=True)
            assert app.handler.get("store", "default") is NewStore
            assert app.handler.resolve("store", "default", setup=True).value() == "new"

    def test_handler_setup_uses_custom_config_section(self):
        """Handler setup merges defaults into an explicitly named config section."""
        from cement import TestApp, Interface, Handler

        class SearchInterface(Interface):
            class Meta:
                interface = "search"

        class SearchHandler(SearchInterface, Handler):
            class Meta:
                label = "memory"
                config_section = "search.backend"
                config_defaults = {"index": "primary", "batch_size": 25}

        with TestApp(interfaces=[SearchInterface], handlers=[SearchHandler]) as app:
            handler = app.handler.resolve("search", "memory", setup=True)
            assert isinstance(handler, SearchHandler)
            assert app.config.get("search.backend", "index") == "primary"
            assert str(app.config.get("search.backend", "batch_size")) == "25"


# =============================================================================
# Config System
# =============================================================================


class TestConfigSystem:
    """Tests for the config handler."""

    def test_config_file_parsing_and_merge(self):
        """Config parses .conf files and merges dicts."""
        from cement import TestApp

        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write("[myapp]\ndebug = true\n\n[database]\nhost = db.example.com\nport = 5432\n")
            f.flush()
            conf_path = f.name

        try:
            with TestApp() as app:
                app.config.parse_file(conf_path)
                assert app.config.has_section("database")
                assert app.config.get("database", "host") == "db.example.com"

                # Merge
                app.config.merge({"new_section": {"key1": "val1"}})
                assert app.config.has_section("new_section")
                assert app.config.get("new_section", "key1") == "val1"

                # Section dict
                section = app.config.get_section_dict("database")
                assert section["host"] == "db.example.com"
        finally:
            os.unlink(conf_path)

    def test_config_env_var_override(self):
        """Config values can be overridden by environment variables."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "myapp")
        defaults["myapp"]["setting"] = "default_value"

        env_key = "MYAPP_SETTING"
        os.environ[env_key] = "from_env"
        try:
            class MyApp(TestApp):
                class Meta:
                    label = "myapp"

            with MyApp(config_defaults=defaults) as app:
                val = app.config.get("myapp", "setting")
                assert val == "from_env"
        finally:
            del os.environ[env_key]

    def test_config_env_var_override_for_non_app_section(self):
        """Environment overrides for non-app sections include app, section, and key."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "database")
        defaults["database"]["host"] = "default-db"
        defaults["database"]["port"] = "5432"

        env_key = "MYAPP_DATABASE_HOST"
        os.environ[env_key] = "env-db"
        try:
            class MyApp(TestApp):
                class Meta:
                    label = "myapp"

            with MyApp(config_defaults=defaults) as app:
                assert app.config.get("database", "host") == "env-db"
                assert app.config.get("database", "port") == "5432"
        finally:
            del os.environ[env_key]

    def test_config_set_sections_and_section_dict_reflect_updates(self):
        """Config set/get_sections/get_section_dict reflect runtime updates."""
        from cement import TestApp

        with TestApp() as app:
            app.config.add_section("runtime")
            app.config.set("runtime", "enabled", "true")
            app.config.set("runtime", "workers", "4")

            assert "runtime" in app.config.get_sections()
            assert app.config.get("runtime", "enabled") == "true"
            assert app.config.get_section_dict("runtime") == {
                "enabled": "true",
                "workers": "4",
            }

    def test_yaml_config_file(self):
        """YAML config handler parses .yml files."""
        from cement import TestApp
        import yaml

        config_data = {"myapp": {"version": "1.0"}, "server": {"host": "localhost", "port": 8080}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            yaml.dump(config_data, f)
            f.flush()
            yml_path = f.name

        try:
            class MyApp(TestApp):
                class Meta:
                    label = "myapp"
                    extensions = ["yaml"]
                    config_handler = "yaml"

            with MyApp() as app:
                app.config.parse_file(yml_path)
                assert app.config.get("server", "host") == "localhost"
        finally:
            os.unlink(yml_path)


# =============================================================================
# Output Handlers
# =============================================================================


class TestOutputHandlers:
    """Tests for JSON and print output handlers."""

    def test_json_output_handler(self):
        """JSON output handler renders data as JSON string."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["json"]
                output_handler = "json"

        with MyApp() as app:
            out = StringIO()
            app.render({"users": ["alice", "bob"], "count": 2}, out=out)
            data = json.loads(out.getvalue())
            assert data["users"] == ["alice", "bob"]
            assert data["count"] == 2

    def test_print_output_handler(self):
        """Print output handler prints data['out'] key."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["print"]
                output_handler = "print"

        with MyApp() as app:
            out = StringIO()
            app.render({"out": "Hello from print handler"}, out=out)
            assert "Hello from print handler" in out.getvalue()

    def test_tabulate_output_handler(self):
        """Tabulate output handler renders data as a table."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["tabulate"]
                output_handler = "tabulate"

        with MyApp() as app:
            out = StringIO()
            data = [["Alice", 30], ["Bob", 25]]
            app.render(data, headers=["Name", "Age"], out=out)
            output = out.getvalue()
            assert "Alice" in output
            assert "Bob" in output
            assert "Name" in output

    def test_scrub_extension(self):
        """Scrub extension provides app.scrub() for regex-based text obfuscation."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(help="show data")
            def show(self):
                text = "User email: alice@example.com, phone: 555-1234"
                scrubbed = self.app.scrub(text)
                self.app.extend("scrubbed", scrubbed)

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["scrub"]
                handlers = [Base]
                scrub = [
                    (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "***@***.***"),
                    (r"\d{3}-\d{4}", "***-****"),
                ]

        with MyApp(argv=["show"]) as app:
            app.run()
            assert "***@***.***" in app.scrubbed
            assert "***-****" in app.scrubbed
            assert "alice@example.com" not in app.scrubbed

    def test_yaml_output_handler_round_trips_structured_data(self):
        """YAML output renders structured data that can be parsed back."""
        from cement import TestApp
        import yaml

        class MyApp(TestApp):
            class Meta:
                extensions = ["yaml"]
                output_handler = "yaml"

        with MyApp() as app:
            out = StringIO()
            app.render({"items": ["alpha", "beta"], "enabled": True}, out=out)
            parsed = yaml.safe_load(out.getvalue())
            assert parsed == {"items": ["alpha", "beta"], "enabled": True}

# =============================================================================
# Additional Extension Tests
# =============================================================================


class TestAdditionalExtensions:
    """Tests for Redis cache, colorlog, Jinja2, alarm, and watchdog extensions."""

    def test_redis_cache_handler(self):
        """Redis cache extension provides set/get/delete/purge through App.cache."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "cache.redis")
        defaults["cache.redis"]["host"] = "127.0.0.1"
        defaults["cache.redis"]["port"] = "6379"
        defaults["cache.redis"]["db"] = "0"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["redis"]
                cache_handler = "redis"

        with MyApp(config_defaults=defaults) as app:
            app.cache.set("test_key_1", "value_1")
            app.cache.set("test_key_2", "value_2")
            assert app.cache.get("test_key_1") == "value_1"
            assert app.cache.get("test_key_2") == "value_2"
            assert app.cache.get("nonexistent") is None
            assert app.cache.get("nonexistent", fallback="default") == "default"

            app.cache.delete("test_key_1")
            assert app.cache.get("test_key_1") is None

            app.cache.purge()
            assert app.cache.get("test_key_2") is None

    def test_colorlog_handler(self):
        """Colorlog extension provides colorized logging with level control."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "log.colorlog")
        defaults["log.colorlog"]["level"] = "DEBUG"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["colorlog"]
                log_handler = "colorlog"

        with MyApp(config_defaults=defaults) as app:
            # The active log handler must be the colorlog handler itself, not the
            # plain logging handler — an impl that maps log_handler="colorlog" to
            # the logging handler would fail this.
            assert isinstance(app.log, app.handler.get("log", "colorlog"))
            app.log.info("colorlog info message")
            app.log.debug("colorlog debug message")
            app.log.warning("colorlog warning")

    def test_jinja2_template_output(self):
        """Jinja2 extension renders templates with variable substitution."""
        from cement import TestApp
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create template file
            with open(os.path.join(tmpdir, "report.jinja2"), "w") as f:
                f.write("Hello {{ name }}! Count: {{ count }}")

            class MyApp(TestApp):
                class Meta:
                    extensions = ["jinja2"]
                    output_handler = "jinja2"
                    template_dirs = [tmpdir]

            with MyApp() as app:
                out = StringIO()
                app.render({"name": "Alice", "count": 42}, "report.jinja2", out=out)
                output = out.getvalue()
                assert "Alice" in output
                assert "42" in output

    def test_mustache_template_output(self):
        """Mustache extension renders filesystem templates with pystache semantics."""
        from cement import TestApp
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "card.mustache"), "w") as f:
                f.write("{{name}}: {{#active}}active{{/active}}{{^active}}inactive{{/active}}")

            class MyApp(TestApp):
                class Meta:
                    extensions = ["mustache"]
                    output_handler = "mustache"
                    template_dirs = [tmpdir]

            with MyApp() as app:
                out = StringIO()
                app.render({"name": "Ada", "active": True}, "card.mustache", out=out)
                assert out.getvalue() == "Ada: active"

    def test_alarm_extension(self):
        """Alarm extension fires SIGALRM after timeout."""
        import signal
        import time
        from cement import TestApp, CaughtSignal

        class MyApp(TestApp):
            class Meta:
                extensions = ["alarm"]

        caught = False
        try:
            with MyApp() as app:
                app.alarm.set(1, "test alarm")
                time.sleep(3)
        except CaughtSignal as e:
            assert e.signum == signal.SIGALRM
            caught = True
        assert caught, "Expected CaughtSignal with SIGALRM"

    def test_alarm_stop_prevents_pending_signal(self):
        """Stopping an alarm cancels the pending SIGALRM before it fires."""
        import time
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["alarm"]

        with MyApp() as app:
            app.alarm.set(1, "should not fire")
            app.alarm.stop()
            time.sleep(2)

    def test_watchdog_file_monitoring(self):
        """Watchdog detects a filesystem change and invokes the registered event handler."""
        import time
        import tempfile
        from cement import TestApp
        from cement.ext.ext_watchdog import WatchdogEventHandler

        observed = []

        class RecordingEventHandler(WatchdogEventHandler):
            def on_any_event(self, event):
                observed.append(event.src_path)

        class MyApp(TestApp):
            class Meta:
                extensions = ["watchdog"]

        with tempfile.TemporaryDirectory() as tmpdir:
            with MyApp() as app:
                assert app.watchdog.add(tmpdir, event_handler=RecordingEventHandler) is True
                app.watchdog.start()

                # Create a file — the observer should fire an event for it.
                target = os.path.join(tmpdir, "created.txt")
                with open(target, "w") as f:
                    f.write("hello")

                # Poll for the observer thread to deliver the event.
                deadline = time.time() + 5
                while not observed and time.time() < deadline:
                    time.sleep(0.05)

                app.watchdog.stop()
                app.watchdog.join()

            assert observed, "watchdog did not deliver any filesystem event"
            assert any(os.path.basename(p) == "created.txt" for p in observed)

    def test_daemon_environment_switch_with_mock(self):
        """Daemon Environment.switch() applies the configured user/group/dir via OS calls."""
        import getpass
        import pwd
        from unittest.mock import patch
        from cement.ext.ext_daemon import Environment

        current_user = getpass.getuser()
        # No group is configured below, so the resolved group is the user's primary group.
        entry = pwd.getpwnam(current_user)

        with patch("os.setuid") as mock_setuid, \
             patch("os.setgid") as mock_setgid, \
             patch("os.chdir") as mock_chdir:
            # Construct through the documented public constructor for an existing user.
            env = Environment(user=current_user, dir="/tmp")
            env.switch()
            mock_setuid.assert_called_once_with(entry.pw_uid)
            mock_setgid.assert_called_once_with(entry.pw_gid)
            mock_chdir.assert_called_once_with("/tmp")


# =============================================================================
# Utilities + Exceptions
# =============================================================================


class TestUtilitiesAndExceptions:
    """Tests for utility functions and exception classes."""

    def test_utilities_and_exceptions(self):
        """init_defaults, is_true, fs.Tmp, shell.cmd, and exception classes work correctly."""
        from cement import init_defaults, misc, fs, shell
        from cement import FrameworkError, InterfaceError, CaughtSignal

        # init_defaults
        defaults = init_defaults("app", "db", "cache")
        assert "app" in defaults and "db" in defaults and isinstance(defaults["app"], dict)

        # is_true
        assert misc.is_true(True) and misc.is_true("true") and misc.is_true("1") and misc.is_true(1)
        assert not misc.is_true(False) and not misc.is_true("no") and not misc.is_true(0)

        # fs.Tmp context manager
        with fs.Tmp() as tmp:
            assert os.path.isdir(tmp.dir)
            assert os.path.isfile(tmp.file)
            dir_path = tmp.dir
        assert not os.path.exists(dir_path)

        # fs path operations
        assert "~" not in fs.abspath("~/test")
        assert fs.join("/tmp", "a", "b") == "/tmp/a/b"

        # shell.cmd
        stdout, stderr, exitcode = shell.cmd("echo hello")
        assert exitcode == 0
        assert b"hello" in stdout

        # Exceptions
        e = FrameworkError("broke")
        assert str(e) == "broke" and e.msg == "broke"
        assert isinstance(InterfaceError("bad"), FrameworkError)
        sig = CaughtSignal(15, None)
        assert sig.signum == 15

    def test_filesystem_and_shell_edge_behaviors(self):
        """Filesystem helpers and shell command execution handle edge cases."""
        from cement import fs, shell

        with tempfile.TemporaryDirectory() as tmpdir:
            nested = fs.join(tmpdir, "a", "b")
            fs.ensure_dir_exists(nested)
            assert os.path.isdir(nested)

        stdout, stderr, exitcode = shell.cmd(
            "printf out; printf err >&2; exit 7",
            capture=True,
        )
        assert stdout == b"out"
        assert stderr == b"err"
        assert exitcode == 7

        assert shell.cmd("exit 5", capture=False) == 5


# =============================================================================
# Log Handler
# =============================================================================


class TestLogHandler:
    """Tests for the logging handler."""

    def test_log_levels_and_messages(self):
        """Log handler supports multiple levels and level get/set."""
        from cement import TestApp

        with TestApp() as app:
            assert app.log.get_level() == "INFO"
            app.log.set_level("DEBUG")
            assert app.log.get_level() == "DEBUG"
            app.log.info("info")
            app.log.warning("warn")
            app.log.error("err")
            app.log.debug("debug")


# =============================================================================
# Integration: Full Application Workflows
# =============================================================================


class TestIntegrationWorkflows:
    """End-to-end integration tests composing many cement features."""

    def test_full_app_with_controllers_hooks_config(self):
        """Complete app with controllers, hooks, config, and output rendering."""
        from cement import TestApp, Controller, ex, init_defaults

        events = []

        def on_pre_run(app):
            events.append("pre_run")

        def on_post_run(app):
            events.append("post_run")

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(help="show status")
            def status(self):
                host = self.app.config.get("server", "host")
                self.app.extend("status_msg", f"Server at {host}")

        defaults = init_defaults("myapp", "server")
        defaults["server"]["host"] = "localhost"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                handlers = [Base]
                hooks = [("pre_run", on_pre_run), ("post_run", on_post_run)]

        with MyApp(argv=["status"], config_defaults=defaults) as app:
            app.run()
            assert "pre_run" in events and "post_run" in events
            assert app.status_msg == "Server at localhost"

    def test_multiple_nested_controllers(self):
        """App with multiple nested controllers dispatching correctly."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"

        class Users(Controller):
            class Meta:
                label = "users"
                stacked_on = "base"
                stacked_type = "nested"

            @ex(help="list users")
            def list_users(self):
                self.app.extend("users_result", "listed")

        class Items(Controller):
            class Meta:
                label = "items"
                stacked_on = "base"
                stacked_type = "nested"

            @ex(help="add item", arguments=[(["name"], dict(help="item name"))])
            def add(self):
                self.app.extend("item_added", self.app.pargs.name)

        with TestApp(handlers=[Base, Users, Items], argv=["items", "add", "widget"]) as app:
            app.run()
            assert app.item_added == "widget"

    def test_custom_handler_in_app(self):
        """Custom interface + handler integrated into full app lifecycle."""
        from cement import TestApp, Interface, Handler, Controller, ex

        class StorageInterface(Interface):
            class Meta:
                interface = "storage"

        class MemoryStorage(StorageInterface, Handler):
            class Meta:
                label = "memory"
                config_defaults = dict(max_items="100")

            def __init__(self, **kw):
                super().__init__(**kw)
                self._data = {}

            def save(self, key, value):
                self._data[key] = value

            def load(self, key):
                return self._data.get(key)

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(help="save data")
            def save(self):
                storage = self.app.handler.resolve("storage", "memory", setup=True)
                storage.save("test_key", "test_value")
                self.app.extend("saved", storage.load("test_key"))

        with TestApp(
            interfaces=[StorageInterface],
            handlers=[MemoryStorage, Base],
            argv=["save"],
        ) as app:
            app.run()
            assert app.saved == "test_value"

    def test_json_config_file_integration(self):
        """App loads JSON config file and merges with defaults."""
        from cement import TestApp, init_defaults

        config_data = {"myapp": {"version": "1.0"}, "database": {"host": "prod-db", "port": "3306"}}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            f.flush()
            config_path = f.name

        try:
            defaults = init_defaults("myapp", "database")
            defaults["database"]["host"] = "localhost"

            class MyApp(TestApp):
                class Meta:
                    label = "myapp"
                    extensions = ["json"]
                    config_handler = "json"

            with MyApp(config_defaults=defaults) as app:
                app.config.parse_file(config_path)
                assert app.config.get("database", "host") == "prod-db"
        finally:
            os.unlink(config_path)

    def test_meta_mixin_merges_across_inheritance(self):
        """MetaMixin merges Meta from parent to child correctly."""
        from cement import TestApp, Controller, ex

        class Base(Controller):
            class Meta:
                label = "base"
                arguments = [(["-v", "--verbose"], dict(dest="verbose", action="store_true"))]

            @ex(help="cmd")
            def shared_cmd(self):
                self.app.extend("from_base", True)

        with TestApp(handlers=[Base], argv=["--verbose", "shared-cmd"]) as app:
            app.run()
            assert app.pargs.verbose is True
            assert app.from_base is True

    def test_full_rendering_workflow_with_config_env_hooks_and_json(self):
        """A controller can combine env config, hooks, and JSON rendering in one workflow."""
        from cement import TestApp, Controller, ex, init_defaults

        events = []

        def on_pre_run(app):
            events.append("pre")

        def on_post_run(app):
            events.append("post")

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(arguments=[(["--name"], dict(default="service"))])
            def status(self):
                data = {
                    "name": self.app.pargs.name,
                    "host": self.app.config.get("server", "host"),
                    "events_before_render": list(events),
                }
                out = StringIO()
                self.app.render(data, out=out)
                self.app.extend("rendered_status", json.loads(out.getvalue()))

        defaults = init_defaults("myapp", "server")
        defaults["server"]["host"] = "default-host"

        os.environ["MYAPP_SERVER_HOST"] = "env-host"
        try:
            class MyApp(TestApp):
                class Meta:
                    label = "myapp"
                    extensions = ["json"]
                    output_handler = "json"
                    handlers = [Base]
                    hooks = [("pre_run", on_pre_run), ("post_run", on_post_run)]

            with MyApp(argv=["status", "--name", "api"], config_defaults=defaults) as app:
                app.run()
                assert app.rendered_status == {
                    "name": "api",
                    "host": "env-host",
                    "events_before_render": ["pre"],
                }
                assert events == ["pre", "post"]
        finally:
            del os.environ["MYAPP_SERVER_HOST"]


# =============================================================================
# Public API Compatibility
# =============================================================================


class TestPublicApiCompatibility:
    """Tests for public modules and compatibility helpers exposed by Cement."""

    def test_top_level_version_and_backend_helpers(self):
        """get_version formats a PEP-386 version string, including non-final release suffixes."""
        import cement
        from cement.core import backend
        from cement.utils.version import VERSION, get_version, get_version_banner

        assert backend.VERSION == VERSION
        assert cement.get_version() == get_version()

        # The only real branch in get_version() is the release-suffix mapping for
        # non-"final" releases; exercise it with explicit version tuples.
        assert get_version((3, 0, 15, "final", 0)) == "3.0.15"
        assert get_version((3, 0, 15, "beta", 2)) == "3.0.15b2"
        assert get_version((1, 2, 0, "rc", 1)) == "1.2.0c1"
        assert get_version((2, 1, 0, "alpha", 3)) == "2.1.0a3"

        # The banner's first line is exactly "Cement Framework <version>".
        assert get_version_banner().splitlines()[0] == f"Cement Framework {get_version()}"

    def test_public_module_layout_exposes_documented_names(self):
        """The documented public module layout exists and carries its documented names."""
        import cement
        import cement.cli.controllers.base  # noqa: F401
        from cement.core import cache, deprecations, extension, foundation, mail, plugin, template
        from cement.utils import fs as utils_fs
        from cement.utils import misc as utils_misc
        from cement.utils import shell as utils_shell

        # cement.core.foundation carries the framework base classes, and they are the same
        # objects the top-level package exposes.
        for name in ("App", "TestApp", "Controller", "Handler", "Interface"):
            assert hasattr(foundation, name), f"cement.core.foundation.{name} is missing"
        assert foundation.App is cement.App
        assert issubclass(foundation.TestApp, foundation.App)

        # Interface/handler pairs published by the compatibility modules.
        assert hasattr(extension, "ExtensionInterface") and hasattr(extension, "ExtensionHandler")
        assert hasattr(mail, "MailInterface") and hasattr(mail, "MailHandler")
        assert hasattr(plugin, "PluginInterface") and hasattr(plugin, "PluginHandler")
        assert hasattr(template, "TemplateInterface") and hasattr(cache, "CacheInterface")
        for method in ("load", "render", "copy"):
            assert callable(getattr(template.TemplateHandler, method))
        for method in ("get", "set", "delete", "purge"):
            assert callable(getattr(cache.CacheHandler, method))

        # Deprecation registry.
        assert isinstance(deprecations.DEPRECATIONS, dict)
        assert callable(deprecations.deprecate)

        # Top-level utility aliases really are the cement.utils implementations.
        assert cement.fs is utils_fs
        assert cement.misc is utils_misc
        assert cement.shell is utils_shell


# =============================================================================
# Mail, Template, Plugin, and Cache Interfaces
# =============================================================================


class TestMailTemplatePluginCache:
    """Tests for framework interfaces that sit outside the main CLI path."""

    def test_dummy_template_handler_loads_from_template_dirs(self):
        """The dummy template handler loads templates from configured directories."""
        from cement import TestApp

        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = os.path.join(tmpdir, "emails", "welcome.txt")
            os.makedirs(os.path.dirname(template_path))
            with open(template_path, "w") as f:
                f.write("Welcome {{ name }}")

            class MyApp(TestApp):
                class Meta:
                    template_handler = "dummy"
                    template_dirs = [tmpdir]

            with MyApp() as app:
                content, template_type, path = app.template.load("emails/welcome.txt")
                assert content == "Welcome {{ name }}"
                assert template_type == "directory"
                assert path == template_path
                assert app.template.render(content, {"name": "Ada"}) is None

    def test_dummy_template_handler_missing_template_raises(self):
        """Missing template paths raise FrameworkError instead of returning None."""
        from cement import FrameworkError, TestApp

        class MyApp(TestApp):
            class Meta:
                template_handler = "dummy"
                template_dirs = []

        with MyApp() as app:
            with pytest.raises(FrameworkError):
                app.template.load("missing/template.txt")

    def test_dummy_mail_handler_uses_config_and_call_overrides(self, capsys):
        """The dummy mail handler merges config defaults with send-time overrides."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.dummy")
        defaults["mail.dummy"]["to"] = ["default@example.com"]
        defaults["mail.dummy"]["from_addr"] = "sender@example.com"
        defaults["mail.dummy"]["subject"] = "Default Subject"
        defaults["mail.dummy"]["subject_prefix"] = "[cement]"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                mail_handler = "dummy"
                config_defaults = defaults

        with MyApp() as app:
            assert app.mail.send("Body text", to=["override@example.com"]) is True

        output = capsys.readouterr().out
        assert "DUMMY MAIL MESSAGE" in output
        assert "To: override@example.com" in output
        assert "From: sender@example.com" in output
        assert "Subject: [cement] Default Subject" in output
        assert "Body text" in output

    def test_plugin_handler_starts_with_empty_state(self):
        """The built-in plugin handler exposes loaded/enabled/disabled plugin lists."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["plugin"]
                plugin_handler = "cement"

        with MyApp() as app:
            assert app.handler.registered("plugin", "cement")
            assert app.plugin.get_loaded_plugins() == []
            assert app.plugin.get_enabled_plugins() == []
            assert app.plugin.get_disabled_plugins() == []

    def test_custom_template_handler_can_be_selected_by_meta(self):
        """Custom template handlers integrate through App.Meta.template_handler."""
        from cement import Handler, TestApp
        from cement.core.template import TemplateInterface

        class MemoryTemplate(TemplateInterface, Handler):
            class Meta:
                label = "memory"

            def load(self, template_path):
                return ("Hello {name}", "memory", template_path)

            def render(self, content, data):
                return content.format(**data)

            def copy(self, src, dest):
                return True

        class MyApp(TestApp):
            class Meta:
                handlers = [MemoryTemplate]
                template_handler = "memory"

        with MyApp() as app:
            content, template_type, path = app.template.load("ignored")
            assert (template_type, path) == ("memory", "ignored")
            assert app.template.render(content, {"name": "Ada"}) == "Hello Ada"

    def test_custom_mail_handler_can_be_selected_by_meta(self):
        """Custom mail handlers integrate through App.Meta.mail_handler."""
        from cement import Handler, TestApp
        from cement.core.mail import MailInterface

        class MemoryMail(MailInterface, Handler):
            class Meta:
                label = "memory"

            def send(self, body, **kw):
                return {"body": body, "to": kw.get("to", [])}

        class MyApp(TestApp):
            class Meta:
                handlers = [MemoryMail]
                mail_handler = "memory"

        with MyApp() as app:
            result = app.mail.send("hello", to=["ops@example.com"])
            assert result == {"body": "hello", "to": ["ops@example.com"]}

    def test_custom_cache_handler_lifecycle_and_fallbacks(self):
        """Custom cache handlers support get/set/delete/purge via App.cache."""
        from cement import Handler, TestApp
        from cement.core.cache import CacheInterface

        class MemoryCache(CacheInterface, Handler):
            class Meta:
                label = "memory"

            def __init__(self, **kw):
                super().__init__(**kw)
                self._data = {}

            def get(self, key, fallback=None):
                return self._data.get(key, fallback)

            def set(self, key, value, time=None):
                self._data[key] = value
                return True

            def delete(self, key):
                self._data.pop(key, None)
                return True

            def purge(self):
                self._data.clear()
                return True

        class MyApp(TestApp):
            class Meta:
                handlers = [MemoryCache]
                cache_handler = "memory"

        with MyApp() as app:
            assert app.cache.get("missing", fallback="fallback") == "fallback"
            assert app.cache.set("token", "abc") is True
            assert app.cache.get("token") == "abc"
            assert app.cache.delete("token") is True
            assert app.cache.get("token") is None
            app.cache.set("another", "value")
            assert app.cache.purge() is True
            assert app.cache.get("another") is None

    def test_unknown_extension_raises_framework_error(self):
        """Loading an extension that cannot be imported raises FrameworkError."""
        from cement import FrameworkError, TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["definitely_missing"]

        with pytest.raises(FrameworkError) as exc:
            with MyApp():
                pass

        assert "definitely_missing" in exc.value.msg

    def test_plugin_handler_missing_plugin_raises_framework_error(self):
        """The plugin handler reports missing plugins with FrameworkError."""
        from cement import FrameworkError, TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["plugin"]
                plugin_handler = "cement"

        with MyApp() as app:
            with pytest.raises(FrameworkError) as exc:
                app.plugin.load_plugin("missing_plugin")
            assert "missing_plugin" in exc.value.msg

    def test_smtp_mail_handler_uses_smtp_ssl_when_ssl_enabled(self):
        """With ssl enabled the SMTP handler connects via smtplib.SMTP_SSL, not plain SMTP."""
        from unittest.mock import patch
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.smtp")
        defaults["mail.smtp"]["host"] = "secure.example.com"
        defaults["mail.smtp"]["port"] = "465"
        defaults["mail.smtp"]["ssl"] = True
        defaults["mail.smtp"]["from_addr"] = "sender@example.com"
        defaults["mail.smtp"]["to"] = ["ops@example.com"]
        defaults["mail.smtp"]["subject"] = "Status"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["smtp"]
                mail_handler = "smtp"
                config_defaults = defaults

        with patch("smtplib.SMTP_SSL") as ssl_cls, patch("smtplib.SMTP") as plain_cls:
            smtp = ssl_cls.return_value
            smtp.send_message.return_value = {}
            with MyApp() as app:
                assert app.mail.send("Body") is True

            # The ssl branch is taken: SMTP_SSL is constructed from config host/port/timeout
            # and plain SMTP is never used.
            assert ssl_cls.call_count == 1
            assert plain_cls.call_count == 0
            _assert_smtp_connection(ssl_cls, "secure.example.com", "465", 30)
            smtp.send_message.assert_called_once()
            msg = smtp.send_message.call_args.args[0]
            assert msg["To"] == "ops@example.com"
            assert msg["From"] == "sender@example.com"
            assert msg["Subject"] == "Status"
            smtp.quit.assert_called_once()

    def test_smtp_mail_handler_tls_auth_and_error_return(self):
        """SMTP handler starts TLS, authenticates, and returns False on recipient errors."""
        from unittest.mock import patch
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.smtp")
        defaults["mail.smtp"]["host"] = "mail.example.com"
        defaults["mail.smtp"]["port"] = "2525"
        defaults["mail.smtp"]["tls"] = True
        defaults["mail.smtp"]["auth"] = True
        defaults["mail.smtp"]["username"] = "user"
        defaults["mail.smtp"]["password"] = "secret"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["smtp"]
                mail_handler = "smtp"
                config_defaults = defaults

        with patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value
            smtp.send_message.return_value = {"bad@example.com": (550, b"bad")}
            with MyApp() as app:
                sent = app.mail.send("Body", to=["bad@example.com"])

            assert sent is False
            smtp.starttls.assert_called_once()
            smtp.login.assert_called_once_with("user", "secret")

    def test_template_handler_rejects_empty_template_path(self):
        """Template handlers reject empty template paths with FrameworkError."""
        from cement import FrameworkError, TestApp

        class MyApp(TestApp):
            class Meta:
                template_handler = "dummy"

        with MyApp() as app:
            with pytest.raises(FrameworkError):
                app.template.load("")

    def test_render_can_select_output_handler_per_call(self):
        """App.render can override the app's default output handler per call."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["json", "yaml"]
                output_handler = "dummy"

        with MyApp() as app:
            json_out = StringIO()
            assert app.render({"alpha": 1}, out=json_out, handler="json") == '{"alpha": 1}'
            assert json.loads(json_out.getvalue()) == {"alpha": 1}

            yaml_out = StringIO()
            app.render({"beta": 2}, out=yaml_out, handler="yaml")
            assert "beta: 2" in yaml_out.getvalue()

    def test_render_with_unknown_handler_raises_interface_error(self):
        """App.render reports an unknown output handler through InterfaceError."""
        from cement import InterfaceError, TestApp

        with TestApp() as app:
            with pytest.raises(InterfaceError) as exc:
                app.render({"alpha": 1}, handler="missing")
            assert "missing" in exc.value.msg


# =============================================================================
# Advanced Controller and Handler Semantics
# =============================================================================


class TestAdvancedControllerHandlerSemantics:
    """Tests for return values, defaults, parser behavior, and handler resolution."""

    def test_run_returns_exposed_command_return_value(self):
        """App.run returns the value from the executed exposed controller method."""
        from cement import Controller, TestApp, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex()
            def compute(self):
                return {"status": "ok", "count": 3}

        with TestApp(handlers=[Base], argv=["compute"]) as app:
            assert app.run() == {"status": "ok", "count": 3}

    def test_default_controller_method_runs_without_subcommand(self):
        """A base controller _default method dispatches when no subcommand is provided."""
        from cement import Controller, TestApp, ex

        class Base(Controller):
            class Meta:
                label = "base"

            def _default(self):
                self.app.extend("default_seen", True)
                return "default-return"

            @ex()
            def explicit(self):
                return "explicit-return"

        with TestApp(handlers=[Base], argv=[]) as app:
            assert app.run() == "default-return"
            assert app.default_seen is True

    def test_command_argument_types_choices_and_return_value(self):
        """Exposed command arguments preserve argparse type and choices behavior."""
        from cement import Controller, TestApp, ex

        class Base(Controller):
            class Meta:
                label = "base"

            @ex(arguments=[
                (["--count"], dict(type=int, default=1)),
                (["mode"], dict(choices=["fast", "slow"])),
            ])
            def process(self):
                return (self.app.pargs.mode, self.app.pargs.count, type(self.app.pargs.count))

        with TestApp(handlers=[Base], argv=["process", "slow", "--count", "5"]) as app:
            assert app.run() == ("slow", 5, int)

        with pytest.raises(SystemExit):
            with TestApp(handlers=[Base], argv=["process", "invalid"]) as app:
                app.run()

    def test_embedded_controller_level_arguments_feed_embedded_command(self):
        """Embedded controller Meta.arguments are attached before embedded commands run."""
        from cement import Controller, TestApp, ex

        class Base(Controller):
            class Meta:
                label = "base"

        class Tools(Controller):
            class Meta:
                label = "tools"
                stacked_on = "base"
                stacked_type = "embedded"
                arguments = [(["--profile"], dict(default="dev"))]

            @ex()
            def inspect(self):
                self.app.extend("profile_seen", self.app.pargs.profile)

        with TestApp(handlers=[Base, Tools], argv=["--profile", "prod", "inspect"]) as app:
            app.run()
            assert app.profile_seen == "prod"

    def test_nested_controller_help_includes_group_and_command(self, capsys):
        """Nested controller help includes both the command group and child command."""
        from cement import Controller, TestApp, ex

        class Base(Controller):
            class Meta:
                label = "base"

        class Admin(Controller):
            class Meta:
                label = "admin"
                stacked_on = "base"
                stacked_type = "nested"
                help = "admin tools"

            @ex(help="rotate keys")
            def rotate(self):
                pass

        with pytest.raises(SystemExit):
            with TestApp(handlers=[Base, Admin], argv=["--help"]) as app:
                app.run()

        root_help = capsys.readouterr().out
        assert "admin" in root_help
        assert "admin tools" in root_help

        with pytest.raises(SystemExit):
            with TestApp(handlers=[Base, Admin], argv=["admin", "--help"]) as app:
                app.run()

        nested_help = capsys.readouterr().out
        assert "rotate" in nested_help
        assert "rotate keys" in nested_help

    def test_handler_resolution_supports_instances_and_get_fallback(self):
        """HandlerManager resolves handler instances and returns get() fallbacks."""
        from cement import Handler, Interface, TestApp

        class ServiceInterface(Interface):
            class Meta:
                interface = "service"

        class Primary(ServiceInterface, Handler):
            class Meta:
                label = "primary"

            def __init__(self, **kw):
                super().__init__(**kw)
                self.was_setup = False

            def _setup(self, app):
                super()._setup(app)
                self.was_setup = True

        class Fallback(ServiceInterface, Handler):
            class Meta:
                label = "fallback"

        with TestApp(interfaces=[ServiceInterface], handlers=[Primary]) as app:
            instance = Primary()
            resolved = app.handler.resolve("service", instance, setup=True)
            assert resolved is instance
            assert resolved.was_setup is True
            assert resolved.app is app
            assert app.handler.get("service", "missing", fallback=Fallback) is Fallback


# =============================================================================
# Advanced Config and Utility Semantics
# =============================================================================


class TestAdvancedConfigAndUtilities:
    """Tests for config precedence, utility edge cases, and subprocess passthrough."""

    def test_config_parse_repeated_files_preserves_later_values(self):
        """Parsing a later config file overrides earlier values while preserving others."""
        from cement import TestApp

        first = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        second = tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False)
        try:
            first.write("[service]\nhost = first\nport = 1000\n")
            first.close()
            second.write("[service]\nhost = second\n")
            second.close()

            with TestApp() as app:
                app.config.parse_file(first.name)
                app.config.parse_file(second.name)
                assert app.config.get("service", "host") == "second"
                assert app.config.get("service", "port") == "1000"
        finally:
            os.unlink(first.name)
            os.unlink(second.name)

    def test_config_dict_accessors_reflect_environment_overrides(self):
        """get_section_dict and get_dict both return env-overridden values, matching get()."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "server")
        defaults["server"]["host"] = "default-host"
        defaults["server"]["port"] = "8080"

        os.environ["MYAPP_SERVER_HOST"] = "env-host"
        try:
            class MyApp(TestApp):
                class Meta:
                    label = "myapp"

            with MyApp(config_defaults=defaults) as app:
                assert app.config.get("server", "host") == "env-host"
                assert app.config.get_section_dict("server") == {
                    "host": "env-host",
                    "port": "8080",
                }
                assert app.config.get_dict()["server"] == {
                    "host": "env-host",
                    "port": "8080",
                }
        finally:
            del os.environ["MYAPP_SERVER_HOST"]

    def test_init_defaults_returns_independent_section_dicts(self):
        """init_defaults creates separate dictionaries for each requested section."""
        from cement import init_defaults

        defaults = init_defaults("app", "cache", "cache.redis")
        defaults["app"]["debug"] = True
        defaults["cache"]["enabled"] = False
        assert defaults == {
            "app": {"debug": True},
            "cache": {"enabled": False},
            "cache.redis": {},
        }
        assert defaults["app"] is not defaults["cache"]

    def test_tmp_respects_prefix_suffix_and_cleanup_false(self):
        """Tmp supports prefix/suffix options and can preserve files when cleanup=False."""
        from cement import fs
        import shutil

        with fs.Tmp(prefix="cement-", suffix=".tmp", cleanup=False) as tmp:
            tmp_dir = tmp.dir
            tmp_file = tmp.file
            assert os.path.basename(tmp_dir).startswith("cement-")
            assert tmp_dir.endswith(".tmp")
            assert os.path.basename(tmp_file).startswith("cement-")
            assert tmp_file.endswith(".tmp")

        try:
            assert os.path.isdir(tmp_dir)
            assert os.path.isfile(tmp_file)
        finally:
            shutil.rmtree(tmp_dir)
            if os.path.exists(tmp_file):
                os.unlink(tmp_file)

    def test_shell_cmd_passes_subprocess_kwargs(self):
        """shell.cmd forwards kwargs such as cwd into subprocess.Popen."""
        from cement import shell

        with tempfile.TemporaryDirectory() as tmpdir:
            stdout, stderr, exitcode = shell.cmd("pwd", cwd=tmpdir)
            assert exitcode == 0
            assert stderr == b""
            assert stdout.rstrip().decode() == tmpdir

    def test_is_true_is_case_insensitive_for_common_truthy_values(self):
        """is_true handles upper-case truthy strings and rejects falsey strings."""
        from cement import misc

        assert misc.is_true("TRUE")
        assert misc.is_true("Yes")
        assert misc.is_true("ON")
        assert not misc.is_true("false")
        assert not misc.is_true("off")
        assert not misc.is_true("0")
        assert not misc.is_true(None)


# =============================================================================
# Developer Tooling and Secondary Modules
# =============================================================================


class TestDeveloperToolingModules:
    """Tests for packaged CLI/developer-tool modules included in Cement."""

    def test_bundled_cli_runs_and_shows_developer_tools_help(self, capsys):
        """Running the bundled Cement CLI with no command prints its developer-tools help."""
        from cement.cli.main import CementTestApp

        with CementTestApp(argv=[]) as app:
            app.run()

        out = capsys.readouterr().out
        assert "Cement Framework Developer Tools" in out
        # The bundled CLI loads the generate extension, so its command appears in help.
        assert "generate" in out

    def test_bundled_cli_generate_command_shows_scaffold_subcommands(self, capsys):
        """The bundled CLI's `generate` command dispatches and lists its scaffold sub-commands."""
        from cement.cli.main import CementTestApp

        with CementTestApp(argv=["generate"]) as app:
            app.run()

        out = capsys.readouterr().out
        assert "usage" in out.lower()
        # The generate controller exposes scaffolding sub-commands (e.g. project/plugin).
        assert "project" in out
        assert "plugin" in out

    def test_extension_manager_loads_and_lists_extensions(self):
        """Extension handler can load an extension and report loaded names."""
        from cement import TestApp

        with TestApp() as app:
            assert "cement.ext.ext_dummy" in app.ext.get_loaded_extensions()
            app.ext.load_extension("json")
            assert "cement.ext.ext_json" in app.ext.get_loaded_extensions()
            assert app.handler.registered("output", "json")

    def test_extension_manager_rejects_missing_extensions(self):
        """Extension handler raises FrameworkError for missing extensions."""
        from cement import FrameworkError, TestApp

        with TestApp() as app:
            with pytest.raises(FrameworkError) as exc:
                app.ext.load_extension("missing_extension")
            assert "missing_extension" in exc.value.msg

# =============================================================================
# Advanced Framework Semantics
# =============================================================================


class TestAdvancedFrameworkSemantics:
    """Tests for exact Cement semantics that real applications rely on."""

    def test_config_merge_without_override_preserves_existing_values(self):
        """Config merge respects override=False while still adding missing keys."""
        from cement import TestApp

        with TestApp() as app:
            app.config.merge({"service": {"host": "primary", "port": "8080"}})
            app.config.merge({"service": {"host": "backup", "scheme": "https"}}, override=False)

            assert app.config.get("service", "host") == "primary"
            assert app.config.get("service", "port") == "8080"
            assert app.config.get("service", "scheme") == "https"

    def test_config_env_var_names_are_sanitized_for_dotted_sections_and_keys(self):
        """Environment override names include app, section, key and sanitize punctuation."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("my-app", "api.service-v1")
        defaults["api.service-v1"]["url.path"] = "from-default"
        env_key = "MY_APP_API_SERVICE_V1_URL_PATH"
        os.environ[env_key] = "from-env"

        try:
            class MyApp(TestApp):
                class Meta:
                    label = "my-app"
                    config_section = "my-app"

            with MyApp(config_defaults=defaults) as app:
                assert app.config.get("api.service-v1", "url.path") == "from-env"
                section = app.config.get_section_dict("api.service-v1")
                assert section["url.path"] == "from-env"
        finally:
            del os.environ[env_key]

    def test_hook_register_unknown_returns_false_and_run_unknown_raises(self):
        """Undefined hooks ignore registration but raise when explicitly run."""
        from cement import FrameworkError, TestApp

        with TestApp() as app:
            assert app.hook.register("does_not_exist", lambda app: None) is False
            with pytest.raises(FrameworkError) as exc:
                list(app.hook.run("does_not_exist", app))
            assert "does_not_exist" in exc.value.msg

    def test_hook_run_flattens_generator_results(self):
        """Hook callbacks that yield are flattened by HookManager.run()."""
        from cement import TestApp

        def generator_hook(app):
            yield "first"
            yield "second"

        def scalar_hook(app):
            return "third"

        with TestApp(define_hooks=["pipeline"]) as app:
            app.hook.register("pipeline", scalar_hook, weight=20)
            app.hook.register("pipeline", generator_hook, weight=10)
            assert list(app.hook.run("pipeline", app)) == ["first", "second", "third"]

    def test_duplicate_handler_label_requires_force_for_different_class(self):
        """Different handler classes cannot replace an existing label unless forced."""
        from cement import Handler, Interface, InterfaceError, TestApp

        class ThingInterface(Interface):
            class Meta:
                interface = "thing"

        class FirstThing(ThingInterface, Handler):
            class Meta:
                label = "default"

        class SecondThing(ThingInterface, Handler):
            class Meta:
                label = "default"

        with TestApp(interfaces=[ThingInterface], handlers=[FirstThing]) as app:
            app.handler.register(FirstThing)
            with pytest.raises(InterfaceError):
                app.handler.register(SecondThing)
            app.handler.register(SecondThing, force=True)
            assert app.handler.get("thing", "default") is SecondThing

    def test_handler_labels_with_dashes_are_normalized_to_underscores(self):
        """Handler registration normalizes dash labels for lookup."""
        from cement import Handler, Interface, TestApp

        class StoreInterface(Interface):
            class Meta:
                interface = "store_backend"

        class DashStore(StoreInterface, Handler):
            class Meta:
                label = "file-system"

        with TestApp(interfaces=[StoreInterface], handlers=[DashStore]) as app:
            assert app.handler.registered("store_backend", "file_system")
            assert app.handler.get("store_backend", "file_system") is DashStore

    def test_handler_resolve_missing_can_return_none_without_error(self):
        """Handler resolve supports raise_error=False for optional handlers."""
        from cement import TestApp

        with TestApp() as app:
            assert app.handler.resolve("output", object(), raise_error=False) is None

    def test_template_dirs_precedence_and_runtime_mutation(self):
        """Later configured template dirs take precedence, and runtime changes affect load()."""
        from cement import TestApp

        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            for directory, text in [(first, "first"), (second, "second")]:
                with open(os.path.join(directory, "same.txt"), "w") as f:
                    f.write(text)

            class MyApp(TestApp):
                class Meta:
                    template_handler = "dummy"
                    template_dirs = [first, second]

            with MyApp() as app:
                content, template_type, path = app.template.load("same.txt")
                assert content == "second"
                assert template_type == "directory"
                assert path == os.path.join(second, "same.txt")

                app.remove_template_dir(second)
                content, _, path = app.template.load("same.txt")
                assert content == "first"
                assert path == os.path.join(first, "same.txt")

    def test_print_dict_output_handler_renders_each_key_value_line(self):
        """print_dict renders all key/value pairs as plain text."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["print"]
                output_handler = "print_dict"

        with MyApp() as app:
            out = StringIO()
            app.render({"alpha": 1, "beta": "two"}, out=out)
            rendered = out.getvalue()
            assert "alpha: 1" in rendered
            assert "beta: two" in rendered

    def test_dummy_mail_default_empty_lists_and_subject_prefix_format(self, capsys):
        """Dummy mail output formats empty recipients and optional subject prefix exactly."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.dummy")
        defaults["mail.dummy"]["from_addr"] = "robot@example.com"
        defaults["mail.dummy"]["subject"] = "Report"
        defaults["mail.dummy"]["subject_prefix"] = ""

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                mail_handler = "dummy"
                config_defaults = defaults

        with MyApp() as app:
            assert app.mail.send("body") is True

        text = capsys.readouterr().out
        assert "To: \n" in text
        assert "CC: \n" in text
        assert "BCC: \n" in text
        assert "Subject: Report" in text
        assert "Subject:  Report" not in text

    def test_smtp_send_supports_dict_body_and_custom_headers(self):
        """Sending a dict body produces a multipart/alternative message with X headers and a Message-Id."""
        from unittest.mock import patch
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.smtp")
        defaults["mail.smtp"].update(
            {
                "from_addr": "sender@example.com",
                "to": ["to@example.com"],
                "subject": "Status",
                "subject_prefix": "[prod]",
                "date_enforce": False,
                "msgid_enforce": True,
                "msgid_str": "cement",
                "msgid_domain": "example.com",
            }
        )

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["smtp"]
                mail_handler = "smtp"
                config_defaults = defaults

        with patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value
            smtp.send_message.return_value = {}
            with MyApp() as app:
                # An "X-"/"x_"-prefixed kwarg is carried through to a message header.
                assert app.mail.send({"text": "plain", "html": "<b>html</b>"}, x_trace="abc") is True

        msg = smtp.send_message.call_args.args[0]
        assert msg["Subject"] == "[prod] Status"
        assert msg["X-Trace"] == "abc"
        assert msg["Message-Id"].endswith("@example.com>")
        assert msg.get_content_type() == "multipart/alternative"

    def test_smtp_send_rejects_invalid_body_type(self):
        """Sending an unsupported body type raises TypeError."""
        from unittest.mock import patch
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                extensions = ["smtp"]
                mail_handler = "smtp"

        with patch("smtplib.SMTP"):
            with MyApp() as app:
                with pytest.raises(TypeError):
                    app.mail.send(["not", "valid"])

    def test_app_config_and_template_dir_helpers_deduplicate_paths(self):
        """App helper methods register paths once, observed through public behavior."""
        from cement import FrameworkError, TestApp

        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = os.path.join(tmpdir, "app.conf")
            with open(config_file, "w") as f:
                f.write("[database]\nhost = db.example.com\n")
            with open(os.path.join(tmpdir, "welcome.txt"), "w") as f:
                f.write("Hi {{ name }}")

            class MyApp(TestApp):
                class Meta:
                    template_handler = "dummy"

            with MyApp() as app:
                # Adding the same config dir/file twice is idempotent (no error); the added
                # config file parses through the public config surface.
                app.add_config_dir(tmpdir)
                app.add_config_dir(tmpdir)
                app.add_config_file(config_file)
                app.add_config_file(config_file)
                app.config.parse_file(config_file)
                assert app.config.get("database", "host") == "db.example.com"

                # The template dir is registered exactly once: a single removal fully clears it,
                # so loading a template from it then fails (a duplicate entry would survive).
                app.add_template_dir(tmpdir)
                app.add_template_dir(tmpdir)
                content, template_type, _ = app.template.load("welcome.txt")
                assert content == "Hi {{ name }}"
                assert template_type == "directory"
                app.remove_template_dir(tmpdir)
                with pytest.raises(FrameworkError):
                    app.template.load("welcome.txt")

    def test_app_alternative_module_mapping_imports_replacement_module(self):
        """App.__import__ honors alternative_module_mapping for compatibility imports."""
        from cement import TestApp

        class MyApp(TestApp):
            class Meta:
                alternative_module_mapping = {"legacy_json": "json"}

        with MyApp() as app:
            module = app.__import__("legacy_json")
            assert module.dumps({"ok": True}) == '{"ok": true}'

    def test_daemon_environment_switch_writes_pid_file(self):
        """Daemon Environment.switch() writes the current pid to the configured pid file."""
        import getpass
        from unittest.mock import patch
        from cement.ext.ext_daemon import Environment

        current_user = getpass.getuser()

        with tempfile.TemporaryDirectory() as tmpdir:
            pid_file = os.path.join(tmpdir, "app.pid")
            # switch() performs uid/gid/chdir/chown as a side effect; mock those so the
            # documented pid-file write can be exercised without root.
            with patch("os.setuid"), patch("os.setgid"), patch("os.chdir"), patch("os.chown"):
                env = Environment(user=current_user, pid_file=pid_file, dir=tmpdir)
                env.switch()

            assert os.path.exists(pid_file)
            assert open(pid_file).read().strip() == str(os.getpid())

    def test_daemon_environment_strictly_requires_existing_user_and_group(self):
        """Daemon Environment raises FrameworkError for unknown user or group names."""
        from cement import FrameworkError
        from cement.ext.ext_daemon import Environment

        with pytest.raises(FrameworkError):
            Environment(user="__cement_missing_user__")

        with pytest.raises(FrameworkError):
            Environment(group="__cement_missing_group__")

    def test_dummy_mail_subject_prefix_is_config_only_not_send_overridable(self, capsys):
        """Dummy mail's subject_prefix comes from config and ignores a send-time override."""
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.dummy")
        defaults["mail.dummy"]["subject"] = "Default Subject"
        defaults["mail.dummy"]["subject_prefix"] = "[cfg]"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                mail_handler = "dummy"
                config_defaults = defaults

        with MyApp() as app:
            assert app.mail.send("body", subject_prefix="[run]") is True

        assert "Subject: [cfg] Default Subject" in capsys.readouterr().out

    def test_smtp_send_keeps_connection_config_and_applies_message_overrides(self):
        """SMTP connection params come from config while message fields honor send overrides."""
        from unittest.mock import patch
        from cement import TestApp, init_defaults

        defaults = init_defaults("myapp", "mail.smtp")
        defaults["mail.smtp"]["host"] = "configured-host"
        defaults["mail.smtp"]["port"] = "2525"
        defaults["mail.smtp"]["timeout"] = 45
        defaults["mail.smtp"]["from_addr"] = "configured@example.com"
        defaults["mail.smtp"]["to"] = ["configured@example.com"]
        defaults["mail.smtp"]["subject"] = "Configured"

        class MyApp(TestApp):
            class Meta:
                label = "myapp"
                extensions = ["smtp"]
                mail_handler = "smtp"
                config_defaults = defaults

        with patch("smtplib.SMTP") as smtp_cls:
            smtp = smtp_cls.return_value
            smtp.send_message.return_value = {}
            with MyApp() as app:
                # Connection settings (host/port/timeout) are taken from config and the
                # attempt to override them via send kwargs is ignored; message fields
                # (to/subject) are overridden by the send kwargs.
                sent = app.mail.send(
                    "Body",
                    host="runtime-host",
                    port="9999",
                    timeout=1,
                    to=["override@example.com"],
                    subject="Override",
                )
                assert sent is True

        assert smtp_cls.call_count == 1
        _assert_smtp_connection(smtp_cls, "configured-host", "2525", 45)
        msg = smtp.send_message.call_args.args[0]
        assert msg["To"] == "override@example.com"
        assert msg["Subject"] == "Override"
        assert msg["From"] == "configured@example.com"
