#!/usr/bin/env python3
"""Generate and retain static HTML regression reports."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
from urllib.parse import quote as url_quote

import jinja2

MAX_HISTORY = 30
_TIMESTAMP_RE = re.compile(r"[0-9]{8}_[0-9]{6}(?:_[0-9]{6})?\Z")


def _validate_component(value):
    if (not isinstance(value, str) or not value or value in (".", "..") or value.endswith((".", " "))
            or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value)):
        raise ValueError("Invalid report path component: {!r}".format(value))
    return value


def _validate_timestamp(value):
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("Invalid report timestamp: {!r}".format(value))
    return value


def _contained_path(root, *components):
    """Keep report paths, including existing symlink targets, below their owner."""
    root_path = Path(root).resolve()
    candidate = root_path.joinpath(*(_validate_component(part) for part in components))
    if not candidate.resolve().is_relative_to(root_path) or candidate.resolve() == root_path:
        raise ValueError("Report path escapes its directory: {}".format(candidate))
    return str(candidate)


def regression_status(summary):
    """Keep compilation failures and unexecuted tests distinct from a pass."""
    if summary.get("compile_failed") or _safe_int(summary.get("failed")):
        return "Failed"
    if summary.get("compile_skipped") or _safe_int(summary.get("skipped")):
        return "Partial"
    if summary.get("compile_only"):
        return "Compile only"
    return "Passed" if _safe_int(summary.get("total")) else "No tests"


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coverage_value(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).rstrip("%"))
    except (TypeError, ValueError):
        return None


def _coverage_metric(coverage, section, metric="Overall"):
    return _coverage_value(coverage.get(section, {}).get(metric))


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "item"


def _write_text_atomic(path, contents):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".report-", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as filep:
            filep.write(contents)
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _write_json_atomic(path, value):
    _write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as filep:
        value = json.load(filep)
    if not isinstance(value, type(default)):
        raise ValueError("Unexpected JSON structure in {}".format(path))
    return value


def create_template_environment(template_dir):
    """Create the autoescaping Jinja environment used by HTML reports."""
    environment = jinja2.Environment(
        autoescape=jinja2.select_autoescape(enabled_extensions=("html", "xml", "html.j2", "xml.j2")),
        loader=jinja2.FileSystemLoader(searchpath=template_dir),
    )
    environment.filters["zip"] = zip
    environment.filters["regression_status"] = regression_status
    return environment


def regression_history_series(regressions, timestamps):
    """Return pass and coverage chart series."""
    entries = [regressions[timestamp] for timestamp in timestamps if timestamp in regressions]
    return (
        [entry.get("passrate", 0) for entry in entries],
        [entry.get("cov_total") for entry in entries],
        [entry.get("cov_code", 0) for entry in entries],
        [entry.get("cov_func", 0) for entry in entries],
    )


class RegressionReport:
    """Own static report rendering and retention."""

    def __init__(self, rcfg, template_env, webroot_dir):
        self.rcfg = rcfg
        self.env = template_env
        self.webroot_dir = webroot_dir
        self.output_path = _contained_path(self.webroot_dir, "regression_report")
        self.project_info_path = _contained_path(self.output_path, "project_info.json")

        self.HOME_TEMPLATE = self.env.get_template("regression_report_templates/home_template.html.j2")
        self.BENCHS_TEMPLATE = self.env.get_template("regression_report_templates/benchs_template.html.j2")
        self.REGRESSION_REPORT_TEMPLATE = self.env.get_template(
            "regression_report_templates/regression_report_template.html.j2")
        self.LOGS_TEMPLATE = self.env.get_template("regression_report_templates/logs_template.html.j2")

        self.header = {}
        self.trd = {}
        self.cov = {}
        self.proj_name = ""
        self.project_info = {}
        self.bench_list = []
        self.category_stats = {}
        self.processed_category_stats = []

    def _refresh_project_info(self):
        try:
            project_info = _load_json(self.project_info_path, {})
        except (json.JSONDecodeError, ValueError) as exc:
            self.rcfg.log.warning("Ignoring invalid report project index %s: %s", self.project_info_path, exc)
            project_info = {}
        safe_projects = {}
        for project_name, project_benches in project_info.items():
            try:
                project_path = _contained_path(self.output_path, project_name)
                if not isinstance(project_benches, list):
                    raise ValueError("Report benches must be a list")
                safe_benches = []
                for bench in project_benches:
                    _contained_path(project_path, bench)
                    safe_benches.append(bench)
                safe_projects[project_name] = safe_benches
            except ValueError as exc:
                self.rcfg.log.warning("Ignoring invalid report project entry %r: %s", project_name, exc)
        project_info = safe_projects
        benches = set(project_info.get(self.proj_name, []))
        benches.update(self.bench_list)
        project_info[self.proj_name] = sorted(benches)
        self.project_info = project_info

    def process_trd(self, trd):
        """Normalize print_summary rows and group them by bench."""
        self.trd = {}
        current_bench = None
        last_job = None

        for raw_entry in trd:
            entry = list(raw_entry)
            entry.extend([""] * max(0, 9 - len(entry)))
            if entry[0]:
                current_bench = entry[0]
            if entry[1] and current_bench:
                total = _safe_int(entry[6])
                pass_rate = (_safe_int(entry[3]) / total * 100) if total else 0
                normalized = entry[:7] + ["{:.2f}".format(pass_rate), entry[7], entry[8]]
                self.trd.setdefault(current_bench, []).append(normalized)
                last_job = normalized
            elif entry[7] and last_job is not None:
                last_job[8] = "|".join(part for part in [last_job[8], entry[7]] if part)

        for bench, rows in self.trd.items():
            test_rows = rows[1:] if rows and rows[0][1] == "vcomp" else rows
            passed = sum(_safe_int(row[3]) for row in test_rows)
            skipped = sum(_safe_int(row[4]) for row in test_rows)
            failed = sum(_safe_int(row[5]) for row in test_rows)
            total = passed + skipped + failed
            rows.append([
                "Total",
                "",
                "",
                str(passed) if passed else "",
                str(skipped) if skipped else "",
                str(failed) if failed else "",
                str(total) if total else "",
                "{:.2f}".format(passed / total * 100) if total else "0.00",
                "",
                "",
            ])

        self.bench_list = list(self.trd)

    def process_category_stats(self):
        """Convert category statistics into template-friendly rows."""
        self.processed_category_stats = []
        for category, stats in (self.category_stats or {}).items():
            total = stats["total"]
            executed = stats["executed"]
            passed = stats["passed"]
            completion_rate = "{:.2f}%".format(executed / total * 100) if total else "N/A"
            pass_rate = "{:.2f}%".format(passed / executed * 100) if executed else "N/A"
            self.processed_category_stats.append([
                category,
                str(total),
                str(executed),
                completion_rate,
                str(passed),
                pass_rate,
            ])

    def run(self, header, trd, cov, category_stats):
        """Prepare and render a complete report."""
        self.prepare(header, trd, cov, category_stats)
        self.render_regression_page()
        self.render_home_page()
        self.render_bench_page()

    def prepare(self, header, trd, cov, category_stats):
        self.header = dict(header)
        self.proj_name = _validate_component(self.header["project_name"])
        _validate_timestamp(self.header["time"])
        self.cov = cov or {}
        self.category_stats = category_stats or {}
        self.process_trd(trd)
        self.process_category_stats()
        project_path = _contained_path(self.output_path, self.proj_name)
        for bench in self.bench_list:
            _contained_path(project_path, bench)
        os.makedirs(self.output_path, exist_ok=True)
        self._refresh_project_info()

    def _load_history(self, bench_path):
        path = _contained_path(bench_path, "regressions.json")
        try:
            history = _load_json(path, {})
        except (json.JSONDecodeError, ValueError) as exc:
            self.rcfg.log.warning("Ignoring invalid regression history %s: %s", path, exc)
            return {}
        return self._safe_history(history)

    def _safe_history(self, history):
        safe_history = {}
        for timestamp, summary in history.items():
            try:
                _validate_timestamp(timestamp)
                if not isinstance(summary, dict):
                    raise ValueError("Report summary must be an object")
                safe_history[timestamp] = summary
            except ValueError as exc:
                # Invalid metadata is dropped, never used to locate artifacts.
                self.rcfg.log.warning("Ignoring invalid regression history entry %r: %s", timestamp, exc)
        return safe_history

    def dashboard_data(self):
        """Return latest per-bench summaries for every known project."""
        dashboard = {}
        for project_name, benches in self.project_info.items():
            project_rows = []
            for bench in benches:
                try:
                    bench_path = _contained_path(self.output_path, project_name, bench)
                    regressions = self._load_history(bench_path)
                except ValueError:
                    regressions = {}
                timestamp = max(regressions, default="")
                summary = dict(regressions.get(timestamp, {}))
                summary.update({"bench": bench, "timestamp": timestamp})
                project_rows.append(summary)
            dashboard[project_name] = project_rows
        return dashboard

    def render_home_page(self):
        self._refresh_project_info()
        rendered_html = self.HOME_TEMPLATE.render(
            project=self.project_info,
            dashboard=self.dashboard_data(),
        )
        _write_text_atomic(_contained_path(self.output_path, "index.html"), rendered_html)

    def render_bench_page(self):
        self._refresh_project_info()
        project_path = _contained_path(self.output_path, self.proj_name)
        os.makedirs(project_path, exist_ok=True)
        for bench in self.bench_list:
            os.makedirs(_contained_path(project_path, bench), exist_ok=True)
        _write_json_atomic(self.project_info_path, self.project_info)
        rendered_html = self.BENCHS_TEMPLATE.render(
            project_name=self.proj_name,
            project=self.project_info,
            bench_summaries=self.dashboard_data().get(self.proj_name, []),
        )
        _write_text_atomic(_contained_path(project_path, "index.html"), rendered_html)

    def write_run_launcher(self, report_url=None):
        """Write an executable that opens this run's immutable report pages."""
        timestamp = _validate_timestamp(self.header["time"])
        targets = []
        for bench in self.bench_list:
            if report_url:
                targets.append("{}/{}/{}/{}.html".format(
                    report_url.rstrip("/"),
                    url_quote(self.proj_name, safe=""),
                    url_quote(bench, safe=""),
                    url_quote(timestamp, safe=""),
                ))
            else:
                report_path = Path(_contained_path(self.output_path, self.proj_name, bench,
                                                   "{}.html".format(timestamp)))
                targets.append(report_path.as_uri())

        if not targets:
            return None

        launcher_path = _contained_path(self.output_path, "open_{}.sh".format(timestamp))
        target_lines = "\n".join("    {}".format(shlex.quote(target)) for target in targets)
        launcher = """#!/usr/bin/env bash

set -Eeuo pipefail

REPORT_TARGETS=(
{targets}
)

open_report() {{
    local report_target=$1
    if [ -n "${{BROWSER:-}}" ]; then
        "$BROWSER" "$report_target"
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$report_target"
    elif command -v gio >/dev/null 2>&1; then
        gio open "$report_target"
    elif command -v firefox >/dev/null 2>&1; then
        firefox "$report_target"
    elif command -v google-chrome >/dev/null 2>&1; then
        google-chrome "$report_target"
    else
        printf 'ERROR: No browser launcher found. Report: %s\n' "$report_target" >&2
        return 1
    fi
}}

for report_target in "${{REPORT_TARGETS[@]}}"; do
    printf 'Opening Simmer report: %s\n' "$report_target"
    open_report "$report_target"
done
""".format(targets=target_lines)
        _write_text_atomic(launcher_path, launcher)
        os.chmod(launcher_path, 0o755)

        launchers = sorted(path for path in Path(self.output_path).glob("open_*.sh")
                           if _TIMESTAMP_RE.fullmatch(path.name[5:-3]) and path.is_file())
        for stale_launcher in launchers[:-MAX_HISTORY]:
            try:
                Path(_contained_path(self.output_path, stale_launcher.name)).unlink()
            except ValueError as exc:
                self.rcfg.log.warning("Skipping unsafe report launcher cleanup: %s", exc)
        return launcher_path

    def _copy_logs(self, bench_path, details):
        timestamp = _validate_timestamp(self.header["time"])
        run_logs_path = _contained_path(bench_path, "logs", timestamp)
        logs_list = []

        for row_index, row in enumerate(details[:-1], start=1):
            copied_logs = []
            for log_index, log_path in enumerate(filter(None, row[8].split("|")), start=1):
                source = Path(log_path)
                if not source.is_file():
                    self.rcfg.log.warning("Regression log does not exist: %s", source)
                    continue
                os.makedirs(run_logs_path, exist_ok=True)
                destination_name = "{}_{:02d}_{}.log".format(_slug(row[1]), log_index, _slug(source.parent.name))
                destination_path = _contained_path(run_logs_path, destination_name)
                shutil.copy2(source, destination_path)
                os.chmod(destination_path, 0o644)
                copied_logs.append(destination_name)

            if not copied_logs:
                continue
            logs_page = "{:03d}_{}.html".format(row_index, _slug(row[1]))
            rendered_logs = self.LOGS_TEMPLATE.render(
                project_name=self.proj_name,
                bench_name=os.path.basename(bench_path),
                logs=copied_logs,
            )
            _write_text_atomic(_contained_path(run_logs_path, logs_page), rendered_logs)
            row[-1] = "{}/{}".format(timestamp, logs_page)
            logs_list.append(["logs/{}/{}".format(timestamp, name) for name in copied_logs])

        return logs_list

    def _remove_history_artifacts(self, bench_path, timestamp, summary):
        try:
            _validate_timestamp(timestamp)
            run_logs_path = _contained_path(bench_path, "logs", timestamp)
            history_page = _contained_path(bench_path, "{}.html".format(timestamp))
        except ValueError as exc:
            self.rcfg.log.warning("Skipping unsafe report history cleanup: %s", exc)
            return
        shutil.rmtree(run_logs_path, ignore_errors=True)
        if os.path.isfile(history_page):
            os.remove(history_page)

        bench_root = Path(bench_path).resolve()
        log_groups = summary.get("logs", [])
        for group in log_groups if isinstance(log_groups, list) else []:
            paths = [group] if isinstance(group, str) else group
            if not isinstance(paths, list):
                continue
            for log_path in paths:
                if not isinstance(log_path, str):
                    continue
                candidate = Path(log_path)
                if not candidate.is_absolute():
                    candidate = bench_root / candidate
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if resolved.is_relative_to(bench_root) and resolved.is_file():
                    resolved.unlink()

    def _prune_history(self, bench_path, regressions):
        safe_history = self._safe_history(regressions)
        regressions.clear()
        regressions.update(safe_history)
        timestamps = sorted(regressions)
        for timestamp in timestamps[:-MAX_HISTORY]:
            self._remove_history_artifacts(bench_path, timestamp, regressions[timestamp])
            del regressions[timestamp]
        return sorted(regressions)

    def render_regression_page(self):
        for bench, source_details in self.trd.items():
            coverage = self.cov.get(bench, {})
            cc_info = coverage.get("cc", {})
            cf_info = coverage.get("cf", {})
            bench_path = _contained_path(self.output_path, self.proj_name, bench)
            os.makedirs(bench_path, exist_ok=True)
            details = [row[:] + [""] for row in source_details]
            logs_list = self._copy_logs(bench_path, details)

            compile_row = source_details[0] if source_details[0][1] == "vcomp" else None
            test_rows = source_details[1:-1] if compile_row else source_details[:-1]
            passed = sum(_safe_int(row[3]) for row in test_rows)
            skipped = sum(_safe_int(row[4]) for row in test_rows)
            failed = sum(_safe_int(row[5]) for row in test_rows)
            total = sum(_safe_int(row[6]) for row in test_rows)
            regression_summary = {
                "schema_version": 2,
                "compile_failed": bool(compile_row and _safe_int(compile_row[5])),
                "compile_skipped": bool(compile_row and _safe_int(compile_row[4])),
                "compile_only": bool(getattr(getattr(self.rcfg, "options", None), "no_run", not test_rows)),
                "passed": passed,
                "skipped": skipped,
                "failed": failed,
                "total": total,
                "passrate": round(passed / total * 100, 2) if total else 0.0,
                "cov_total": _coverage_value(coverage.get("total")),
                "cov_code": _coverage_metric(coverage, "cc"),
                "cov_func": _coverage_metric(coverage, "cf"),
                "cov_vendor_score": _coverage_value(coverage.get("vendor_score")),
                "logs": logs_list,
            }

            json_file_path = _contained_path(bench_path, "regressions.json")
            regressions = self._load_history(bench_path)
            regressions[self.header["time"]] = regression_summary
            remain_list = self._prune_history(bench_path, regressions)
            passrate_list, cov_total_list, cov_code_list, cov_func_list = regression_history_series(
                regressions, remain_list)
            history = [dict(regressions[timestamp], timestamp=timestamp) for timestamp in reversed(remain_list)]

            rendered_html = self.REGRESSION_REPORT_TEMPLATE.render(
                header=self.header,
                bench_name=bench,
                regression_details=details,
                regressions=remain_list,
                history=history,
                latest_summary=regression_summary,
                passrate_list=passrate_list,
                cov_total_list=cov_total_list,
                cov_code_list=cov_code_list,
                cov_func_list=cov_func_list,
                project=self.project_info,
                cc_info=cc_info,
                cf_info=cf_info,
                processed_category_stats=self.processed_category_stats,
            )

            index_path = _contained_path(bench_path, "index.html")
            _write_text_atomic(index_path, rendered_html)
            _write_text_atomic(_contained_path(bench_path, "{}.html".format(self.header["time"])), rendered_html)
            _write_json_atomic(json_file_path, regressions)
