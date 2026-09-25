# Cement — CLI Application Framework

Build **cement**, a Python framework for building CLI applications. Cement uses a handler/interface plugin architecture where an `App` orchestrates managers for interfaces, handlers, and hooks. Controllers define commands via decorators, and the framework provides config, logging, output, and utility systems.

**Version**: 3.0.15

**Environment & Dependencies**: The environment is **offline** — there is no network access, so you must **not** install anything. Every dependency you need is already installed, and the project itself is installed for you by a `setup.sh` that runs offline (an editable install). Core cement has no required dependencies; the `json`, `print`, `scrub`, `alarm`, `plugin`, `generate`, and `smtp` extensions rely only on the Python standard library. The remaining optional extensions use packages that are pre-installed and importable: `pyyaml` (YAML config/output), `tabulate`, `colorlog`, `jinja2`, `pystache` (Mustache), `watchdog`, and `redis`. A Redis server is already installed and running, so the `redis` cache extension can connect to a live instance.

---

## Core Architecture

### App (`cement.App`, `cement.TestApp`)

The central class. All configuration via inner `Meta` class. Supports context manager for automatic setup/close.

```python
from cement import App, TestApp

class MyApp(App):
    class Meta:
        label = "myapp"
        handlers = [MyController]
        extensions = ["json"]
        output_handler = "json"

with MyApp(argv=["command", "--flag"]) as app:
    app.run()
```

Key Meta options: `label` (required), `debug`, `quiet`, `argv`, `config_handler` (`"configparser"`), `log_handler` (`"logging"`), `output_handler` (`"dummy"`), `mail_handler` (`"dummy"`), `template_handler` (`"dummy"`), `plugin_handler` (`"cement"`), `cache_handler`, `controller` (`"base"`), `extensions` (list), `handlers` (list of Handler classes), `interfaces` (list of Interface classes), `define_hooks` (list of hook name strings), `hooks` (list of `(name, func)` tuples), `config_defaults` (dict), `config_dirs` (list), `config_files` (list), `template_dirs` (list), `alternative_module_mapping` (dict mapping a module name to a replacement module name, used by `app.__import__`).

Key methods: `setup()`, `run()` (fires `pre_run`/`post_run` hooks and returns the executed controller method's return value), `close()`, `render(data, template=None, out=sys.stdout, handler=None, **kwargs)` (fires render hooks, can select an output handler per call, sets `app.last_rendered`, raises `InterfaceError` for unknown output handlers, and returns the selected output handler's rendered text — the same value stored as the second element of `app.last_rendered` — in addition to writing it to `out`; the content written to `out` is exactly that rendered text, written verbatim (byte-for-byte, with no trailing newline or other decoration added by `render`); in quiet mode the write to `out` is suppressed when `out` is stdout, so nothing is printed even though the rendered text is still returned and recorded in `last_rendered`; any additional keyword arguments beyond `data`/`template`/`out`/`handler` are forwarded verbatim to the selected output handler's `render()` method, so a caller can supply handler-specific options through `app.render` — e.g. `app.render(data, headers=[...])` passes `headers` through to the tabulate handler's `render(data, headers=[], **kw)`), `extend(name, obj)` (raises `FrameworkError` if exists), `__import__(name)` (imports a module, redirecting through `Meta.alternative_module_mapping` when the name is mapped). Path helpers `add_config_dir(path)`, `add_config_file(path)`, and `add_template_dir(path)` append to `config_dirs` / `config_files` / `template_dirs`, storing each as an absolute path and skipping duplicates. `remove_template_dir(path)` removes a previously added template dir. Among `template_dirs`, later entries take precedence when a template name resolves in more than one directory.

Properties: `label`, `debug`, `quiet`, `argv`, `pargs` (parsed args namespace), `last_rendered`, `config`, `log`, `output`, `mail`, `template`, `plugin`, `cache`, `args`, `ext`.

The framework registers two built-in global CLI flags independent of the `Meta` options: `--debug` (alias `-d`) and `--quiet` (alias `-q`). When the corresponding flag is present in `argv`, the framework sets the `debug` / `quiet` property to `True` (and `--debug` additionally raises the log level to `DEBUG`), so an app run with `argv=["--debug"]` or `argv=["--quiet"]` enables that mode rather than rejecting the flag as unrecognized. Quiet mode suppresses **all** of the app's console (stdout) output for the duration of the run, not only `render()`'s write to `out`: while the app is in quiet mode nothing it would otherwise print reaches stdout — including the framework's built-in default action, so a quiet-mode `app.run()` that hits the default action (no subcommand selected and no `_default` defined, which otherwise prints a controller's help/usage to stdout per the Controller section) emits nothing to stdout. Debug mode is the exception: an app in `--debug` mode does not suppress console output even if `--quiet` is also set.

**Exit semantics**: command-line parsing is delegated to the `argparse` backend, and — apart from the built-in `--debug` / `--quiet` flags above, which the framework consumes itself — the framework does not alter or intercept the backend's own handling of help and argument errors.

Context manager: `__enter__` calls `setup()`, `__exit__` calls `close()`.

`TestApp` — subclass with random label, empty argv. For testing.

**Framework hooks**: `pre_setup`, `post_setup`, `pre_run`, `post_run`, `pre_close`, `post_close`, `pre_render`, `post_render` (and others). Lifecycle hooks fire in the expected around-order for setup, run, render, and close.

### MetaMixin

All framework classes (App, Handler, Interface) use MetaMixin which merges inner `Meta` classes across the MRO hierarchy. Keyword arguments to constructors override Meta values.

---

## Controller System

### Controller (`cement.Controller`) and `@ex` Decorator

Controllers define CLI commands. The base controller (`label="base"`) is the root. Sub-controllers stack onto the base.

```python
from cement import Controller, ex

class Base(Controller):
    class Meta:
        label = "base"
        arguments = [(["-v", "--verbose"], dict(dest="verbose", action="store_true"))]

    @ex(help="do something", arguments=[(["-n", "--name"], dict(dest="name"))])
    def my_command(self):
        name = self.app.pargs.name
```

Controller Meta: `label`, `stacked_on` (`"base"`), `stacked_type` (`"embedded"` or `"nested"`), `help`, `description`, `arguments` (list of `([args], {kwargs})` tuples).

- **Embedded** stacking adds commands to parent's namespace
- **Nested** stacking creates a sub-command group (sub-parser)
- Underscores in method names become dashes in CLI (`my_command` → `my-command`)

`@ex` (alias for `expose`): marks a method as a CLI command. Takes `help`, `arguments`, `label`, `hide`. The `label` option overrides the CLI command name, `hide=True` omits the command's help description from generated help, and command arguments can include positional arguments as well as flags.

Controllers access the app via `self.app`. If a controller defines a `_default` method, it is dispatched when no subcommand is provided on the command line, and `app.run()` returns its value. When a controller — including a **nested** sub-command group — is reached with no subcommand selected and defines no `_default`, the framework's built-in default action prints that controller's own help/usage (its `usage:` line followed by its list of sub-commands) to stdout and returns without raising. So dispatching a nested group by name alone (e.g. `argv=["generate"]`) emits usage text listing that group's sub-commands, rather than erroring or printing nothing.

---

## Handler & Interface System

### Interface (`cement.Interface`)

Abstract base for capability contracts. Define via `app.interface.define()` or `App.Meta.interfaces`.

```python
from cement import Interface

class MyInterface(Interface):
    class Meta:
        interface = "my_service"
```

InterfaceManager (`app.interface`): `define(ibc)`, `list()`, `defined(interface) -> bool`.

### Handler (`cement.Handler`)

Concrete implementations of interfaces. Must subclass both the Interface and Handler.

```python
from cement import Handler

class MyHandler(MyInterface, Handler):
    class Meta:
        label = "default"
        config_defaults = dict(max_size=1000)

    def _setup(self, app):
        super()._setup(app)
```

Handler Meta: `label` (required), `interface` (auto-set from Interface parent), `config_section` (defaults to `"{interface}.{label}"`), `config_defaults` (merged into app config under the config_section during `_setup`).

HandlerManager (`app.handler`): `register(handler_class, force=False)` (with `force=True` replacing an existing handler for the same interface/label), `get(interface, label, fallback=None)` (returns the handler class), `list(interface)` (returns handler classes), `registered(interface, label) -> bool`, `resolve(interface, handler_def, setup=False, raise_error=True)`, `setup(handler_class)` (instantiates and calls `_setup`).

`resolve(interface, handler_def, setup=False, raise_error=True)` always returns a handler **instance** (not a class) for a resolvable `handler_def`, which may be given as a string label, a handler class, or a handler instance: a string label or class is instantiated (and registered if not already), while an instance is returned as-is. The `setup` flag controls only whether `_setup` is invoked before returning — it does **not** change whether instantiation happens (so the return is an instance regardless of `setup`). A `handler_def` that cannot be resolved to a handler for `interface` — including a non-handler object — yields `None` when `raise_error=False` and raises `InterfaceError` when `raise_error=True` (the default). (Use `get()` / `list()` when you want the handler class rather than an instance.)

Default app setup defines these built-in interfaces: `extension`, `log`, `config`, `mail`, `plugin`, `output`, `template`, `argument`, `controller`, and `cache`.

Handler labels containing dashes are normalized to underscores at registration time. Registering a different handler class for an existing interface/label raises `InterfaceError` unless `force=True`; registering the same class again is allowed.

---

## Hook System

HookManager (`app.hook`): `define(name)`, `defined(name) -> bool`, `register(name, func, weight=0)`, `run(name, *args, **kwargs)` (generator yielding results, sorted by weight ascending), `list()`.

Hooks can be defined via `App.Meta.define_hooks` and registered via `App.Meta.hooks = [(name, func)]`.

Registering a function to an undefined hook returns `False`; running an undefined hook raises `FrameworkError`. If a hook callback itself yields results, `HookManager.run()` flattens that nested generator.

---

## Config System

The default config handler (`"configparser"`) wraps `RawConfigParser`. Supports sections, key-value pairs, file parsing, and environment variable overrides.

During default app setup the framework creates the app's own config section — a section named after `Meta.label` — so that after an `App` has been set up, `app.config.has_section(app.label)` is `True` even before any `config_defaults`, config files, or handler defaults are applied.

Key methods: `get(section, key)`, `set(section, key, value)`, `add_section(section)`, `has_section(section)`, `get_sections()`, `get_section_dict(section)`, `get_dict()`, `merge(dict_obj, override=True)`, `parse_file(path)`.

**Env var override**: `get(section, key)` checks environment variables before returning the config value. The format is `{APP_LABEL}_{SECTION}_{KEY}` (uppercased), except when the section is the app's own config section (matching the label), where it simplifies to `{APP_LABEL}_{KEY}` to avoid duplication (e.g., `MYAPP_SETTING` instead of `MYAPP_MYAPP_SETTING`).
Non-alphanumeric characters in app labels, section names, and keys are converted to underscores, so `myapp`, section `api.service-v1`, key `url.path` maps to `MYAPP_API_SERVICE_V1_URL_PATH`. `get_section_dict()` and `get_dict()` reflect environment overrides. `merge(..., override=False)` preserves existing values while adding missing keys.

Config defaults via `init_defaults(*sections)` which creates `{"section1": {}, ...}`.

---

## Extensions and Output Handlers

Extensions are loaded via `App.Meta.extensions` list. Each extension's `load(app)` function registers handlers.

### JSON Extension (`"json"`)
- `JsonOutputHandler` (output): `render(data)` returns `json.dumps(data)`
- `JsonConfigHandler` (config): parses JSON config files

### Print Extension (`"print"`)
- `PrintOutputHandler` (output, registered under label `print`): prints `data["out"]` key
- `PrintDictOutputHandler` (output, registered under label `print_dict`): renders each key/value pair as `key: value`. Select it with `output_handler = "print_dict"`.
- Loading the extension adds `app.print(text)`, which routes through `app.render({"out": text}, handler="print")` so render hooks still apply.

### Dummy Extension (`"dummy"`)
- Registers `DummyOutputHandler`, `DummyMailHandler`, and `DummyTemplateHandler`.
- `DummyTemplateHandler.load(template_path)` searches `App.Meta.template_dirs` and raises `FrameworkError` for empty or missing paths. It returns a `(content, template_type, full_path)` tuple. The `template_type` denotes the *source* the template was resolved from, not a filesystem file-vs-directory distinction: any template found under a configured `template_dirs` entry is tagged `"directory"` (the literal string), even when the resolved `full_path` points at a regular file. `content` is the file's text and `full_path` is its absolute path. `DummyTemplateHandler.render(content, data)` is a no-op that returns `None` (mirroring the dummy output handler).
- `DummyMailHandler.send(body, **kw)` prints a dummy email message and returns `True`, merging `mail.dummy` config defaults with send-time overrides for `to`, `from_addr`, `cc`, `bcc`, and `subject`. `subject_prefix` comes from configuration only (not overridable per `send()`) and is prepended to the subject when non-empty. The printed message contains a `DUMMY MAIL MESSAGE` banner followed by the lines `To: <recipients>`, `From: <addr>`, `CC: <recipients>`, `BCC: <recipients>`, and `Subject: <subject>`, and then the message `body` text itself (the raw string passed to `send()`) printed after those header lines. Recipient lists are joined with `", "` (so an empty list yields an empty value after the label, e.g. `To: `), and the subject line is `Subject: <subject_prefix> <subject>` when a prefix is set, otherwise `Subject: <subject>` (no leading space).

### YAML Extension (`"yaml"`)
- `YamlConfigHandler` (config): parses YAML `.yml`/`.yaml` config files. Requires `pyyaml`.
- `YamlOutputHandler` (output): renders Python data as YAML text

### Tabulate Extension (`"tabulate"`)
- `TabulateOutputHandler` (output): renders data as formatted text tables. Requires `tabulate`. `render(data, headers=[], **kw)` — data is a list of rows, headers is a list of column names. Passes through to `tabulate.tabulate()`.

### Scrub Extension (`"scrub"`)
- Adds `app.scrub(text)` method for regex-based text obfuscation. Registers a `ScrubController` (embedded on base) that adds `--scrub` CLI flag. Configure via `App.Meta.scrub` — a list of `(regex_pattern, replacement)` tuples. When `app.scrub(text)` is called, all patterns are applied via `re.sub`.

### Colorlog Extension (`"colorlog"`)
- `ColorLogHandler` (log): colorized console logging. Requires `colorlog`. Same API as LoggingLogHandler. Configure via `log.colorlog` config section (level, file, etc.).

### Redis Extension (`"redis"`)
- `RedisCacheHandler` (cache): Redis-backed cache. Requires `redis` package + running Redis server. Set via `Meta.cache_handler = 'redis'`. Configure via `cache.redis` section (host, port, db). API: `app.cache.set(key, value, time=None)`, `app.cache.get(key, fallback=None)`, `app.cache.delete(key)`, `app.cache.purge()`. Stored values round-trip as `str`: the handler decodes the response, so a `str` value set via `set()` is returned as the same `str` (not raw `bytes`) by `get()`.

### SMTP Extension (`"smtp"`)
- `SMTPMailHandler` (mail): sends email through `smtplib.SMTP`/`SMTP_SSL`. Configure via `mail.smtp` (`host`, `port`, `timeout`, `tls`, `auth`, `username`, `password`, `from_addr`, `to`, `cc`, `bcc`, `subject`, `subject_prefix`, `files`, `charset`, `date_enforce`, `msgid_enforce`, etc.). The connection is opened with `smtplib.SMTP_SSL(host, port, timeout)` when `ssl` is configured true, otherwise with `smtplib.SMTP(host, port, timeout)`. `send(body, **kw)` returns `True` when `send_message()` reports no recipient errors, otherwise `False`; it starts TLS and logs in when configured.
- Connection/security settings such as `host`, `port`, `ssl`, `tls`, `auth`, `username`, `password`, `timeout`, and `msgid_domain` come from config (not overridable per `send()`); `timeout` defaults to the integer `30`. `host`, `port`, and `timeout` are handed to the `smtplib.SMTP` / `SMTP_SSL` constructor exactly as stored in configuration, with their stored type preserved either way — the framework does not coerce them. A value stored as a string is forwarded as a string (e.g. a `port` of `"465"` stays `"465"`), and a value stored as an integer is forwarded as an integer (e.g. a `timeout` of `45` stays `45`); the config handler must not blanket-stringify stored values. Message fields such as `to`, `from_addr`, `cc`, `bcc`, `subject`, `subject_prefix`, `files`, `charset`, `date_enforce`, and `msgid_enforce` can be overridden per `send()` call. A `send()` keyword whose name starts with `x-`/`x_` (case-insensitive) is added to the message as the corresponding `X-` header. A `dict` body with both `text` and `html` keys produces a `multipart/alternative` message; when `msgid_enforce` is set a `Message-Id` header is generated. A body that is not a string, tuple, or dict raises `TypeError`.

### Plugin Extension (`"plugin"`)
- `CementPluginHandler` (plugin): built-in plugin manager. Set `Meta.plugin_handler = "cement"`. API: `get_loaded_plugins()`, `get_enabled_plugins()`, `get_disabled_plugins()`, `load_plugin(name)`, `load_plugins(list)`. Missing plugins raise `FrameworkError`.

### Generate Extension (`"generate"`)
- Developer tooling extension. Registers `Generate` controller under the `controller` interface with label `"generate"`. Exposes template helpers used by the bundled Cement CLI. The `generate` command is a nested sub-command group whose scaffold sub-commands include `project` and `plugin` (each generates a project/plugin from a bundled template); these appear in `generate`'s help output.

### Jinja2 Extension (`"jinja2"`)
- `Jinja2OutputHandler` (output): renders Jinja2 templates with data. Requires `jinja2`. Set `Meta.template_dirs` for filesystem templates. `app.render(data, 'template.jinja2', out=outfp)`.

### Mustache Extension (`"mustache"`)
- `MustacheOutputHandler` (output): renders Mustache templates with data. Requires `pystache`. Set `Meta.template_dirs` for filesystem templates. `app.render(data, 'template.mustache', out=outfp)`.

### Alarm Extension (`"alarm"`)
- Adds `app.alarm` with `set(seconds, message)` and `stop()`. Uses SIGALRM. When alarm fires, raises `CaughtSignal` with `signum == signal.SIGALRM`; `stop()` cancels a pending alarm.

### Daemon Extension (`"daemon"`)
- `cement.ext.ext_daemon.Environment(user=None, group=None, pid_file=None, dir='/')` — daemon environment. The constructor resolves the `user`/`group` names immediately and raises `FrameworkError` right away for an unknown user or group (the validation is not deferred to `switch()`). When `group` is omitted, it defaults to the configured user's primary group (the group of the user's passwd entry), so a `user`-only `Environment` still has a resolved group. `switch()` always calls `os.setuid()` and `os.setgid()` (with that resolved user/group, including the user's primary group when no `group` was given), along with `os.chdir()`; it updates `HOME` and writes the pid file when configured, raising `FrameworkError` if the PID file already exists. `daemonize()` forks the process.

### Watchdog Extension (`"watchdog"`)
- Adds `app.watchdog` filesystem monitor. Requires `watchdog`. `app.watchdog.add(path, event_handler=None)` registers a directory to monitor and returns `True` when the path is added (`False` if it does not exist). The `event_handler` argument is an event-handler **class** (not an instance): `add()` instantiates it internally to register it with the observer, and when `event_handler` is `None` it uses a default `WatchdogEventHandler`. Event handlers subclass `WatchdogEventHandler` (importable from `cement.ext.ext_watchdog`), overriding methods like `on_any_event(self, event)`. The monitor exposes `start()`, `stop()`, and `join()` to control the observer thread lifecycle.

### Logging (`"logging"`)
Built-in `LoggingLogHandler`: `info()`, `warning()`, `error()`, `debug()`, `fatal()`, `set_level(level)`, `get_level()`. The default log level is `"INFO"` (it becomes `"DEBUG"` when the app runs in debug mode).

### Dummy Output (`"dummy"`)
The default dummy output handler writes no output but still updates `app.last_rendered` with the input data and `None` as the rendered text.

### Extension Manager
`app.ext` manages extensions and exposes `load_extension(name)` plus `get_loaded_extensions()`. Loaded extensions are tracked by full module name such as `cement.ext.ext_json`; missing extensions raise `FrameworkError`.

During default setup the framework auto-loads a built-in set of **core extensions** before applying `App.Meta.extensions`, so they are tracked by `get_loaded_extensions()` (by full module name) even when `Meta.extensions` is empty. This core set comprises `dummy`, `smtp`, `plugin`, `configparser`, `logging`, and `argparse` — i.e. `cement.ext.ext_dummy`, `cement.ext.ext_smtp`, `cement.ext.ext_plugin`, `cement.ext.ext_configparser`, `cement.ext.ext_logging`, and `cement.ext.ext_argparse`. In particular the `dummy` extension (which provides the default output/mail/template handlers) is always loaded by default, so `cement.ext.ext_dummy` appears in `get_loaded_extensions()` for any default app.

---

## Utilities

### `cement.fs`
- `Tmp(**kwargs)` — context manager creating temp dir+file, cleans up on exit. Properties: `dir`, `file`. Accepts `prefix` and `suffix` (applied to the generated dir/file names) and `cleanup` (default `True`); when `cleanup=False` the temp dir and file are preserved after the context exits.
- `abspath(path)` — expands `~` and resolves path
- `join(*args)` — `os.path.join` with `abspath` on first arg
- `ensure_dir_exists(path)` — creates directory if not exists

### `cement.shell`
- `cmd(command, capture=True, **kwargs)` — executes shell command. `capture=True` returns `(stdout_bytes, stderr_bytes, exitcode)`. `capture=False` returns exitcode only. Extra keyword args such as `cwd` are forwarded to `subprocess.Popen`.

### `cement.misc`
- `init_defaults(*sections)` — creates config defaults dict. In addition to being available as `cement.misc.init_defaults`, this is re-exported at the top level so `from cement import init_defaults` works directly.
- `is_true(item)` — True for `True`, `"true"`, `"yes"`, `"y"`, `"on"`, `"1"`, `1`. String matching is case-insensitive (the input is lower-cased before comparison, so `"TRUE"`, `"Yes"`, and `"ON"` are also truthy).

---

## Exceptions

- `FrameworkError(msg)` — `str(e)` returns msg, `e.msg` attribute
- `InterfaceError(msg)` — subclass of FrameworkError
- `CaughtSignal(signum, frame)` — `e.signum`, `e.frame`

All importable from `cement`.

---

## Public Compatibility Modules

Implement the public module layout, not only top-level imports. These modules/classes should import successfully:

- `cement.core.foundation`: `App`, `TestApp`, `Controller`, `Handler`, `Interface`
- `cement.core.extension`: `ExtensionInterface`, `ExtensionHandler`
- `cement.core.mail`: `MailInterface`, `MailHandler`
- `cement.core.plugin`: `PluginInterface`, `PluginHandler`
- `cement.core.template`: `TemplateInterface`, `TemplateHandler`. The template handler contract provides `load` and `render` plus a `copy(src, dest)` method (copies a source template/directory to a destination).
- `cement.core.cache`: `CacheInterface`, `CacheHandler`. The cache handler contract provides `get(key, fallback=None)`, `set(key, value, time=None)`, `delete(key)`, and `purge()`.
- `cement.core.backend.VERSION` and `cement.utils.version` helpers: `VERSION`, `get_version()`, `get_version_banner()`. `VERSION` is a 5-tuple `(major, minor, patch, release, serial)` where `release` is one of `"alpha"`, `"beta"`, `"rc"`, or `"final"` (e.g. `(3, 0, 15, "final", 0)`). `get_version(version=VERSION)` accepts an optional version tuple (defaulting to `VERSION`) and returns its PEP-386 string: the `major.minor.patch` dotted prefix, with a release suffix appended for non-`final` releases — `"alpha"`/`"beta"`/`"rc"` map to `a`/`b`/`c` followed immediately by the serial — while `"final"` adds no suffix. `get_version_banner()` returns a multi-line banner whose first line is exactly `Cement Framework <version>`. `get_version` is also re-exported at the top level of the `cement` package (mirroring the `init_defaults` re-export on the `cement.misc` line above), so `from cement import get_version` and `cement.get_version()` work directly.
- `cement.core.deprecations`: a `DEPRECATIONS` dict (maps deprecation ids to messages) and a `deprecate(id)` callable.
- Extensions: `ext_argparse`, `ext_configparser`, `ext_dummy`, `ext_json`, `ext_yaml`, `ext_print`, `ext_plugin`, `ext_smtp`, `ext_generate`, and the extensions listed above
- Top-level utility aliases: `cement.fs`, `cement.misc`, and `cement.shell` must refer to their `cement.utils.*` implementations
- Bundled developer CLI modules: `cement.cli.main` and `cement.cli.controllers.base`. `cement.cli.main` exposes a runnable app `CementTestApp` (a `TestApp`-style variant with empty `argv` for testing); it loads the `generate` extension, so `generate` is listed in its help. Running it with no command prints a help banner whose text includes the literal `Cement Framework Developer Tools`.

---

## setup.sh

```bash
pip install -e .
```
