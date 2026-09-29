# Invoke - Python Task Execution Framework

## Overview

Build `invoke`, a Python task execution and shell subprocess library. Decorator-based tasks, hand-rolled CLI parser, hierarchical configuration, context-managed command execution, testing utilities. Installable via `pip install -e .` using `pyproject.toml` with name `invoke`, version `3.0.0`. You may vendor or reimplement supporting libraries internally as long as the public API works.

## Dependencies

The environment is **offline** — there is no network access, and every dependency is **already installed**. Do not install, download, or fetch anything.

`invoke` has **no external runtime dependencies**: the entire library is pure Python and vendors any helpers it needs internally (e.g. PyYAML for YAML config loading is vendored, not pip-installed). The build backend (`setuptools`) is pre-installed.

The project is installed by a `setup.sh` script that runs **offline**. Write it to perform an editable install with build isolation disabled:

```bash
pip install -e . --no-build-isolation
```

`--no-build-isolation` is required because the environment is offline and the build backend is already present, so pip must not try to provision an isolated build environment from the network.

## Package Exports

The top-level `invoke` package must export:

`Collection`, `Config`, `Context`, `MockContext`, `Executor`, `FilesystemLoader`, `Task`, `Call`, `Parser`, `Argument`, `ParserContext`, `ParseResult`, `Result`, `Runner`, `Local`, `Promise`, `Program`, `Responder`, `FailingResponder`, `StreamWatcher`, `Failure`, `UnexpectedExit`, `CommandTimedOut`, `AuthFailure`, `Exit`, `ParseError`, `CollectionNotFound`, `ThreadException`, `WatcherError`, `SubprocessPipeError`, `AmbiguousEnvVar`, `UncastableEnvVar`, `UnknownFileType`, `PlatformError`, `ResponseNotAccepted`, `task`, `call`, `run`, `sudo`

Parser subpackage: `from invoke.parser import ParserContext`

Exceptions: `from invoke.exceptions import CollectionNotFound, Failure, WatcherError, ResponseNotAccepted, AuthFailure, CommandTimedOut`

## Task System

The `@task` decorator converts a function into a `Task` object. First parameter must be a context argument. Decorator kwargs: `aliases`, `default`, `pre`, `post`, `positional`, `iterable`, `incrementable`, `autoprint`, `help` (dict mapping param names to help strings), `optional`.

Task properties: `name`, `aliases`, `pre`, `post`, `called` (bool), `help` (dict), `autoprint`, `positional`, `iterable`, `incrementable`, `optional`. Tasks are callable -- `task(context, **kwargs)` executes the body and sets `called = True`. When `autoprint=True`, the return value is printed to stdout.

`get_arguments()` introspects the function signature and returns `Argument` objects, inferring `kind` from defaults (bool default -> bool, int -> int, etc.), respecting `iterable` (kind=list) and `incrementable` (kind=int, incrementable=True).

`call(task, *args, **kwargs)` creates a `Call` object representing a deferred invocation with specific arguments. `Call` has `clone()`.

## Collection

Collections organize tasks into namespaces with dotted-name resolution and configuration. Constructor: `Collection(*args, auto_dash_names=True)`. The first positional argument may optionally be a string used as the collection's name; when it is not a string the collection is unnamed. Any remaining positional arguments are `Task` or `Collection` objects: `Task` objects are added as via `add_task`, and `Collection` objects are added as sub-collections as via `add_collection`. For example, `Collection("name", task1, task2)` builds a named collection with two tasks, while `Collection(task_a, sub_collection)` builds an unnamed collection with one task and one nested sub-collection. `add_task(task, name=None, aliases=(), default=False)` adds a task; same name replaces existing. `add_collection(subcoll, name=None)` creates dotted paths like `"sub.task"`. `configure(mapping)` sets collection-level config that flows to task Contexts via Executor. `configuration(taskpath=None)` returns a config dict: with no argument it returns the collection's own config; given a (dotted) task name like `"inner.show-config"` it returns the effective merged config visible to that task — the task's own subcollection config deep-merged with the config inherited from its parent/outer collections. `Collection.from_module(module, name=None, auto_dash_names=True)` loads from a module.

`task_names` returns a dict mapping canonical task names to their alias lists (including subcollection dotted paths). `auto_dash_names` (default True) converts underscores to dashes in task/collection names. `default` is the NAME (a `str`) of the default task invoked when the collection name is used as a task, or `None` when no default is set (matching the `"default"` key in `serialized()`). `serialized()` returns a recursive dict `{"name": str, "default": str|None, "tasks": [{"name": str, "aliases": [str], ...}], "collections": [{"name": str, ...}]}`; the top-level `"default"` key holds the collection's default task name (`None` when unset), each task entry carries its transformed `"name"` plus its `"aliases"` list, and sub-collections are serialized recursively under `"collections"`. `to_contexts()` converts tasks to `ParserContext` objects for the parser.

## Parser System

Hand-rolled argument parser (not argparse).

`Argument` represents a CLI flag/argument with type-aware value setting. Constructor: `Argument(name=None, names=None, kind=str, default=None, positional=False, optional=False, incrementable=False, help=None)` -- must provide exactly one of `name` or `names`. The `value` setter performs type casting: str->int for int kind, toggles bool, appends to list, increments for incrementable. `takes_value` is False for bool and incrementable args. `got_value` tracks whether a value was explicitly set.

`ParserContext` holds arguments for one task during parsing. Constructor: `ParserContext(name=None, aliases=(), args=())`. `args` is accessible by name as a dict (e.g., `ctx.args["verbose"]` returns the `Argument` object). `flags` maps `"--name"` and `"-n"` to Argument objects. `inverse_flags` maps `"--no-name"` for bools defaulting to True. `as_kwargs` is a property returning a dict mapping each argument's attr_name to its current value. Also provides `positional_args`, `missing_positional_args`, `flag_names()`, `help_tuples()`. `missing_positional_args` is a **live list** of the positional arguments that have not yet received a value: an `Argument` drops out of it as soon as its value has been set — including a direct `argument.value = ...` attribute assignment (which sets `got_value`), not only via `add_arg` registration or Parser-driven filling. `add_arg(argument)` registers an `Argument` after construction -- the dynamic counterpart to the `args=` constructor list -- updating `args`, `flags`/`inverse_flags`, and `positional_args`/`missing_positional_args` accordingly. `help_tuples()` returns a list of `(flag_spec, help_str)` tuples, one per argument, where `flag_spec` is the rendered flag-name string (containing the argument's flag name) and `help_str` is that argument's help text verbatim (empty string when no help was provided).

Flag rendering: underscores in an argument name translate to dashes in its long flag (an `Argument` named `my_task` registers `--my-task` in `flags`), and a single-character name renders as a short flag (`-v`).

`Parser` constructor: `Parser(contexts=[ctx1, ctx2], initial=core_ctx, ignore_unknown=False)`. `parse_argv(tokens)` returns a `ParseResult`. Matches tokens against context names/aliases to identify tasks. `--flag value` and `--flag=value` both work. Boolean: `--flag` sets True, `--no-flag` sets False. List flags accumulate: `--item a --item b` -> `["a", "b"]`; accumulation stops at task boundaries. Incrementable: `-v -v -v` -> 3. Positional args fill unfilled slots even when mixed with flags. `--` sends remaining tokens to `ParseResult.remainder`. Unknown names raise `ParseError` (or go to `ParseResult.unparsed` if `ignore_unknown=True`). `initial` context captures core flags and appears as first result element with `name=None`. When core and task contexts share a flag name, the task's flag wins and the task's type determines parsing behavior. Same task can appear multiple times with different arg values.

## Configuration

Nested config dicts are transparently wrapped so that nested values support both attribute access (e.g. `config.db.host`) and item access (e.g. `config["db"]["host"]`), recursively.

`Config` provides hierarchical config with deep merge. Merge precedence (lowest to highest): defaults < collection (`load_collection`) < project file (`load_project`) < overrides < runtime modifications. Nested dicts merge deeply (not shallow overwrite). Runtime attribute/item writes on a `Config` (e.g. `config.run.echo = True`) are captured into a top-precedence modifications layer rather than mutating the merged result directly; that layer is re-applied last on every subsequent re-merge (`load_collection`, `load_project`, `load_shell_env`), so a runtime write always wins over config loaded afterward. `clone()` creates an independent deep copy; modifications to clone don't affect original. `load_collection(data)` merges collection-level config. `load_shell_env()` scans `INVOKE_`-prefixed env vars where underscores separate nesting levels, and casts each env-var string to the type of the *existing* config value at that key: for a bool entry the string becomes `True` unless it is `"0"` or `""` (so `INVOKE_RUN_ECHO="1"` yields `run.echo is True`); a str/`None` entry keeps the raw string; an int (or other scalar) entry is built from the string via its type; a list/tuple entry raises `UncastableEnvVar`. `Config(project_location=path)` or `set_project_location(path)` sets the project directory; `load_project()` then loads config from `invoke.yaml`, `invoke.yml`, `invoke.json`, or `invoke.py` in that directory. YAML loading uses the vendored yaml library (`yaml.safe_load`). Full dict protocol: `__getitem__`, `__setitem__`, `__contains__`, `keys()`, iteration. Built-in `run` defaults: `echo` (bool, default `False`), `warn`, `hide`, `shell`, `env`, `encoding`, `in_stream`, `timeout`, etc. Config attribute proxying: `context.some_key` delegates to `context.config.some_key`.

## Context and Command Execution

`Context` wraps command execution with config proxying and composable context managers. `run(command, **kwargs)` executes via `Local` runner; key kwargs: `hide` (accepts `True`, `"stdout"`, `"stderr"`, or `"both"`), `warn`, `pty`, `env`, `timeout`, `encoding`, `in_stream` (controls the caller's/parent stdin forwarded to the subprocess; `False` stops that forwarding — but it does **not** disable watcher-driven writes: a watched command run with `in_stream=False` still receives its `watchers`' responses on stdin), `watchers` (list of StreamWatcher instances for auto-responding). Returns `Result`. `sudo(command, **kwargs)` composes the command as `sudo -S -p '<prompt>' <command>` and adds a `FailingResponder` to handle the password prompt. Accepts `password` kwarg for the sudo password. Raises `AuthFailure` on authentication failure. `cd(path)` is a context manager for working directory; nested `cd` joins paths; cd occurs before prefixes in the composed command. `prefix(command)` is a context manager prepending commands with `&&`; nested prefixes compose in order. `cwd` returns the current effective working directory.

`MockContext` is a testing utility that returns predetermined results instead of executing commands. Its `run=` and `sudo=` kwargs each accept one of: a single `Result`; a bool (`True` yields a `Result` with `exited == 0`, `False` yields `exited == 1`); a string (used as the `Result` stdout); a top-level iterable/sequence of any of those values (e.g. `run=[Result(...), Result(...), ...]`); or a dict mapping exact command strings or compiled regexes (`re.compile(...)` keys) to any of those values. A top-level iterable (whether passed directly or as a dict value) is consumed one element per successive matching call, returning results in declaration order. The `repeat` flag controls exhaustion: with `repeat=False` a configured sequence (or single value) is consumed once and any further call after exhaustion raises `NotImplementedError`, whereas with `repeat=True` the configured result(s) are re-served on every subsequent call rather than exhausting. Also supports `sudo`, `set_result_for(attr, command, result)` (adds or replaces a stored result after construction — the first positional `attr` selects the channel, `"run"` or `"sudo"`; `command` is the command string or compiled-regex key; and `result` is the value to store, in the same accepted forms as the `run=`/`sudo=` kwargs — so `mc.set_result_for("run", "cmd", Result("out"))` makes a subsequent `mc.run("cmd")` return that result), and Mock-wrapped `run`/`sudo` methods for assertion checking (so `mc.run.assert_called_once_with(...)` works). Unmatched commands raise `NotImplementedError`.

`Result` contains command output: `stdout`, `stderr`, `encoding`, `command`, `shell`, `exited`, `pty` (bool), `hide` (tuple/set of hidden stream names, e.g. `("stdout", "stderr")`), `ok` (bool), `failed` (bool), `return_code` (alias for `exited`), `tail(stream, count)`, `__bool__` (True if ok). `__repr__` embeds the command string (e.g. `<Result cmd='...' exited=N>`). Constructor accepts stdout as first positional arg: `Result("output text")`.

`Runner` is abstract; `Local` is the concrete runner for local command execution. `Promise` wraps async results.

## Executor

Executes tasks with pre/post dependency resolution and deduplication. Constructor: `Executor(collection, config=Config())`. `execute("task1", "task2")` returns `{Call: return_value}`. Also accepts `(task_name, kwargs_dict)` tuples. Pre-tasks run depth-first before the task; post-tasks run after. Within a single `pre=[...]` (or `post=[...]`) list, dependencies run in left-to-right declaration order, so reordering the list reorders their execution. Deduplication keys on the `Call`'s identity as `(task, bound arguments)`, not the task alone: two entries collapse to a single run only when they resolve to the same task **and** the same bound args. So two identical `call(task, **kwargs)` entries dedupe to one, while a `call()` carrying non-default kwargs and a plain reference to the same task (its defaults) are treated as distinct calls and each run. Each task gets a fresh Context, but all tasks in one `execute()` call share the same Config object -- mutations in one task's config are visible to subsequent tasks. Subcollection config propagation: each subcollection's `configure()` data flows to its tasks' Contexts. Executing a subcollection name resolves to its default task. Calling `execute()` with no task names at all runs the root collection's own default task (the one marked `default=True`), if one is defined.

## Program

CLI entry point. Constructor: `Program(namespace=None, ...)`. When `namespace` is None, auto-loads from `tasks.py` in the current directory via `FilesystemLoader`. `run(argv=None)` parses argv (or `sys.argv`), resolves tasks, and executes them. `argv` follows `sys.argv` convention -- `argv[0]` is the program name and is skipped during parsing. Core flags: `--help` (display usage and available tasks), `--list` (list available tasks with descriptions). An unknown task name causes a non-zero exit with an error message that names the offending token (the unknown task name appears verbatim in the error output). Uses `Parser`, `Executor`, and `FilesystemLoader` internally.

## Watchers

`StreamWatcher` base class with `submit(stream)` yielding responses (raises `NotImplementedError`).

When `watchers` are supplied to `run`, the runner opens a stdin channel to the subprocess and writes each response yielded by a watcher's `submit(stream)` back to that channel as the corresponding prompt appears on the command's output. This is how a `Responder` drives an interactive command (one that prints a prompt and reads stdin) to completion — the matched response is fed to the command's stdin so it can proceed and exit successfully. Watcher-driven writes happen regardless of `in_stream` (they are not suppressed by `in_stream=False`).

`Responder(pattern, response)` -- regex pattern matching that avoids duplicate matches on the same stream content.

`FailingResponder(pattern, response, sentinel)` -- raises `ResponseNotAccepted` when sentinel appears after a response.

## FilesystemLoader

Loads task modules from disk: looks for `tasks.py` or `tasks/__init__.py`. Constructor: `FilesystemLoader(start="/path")`. `load("tasks")` returns `(module, path)`. Raises `CollectionNotFound` if not found. Modules may contain an explicit `ns` namespace object.

## Exceptions

`Failure(result, reason=None)` is the base; subclasses: `UnexpectedExit` (non-zero exit, str includes command + code), `CommandTimedOut(result, timeout)` (str includes the configured timeout value, e.g. "Command did not complete within 30 seconds"), `AuthFailure(result, prompt)` (str mentions "rejected"). `Exit(message=None, code=None)` for clean exit; message without code defaults to 1, no args defaults to 0. Also: `ParseError`, `CollectionNotFound(name, start)`, `ThreadException`, `WatcherError`, `ResponseNotAccepted`, `SubprocessPipeError`, `AmbiguousEnvVar`, `UncastableEnvVar`, `UnknownFileType`, `PlatformError`.

## Top-Level Convenience

`invoke.run(command, **kwargs)` creates a Context and calls run().

`invoke.sudo(command, **kwargs)` creates a Context and calls sudo().

## setup.sh

```bash
pip install -e . --no-build-isolation
```
