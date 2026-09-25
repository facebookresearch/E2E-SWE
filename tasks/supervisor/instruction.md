# supervisor — Process Control System

## Overview

Implement **supervisor**, a Python process control system. Supervisor manages child processes on Unix-like systems, providing a client/server model for starting, stopping, and monitoring processes. The core consists of: a process state machine, an event notification system, an XML-RPC interface for process control, INI-style config parsing, and child utility protocols for event listener processes.

## Dependencies

- The environment is **offline** — no network access is available, and you must not install
  anything (there is no package index to install from). Everything needed is already present.
- **No external runtime dependencies.** This project is pure Python and uses only the standard
  library, so there is nothing to install at runtime.
- The project is installed offline by a `setup.sh` script (already provided) that runs
  `pip install -e . --no-build-isolation` against the pre-installed build backend
  (`setuptools` + `wheel`). This registers the `supervisord` and `supervisorctl` console scripts
  on `PATH`. Do not modify how the project is installed.

---

## 1. Process State Machine (`supervisor.states`)

Processes transition through 8 states: STOPPED, STARTING, RUNNING, BACKOFF, STOPPING, EXITED, FATAL, UNKNOWN. Each state is an integer constant on `ProcessStates`.

Module-level grouping tuples: `STOPPED_STATES`, `RUNNING_STATES`, `SIGNALLABLE_STATES`.

`SupervisorStates`: SHUTDOWN, RESTARTING, RUNNING, FATAL.

Description helpers: `getProcessStateDescription(code)` → state name string.

---

## 2. Event System (`supervisor.events`)

Module-level pub/sub: `subscribe(type, callback)`, `unsubscribe(type, callback)`, `notify(event)`, `clear()`. Uses `isinstance` matching — subscribing to a parent type catches all subclass events.

Event hierarchy: `ProcessStateEvent` (abstract) → `ProcessStateStartingEvent`, `ProcessStateRunningEvent`, `ProcessStateStoppingEvent`, `ProcessStateStoppedEvent`, `ProcessStateExitedEvent`, `ProcessStateBackoffEvent`, `ProcessStateFatalEvent`. Each carries `from_state`. `SupervisorStateChangeEvent` → `SupervisorRunningEvent`, `SupervisorStoppingEvent`. `ProcessCommunicationEvent` with `BEGIN_TOKEN`/`END_TOKEN` constants — these are **byte-string** constants (`bytes`, e.g. `b'<!--XSUPERVISOR:BEGIN-->'` / `b'<!--XSUPERVISOR:END-->'`), so they can be located directly in a binary stream. Plus its stdout/stderr subclasses `ProcessCommunicationStdoutEvent` and `ProcessCommunicationStderrEvent`. `ProcessGroupAddedEvent`, `ProcessGroupRemovedEvent`. Tick events.

---

## 3. Subprocess (`supervisor.process`)

`Subprocess(config)` — manages a child process. `change_state(new_state)` fires events via `notify()`. Returns False if unchanged. BACKOFF increments backoff counter. `give_up()` → FATAL. `transition()` drives auto-restart and retry exhaustion (BACKOFF → FATAL after `startretries`). Other methods: `spawn()`, `stop()`, `kill(sig)`, `signal(sig)`, `finish(pid, sts)`.

`ProcessGroupBase` → `ProcessGroup` (calls `transition()` on children), `EventListenerPool`. A group exposes a `.processes` mapping (process name → `Subprocess`) and a `stop_all()` method that calls `stop()` on each member process. A group is built from a `ProcessGroupConfig` (see section 8) and retains it as `group.config`, so the group's own name is read as `group.config.name`.

---

## 4. XML-RPC Interface (`supervisor.rpcinterface`)

`SupervisorNamespaceRPCInterface(supervisord)` — process control API.

Methods: `getAPIVersion()` → `"3.0"`, `getState()` → dict with `"statecode"` and `"statename"`, `getPID()`, `getProcessInfo(name)`, `getAllProcessInfo()`, `startProcess(name, wait)`, `stopProcess(name, wait)`, `stopAllProcesses(wait)`, `signalProcess(name, signal)`, `addProcessGroup(name)`, `removeProcessGroup(name)`, `readLog(offset, length)`, `getAllConfigInfo()`, `shutdown()`, `restart()`.

`getProcessInfo` returns a dict with: name, group, state, statename, pid, start, stop, now, exitstatus, spawnerr, logfile, stdout_logfile, stderr_logfile, description. The values are sourced from the process/config/group collaborators as follows:
- `name` is the member process's own name (`process.config.name`) and `group` is the containing group's name, sourced from the group object as `group.config.name` (the same accessor `getAllProcessInfo` and the batch status structs use for their `group` field).
- `start` and `stop` are the process's last-start and last-stop epoch times, read from the Subprocess's `laststart` / `laststop` attributes (each `0` when the process has never been started / stopped, respectively).
- `stdout_logfile` and `stderr_logfile` come from the config as `process.config.stdout_logfile` / `process.config.stderr_logfile` (falling back to `''` when unset), and `logfile` is a backward-compatibility alias equal to `stdout_logfile`. Note there is no separate plain `logfile` attribute on the config — the `logfile` key mirrors `stdout_logfile`.

Namespec format: `group:name`. Helpers: `make_namespec(group, name)`, `split_namespec(namespec)`, with these round-trip rules:
- `make_namespec(group, name)` collapses to just `name` when `group == name` (a process whose group shares its name has the short name), otherwise returns `group:name`.
- `split_namespec("group:name")` → `(group, name)`; a bare `"name"` (no colon) → `(name, name)` (group and process share the name); a trailing-colon `"group:"` (whole-group selector) → `(group, None)`.

Methods raise `RPCError` with fault codes for errors (ALREADY_STARTED, NOT_RUNNING, BAD_NAME, SHUTDOWN_STATE, ALREADY_ADDED, etc.).

`readLog(offset, length)` returns bytes of the daemon's main log file as a string. A non-negative `offset` with `length == 0` returns the log from `offset` to end; with `length > 0` it returns `length` bytes starting at `offset`. A negative `offset` returns that many bytes from the tail of the log and requires `length == 0`; a negative `offset` combined with a non-zero `length` is rejected with `RPCError(Faults.BAD_ARGUMENTS)`. (`stopAllProcesses(wait)` and the other batch operations return an array of per-process status structs, each a dict with `name`, `group`, `status` (a fault code, `Faults.SUCCESS` on success), and `description` (`"OK"` on success).)

**Shutdown gating.** Every method on this interface — including pure queries such as `getAPIVersion()` and `getState()`, not just mutating control calls like `startProcess`/`stopProcess`/`addProcessGroup` — first checks the daemon mood (`supervisord.options.mood`, a `SupervisorStates` value). If the mood is below `SupervisorStates.RUNNING` (i.e. `SHUTDOWN` or `RESTARTING`), the call is rejected immediately by raising `RPCError(Faults.SHUTDOWN_STATE)`. So once the supervisor enters the SHUTDOWN state, `getAPIVersion()` raises `RPCError(SHUTDOWN_STATE)` rather than returning `"3.0"`.

---

## 5. XML-RPC Faults (`supervisor.xmlrpc`)

`Faults` — named fault code constants (ALREADY_STARTED, NOT_RUNNING, BAD_NAME, SHUTDOWN_STATE, ALREADY_ADDED, STILL_RUNNING, etc.).

`RPCError(code, extra=None)` — exception with `.code` and `.text` (includes fault name string, e.g. `"BAD_NAME"`).

---

## 6. Data Types (`supervisor.datatypes`)

Type converters: `boolean(s)`, `byte_size(v)`, `signal_number(v)`, `list_of_exitcodes(s)`, `list_of_strings(s)`, `auto_restart(v)` (returns `RestartUnconditionally`, `RestartWhenExitUnexpected`, or `False`), `inet_address(s)` (parses `"host:port"` → `(host, port)` tuple), `logging_level(s)` (converts level name to `logging` int), `dict_of_key_value_pairs(s)` (parses `"KEY=val,KEY2=val2"` → dict).

`byte_size(v)` accepts a number optionally followed by a case-insensitive two-letter size suffix — `KB`, `MB`, or `GB` — using **binary (1024-based)** multipliers, and returns the size in bytes as an int. So `byte_size("1KB") == 1024`, `byte_size("1MB") == 1024 * 1024`, and `byte_size("1GB") == 1024 ** 3`; a bare number with no suffix is taken as bytes (e.g. `byte_size("512") == 512`).

---

## 7. Child Utilities (`supervisor.childutils`)

`get_headers(line)` — parses space-delimited `key:val` pairs. `eventdata(payload)` — splits headers from data on first newline.

`EventListenerProtocol` — `ready(stdout=sys.stdout)`, `ok(stdout=sys.stdout)`, `fail(stdout=sys.stdout)` for event listener communication. Each method takes the output stream to write to as its sole argument (a writable file object, defaulting to `sys.stdout`) and writes the result tokens to that stream — so a caller can pass its own buffer (e.g. an `io.StringIO`) to capture the output. The result protocol uses these literal tokens: `ready()` writes `READY\n`; `ok()` and `fail()` write a `RESULT <len>\n` header (where `<len>` is the byte length of the body) followed immediately by the body — `OK` for `ok()`, `FAIL` for `fail()`.

`ProcessCommunicationsProtocol` — `send(msg, fp)` writes the raw bytes framing to the given binary stream: the (bytes) `ProcessCommunicationEvent.BEGIN_TOKEN`, then the message bytes, then the (bytes) `END_TOKEN`. So for a `send(b"...", io.BytesIO())`, the resulting buffer contains `BEGIN_TOKEN`, the message, and `END_TOKEN` as byte sequences.

---

## 8. Config Parsing (`supervisor.options`)

`ServerOptions` — parses INI-style config files with `[supervisord]` and `[program:name]` sections. `options.realize(args, doc)` processes the config. Produces `process_group_configs` list. Filesystem-path settings such as the `[supervisord]` `logfile` are normalized to absolute paths (e.g. `options.logfile` is always absolute after realizing the config).

`ServerOptions` exposes a settable `configfile` attribute holding the path to the config file. `realize(args, doc)` determines which file to parse as follows: a `-c`/`--configuration` value in `args` is used when present; otherwise it falls back to an already-assigned `self.configfile`, then to the default search paths. So a caller may set `options.configfile = <path>` and then call `options.realize(args=[], doc=...)` (no `-c`) to parse that file.

`ProcessConfig` — holds process settings (name, command, priority, autostart, autorestart, startsecs, startretries, stopsignal, stopwaitsecs, exitcodes, redirect_stderr, logfile settings).

`ProcessGroupConfig(options, name, priority, process_configs)` — `make_group()` → `ProcessGroup`.

---

## 9. Dispatchers (`supervisor.dispatchers`)

`POutputDispatcher(process, event_type, fd)` — reads stdout/stderr from child processes. Methods: `.readable()`, `.writable()`, `.close()`. Property: `.closed`.

`PInputDispatcher(process, channel, fd)` — writes to child stdin. Methods: `.readable()`, `.writable()`. Property: `.input_buffer`.

---

## 10. Subprocess Operations

`Subprocess.spawn()` — forks and executes the configured command. Returns None if already running or if the command is invalid (sets `spawnerr` and transitions to BACKOFF). Uses `options.check_execv_args()` to validate the executable.

`Subprocess.stop()` — requests an administrative stop, sending the configured stop signal to the process. It **returns `None` on a successful stop request** (a `None`/falsy return is the success sentinel, *not* a failure indicator); it returns an error-message string only when the stop could not be issued. Any process in a signallable state is stoppable, so a successful stop does not require the process to already carry a truthy `pid`. Consequently the batch/RPC controls (`stopProcess`, `stopAllProcesses`) treat a `None` return from `stop()` as success (reporting `Faults.SUCCESS`) and must not report a fault merely because `stop()` returned `None` or the process's `pid` was falsy.

`supervisor.options.NotFound` — raised by `check_execv_args` when the executable doesn't exist.

---

## 11. confecho utility

`supervisor.confecho` — prints a bundled sample `supervisord` configuration to stdout. Calling `confecho.main()` (with no config-file argument) writes the built-in sample config, which includes a `[supervisord]` section containing a `logfile` setting. It can be run as `python -m supervisor.confecho`.

---

## 12. supervisord Daemon (`supervisor.supervisord`)

The `supervisord` command starts the supervisor daemon. Key config sections in INI format:
- `[supervisord]` — daemon settings: `nodaemon` (bool), `logfile`, `pidfile`, `loglevel`
- `[unix_http_server]` — Unix socket: `file` path
- `[inet_http_server]` — TCP socket: `port` (e.g., `127.0.0.1:9001`), enables HTTP/web UI access
- `[supervisorctl]` — client settings: `serverurl` (unix:// or http://)
- `[rpcinterface:supervisor]` — RPC interface factory (see below)
- `[program:name]` — managed processes: `command`, `autostart`, `autorestart`

The daemon can run in foreground with `nodaemon=true` or background with `nodaemon=false`.

**Runtime composition.** On startup `supervisord` reads the config, builds the process groups, and starts an HTTP server bound to the configured socket(s). That HTTP server dispatches XML-RPC calls (POST to `/RPC2`) and serves the web UI (GET `/`). The XML-RPC handler under the `supervisor` namespace is produced by the factory named in `[rpcinterface:supervisor]` via the `supervisor.rpcinterface_factory` key. The default value `supervisor.rpcinterface:make_main_rpcinterface` must resolve to a callable `make_main_rpcinterface(supervisord)` in `supervisor.rpcinterface` that returns a `SupervisorNamespaceRPCInterface` bound to the running daemon.

**Web UI.** When an `[inet_http_server]` is configured, a GET request to the server root returns HTTP 200 with an HTML status page that lists the managed program names (each `[program:name]` appears in the page).

## 13. supervisorctl Client (`supervisor.supervisorctl`)

The `supervisorctl` command controls a running supervisord over the configured `serverurl`. All command output — both the per-command success confirmations and the `ERROR:` fault/bad-name messages described below — is written to **standard output (stdout)**. Key commands:
- `supervisorctl -c <conf> status` — show process status: one line per process, `<name> <STATE> <description>`, where `<STATE>` is the uppercase process state name (e.g. `RUNNING`, `STOPPED`)
- `supervisorctl -c <conf> start <name>` / `stop <name>` — start/stop a process; on success prints the per-process confirmation as `<name>: started` / `<name>: stopped` (colon-joined, one line per process), matching the add/remove format
- `supervisorctl -c <conf> restart <name>` — restart a process; prints both the stop and start confirmations (`<name>: stopped` then `<name>: started`)
- `supervisorctl -c <conf> tail <name>` — tail a process's stdout log
- `supervisorctl -c <conf> add <name>` / `remove <name>` — add/remove a process group at runtime from the loaded config; on success prints `<name>: added process group` / `<name>: removed process group`, and an unknown group prints an `ERROR: no such process/group: <name>` message. Re-adding a group that is already active (the `ALREADY_ADDED` fault) prints an error message containing the word `already` (the client message is `ERROR: process group already active`)
- `supervisorctl -c <conf> pid` — print the supervisord PID (the integer only)
- `supervisorctl -c <conf> version` — print the supervisor version string
- `supervisorctl -c <conf> shutdown` — shut down the daemon
- `supervisorctl --help` — display help (mentions `supervisorctl`)

## 14. Loggers (`supervisor.loggers`)

`Logger(level=None, handlers=None)` — custom logger with level filtering. Methods: `info()`, `warn()`, `debug()`, `error()`, `critical()`, `close()`. `handle_file(logger, filename, fmt)` — adds a file handler to the logger.

`LevelsByName` — level constants: `INFO`, `DEBG`, `WARN`, `ERRO`, `CRIT`, `TRAC`, `BLAT`. Integer values follow standard logging conventions.

`BoundIO(maxbytes, buf=b'')` — in-memory byte buffer. `.write(data)`, `.getvalue()`, `.close()`.

---

## 15. PidProxy (`supervisor.pidproxy`)

`PidProxy(args)` — runs a command and proxies received signals to it via a pidfile. Constructor takes the argv list `[script, pidfile_path, command, *cmd_args]` and parses it into:
- `.pidfile` — the pidfile path (`args[1]`).
- `.abscmd` — the absolute path of the command (`os.path.abspath` of the command).
- `.cmdargs` — the full argv of the child command, i.e. `args[2:]` (the command path followed by its arguments, *including* the command itself as the first element).

`passtochild(sig, frame)` — reads the PID from `.pidfile` and forwards signal `sig` to that PID. After forwarding, it exits the proxy (`sys.exit(0)`) only for `SIGTERM`, `SIGINT`, and `SIGQUIT`; for any other signal it simply returns. If the pidfile is missing or unreadable, it reports that and returns without raising.

---

## 16. setup.sh

The project is installed offline (no build isolation, since the build backend is pre-installed):

```bash
pip install -e . --no-build-isolation
```
