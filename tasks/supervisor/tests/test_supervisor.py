"""
Tests for supervisor — process control system.

Tests exercise integration scenarios: process state machine transitions with
event notifications, XML-RPC process control with fault codes, dynamic group
management, batch operations, auto-restart logic, event subscription/dispatch,
child utility protocols, config parsing, and data type converters.
All tests use lightweight mock objects — no real processes are spawned.
"""

import signal
import io
import os
import tempfile

import pytest


# ============================================================
# Test-only mock infrastructure
# ============================================================


class _MockLogger:
    """Minimal logger stub."""
    def __init__(self):
        self.data = []
    def info(self, *args, **kw): self.data.append(args)
    def warn(self, *args, **kw): self.data.append(args)
    def debug(self, *args, **kw): self.data.append(args)
    def critical(self, *args, **kw): self.data.append(args)
    def error(self, *args, **kw): self.data.append(args)
    def trace(self, *args, **kw): self.data.append(args)
    def blather(self, *args, **kw): self.data.append(args)
    def close(self): pass
    def reopen(self): pass
    def log(self, level, msg, **kw): self.data.append((level, msg))
    def getvalue(self): return ''.join(str(x) for x in self.data)


class _MockOptions:
    """Minimal options stub."""
    loglevel = 20
    minfds = 5
    chdir_exception = None
    fork_exception = None
    execv_exception = None
    kill_exception = None
    make_pipes_exception = None
    remove_exception = None
    write_exception = None

    def __init__(self):
        from supervisor.states import SupervisorStates
        self.identifier = 'supervisor'
        self.childlogdir = '/tmp'
        self.uid = 999
        self.logger = _MockLogger()
        self.backofflimit = 10
        self.logfile = '/tmp/logfile'
        self.nocleanup = False
        self.strip_ansi = False
        self.pidhistory = {}
        self.process_group_configs = []
        self.nodaemon = False
        self.socket_map = {}
        self.mood = SupervisorStates.RUNNING
        self.mustreopen = False
        self.forkpid = 0
        self.kills = {}
        self.duped = {}
        self.written = {}
        self.fds_closed = []
        self.waitpid_return = None, None
        self.directory = None
        self.serverurl = 'http://localhost:9001'
        self.existing = []

    def getLogger(self, *args, **kw): return self.logger
    def get_pid(self): return os.getpid()
    def get_signal(self): return None
    def get_path(self): return ['/bin', '/usr/bin']
    def stat(self, path): return os.stat(path)
    def waitpid(self): return self.waitpid_return

    def _read_logfile(self, *args, **kw):
        """Read a slice of a log file, for an implementation that routes the read through options.

        The spec pins readLog's offset/length/negative-tail semantics but not which collaborator
        performs the read, so accept the common wirings — `options.read_log(offset, length)` and
        `options.readFile(path, offset, length)` — and apply exactly the documented slicing to the
        given path (defaulting to `self.logfile`). Bad argument combinations signal
        `ValueError('BAD_ARGUMENTS')` so a caller that maps the error onto a fault still reports
        BAD_ARGUMENTS.
        """
        rest = list(args)
        if rest and isinstance(rest[0], str):
            path = rest.pop(0)
        else:
            path = kw.get('filename') or kw.get('path') or self.logfile
        offset = int(rest.pop(0)) if rest else int(kw.get('offset', 0))
        length = int(rest.pop(0)) if rest else int(kw.get('length', 0))
        if length < 0 or (offset < 0 and length):
            raise ValueError('BAD_ARGUMENTS')
        with open(path, 'rb') as f:
            if offset < 0:
                f.seek(0, 2)
                f.seek(max(0, f.tell() + offset))
                data = f.read(-offset)
            else:
                f.seek(offset)
                data = f.read(length) if length else f.read()
        return data.decode('utf-8', 'replace')

    read_log = _read_logfile
    read_file = _read_logfile
    readFile = _read_logfile

    def check_execv_args(self, command_or_filename, *args):
        """Check if executable is valid — raises NotFound for missing files.

        The spec does not pin how spawn() invokes this collaborator, so accept either a
        single-arg call (the raw command string, split internally) or a pre-split
        (filename, argv, st) call; in both cases the first positional's leading token is the
        program path.
        """
        from supervisor.options import NotFound
        program = str(command_or_filename).split()[0] if str(command_or_filename).split() else str(command_or_filename)
        if not os.path.isfile(program):
            raise NotFound("bad filename")

    def fork(self):
        if self.fork_exception: raise self.fork_exception
        return self.forkpid

    def make_pipes(self, stderr=True):
        if self.make_pipes_exception: raise self.make_pipes_exception
        return {}

    def dup2(self, old, new):
        self.duped[new] = old

    def close_fd(self, fd):
        self.fds_closed.append(fd)

    def setpgrp(self):
        self.pgrp_set = True

    def execve(self, filename, argv, env):
        if self.execv_exception: raise self.execv_exception

    def kill(self, pid, sig):
        if self.kill_exception: raise self.kill_exception
        self.kills[pid] = sig

    def write(self, fd, chars):
        if self.write_exception: raise self.write_exception
        self.written[fd] = chars


class _MockPConfig:
    """Minimal process config stub."""
    def __init__(self, options, name, command, **kw):
        self.options = options
        self.name = name
        self.command = command
        self.priority = kw.get('priority', 999)
        self.autostart = kw.get('autostart', True)
        self.autorestart = kw.get('autorestart', True)
        self.startsecs = kw.get('startsecs', 10)
        self.startretries = kw.get('startretries', 999)
        self.uid = kw.get('uid', None)
        self.stdout_logfile = kw.get('stdout_logfile', None)
        self.stdout_capture_maxbytes = kw.get('stdout_capture_maxbytes', 0)
        self.stdout_events_enabled = kw.get('stdout_events_enabled', False)
        self.stdout_logfile_backups = kw.get('stdout_logfile_backups', 0)
        self.stdout_logfile_maxbytes = kw.get('stdout_logfile_maxbytes', 0)
        self.stdout_syslog = kw.get('stdout_syslog', False)
        self.stderr_logfile = kw.get('stderr_logfile', None)
        self.stderr_capture_maxbytes = kw.get('stderr_capture_maxbytes', 0)
        self.stderr_events_enabled = kw.get('stderr_events_enabled', False)
        self.stderr_logfile_backups = kw.get('stderr_logfile_backups', 0)
        self.stderr_logfile_maxbytes = kw.get('stderr_logfile_maxbytes', 0)
        self.stderr_syslog = kw.get('stderr_syslog', False)
        self.redirect_stderr = kw.get('redirect_stderr', False)
        self.stopsignal = kw.get('stopsignal', signal.SIGTERM)
        self.stopwaitsecs = kw.get('stopwaitsecs', 10)
        self.stopasgroup = kw.get('stopasgroup', False)
        self.killasgroup = kw.get('killasgroup', False)
        self.exitcodes = kw.get('exitcodes', (0,))
        self.environment = kw.get('environment', None)
        self.serverurl = kw.get('serverurl', None)
        self.directory = kw.get('directory', None)
        self.umask = kw.get('umask', None)

    def make_process(self, group=None): return _MockProcess(self, group=group)
    def make_dispatchers(self, proc): return {}, {}
    def create_autochildlogs(self): pass


class _MockProcess:
    """Minimal process stub for RPC tests."""
    def __init__(self, config, group=None, state=None):
        from supervisor.states import ProcessStates
        self.config = config
        self.group = group
        self.state = state if state is not None else ProcessStates.RUNNING
        self.pid = 0
        self.laststart = 0
        self.laststop = 0
        self.delay = 0
        self.administrative_stop = False
        self.system_stop = False
        self.killing = False
        self.backoff = 0
        self.exitstatus = None
        self.spawnerr = None
        self.description = ''
        self.listener_state = None
        self.spawned = False
        self.stopped = False
        self.transitioned = False

    # A real Subprocess exposes its process name (getProcessInfo reports it); mirror that so a
    # group that keys its `.processes` map off the member process rather than the config still
    # resolves to the same "process name -> Subprocess" mapping the spec guarantees.
    @property
    def name(self): return self.config.name

    # getProcessInfo reports a `description` string, but the spec pins neither its content nor
    # which collaborator composes it, and no assertion inspects the value — so accept the common
    # wirings: an implementation may build it in the RPC layer or read it off the process.
    def get_description(self): return self.description

    def get_state(self): return self.state
    def spawn(self):
        from supervisor.states import ProcessStates
        self.spawned = True; self.state = ProcessStates.RUNNING; self.pid = 12345; return self.pid
    def stop(self):
        # Matches real Subprocess.stop(): returns None on a successful stop request.
        from supervisor.states import ProcessStates
        self.stopped = True; self.state = ProcessStates.STOPPED; return None
    def kill(self, sig):
        from supervisor.states import ProcessStates
        self.killing = True; self.state = ProcessStates.STOPPING
    def signal(self, sig): return None
    def transition(self): self.transitioned = True
    def drain(self): pass
    def write(self, chars): pass
    def get_execv_args(self): return self.config.command, [self.config.command]
    def removelogs(self): pass
    def reopenlogs(self): pass
    def stop_report(self): pass
    def __lt__(self, other): return self.config.priority < other.config.priority


class _MockProcessGroup:
    """Minimal process group stub."""
    def __init__(self, config, processes=None):
        self.config = config
        self.processes = processes or {}
    def get_unstopped_processes(self):
        from supervisor.states import STOPPED_STATES
        return [p for p in self.processes.values() if p.state not in STOPPED_STATES]
    def get_dispatchers(self): return {}
    def transition(self):
        for p in self.processes.values(): p.transition()
    def stop_all(self):
        for p in self.processes.values(): p.stop()
    def before_remove(self): pass
    def __lt__(self, other): return self.config.priority < other.config.priority


class _MockSupervisor:
    """Minimal supervisord stub for RPC tests."""
    def __init__(self, options=None, process_groups=None):
        if options is None: options = _MockOptions()
        self.options = options
        self.process_groups = process_groups or {}
    @property
    def mood(self): return self.options.mood
    def get_state(self): return self.options.mood

    def reap(self, once=False):
        """Reap exited children (no-op when waitpid yields no pid)."""
        pid, sts = self.options.waitpid()
        if pid:
            proc = self.options.pidhistory.get(pid)
            if proc is not None:
                proc.finish(pid, sts)

    def add_process_group(self, config):
        """Add a process group from config."""
        name = config.name
        if name in self.process_groups:
            return False
        self.process_groups[name] = config.make_group()
        return True

    def remove_process_group(self, name):
        """Remove a process group by name."""
        if name not in self.process_groups:
            return False
        group = self.process_groups[name]
        group.before_remove()
        del self.process_groups[name]
        return True


def _make_populated_supervisor(options, group_name, *pconfigs):
    """Create a supervisor with one process group."""
    from supervisor.states import ProcessStates
    processes = {}
    for pc in pconfigs:
        proc = _MockProcess(pc, state=ProcessStates.RUNNING)
        processes[pc.name] = proc
    gc = type('MockGConfig', (), {
        'name': group_name, 'priority': 999, 'process_configs': list(pconfigs),
    })()
    group = _MockProcessGroup(gc, processes)
    for proc in processes.values(): proc.group = group
    return _MockSupervisor(options, {group_name: group})


def _set_procattr(sup, group_name, proc_name, attr, val):
    setattr(sup.process_groups[group_name].processes[proc_name], attr, val)


# ============================================================
# 1. Process State Machine + Events (merged)
# ============================================================


class TestProcessStateMachineAndEvents:
    """Tests for Subprocess state transitions, event firing, backoff, and auto-restart logic."""

    def test_full_lifecycle_with_event_tracking(self):
        """Full lifecycle STOPPED→STARTING→RUNNING→STOPPING→STOPPED fires correct events; same-state is no-op."""
        from supervisor import events
        from supervisor.process import Subprocess
        from supervisor.states import ProcessStates, getProcessStateDescription, STOPPED_STATES, RUNNING_STATES

        events.clear()
        fired = []
        events.subscribe(events.ProcessStateEvent, lambda ev: fired.append(ev))

        options = _MockOptions()
        config = _MockPConfig(options, "proc", "/bin/test")
        proc = Subprocess(config)
        assert proc.state == ProcessStates.STOPPED

        # State descriptions work
        assert getProcessStateDescription(ProcessStates.RUNNING) == "RUNNING"
        assert getProcessStateDescription(ProcessStates.FATAL) == "FATAL"

        # State groupings
        assert ProcessStates.STOPPED in STOPPED_STATES
        assert ProcessStates.RUNNING in RUNNING_STATES

        # Lifecycle
        proc.change_state(ProcessStates.STARTING)
        assert isinstance(fired[-1], events.ProcessStateStartingEvent)
        assert fired[-1].from_state == ProcessStates.STOPPED

        proc.change_state(ProcessStates.RUNNING)
        assert isinstance(fired[-1], events.ProcessStateRunningEvent)

        proc.change_state(ProcessStates.STOPPING)
        assert isinstance(fired[-1], events.ProcessStateStoppingEvent)

        proc.change_state(ProcessStates.STOPPED)
        assert isinstance(fired[-1], events.ProcessStateStoppedEvent)
        assert len(fired) == 4

        # Same state = no-op
        assert proc.change_state(ProcessStates.STOPPED) is False
        assert len(fired) == 4

        events.clear()

    def test_backoff_give_up_and_transition_retry_exhaustion(self):
        """Backoff increments; give_up→FATAL; transition() promotes BACKOFF→FATAL after startretries exhausted."""
        from supervisor import events
        from supervisor.process import Subprocess
        from supervisor.states import ProcessStates

        events.clear()
        options = _MockOptions()
        config = _MockPConfig(options, "proc", "/bin/x", startretries=2)
        proc = Subprocess(config)

        # Backoff increments
        proc.change_state(ProcessStates.STARTING)
        proc.change_state(ProcessStates.BACKOFF)
        assert proc.backoff == 1

        proc.change_state(ProcessStates.STARTING)
        proc.change_state(ProcessStates.BACKOFF)
        assert proc.backoff == 2

        # give_up → FATAL
        proc.give_up()
        assert proc.state == ProcessStates.FATAL

        # Now test transition() auto-promoting BACKOFF→FATAL
        proc2 = Subprocess(_MockPConfig(options, "p2", "/bin/y", startretries=1))
        proc2.change_state(ProcessStates.STARTING)
        proc2.change_state(ProcessStates.BACKOFF)
        proc2.backoff = 2  # exceed startretries=1
        proc2.transition()
        assert proc2.state == ProcessStates.FATAL

        events.clear()


# ============================================================
# 2. Event System
# ============================================================


class TestEventSystem:
    """Tests for event subscription, notification, parent-type catching, and supervisor events."""

    def test_subscribe_notify_unsubscribe_with_parent_catching(self):
        """Subscribe to parent type, receive child events, unsubscribe stops delivery."""
        from supervisor import events
        from supervisor.states import ProcessStates

        events.clear()
        received = []
        handler = lambda ev: received.append(type(ev).__name__)
        events.subscribe(events.ProcessStateEvent, handler)

        proc = _MockProcess(_MockPConfig(_MockOptions(), "p", "/bin/p"))
        proc.pid = 1; proc.backoff = 0

        events.notify(events.ProcessStateStartingEvent(proc, ProcessStates.STOPPED))
        events.notify(events.ProcessStateRunningEvent(proc, ProcessStates.STARTING))
        events.notify(events.ProcessStateStoppedEvent(proc, ProcessStates.STOPPING))
        assert received == ["ProcessStateStartingEvent", "ProcessStateRunningEvent", "ProcessStateStoppedEvent"]

        events.unsubscribe(events.ProcessStateEvent, handler)
        events.notify(events.ProcessStateRunningEvent(proc, ProcessStates.STARTING))
        assert len(received) == 3  # no new event

        # Supervisor state change events
        sup_received = []
        events.subscribe(events.SupervisorStateChangeEvent, lambda ev: sup_received.append(ev))
        events.notify(events.SupervisorRunningEvent())
        events.notify(events.SupervisorStoppingEvent())
        assert len(sup_received) == 2
        assert isinstance(sup_received[0], events.SupervisorRunningEvent)

        events.clear()


# ============================================================
# 3. XML-RPC Interface — queries + faults + dynamic groups + batch ops
# ============================================================


class TestRPCInterface:
    """Tests for RPC: queries, fault codes, dynamic group management, batch operations."""

    def _make_rpc(self, process_states=None):
        from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
        options = _MockOptions()
        pc1 = _MockPConfig(options, "foo", "/bin/foo", priority=1)
        pc2 = _MockPConfig(options, "bar", "/bin/bar", priority=2)
        sup = _make_populated_supervisor(options, "grp", pc1, pc2)
        if process_states:
            for name, state in process_states.items():
                _set_procattr(sup, "grp", name, "state", state)
        return SupervisorNamespaceRPCInterface(sup), sup

    def test_query_methods_and_process_info(self):
        """getAPIVersion, getState, getPID, getProcessInfo, getAllProcessInfo."""
        from supervisor.states import ProcessStates
        rpc, sup = self._make_rpc({"foo": ProcessStates.RUNNING})
        _set_procattr(sup, "grp", "foo", "pid", 1234)

        assert rpc.getAPIVersion() == "3.0"
        assert rpc.getState()["statename"] == "RUNNING"
        assert rpc.getPID() == os.getpid()

        info = rpc.getProcessInfo("grp:foo")
        assert info["name"] == "foo"
        assert info["group"] == "grp"
        assert info["state"] == ProcessStates.RUNNING
        assert info["statename"] == "RUNNING"
        assert info["pid"] == 1234

        all_info = rpc.getAllProcessInfo()
        assert len(all_info) == 2
        assert {i["name"] for i in all_info} == {"foo", "bar"}

    def test_start_stop_faults(self):
        """ALREADY_STARTED on running; NOT_RUNNING on stopped; BAD_NAME on unknown; SHUTDOWN_STATE on shutdown."""
        from supervisor.states import ProcessStates, SupervisorStates
        from supervisor.xmlrpc import Faults, RPCError

        rpc, sup = self._make_rpc({"foo": ProcessStates.RUNNING, "bar": ProcessStates.STOPPED})

        with pytest.raises(RPCError) as exc:
            rpc.startProcess("grp:foo")
        assert exc.value.code == Faults.ALREADY_STARTED

        with pytest.raises(RPCError) as exc:
            rpc.stopProcess("grp:bar")
        assert exc.value.code == Faults.NOT_RUNNING

        with pytest.raises(RPCError) as exc:
            rpc.getProcessInfo("nonexistent:proc")
        assert exc.value.code == Faults.BAD_NAME

        with pytest.raises(RPCError) as exc:
            rpc.signalProcess("grp:nonexistent", "TERM")
        assert exc.value.code == Faults.BAD_NAME

        sup.options.mood = SupervisorStates.SHUTDOWN
        with pytest.raises(RPCError) as exc:
            rpc.getAPIVersion()
        assert exc.value.code == Faults.SHUTDOWN_STATE

    def test_stop_all_processes(self):
        """stopAllProcesses dispatch returns a per-process SUCCESS status struct for each process."""
        from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
        from supervisor.states import ProcessStates
        from supervisor.xmlrpc import Faults

        options = _MockOptions()
        pc1 = _MockPConfig(options, "web", "/bin/web")
        pc2 = _MockPConfig(options, "worker", "/bin/worker")
        sup = _make_populated_supervisor(options, "app", pc1, pc2)
        _set_procattr(sup, "app", "web", "state", ProcessStates.RUNNING)
        _set_procattr(sup, "app", "worker", "state", ProcessStates.RUNNING)

        rpc = SupervisorNamespaceRPCInterface(sup)
        result = rpc.stopAllProcesses(wait=False)
        # The result is a deferred callable; drive it to completion.
        if callable(result):
            from supervisor.http import NOT_DONE_YET
            for _ in range(100):
                r = result()
                if r is not NOT_DONE_YET:
                    result = r
                    break

        # The dispatch produces one status struct per process, each reporting SUCCESS/OK.
        assert isinstance(result, list)
        by_name = {struct["name"]: struct for struct in result}
        assert set(by_name) == {"web", "worker"}
        for struct in by_name.values():
            assert struct["group"] == "app"
            assert struct["status"] == Faults.SUCCESS
            assert struct["description"] == "OK"


# ============================================================
# 4. ReadLog (public RPC surface)
# ============================================================


class TestReadLog:
    """Tests for the public readLog RPC method's offset/length log-reading contract."""

    def _assert_readlog_contract(self, rpc):
        """Assert the section-4 readLog contract against an RPC interface bound to a 16-byte log."""
        from supervisor.xmlrpc import Faults, RPCError

        # Read all: offset 0, length 0 returns the whole file.
        assert rpc.readLog(0, 0) == "0123456789abcdef"

        # Read a middle slice: length bytes starting at offset.
        assert rpc.readLog(5, 5) == "56789"

        # Read from the tail: a negative offset returns that many bytes from the end.
        assert rpc.readLog(-4, 0) == "cdef"

        # A negative offset with a non-zero length is invalid: BAD_ARGUMENTS fault.
        with pytest.raises(RPCError) as exc:
            rpc.readLog(-4, 5)
        assert exc.value.code == Faults.BAD_ARGUMENTS

    def test_read_log_with_offset_and_length(self):
        """rpc.readLog reads the main log with offset/length slicing and faults on bad arguments."""
        import shutil

        from supervisor.options import ServerOptions
        from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
        from supervisor.states import SupervisorStates

        # Point the daemon's main log at a temp file, then exercise readLog through the public
        # RPC surface (rather than the internal readFile helper).
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
            f.write("0123456789abcdef")
            tmppath = f.name

        try:
            options = _MockOptions()
            options.logfile = tmppath
            self._assert_readlog_contract(
                SupervisorNamespaceRPCInterface(_MockSupervisor(options, {})))
        finally:
            os.unlink(tmppath)

        # The same contract must hold with a real ServerOptions realized from a config whose
        # [supervisord] logfile names the log (sections 8 and 12), i.e. when the daemon's own
        # collaborators — not a stub — do the reading.
        tmpdir = tempfile.mkdtemp()
        try:
            conf_path = os.path.join(tmpdir, "supervisord.conf")
            with open(conf_path, "w") as f:
                f.write("[supervisord]\nlogfile=%s\n" % os.path.join(tmpdir, "supervisord.log"))

            options = ServerOptions()
            options.configfile = conf_path
            options.realize(args=[], doc="test")
            options.mood = SupervisorStates.RUNNING
            # Fill the log after realize() so config processing cannot perturb the content.
            with open(options.logfile, "w") as f:
                f.write("0123456789abcdef")

            self._assert_readlog_contract(
                SupervisorNamespaceRPCInterface(_MockSupervisor(options, {})))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 5. Data Types
# ============================================================


class TestDataTypes:
    """Tests for supervisor.datatypes type converters."""

    def test_all_type_converters(self):
        """All datatypes converters: boolean, byte_size, signal_number, list_of_exitcodes, auto_restart, inet_address, logging_level, dict_of_key_value_pairs."""
        from supervisor.datatypes import (
            RestartUnconditionally, RestartWhenExitUnexpected,
            auto_restart, boolean, byte_size, dict_of_key_value_pairs,
            inet_address, list_of_exitcodes, list_of_strings,
            logging_level, signal_number,
        )

        assert boolean("true") is True
        assert boolean("yes") is True
        assert boolean("false") is False
        assert boolean("0") is False

        assert byte_size("1KB") == 1024
        assert byte_size("1MB") == 1024 * 1024

        assert signal_number("TERM") == signal.SIGTERM
        assert signal_number("SIGTERM") == signal.SIGTERM
        assert signal_number("9") == 9

        assert list_of_exitcodes("0,1,2") == [0, 1, 2]
        assert list_of_strings("a,b,c") == ["a", "b", "c"]

        assert auto_restart("true") is RestartUnconditionally
        assert auto_restart("unexpected") is RestartWhenExitUnexpected
        assert auto_restart("false") is False

        host, port = inet_address("127.0.0.1:9001")
        assert host == "127.0.0.1"
        assert port == 9001
        host2, port2 = inet_address(":9001")
        assert port2 == 9001

        import logging
        assert logging_level("info") == logging.INFO
        assert logging_level("debug") == logging.DEBUG
        assert logging_level("error") == logging.ERROR

        result = dict_of_key_value_pairs("FOO=bar,BAZ=qux")
        assert result["FOO"] == "bar"
        assert result["BAZ"] == "qux"
        assert dict_of_key_value_pairs("") == {}


# ============================================================
# 6. Process Group
# ============================================================


class TestProcessGroup:
    """Tests for ProcessGroup with real Subprocess instances."""

    def test_process_group_stop_all(self):
        """ProcessGroup.stop_all() sends stop to running processes."""
        from supervisor.options import ProcessGroupConfig
        from supervisor.states import ProcessStates

        options = _MockOptions()
        pc1 = _MockPConfig(options, "p1", "/bin/p1")
        pc2 = _MockPConfig(options, "p2", "/bin/p2")
        gconfig = ProcessGroupConfig(options, "grp", 999, [pc1, pc2])
        group = gconfig.make_group()

        for proc in group.processes.values():
            proc.state = ProcessStates.RUNNING
            proc.pid = 123

        group.stop_all()
        for proc in group.processes.values():
            assert proc.state in (ProcessStates.STOPPING, ProcessStates.STOPPED)


# ============================================================
# 7. Child Utilities
# ============================================================


class TestChildUtils:
    """Tests for childutils event listener protocol helpers."""

    def test_headers_eventdata_and_protocols(self):
        """get_headers, eventdata parsing, and EventListenerProtocol/ProcessCommunicationsProtocol tokens."""
        from supervisor.childutils import (
            EventListenerProtocol, ProcessCommunicationsProtocol,
            eventdata, get_headers,
        )
        from supervisor.events import ProcessCommunicationEvent

        # get_headers
        headers = get_headers("ver:3.0 server:supervisor serial:21 eventname:TICK_60 len:0")
        assert headers["ver"] == "3.0"
        assert headers["eventname"] == "TICK_60"

        # eventdata
        payload = "processname:foo groupname:bar pid:123\nextra data"
        hdrs, data = eventdata(payload)
        assert hdrs["processname"] == "foo"
        assert data == "extra data"

        # EventListenerProtocol
        proto = EventListenerProtocol()
        out = io.StringIO()
        proto.ready(out)
        assert "READY" in out.getvalue()

        out = io.StringIO()
        proto.ok(out)
        assert "RESULT" in out.getvalue() and "OK" in out.getvalue()

        out = io.StringIO()
        proto.fail(out)
        assert "RESULT" in out.getvalue() and "FAIL" in out.getvalue()

        # ProcessCommunicationsProtocol
        pproto = ProcessCommunicationsProtocol()
        bout = io.BytesIO()
        pproto.send(b"hello world", bout)
        written = bout.getvalue()
        assert ProcessCommunicationEvent.BEGIN_TOKEN in written
        assert ProcessCommunicationEvent.END_TOKEN in written
        assert b"hello world" in written


# ============================================================
# 8. Config Parsing
# ============================================================


class TestConfigParsing:
    """Tests for parsing [program:x] config sections into ProcessConfig."""

    def test_parse_program_section(self):
        """ServerOptions processes a [program:x] section into a ProcessGroupConfig."""
        from supervisor.options import ServerOptions

        # Create a minimal config file
        config_text = """\
[supervisord]
logfile=/tmp/supervisord.log

[program:myworker]
command=/bin/sleep 100
autostart=true
autorestart=unexpected
startsecs=5
startretries=3
stopsignal=TERM
stopwaitsecs=10
exitcodes=0,2
priority=100
redirect_stderr=false
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            f.write(config_text)
            config_path = f.name

        try:
            options = ServerOptions()
            options.configfile = config_path
            options.realize(args=[], doc="test")

            # Should have parsed at least one process group config
            assert len(options.process_group_configs) == 1

            # Find our program config
            found = False
            for gc in options.process_group_configs:
                for pc in gc.process_configs:
                    if pc.name == "myworker":
                        found = True
                        assert pc.command == "/bin/sleep 100"
                        assert pc.autostart is True
                        assert pc.startsecs == 5
                        assert pc.startretries == 3
                        assert pc.stopsignal == signal.SIGTERM
                        assert pc.stopwaitsecs == 10
                        assert pc.exitcodes == [0, 2]
                        assert pc.priority == 100
                        assert pc.redirect_stderr is False
            assert found, "myworker program config not found"
        finally:
            os.unlink(config_path)


# ============================================================
# 9. Complex Integration
# ============================================================


class TestComplexIntegration:
    """Tests for the namespec helpers and RPCError text formatting."""

    def test_namespec_resolution_through_rpc_and_rpcerror_text(self):
        """Namespec forms resolve through the public RPC surface; RPCError.text names the fault."""
        from supervisor.rpcinterface import SupervisorNamespaceRPCInterface
        from supervisor.xmlrpc import Faults, RPCError

        # A supervisor with a multi-process group ("myapp") and a collapse-case group whose name
        # equals its single process ("web"). Namespec behavior is exercised only via RPC methods.
        options = _MockOptions()
        web = _MockPConfig(options, "web", "/bin/web")
        worker = _MockPConfig(options, "worker", "/bin/worker")
        single = _MockPConfig(options, "web", "/bin/web")
        myapp = _make_populated_supervisor(options, "myapp", web, worker)
        web_group = _make_populated_supervisor(options, "web", single)
        sup = _MockSupervisor(options, {**myapp.process_groups, **web_group.process_groups})
        rpc = SupervisorNamespaceRPCInterface(sup)

        # The "group:name" namespec resolves to the right process.
        info = rpc.getProcessInfo("myapp:worker")
        assert info["group"] == "myapp" and info["name"] == "worker"

        # A bare name (no colon) resolves when the group and process share that name.
        info = rpc.getProcessInfo("web")
        assert info["group"] == "web" and info["name"] == "web"

        # getAllProcessInfo iterates every group/process across the daemon.
        all_info = {(i["group"], i["name"]) for i in rpc.getAllProcessInfo()}
        assert all_info == {("myapp", "web"), ("myapp", "worker"), ("web", "web")}

        # A whole-group selector ("group:") is not a single process: getProcessInfo rejects it.
        with pytest.raises(RPCError) as exc:
            rpc.getProcessInfo("myapp:")
        assert exc.value.code == Faults.BAD_NAME

        # RPCError carries the numeric code and a .text that embeds the fault's name.
        err = RPCError(Faults.BAD_NAME, "test")
        assert err.code == Faults.BAD_NAME
        assert "BAD_NAME" in err.text


# ============================================================
# 10. Dispatchers
# ============================================================


class TestDispatchers:
    """Tests for the section-9 POutputDispatcher / PInputDispatcher surface."""

    def test_dispatcher_read_write_polarity_and_close(self):
        """An output dispatcher only reads (until closed); an input dispatcher writes only when buffered."""
        from supervisor import events
        from supervisor.dispatchers import PInputDispatcher, POutputDispatcher

        events.clear()
        options = _MockOptions()
        read_fd, write_fd = os.pipe()
        try:
            # An output dispatcher pulls a child's stdout: it is readable, never writable, and
            # starts out open; close() marks it closed.
            out_config = _MockPConfig(options, "proc", "/bin/proc",
                                      stdout_logfile=None, stdout_capture_maxbytes=0)
            out = POutputDispatcher(_MockProcess(out_config),
                                    events.ProcessCommunicationStdoutEvent, read_fd)
            assert out.readable()
            assert not out.writable()
            assert not out.closed

            out.close()
            assert out.closed

            # An input dispatcher pushes to a child's stdin: it is never readable, and becomes
            # writable only once its input_buffer holds data to send.
            inp = PInputDispatcher(_MockProcess(_MockPConfig(options, "proc", "/bin/proc")),
                                   "stdin", write_fd)
            assert not inp.readable()
            assert not inp.writable()

            inp.input_buffer = b"some data"
            assert inp.writable()
        finally:
            for fd in (read_fd, write_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
            events.clear()


# ============================================================
# 11. Subprocess Spawn/Stop with Mocks
# ============================================================


class TestSubprocessOperations:
    """Tests for Subprocess spawn/stop using DummyOptions mock pattern."""

    def test_spawn_running_and_bad_filename(self):
        """spawn() returns None when already running; spawn() with bad filename goes to BACKOFF with spawnerr."""
        from supervisor import events
        from supervisor.process import Subprocess
        from supervisor.states import ProcessStates

        events.clear()
        options = _MockOptions()

        # Already running → None
        config = _MockPConfig(options, "proc", "/bin/proc")
        proc = Subprocess(config)
        proc.pid = 123
        proc.state = ProcessStates.RUNNING
        assert proc.spawn() is None

        # Bad filename → BACKOFF
        fired = []
        events.subscribe(events.ProcessStateEvent, lambda ev: fired.append(ev))
        config2 = _MockPConfig(options, "bad", "/nonexistent/bad_file")
        proc2 = Subprocess(config2)
        proc2.state = ProcessStates.EXITED
        result = proc2.spawn()
        assert result is None
        assert proc2.spawnerr is not None
        assert proc2.state == ProcessStates.BACKOFF
        events.clear()

    def test_stop_sets_administrative_stop(self, monkeypatch):
        """Subprocess.stop() on a RUNNING process transitions to STOPPING and sends the kill signal."""
        from supervisor import events
        from supervisor.process import Subprocess
        from supervisor.states import ProcessStates

        events.clear()
        options = _MockOptions()
        config = _MockPConfig(options, "proc", "/bin/proc")
        proc = Subprocess(config)
        # Simulate running process
        proc.state = ProcessStates.RUNNING
        proc.pid = 999

        # Capture the signal at the OS boundary so a faithful implementation that calls
        # os.kill(pid, sig) directly is observed too — the spec only requires that the configured
        # stop signal reach the process's pid, not which collaborator delivers it.
        os_kills = {}
        monkeypatch.setattr(os, "kill", lambda pid, sig: os_kills.__setitem__(pid, sig))

        proc.stop()
        # stop() requests an administrative stop: the process transitions to STOPPING (the
        # documented public effect) and the configured stop signal is delivered to the running
        # process's pid. Accept delivery via either OS boundary the spec leaves open — a direct
        # os.kill or an options-mediated kill — without pinning the internal delivery seam.
        assert proc.state == ProcessStates.STOPPING
        assert os_kills.get(999) == signal.SIGTERM or options.kills.get(999) == signal.SIGTERM
        events.clear()


# ============================================================
# 12. confecho CLI
# ============================================================


class TestConfechoCLI:
    """Tests for supervisor confecho utility via subprocess."""

    def test_confecho_output_roundtrips_through_config_parser(self):
        """confecho emits a sample config that round-trips through ServerOptions with a [supervisord] logfile."""
        import subprocess

        from supervisor.options import ServerOptions

        result = subprocess.run(
            ["python3", "-c", "from supervisor.confecho import main; main()"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        sample = result.stdout
        assert "[supervisord]" in sample

        # The emitted sample must be a valid, round-trippable config: feed it back into the real
        # INI parser and confirm it parses without error into the documented [supervisord] section,
        # rather than just grepping for substrings in a static file dump. The spec only guarantees a
        # [supervisord] section with a logfile setting, so that is all this test pins.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(sample)
            conf_path = f.name
        try:
            options = ServerOptions()
            options.configfile = conf_path
            options.realize(args=[], doc="test")

            # The [supervisord] logfile setting survives the round-trip (path normalized to absolute).
            assert options.logfile
            assert os.path.isabs(options.logfile)
        finally:
            os.unlink(conf_path)


# ============================================================
# 13. supervisord + supervisorctl CLI Integration
# ============================================================


class TestSupervisordCLI:
    """Tests for supervisord daemon and supervisorctl client via subprocess."""

    def _write_config(self, tmpdir, programs=None, logfiles=None):
        """Write a minimal supervisord config file and return its path.

        `logfiles` optionally maps a program name to an explicit `stdout_logfile` path so a test
        that reads captured stdout back (e.g. via `tail`) pins the capture target the spec
        documents (`process.config.stdout_logfile`) instead of relying on an unset logfile.
        """
        if programs is None:
            programs = {"test_worker": "sleep 3600"}
        logfiles = logfiles or {}

        prog_sections = ""
        for name, cmd in programs.items():
            logfile_line = f"stdout_logfile={logfiles[name]}\n" if name in logfiles else ""
            prog_sections += f"""
[program:{name}]
command={cmd}
autostart=true
autorestart=false
{logfile_line}"""
        conf = f"""
[supervisord]
nodaemon=false
logfile={tmpdir}/supervisord.log
pidfile={tmpdir}/supervisord.pid

[unix_http_server]
file={tmpdir}/supervisor.sock

[supervisorctl]
serverurl=unix://{tmpdir}/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface
{prog_sections}
"""
        conf_path = os.path.join(tmpdir, "supervisord.conf")
        with open(conf_path, "w") as f:
            f.write(conf)
        return conf_path

    def _start_supervisord(self, conf_path):
        """Start supervisord and wait for it to be ready."""
        import subprocess
        import time

        proc = subprocess.Popen(
            ["supervisord", "-c", conf_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(2)  # wait for startup
        return proc

    def _supervisorctl(self, conf_path, *args):
        """Run a supervisorctl command and return the result."""
        import subprocess

        return subprocess.run(
            ["supervisorctl", "-c", conf_path] + list(args),
            capture_output=True, text=True, timeout=10,
        )

    def test_supervisord_start_status_stop_shutdown(self):
        """Start supervisord, check status, stop a process, restart it, then shutdown."""
        import time

        tmpdir = tempfile.mkdtemp()
        try:
            conf_path = self._write_config(tmpdir, {
                "worker1": "sleep 3600",
                "worker2": "sleep 3600",
            })

            # Start supervisord
            self._start_supervisord(conf_path)

            # Check status — both workers should be RUNNING
            result = self._supervisorctl(conf_path, "status")
            assert result.returncode == 0
            assert "worker1" in result.stdout
            assert "worker2" in result.stdout
            assert "RUNNING" in result.stdout

            # Stop worker1
            result = self._supervisorctl(conf_path, "stop", "worker1")
            assert result.returncode == 0
            assert "stopped" in result.stdout.lower()

            # Check status — worker1 should be STOPPED
            result = self._supervisorctl(conf_path, "status")
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if "worker1" in line:
                    assert "STOPPED" in line
                if "worker2" in line:
                    assert "RUNNING" in line

            # Restart worker1
            result = self._supervisorctl(conf_path, "start", "worker1")
            assert result.returncode == 0
            time.sleep(1)

            result = self._supervisorctl(conf_path, "status")
            for line in result.stdout.strip().split("\n"):
                if "worker1" in line:
                    assert "RUNNING" in line

            # Shutdown
            result = self._supervisorctl(conf_path, "shutdown")
            assert result.returncode == 0
        finally:
            # Ensure cleanup
            import subprocess
            subprocess.run(["supervisorctl", "-c", conf_path, "shutdown"],
                           capture_output=True, timeout=5)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_supervisorctl_extended_commands_and_help(self):
        """Test supervisorctl tail, restart, pid, version, --help — asserting real command output."""
        import re
        import time
        import subprocess as sp

        # --help (no daemon needed)
        result = sp.run(["supervisorctl", "--help"],
                        capture_output=True, text=True, timeout=10)
        assert result.returncode == 0
        assert "supervisorctl" in result.stdout.lower()

        tmpdir = tempfile.mkdtemp()
        try:
            # The process writes a known marker to stdout so `tail` has real content to return.
            # Point its stdout at an explicit stdout_logfile (the spec-documented capture target,
            # process.config.stdout_logfile) so `tail` reads the captured stdout back from a
            # configured path rather than depending on an unset (AUTO) logfile.
            marker = "TAILMARKER_8f3a"
            echo_log = os.path.join(tmpdir, "echo_proc.log")
            conf_path = self._write_config(
                tmpdir,
                {"echo_proc": f"bash -c 'echo {marker}; sleep 3600'"},
                logfiles={"echo_proc": echo_log},
            )
            self._start_supervisord(conf_path)
            time.sleep(1)

            # restart stops then starts the process: output names the process for both phases.
            result = self._supervisorctl(conf_path, "restart", "echo_proc")
            assert result.returncode == 0
            assert "echo_proc: stopped" in result.stdout
            assert "echo_proc: started" in result.stdout
            time.sleep(1)

            # tail returns the process's captured stdout, which must contain the marker it printed.
            for _ in range(5):
                result = self._supervisorctl(conf_path, "tail", "echo_proc")
                if result.returncode == 0 and marker in result.stdout:
                    break
                time.sleep(1)
            assert result.returncode == 0
            assert marker in result.stdout

            # pid prints just the supervisord PID integer.
            result = self._supervisorctl(conf_path, "pid")
            assert result.returncode == 0
            assert result.stdout.strip().isdigit()

            # version prints the daemon's version string (e.g. "4.x.y"), not nothing.
            result = self._supervisorctl(conf_path, "version")
            assert result.returncode == 0
            assert re.search(r"\d+\.\d+", result.stdout)

            self._supervisorctl(conf_path, "shutdown")
        finally:
            sp.run(["supervisorctl", "-c", conf_path, "shutdown"],
                   capture_output=True, timeout=5)
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_supervisord_with_inet_http_server(self):
        """supervisord with inet_http_server allows HTTP access to XML-RPC and web UI."""
        import time
        import urllib.error
        import urllib.request

        tmpdir = tempfile.mkdtemp()
        conf = f"""
[supervisord]
nodaemon=false
logfile={tmpdir}/supervisord.log
pidfile={tmpdir}/supervisord.pid

[inet_http_server]
port=127.0.0.1:19876

[supervisorctl]
serverurl=http://127.0.0.1:19876

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:http_test]
command=sleep 3600
autostart=true
"""
        conf_path = os.path.join(tmpdir, "sup.conf")
        with open(conf_path, "w") as f:
            f.write(conf)

        try:
            self._start_supervisord(conf_path)
            time.sleep(1)

            # Web UI should respond — retry up to 3 times for startup timing.
            # ProxyHandler({}) keeps the probe on loopback: the default opener honours any ambient
            # http_proxy in the container and would never contact the daemon under test.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(3):
                try:
                    resp = opener.open("http://127.0.0.1:19876", timeout=5)
                    html = resp.read().decode()
                    assert resp.status == 200
                    assert "http_test" in html
                    break
                except (urllib.error.URLError, OSError):
                    if attempt == 2:
                        raise
                    time.sleep(1)

            # supervisorctl via HTTP
            import subprocess
            result = subprocess.run(
                ["supervisorctl", "-c", conf_path, "status"],
                capture_output=True, text=True, timeout=10,
            )
            assert "http_test" in result.stdout
            assert "RUNNING" in result.stdout

            subprocess.run(["supervisorctl", "-c", conf_path, "shutdown"],
                           capture_output=True, timeout=5)
        finally:
            import subprocess, shutil
            subprocess.run(["supervisorctl", "-c", conf_path, "shutdown"],
                           capture_output=True, timeout=5)
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_add_remove_process_group(self):
        """Remove and re-add a process group at runtime via supervisorctl; bad/duplicate names report errors."""
        import time

        tmpdir = tempfile.mkdtemp()
        # autostart=false so the group is STOPPED and can be removed without STILL_RUNNING.
        conf = f"""
[supervisord]
nodaemon=false
logfile={tmpdir}/supervisord.log
pidfile={tmpdir}/supervisord.pid

[unix_http_server]
file={tmpdir}/supervisor.sock

[supervisorctl]
serverurl=unix://{tmpdir}/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[program:grp_proc]
command=sleep 3600
autostart=false
autorestart=false
"""
        conf_path = os.path.join(tmpdir, "supervisord.conf")
        with open(conf_path, "w") as f:
            f.write(conf)

        try:
            self._start_supervisord(conf_path)

            # Group is present at startup.
            result = self._supervisorctl(conf_path, "status")
            assert "grp_proc" in result.stdout

            # Remove the (stopped) group through the real daemon.
            result = self._supervisorctl(conf_path, "remove", "grp_proc")
            assert "removed process group" in result.stdout
            result = self._supervisorctl(conf_path, "status")
            assert "grp_proc" not in result.stdout

            # Re-add it from the loaded config.
            result = self._supervisorctl(conf_path, "add", "grp_proc")
            assert "added process group" in result.stdout
            time.sleep(1)
            result = self._supervisorctl(conf_path, "status")
            assert "grp_proc" in result.stdout

            # Adding an already-active group reports an error (ALREADY_ADDED dispatch).
            result = self._supervisorctl(conf_path, "add", "grp_proc")
            assert "ERROR" in result.stdout and "already" in result.stdout.lower()

            # Removing an unknown group reports a bad-name error (BAD_NAME dispatch).
            result = self._supervisorctl(conf_path, "remove", "no_such_grp")
            assert "no such process/group" in result.stdout

            self._supervisorctl(conf_path, "shutdown")
        finally:
            import subprocess, shutil
            subprocess.run(["supervisorctl", "-c", conf_path, "shutdown"],
                           capture_output=True, timeout=5)
            shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 15. Loggers — BoundIO and Logger
# ============================================================


class TestLoggers:
    """Tests for supervisor.loggers: Logger with level filtering and BoundIO buffer."""

    def test_logger_level_filtering_and_boundio(self):
        """Logger filters by level; BoundIO buffers writes up to maxbytes."""
        from supervisor.loggers import BoundIO, Logger, LevelsByName, handle_file

        # Logger with file handler and level filtering
        tmplog = tempfile.mktemp(suffix=".log")
        try:
            logger = Logger(level=LevelsByName.INFO)
            handle_file(logger, tmplog, "%(message)s")

            logger.info("info message")
            logger.warn("warn message")
            logger.debug("debug should be filtered")

            logger.close()
            with open(tmplog) as f:
                content = f.read()
            assert "info message" in content
            assert "warn message" in content
            assert "debug should be filtered" not in content
        finally:
            if os.path.exists(tmplog):
                os.unlink(tmplog)

        # BoundIO
        bio = BoundIO(1024)
        bio.write(b"hello ")
        bio.write(b"world")
        assert bio.getvalue() == b"hello world"
        bio.close()


# ============================================================
# 16. PidProxy
# ============================================================


class TestPidProxy:
    """Tests for the PidProxy class."""

    def test_pidproxy_proxies_signal_to_pidfile(self):
        """PidProxy parses its argv and proxies a received signal to the PID named in the pidfile."""
        import subprocess

        from supervisor.pidproxy import PidProxy

        # Constructor splits argv into pidfile / command / command args.
        args = ["pidproxy.py", "/var/run/test.pid", "/usr/bin/myapp", "-f", "--verbose"]
        pp = PidProxy(args)
        assert pp.pidfile == "/var/run/test.pid"
        assert pp.cmdargs == ["/usr/bin/myapp", "-f", "--verbose"]
        assert pp.abscmd == "/usr/bin/myapp"

        # Drive the actual signal-proxying behavior: point the pidfile at a real running
        # child, then deliver a signal to the proxy and assert it is forwarded to that PID.
        # Use SIGUSR1 (default disposition terminates the child) so the proxy does not exit
        # the test process — passtochild() only sys.exit()s for SIGTERM/SIGINT/SIGQUIT.
        child = subprocess.Popen(["sleep", "30"])
        pidfile_path = tempfile.mktemp(suffix=".pid")
        with open(pidfile_path, "w") as f:
            f.write(str(child.pid))
        try:
            proxy = PidProxy(["pidproxy.py", pidfile_path, "/bin/sleep", "30"])
            proxy.passtochild(signal.SIGUSR1, None)
            # The signal must have reached the real child, killing it.
            assert child.wait(timeout=5) == -signal.SIGUSR1
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            if os.path.exists(pidfile_path):
                os.unlink(pidfile_path)

        # A missing/unreadable pidfile is handled gracefully (no exception raised).
        missing = PidProxy(["pidproxy.py", "/nonexistent/pidproxy.pid", "/bin/true"])
        missing.passtochild(signal.SIGUSR1, None)
