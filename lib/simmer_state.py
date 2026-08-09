#!/usr/bin/env python
"""Active simmer run registration and status display helpers."""

import datetime
import json
import math
import os
import shlex
import socket
import subprocess
import threading
import time
import uuid

STATE_SCHEMA_VERSION = 1
STATE_DIRECTORY = os.path.join(".simmer", "runs")
STATUS_SEPARATOR = "-" * 64
ACTIVE_LSF_STATES = {
    "PEND",
    "PROV",
    "PSUSP",
    "RUN",
    "SSUSP",
    "UNKWN",
    "USUSP",
    "WAIT",
}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _safe_int(value, default=0):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _safe_float(value, default=0.0):
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _safe_identifier(value):
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return str(value)
    return None


def state_directory(project_dir):
    return os.path.join(project_dir, STATE_DIRECTORY)


def state_path(project_dir, run_id):
    return os.path.join(state_directory(project_dir), "{}.json".format(run_id))


def _timestamp(epoch_seconds=None):
    when = datetime.datetime.fromtimestamp(epoch_seconds) if epoch_seconds is not None else datetime.datetime.now()
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _display_argv(argv):
    if not argv:
        return ["simmer"]
    display_argv = [str(argument) for argument in argv]
    display_argv[0] = os.path.basename(display_argv[0]) or display_argv[0]
    return display_argv


def format_command(argv):
    return " ".join(shlex.quote(argument) for argument in _display_argv(argv))


def capture_lsf_context(environment=None, hostname=None, interactive=None):
    environment = os.environ if environment is None else environment
    hostname = hostname or socket.gethostname()
    interactive = bool(os.isatty(0)) if interactive is None else bool(interactive)
    job_id = str(environment.get("LSB_JOBID") or "").strip()
    job_index = str(environment.get("LSB_JOBINDEX") or "").strip()
    display_job_id = job_id
    if job_id and job_index not in ("", "0"):
        display_job_id = "{}[{}]".format(job_id, job_index)
    return {
        "job_id": job_id or None,
        "job_index": job_index or None,
        "display_job_id": display_job_id or None,
        "queue": str(environment.get("LSB_QUEUE") or "").strip() or None,
        "host": hostname,
        "submit_host": str(environment.get("LSB_SUB_HOST") or "").strip() or None,
        "interactive": interactive,
    }


def format_submission_command(argv, lsf=None, environment=None):
    environment = os.environ if environment is None else environment
    supplied_command = str(environment.get("SIMMER_SUBMIT_CMD") or "").strip()
    if supplied_command:
        return supplied_command
    lsf = lsf or capture_lsf_context(environment=environment)
    if not lsf.get("job_id"):
        return format_command(argv)
    command = ["bsub"]
    if lsf.get("interactive"):
        command.append("-I")
    if lsf.get("queue"):
        command.extend(["-q", lsf["queue"]])
    command.extend(_display_argv(argv))
    return " ".join(shlex.quote(argument) for argument in command)


def format_lsf_summary(lsf, include_bkill=False):
    if not isinstance(lsf, dict):
        return None
    job_id = lsf.get("display_job_id") or lsf.get("job_id")
    if not job_id:
        return None
    parts = ["job {}".format(job_id)]
    if lsf.get("queue"):
        parts.append("queue {}".format(lsf["queue"]))
    if lsf.get("host"):
        parts.append("host {}".format(lsf["host"]))
    if lsf.get("submit_host"):
        parts.append("submit {}".format(lsf["submit_host"]))
    if include_bkill:
        parts.append("bkill {}".format(shlex.quote(str(job_id))))
    return " | ".join(parts)


def _linux_process_start_time(process_id):
    try:
        with open("/proc/{}/stat".format(process_id), "r", encoding="ascii") as filep:
            return filep.read().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def _posix_process_exists(process_id):
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # EPERM still proves that the process exists. This matters when a
        # shared checkout contains active runs owned by another user.
        return True
    except (OSError, ValueError):
        return False
    return True


def _windows_process_exists(process_id):
    """Query a process without using os.kill(pid, 0), which is destructive on Windows."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, process_id)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            # A transient query failure is not evidence that the process is
            # gone, so preserve its state file for a later status check.
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_exists(process_id, platform_name=None):
    if (os.name if platform_name is None else platform_name) == "nt":
        return _windows_process_exists(process_id)
    return _posix_process_exists(process_id)


def _write_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = "{}.{}.{}.tmp".format(path, os.getpid(), uuid.uuid4().hex)
    try:
        with open(temporary_path, "w", encoding="utf-8") as filep:
            json.dump(state, filep, indent=2)
            filep.write("\n")
        os.replace(temporary_path, path)
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass


class ActiveRun:
    """Own one active-run state file for the lifetime of a simmer process."""

    def __init__(self,
                 project_dir,
                 argv,
                 regression_dir=None,
                 logger=None,
                 environment=None,
                 hostname=None,
                 interactive=None,
                 process_id=None,
                 now=None):
        self.project_dir = os.path.abspath(project_dir)
        self.logger = logger
        self.run_id = uuid.uuid4().hex
        self._path = state_path(self.project_dir, self.run_id)
        self._lock = threading.Lock()
        self._stop_event = None
        self._watch_thread = None
        self._enabled = True
        now = time.time() if now is None else float(now)
        process_id = os.getpid() if process_id is None else int(process_id)
        lsf = capture_lsf_context(environment=environment, hostname=hostname, interactive=interactive)
        self._state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": _timestamp(now),
            "started_at_epoch": now,
            "updated_at": _timestamp(now),
            "command": format_submission_command(argv, lsf=lsf, environment=environment),
            "argv": list(argv),
            "project_dir": self.project_dir,
            "regression_dir": regression_dir,
            "status": "DISCOVERING",
            "planned_tests": 0,
            "finished_tests": 0,
            "active_tests": 0,
            "queued_tests": 0,
            "compile_logs": [],
            "result_log": None,
            "regression_log": None,
            "lsf": lsf,
            "process": {
                "pid": process_id,
                "host": lsf["host"],
                "start_time": _linux_process_start_time(process_id),
            },
        }
        self._publish()

    @property
    def path(self):
        return self._path

    def history_context(self):
        with self._lock:
            return {
                "run_id": self._state["run_id"],
                "started_at": self._state["started_at"],
                "command": self._state["command"],
                "lsf": dict(self._state["lsf"]),
            }

    def _warn(self, message, exc):
        if self.logger is not None:
            self.logger.warning(message, exc)

    def _publish(self):
        if not self._enabled:
            return
        try:
            _write_state(self._path, self._state)
        except OSError as exc:
            self._enabled = False
            self._warn("Could not update simmer active-run state: %s", exc)

    def update(self, **changes):
        with self._lock:
            if not self._enabled:
                return False
            changed = False
            for key, value in changes.items():
                if self._state.get(key) != value:
                    self._state[key] = value
                    changed = True
            if not changed:
                return False
            self._state["updated_at"] = _timestamp()
            self._publish()
            return True

    def start_watching(self, snapshot_fn, interval_seconds=5.0):
        self.stop_watching()
        stop_event = threading.Event()
        self._stop_event = stop_event

        def watch():
            while not stop_event.is_set():
                try:
                    snapshot = snapshot_fn()
                    if stop_event.is_set():
                        break
                    self.update(**snapshot)
                except Exception as exc: # Status reporting must never stop a simulation.
                    self._warn("Could not refresh simmer active-run state: %s", exc)
                stop_event.wait(interval_seconds)

        self._watch_thread = threading.Thread(name="simmer_active_state", target=watch, daemon=True)
        self._watch_thread.start()

    def stop_watching(self):
        stop_event = self._stop_event
        if stop_event is not None:
            stop_event.set()
        watch_thread = self._watch_thread
        if watch_thread is not None and threading.current_thread() is not watch_thread:
            watch_thread.join(timeout=2)
        self._watch_thread = None
        self._stop_event = None

    def close(self):
        self.stop_watching()
        with self._lock:
            self._enabled = False
            try:
                os.remove(self._path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                self._warn("Could not remove simmer active-run state: %s", exc)


def _load_state_files(project_dir):
    directory = state_directory(project_dir)
    try:
        entries = list(os.scandir(directory))
    except FileNotFoundError:
        return []
    states = []
    for entry in entries:
        if not entry.is_file() or not entry.name.endswith(".json"):
            continue
        try:
            with open(entry.path, "r", encoding="utf-8") as filep:
                state = json.load(filep)
            if not isinstance(state, dict) or not state.get("run_id"):
                continue
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        states.append((entry.path, state))
    return states


def _local_state_is_active(state, hostname):
    process = _mapping(state.get("process"))
    if process.get("host") != hostname:
        return None
    process_id = process.get("pid")
    if not isinstance(process_id, int) or process_id < 1 or not _process_exists(process_id):
        return False
    expected_start_time = process.get("start_time")
    if expected_start_time is None:
        return True
    return _linux_process_start_time(process_id) == expected_start_time


def _query_lsf_states(job_ids, runner=subprocess.run):
    if not job_ids:
        return {}
    try:
        result = runner(
            ["bjobs", "-a", "-noheader", *job_ids],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    states = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            states[fields[0]] = fields[2].upper()
    if result.returncode != 0 and not states:
        return None
    return states


def load_active_runs(project_dir, hostname=None, lsf_runner=subprocess.run):
    hostname = hostname or socket.gethostname()
    candidates = _load_state_files(project_dir)
    active = []
    remote_lsf_states = []
    for path, state in candidates:
        local_active = _local_state_is_active(state, hostname)
        if local_active is True:
            active.append((path, state))
        elif local_active is False:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            lsf = _mapping(state.get("lsf"))
            job_id = _safe_identifier(lsf.get("display_job_id"))
            if job_id:
                remote_lsf_states.append((path, state, job_id))
            else:
                active.append((path, state))

    lsf_states = _query_lsf_states([item[2] for item in remote_lsf_states], runner=lsf_runner)
    for path, state, job_id in remote_lsf_states:
        if lsf_states is None or lsf_states.get(job_id) in ACTIVE_LSF_STATES:
            active.append((path, state))
            continue
        try:
            os.remove(path)
        except OSError:
            pass
    return [
        state for _, state in sorted(
            active,
            key=lambda item: (
                _safe_float(item[1].get("started_at_epoch")),
                _safe_identifier(item[1].get("run_id")) or "",
            ),
        )
    ]


def _format_duration(duration_seconds):
    duration_seconds = max(0, _safe_int(duration_seconds))
    hours = duration_seconds // 3600
    minutes = (duration_seconds % 3600) // 60
    seconds = duration_seconds % 60
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)


def _format_heading(index, state, now):
    status = str(state.get("status") or "RUNNING")
    parts = ["[{}] {}".format(index, state.get("started_at") or "-"), status]
    planned = max(0, _safe_int(state.get("planned_tests")))
    finished = max(0, _safe_int(state.get("finished_tests")))
    active = max(0, _safe_int(state.get("active_tests")))
    queued = max(0, _safe_int(state.get("queued_tests")))
    if status in ("RUNNING", "PAUSED"):
        if planned > 1:
            parts.append("{}/{} finished, {} active, {} queued".format(finished, planned, active, queued))
        elif active:
            parts.append("{} active".format(active))
        elif planned == 1 and finished:
            parts.append("1/1 finished")
    elapsed = now - _safe_float(state.get("started_at_epoch"), now)
    return "  ".join(parts) + " | elapsed {}".format(_format_duration(elapsed))


def format_status(project_dir, now=None, hostname=None, lsf_runner=subprocess.run):
    states = load_active_runs(project_dir, hostname=hostname, lsf_runner=lsf_runner)
    if not states:
        return "No active simmer runs."
    now = time.time() if now is None else float(now)
    entries = []
    for index, state in zip(range(len(states), 0, -1), states):
        lines = [_format_heading(index, state, now)]
        lines.append("{:<12}{}".format("cmd:", state.get("command") or "-"))
        lsf_summary = format_lsf_summary(state.get("lsf"), include_bkill=True)
        if lsf_summary:
            lines.append("{:<12}{}".format("lsf:", lsf_summary))
        raw_compile_logs = state.get("compile_logs", [])
        compile_logs = [path for path in raw_compile_logs if path] if isinstance(raw_compile_logs, list) else []
        for log_index, compile_log in enumerate(compile_logs):
            label = "compile:" if log_index == 0 else ""
            lines.append("{:<12}{}".format(label, compile_log))
        if _safe_int(state.get("planned_tests")) > 1:
            if state.get("regression_log"):
                lines.append("{:<12}{}".format("regression:", state["regression_log"]))
        elif state.get("result_log"):
            lines.append("{:<12}{}".format("result:", state["result_log"]))
        entries.append("\n".join(lines))
    return "\n\n{}\n\n".format(STATUS_SEPARATOR).join(entries)


def print_status(project_dir):
    print(format_status(project_dir))
