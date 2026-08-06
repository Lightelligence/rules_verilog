#!/usr/bin/env python
"""Local simmer result history helpers."""

import datetime
import json
import math
import os
import shlex
import sys
import uuid
from contextlib import contextmanager

RESULTS_FILENAME = ".simmer_results.json"
SCHEMA_VERSION = 4
MAX_RUNS = 100
COLOR_GREEN = "\033[0;32m"
COLOR_RED = "\033[0;31m"
COLOR_YELLOW = "\033[0;33m"
COLOR_NC = "\033[0m"


def results_path(project_dir):
    return os.path.join(project_dir, RESULTS_FILENAME)


def format_command(argv):
    if not argv:
        return "simmer"
    display_argv = list(argv)
    display_argv[0] = os.path.basename(display_argv[0]) or display_argv[0]
    return " ".join(shlex.quote(str(arg)) for arg in display_argv)


def _timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run_id():
    return uuid.uuid4().hex


def _duration_seconds(value):
    if value is None:
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration < 0:
        return None
    return round(duration, 3)


def _record_job_interval(record, job, stopped_at=None):
    started_at = getattr(job, "job_start_time", None)
    finished_at = getattr(job, "job_stop_time", None) or stopped_at
    if started_at is None or finished_at is None:
        return
    try:
        started_at_s = started_at.timestamp()
        finished_at_s = finished_at.timestamp()
    except (AttributeError, OSError, OverflowError, ValueError):
        return
    if finished_at_s < started_at_s:
        return
    record["_elapsed_interval_s"] = [started_at_s, finished_at_s]


def _consume_elapsed_time(records):
    intervals = []
    for record in records:
        interval = record.pop("_elapsed_interval_s", None)
        if not isinstance(interval, list) or len(interval) != 2:
            continue
        start, stop = interval
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in interval):
            continue
        if stop >= start:
            intervals.append((start, stop))
    if not intervals:
        return None

    intervals.sort()
    elapsed_s = 0.0
    current_start, current_stop = intervals[0]
    for start, stop in intervals[1:]:
        if start <= current_stop:
            current_stop = max(current_stop, stop)
            continue
        elapsed_s += current_stop - current_start
        current_start, current_stop = start, stop
    elapsed_s += current_stop - current_start
    return round(elapsed_s, 3)


def _finalize_timing(run):
    timing = run.setdefault("timing", {})
    compile_elapsed_s = _consume_elapsed_time(run.get("compile", []))
    tests = run.get("tests", [])
    started_tests = [test for test in tests if test.get("simulation_started", True)]
    for test in tests:
        if not test.get("simulation_started", True):
            test.pop("_elapsed_interval_s", None)
    simulate_elapsed_s = _consume_elapsed_time(started_tests)
    if compile_elapsed_s is not None:
        timing["compile_elapsed_s"] = compile_elapsed_s
    else:
        timing.setdefault("compile_elapsed_s", None)
    if simulate_elapsed_s is not None:
        timing["simulate_elapsed_s"] = simulate_elapsed_s
    else:
        timing.setdefault("simulate_elapsed_s", None)

    compile_records = run.get("compile", [])
    cache_reused = bool(compile_records) and all(
        bool(record.get("metrics", {}).get("compile_cache_hit")) for record in compile_records)
    timing["compile_reused"] = bool(timing.get("compile_reused") or cache_reused)


def _collect_benches(run):
    benches = set(run.get("benches", []))
    for record in run.get("compile", []) + run.get("tests", []):
        bench = record.get("bench")
        if bench:
            benches.add(bench)
    return sorted(benches)


@contextmanager
def _store_lock(path):
    with open(path + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def create_run(argv, rcfg, planned_tests):
    options = getattr(rcfg, "options", None)
    return {
        "run_id": _run_id(),
        "started_at": _timestamp(),
        "finished_at": None,
        "command": format_command(argv),
        "argv": list(argv),
        "project_dir": rcfg.proj_dir,
        "regression_dir": rcfg.regression_dir,
        "planned_tests": planned_tests,
        "status": "RUNNING",
        "regression_log": None,
        "summary": {
            "passed": 0,
            "failed": 0,
            "interrupted": 0,
            "skipped": 0,
            "total": planned_tests,
        },
        "compile": [],
        "tests": [],
        "benches": [],
        "launch_failures": [],
        "timing": {
            "compile_elapsed_s": None,
            "simulate_elapsed_s": None,
            "compile_reused": bool(getattr(options, "no_compile", False)),
        },
    }


def _upsert_by_key(items, key, value):
    for index, item in enumerate(items):
        if item.get(key) == value.get(key):
            items[index] = value
            return
    items.append(value)


def record_compile_job(run, vcomp_job, status=None):
    if run is None:
        return
    compile_record = {
        "bench": vcomp_job.name,
        "vcomp_target": vcomp_job.bazel_vcomp_target,
        "status": status or vcomp_job.jobstatus.name,
        "compile_dir": vcomp_job.job_dir,
        "cmp_log": vcomp_job.log_path,
        "duration_s": _duration_seconds(getattr(vcomp_job, "duration_s", 0) or 0),
        "metrics": getattr(vcomp_job, "compile_metrics", {}),
        "error_message": getattr(vcomp_job, "error_message", None),
    }
    _record_job_interval(
        compile_record,
        vcomp_job,
        stopped_at=datetime.datetime.now() if status == "INTERRUPTED" else None,
    )
    _upsert_by_key(run["compile"], "vcomp_target", compile_record)


def record_test_job(run, test_job, waves_script=None, waves_path=None, status=None, simulation_started=None):
    if run is None:
        return
    waves_enabled = test_job.rcfg.options.waves is not None
    waves = {"enabled": waves_enabled}
    if waves_enabled:
        waves.update({
            "path": waves_path,
            "run_script": waves_script,
            "exists": bool(waves_path and os.path.exists(waves_path)),
        })

    wall_duration_s = _duration_seconds(getattr(test_job, "duration_s", 0) or 0)
    simulation_duration_s = getattr(test_job, "simulation_duration_s", None)
    if simulation_started is None:
        simulation_started = simulation_duration_s is not None
    test_record = {
        "bench": test_job.vcomper.name,
        "test": test_job.name,
        "target": test_job.target,
        "vcomp_target": test_job.vcomper.bazel_vcomp_target,
        "iteration": test_job.iteration,
        "seed": getattr(test_job, "seed", None),
        "status": status or test_job.jobstatus.name,
        "simulation_started": bool(simulation_started),
        "duration_s": _duration_seconds(simulation_duration_s),
        "wall_duration_s": wall_duration_s,
        "compile_dir": test_job.vcomper.job_dir,
        "sim_dir": test_job.job_dir,
        "stdout_log": getattr(test_job, "_log_path", None),
        "cmp_log": test_job.vcomper.log_path,
        "waves": waves,
        "error_message": getattr(test_job, "error_message", None),
    }
    _record_job_interval(
        test_record,
        test_job,
        stopped_at=datetime.datetime.now() if status == "INTERRUPTED" else None,
    )
    for index, existing in enumerate(run["tests"]):
        if all(existing.get(key) == test_record.get(key) for key in ("target", "iteration", "seed")):
            run["tests"][index] = test_record
            return
    run["tests"].append(test_record)


def finalize_run(run, regression_log_path=None, backend_finalize_failed=False):
    if run is None:
        return
    run["finished_at"] = _timestamp()
    run["regression_log"] = regression_log_path

    tests = run.get("tests", [])
    planned_tests = int(run.get("planned_tests") or len(tests))
    passed = sum(1 for test in tests if test.get("status") == "PASSED")
    failed = sum(1 for test in tests if test.get("status") == "FAILED")
    interrupted = sum(1 for test in tests if test.get("status") == "INTERRUPTED")
    skipped = max(0, planned_tests - len(tests))

    run["summary"] = {
        "passed": passed,
        "failed": failed,
        "interrupted": interrupted,
        "skipped": skipped,
        "total": planned_tests,
    }
    _finalize_timing(run)
    run["benches"] = _collect_benches(run)

    if backend_finalize_failed:
        run["status"] = "FAILED"
        return

    if tests:
        if failed:
            run["status"] = "FAILED"
        elif interrupted:
            run["status"] = "INTERRUPTED"
        elif skipped:
            run["status"] = "PARTIAL"
        else:
            run["status"] = "PASSED"
        return

    if any(item.get("status") == "FAILED" for item in run.get("compile", [])):
        run["status"] = "COMPILE_FAILED"
    elif run.get("launch_failures"):
        run["status"] = "FAILED"
    else:
        run["status"] = "NO_SIM_RUN"


def _empty_store():
    return {
        "schema_version": SCHEMA_VERSION,
        "last_run": None,
        "runs": [],
    }


def load_store(project_dir):
    path = results_path(project_dir)
    if not os.path.exists(path):
        return _empty_store()
    with open(path, "r", encoding="utf-8") as filep:
        store = json.load(filep)
    runs = store.get("runs", []) if isinstance(store, dict) else None
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ValueError("Invalid simmer history structure in {}".format(path))
    store.setdefault("schema_version", SCHEMA_VERSION)
    store.setdefault("last_run", None)
    store.setdefault("runs", [])
    return store


def should_save_run(run):
    """Return whether at least one simulation produced a result record."""
    return bool(run and any(test.get("simulation_started", True) for test in run.get("tests", [])))


def save_run(project_dir, run, max_runs=MAX_RUNS):
    if not should_save_run(run):
        return False
    stored_run = dict(run)
    if int(run.get("planned_tests") or len(run["tests"])) > 1 and len(run["tests"]) > 1:
        representative = next(
            (test for test in run["tests"] if test.get("status") == "FAILED"),
            next((test for test in run["tests"] if test.get("status") == "INTERRUPTED"), run["tests"][0]),
        )
        stored_run["tests"] = [representative]
    path = results_path(project_dir)
    with _store_lock(path):
        try:
            store = load_store(project_dir)
        except (json.JSONDecodeError, ValueError):
            corrupt_path = "{}.corrupt.{}".format(path, datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
            os.replace(path, corrupt_path)
            print("Warning: moved invalid simmer history to {}".format(corrupt_path), file=sys.stderr)
            store = _empty_store()
        runs = [item for item in store.get("runs", []) if item.get("run_id") != stored_run.get("run_id")]
        runs.append(stored_run)
        store = {
            "schema_version": SCHEMA_VERSION,
            "last_run": stored_run,
            "runs": runs[-max_runs:],
        }
        temp_path = "{}.{}.{}.tmp".format(path, os.getpid(), uuid.uuid4().hex)
        try:
            with open(temp_path, "w", encoding="utf-8") as filep:
                json.dump(store, filep, indent=2)
                filep.write("\n")
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
    return True


def _select_compile_log(run):
    tests = run.get("tests", [])
    failed_tests = [test for test in tests if test.get("status") == "FAILED"]
    if failed_tests and failed_tests[0].get("cmp_log"):
        return failed_tests[0]["cmp_log"]
    if tests and tests[0].get("cmp_log"):
        return tests[0]["cmp_log"]
    compile_records = run.get("compile", [])
    if compile_records:
        return compile_records[0].get("cmp_log") or "-"
    return "-"


def _select_result_log(run):
    tests = run.get("tests", [])
    if not tests:
        return "-"
    if int(run.get("planned_tests") or len(tests)) > 1:
        return run.get("regression_log") or "-"
    return tests[0].get("stdout_log") or "-"


def _select_waves_script(run):
    tests = run.get("tests", [])
    if int(run.get("planned_tests") or len(tests)) != 1 or not tests:
        return None
    waves = tests[0].get("waves", {})
    return waves.get("run_script") if waves.get("enabled") else "-"


def _color_word(word, color, use_color):
    if not use_color:
        return word
    return "{}{}{}".format(color, word, COLOR_NC)


def _format_test_summary(run, use_color=False):
    summary = run.get("summary", {})
    passed = summary.get("passed", 0)
    failed = summary.get("failed", 0)
    interrupted = summary.get("interrupted", 0)
    skipped = summary.get("skipped", 0)
    total = summary.get("total", run.get("planned_tests", 0))
    if total <= 1:
        return None

    passed_text = _color_word("passed", COLOR_GREEN, use_color)
    details = ["{} {}".format(passed, passed_text)]
    if failed:
        failed_text = _color_word("failed", COLOR_RED, use_color)
        details.append("{} {}".format(failed, failed_text))
    if interrupted:
        interrupted_text = _color_word("interrupted", COLOR_YELLOW, use_color)
        details.append("{} {}".format(interrupted, interrupted_text))
    if skipped:
        details.append("{} skipped".format(skipped))
    return "[tests: {}]".format(" | ".join(details))


def _resolve_use_color(use_color):
    if use_color is None:
        return sys.stdout.isatty()
    return use_color


def _color_status(status, use_color):
    if not use_color:
        return status
    if status == "PASSED":
        return "{}{}{}".format(COLOR_GREEN, status, COLOR_NC)
    if status == "FAILED":
        return "{}{}{}".format(COLOR_RED, status, COLOR_NC)
    if status == "PARTIAL":
        return "{}{}{}".format(COLOR_YELLOW, status, COLOR_NC)
    return status


def _format_duration(duration_s):
    duration_s = _duration_seconds(duration_s)
    if duration_s is None:
        return "-"
    total_seconds = int(duration_s)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)


def _format_timing(run):
    timing = run.get("timing", {})
    if timing.get("compile_reused"):
        compile_duration = "reused"
    else:
        compile_duration = _format_duration(timing.get("compile_elapsed_s"))
    simulate_duration = _format_duration(timing.get("simulate_elapsed_s"))
    return "[compile {} | simulate {}]".format(compile_duration, simulate_duration)


def _is_failed_history_run(run):
    return (run.get("status") in ("FAILED", "COMPILE_FAILED") or int(run.get("summary", {}).get("failed", 0) or 0) > 0)


def _filter_history_runs(runs, bench=None, failed_only=False):
    filtered = []
    for run in runs:
        if bench is not None and bench not in _collect_benches(run):
            continue
        if failed_only and not _is_failed_history_run(run):
            continue
        filtered.append(run)
    return filtered


def format_history(project_dir, count, use_color=None, bench=None, failed_only=False):
    use_color = _resolve_use_color(use_color)
    try:
        store = load_store(project_dir)
    except (OSError, ValueError) as exc:
        return "Unable to read simmer history: {}".format(exc)
    runs = store.get("runs", [])
    if not runs:
        return "No simmer history found."
    runs = _filter_history_runs(runs, bench=bench, failed_only=failed_only)
    if not runs:
        return "No matching simmer history found."

    lines = []
    recent_runs = list(reversed(runs))[:count]
    for index, run in enumerate(recent_runs, start=1):
        if lines:
            lines.append("")
        heading = [
            "[{}] {}".format(index,
                             run.get("finished_at") or run.get("started_at") or "-"),
            _color_status(run.get("status", "-"), use_color),
        ]
        test_summary = _format_test_summary(run, use_color=use_color)
        if test_summary is not None:
            heading.append(test_summary)
        heading.append(_format_timing(run))
        lines.append("  ".join(heading))
        lines.append("cmd:     {}".format(run.get("command") or "-"))
        lines.append("compile: {}".format(_select_compile_log(run)))
        lines.append("result:  {}".format(_select_result_log(run)))
        waves_script = _select_waves_script(run)
        if waves_script is not None:
            lines.append("waves:   {}".format(waves_script or "-"))
    return "\n".join(lines)


def print_history(project_dir, count, use_color=None, bench=None, failed_only=False):
    print(format_history(project_dir, count, use_color=use_color, bench=bench, failed_only=failed_only))
