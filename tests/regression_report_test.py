import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from lib.regression_report import RegressionReport, create_template_environment, regression_history_series


class _Log:

    def warning(self, *_args, **_kwargs):
        pass


class RegressionReportTest(unittest.TestCase):

    @staticmethod
    def _header(**updates):
        header = {
            "branch": "main",
            "commit": "",
            "project_name": "project",
            "revision": "abc",
            "simulator": "VCS",
            "tag": "",
            "time": "20260711_120000_000001",
            "username": "user",
        }
        header.update(updates)
        return header

    def _report_environment(self):
        if os.environ.get("TEST_SRCDIR"):
            runfiles_root = Path(os.environ["TEST_SRCDIR"]) / os.environ.get("TEST_WORKSPACE", "__main__")
            template_dir = runfiles_root / "bin/templates"
        else:
            template_dir = Path(__file__).resolve().parents[1] / "bin/templates"
        return create_template_environment(template_dir)

    def test_report_environment_escapes_html_only(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            template_dir = Path(temporary_dir)
            (template_dir / "report.html.j2").write_text("{{ value }}", encoding="utf-8")
            (template_dir / "script.sh.j2").write_text("{{ value }}", encoding="utf-8")
            environment = create_template_environment(template_dir)

            value = '<script>alert("unsafe")</script>'
            self.assertEqual(
                '&lt;script&gt;alert(&#34;unsafe&#34;)&lt;/script&gt;',
                environment.get_template("report.html.j2").render(value=value),
            )
            self.assertEqual(value, environment.get_template("script.sh.j2").render(value=value))

    def test_real_report_templates_escape_dynamic_content(self):
        environment = self._report_environment()
        logs_html = environment.get_template("regression_report_templates/logs_template.html.j2", ).render(
            project_name="<project>",
            bench_name="bench",
            logs=['bad\"name.log'],
        )
        self.assertIn("&lt;project&gt;", logs_html)
        self.assertIn("bad%22name.log", logs_html)
        self.assertNotIn("</li>>", logs_html)

        report_html = environment.get_template(
            "regression_report_templates/regression_report_template.html.j2", ).render(
                bench_name="<bench>",
                cc_info={},
                cf_info={},
                header={
                    "branch": "main",
                    "commit": "https://example.com",
                    "project_name": "project",
                    "revision": "abc",
                    "simulator": "VCS",
                    "tag": "",
                    "time": "20260711_120000",
                    "username": "user",
                },
                passrate_list=[100.0],
                processed_category_stats=[],
                project={"project": ["bench"]},
                regression_details=[],
                regressions=["</script>"],
                history=[{
                    "timestamp": "</script>"
                }],
            )
        self.assertIn("&lt;bench&gt;", report_html)
        self.assertIn("%3C/script%3E.html", report_html)
        self.assertNotIn("</script>", report_html)
        self.assertIn("Regression Dashboard", report_html)
        self.assertIn("Total Coverage", report_html)
        self.assertIn("Code Coverage", report_html)
        self.assertIn("heat-good", report_html)
        self.assertNotIn("_static", report_html)
        self.assertNotIn("Chart.js", report_html)

    def test_history_keeps_code_and_functional_coverage_separate(self):
        regressions = {
            "20260710_120000": {
                "passrate": 90.0,
                "cov_total": 78.0,
                "cov_code": 81.0,
                "cov_func": 72.0
            },
            "20260711_120000": {
                "passrate": 95.0,
                "cov_total": 82.0,
                "cov_code": 84.0,
                "cov_func": 76.0
            },
        }

        self.assertEqual(
            ([90.0, 95.0], [78.0, 82.0], [81.0, 84.0], [72.0, 76.0]),
            regression_history_series(regressions, list(regressions)),
        )

    def test_report_handles_zero_tests_partial_coverage_and_untagged_header(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "empty_test", "", "", "", "", "0", "", ""),
            ]

            report.run(
                header,
                trd,
                {"bench": {
                    "total": "80%",
                    "vendor_score": "82%",
                    "cc": {
                        "Overall": "75%"
                    },
                }},
                {},
            )

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            regressions = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            summary = regressions[header["time"]]
            self.assertEqual(0.0, summary["passrate"])
            self.assertEqual(80.0, summary["cov_total"])
            self.assertEqual(75.0, summary["cov_code"])
            self.assertIsNone(summary["cov_func"])
            self.assertEqual(82.0, summary["cov_vendor_score"])
            self.assertTrue((bench_path / "index.html").is_file())
            report_html = (bench_path / "index.html").read_text(encoding="utf-8")
            self.assertGreaterEqual(report_html.count("N/A"), 2)
            self.assertIn(">No tests</span>", report_html)

    def test_compile_only_reports_preserve_compile_failure_and_never_claim_test_pass(self):
        for compile_failed in (False, True):
            with self.subTest(compile_failed=compile_failed), tempfile.TemporaryDirectory() as temporary_dir:
                rcfg = SimpleNamespace(log=_Log(), options=SimpleNamespace(no_run=True))
                report = RegressionReport(rcfg, self._report_environment(), temporary_dir)
                header = self._header()
                trd = [("bench", "vcomp", "", "" if compile_failed else "1", "", "1" if compile_failed else "", "1", "",
                        "")]
                report.run(header, trd, {}, {})
                report_root = Path(temporary_dir) / "regression_report"
                bench_path = report_root / "project" / "bench"
                summary = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))[header["time"]]
                self.assertEqual(0, summary["total"])
                self.assertEqual(0, summary["failed"])
                self.assertEqual(compile_failed, summary["compile_failed"])
                self.assertTrue(summary["compile_only"])
                status = "Failed" if compile_failed else "Compile only"
                for page in (bench_path / "index.html", bench_path / (header["time"] + ".html")):
                    html = page.read_text(encoding="utf-8")
                    self.assertIn(">{}<".format(status), html)
                    self.assertNotIn('status-passed">Passed', html)
                for page in (report_root / "index.html", report_root / "project" / "index.html"):
                    self.assertIn("<td>{}</td>".format(status), page.read_text(encoding="utf-8"))

    def test_report_rejects_unsafe_names_and_timestamps_before_writing(self):
        invalid_headers = [self._header(project_name=value) for value in ("..", "../escape", "/escape", "C:\\escape")]
        invalid_headers += [self._header(time=value) for value in ("../../victim", "/victim", "not a timestamp")]
        cases = [(header, "bench") for header in invalid_headers]
        cases += [(self._header(), name) for name in ("..", "../escape", "C:\\escape")]
        with tempfile.TemporaryDirectory() as temporary_dir:
            for header, bench in cases:
                with self.subTest(header=header, bench=bench):
                    report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
                    with self.assertRaises(ValueError):
                        report.run(header, [(bench, "vcomp", "", "1", "", "", "1", "", "")], {}, {})
                    self.assertFalse((Path(temporary_dir) / "regression_report").exists())

    def test_malformed_history_never_controls_retention_paths(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            bench_path = root / "regression_report" / "project" / "bench"
            bench_path.mkdir(parents=True)
            victim_directory = root / "regression_report" / "victim"
            victim_directory.mkdir()
            marker = victim_directory / "keep.txt"
            marker.write_text("keep directory", encoding="utf-8")
            victim_page = root / "victim.html"
            victim_page.write_text("keep page", encoding="utf-8")
            history = {"20260101_{:06d}".format(index): {"logs": []} for index in range(30)}
            history["../../../victim"] = {"logs": []}
            history["20250101_000000"] = []
            (bench_path / "regressions.json").write_text(json.dumps(history), encoding="utf-8")
            report.run(self._header(), [("bench", "vcomp", "", "1", "", "", "1", "", "")], {}, {})
            retained = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            self.assertEqual(30, len(retained))
            self.assertNotIn("../../../victim", retained)
            self.assertNotIn("20250101_000000", retained)
            self.assertEqual("keep directory", marker.read_text(encoding="utf-8"))
            self.assertEqual("keep page", victim_page.read_text(encoding="utf-8"))

    def test_report_drops_unsafe_persisted_project_index_entries(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir) / "regression_report"
            root.mkdir()
            (root / "project_info.json").write_text(json.dumps({
                "../escape": ["bench"],
                "other": ["../escape"],
                "bad_type": "bench"
            }),
                                                    encoding="utf-8")
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            report.run(self._header(), [("bench", "vcomp", "", "1", "", "", "1", "", "")], {}, {})
            self.assertEqual({"project": ["bench"]}, json.loads(
                (root / "project_info.json").read_text(encoding="utf-8")))

    def test_report_write_and_retention_reject_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            bench_path = root / "regression_report" / "project" / "bench"
            bench_path.mkdir(parents=True)
            timestamp = self._header()["time"]
            outside = root / "outside"
            (outside / timestamp).mkdir(parents=True)
            marker = outside / timestamp / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            try:
                (bench_path / "logs").symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest("symlinks unavailable: {}".format(exc))
            report._remove_history_artifacts(str(bench_path), timestamp, {"logs": []})
            self.assertEqual("keep", marker.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "escapes"):
                report.run(self._header(), [("bench", "vcomp", "", "1", "", "", "1", "", "")], {}, {})
            self.assertEqual(["keep.txt"], [path.name for path in marker.parent.iterdir()])

    def test_compile_failure_log_is_copied_and_linked(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            compile_dir = Path(temporary_dir) / "compile"
            compile_dir.mkdir()
            compile_log = compile_dir / "cmp.log"
            compile_log.write_text("compile failed\n", encoding="utf-8")
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }

            report.run(
                header,
                [("bench", "vcomp", "0:00:01", "", "", "1", "1", str(compile_log), "")],
                {},
                {},
            )

            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            copied_log = bench_path / "logs" / header["time"] / "vcomp_01_compile.log"
            self.assertEqual("compile failed\n", copied_log.read_text(encoding="utf-8"))
            report_html = (bench_path / "index.html").read_text(encoding="utf-8")
            self.assertIn("{}/001_vcomp.html".format(header["time"]), report_html)
            logs_html = (copied_log.parent / "001_vcomp.html").read_text(encoding="utf-8")
            self.assertIn("vcomp_01_compile.log", logs_html)

    def test_report_retention_removes_snapshot_and_timestamp_logs(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project",
                "revision": "abc",
                "simulator": "XRUN",
                "tag": "",
                "time": "20260711_120000_000001",
                "username": "user",
            }
            trd = [
                ("bench", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            bench_path = Path(temporary_dir) / "regression_report" / "project" / "bench"
            bench_path.mkdir(parents=True)
            regressions = {}
            for index in range(30):
                timestamp = "20260101_{:06d}".format(index)
                regressions[timestamp] = {
                    "passrate": 100,
                    "cov_code": 0,
                    "cov_func": 0,
                    "logs": [],
                }
            oldest = min(regressions)
            (bench_path / "regressions.json").write_text(json.dumps(regressions), encoding="utf-8")
            (bench_path / "{}.html".format(oldest)).write_text("old", encoding="utf-8")
            old_logs = bench_path / "logs" / oldest
            old_logs.mkdir(parents=True)
            (old_logs / "old.log").write_text("old", encoding="utf-8")

            report.run(header, trd, {}, {})

            retained = json.loads((bench_path / "regressions.json").read_text(encoding="utf-8"))
            self.assertEqual(30, len(retained))
            self.assertNotIn(oldest, retained)
            self.assertFalse((bench_path / "{}.html".format(oldest)).exists())
            self.assertFalse(old_logs.exists())

    def test_run_launcher_opens_only_this_regression_snapshot(self):
        if os.name == "nt":
            self.skipTest("generated launcher execution requires POSIX shell semantics")
        with tempfile.TemporaryDirectory(prefix="report launcher ") as temporary_dir:
            report = RegressionReport(SimpleNamespace(log=_Log()), self._report_environment(), temporary_dir)
            header = {
                "branch": "main",
                "commit": "",
                "project_name": "project name",
                "revision": "abc",
                "simulator": "VCS",
                "tag": "",
                "time": "20260716_140000_000001",
                "username": "user",
            }
            trd = [
                ("bench one", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
                ("bench two", "vcomp", "", "1", "", "", "1", "", ""),
                ("", "test", "0:00:01", "1", "", "", "1", "", ""),
            ]
            report.run(header, trd, {}, {})

            launcher_path = Path(report.write_run_launcher())
            self.assertEqual(
                Path(temporary_dir) / "regression_report" / "open_20260716_140000_000001.sh",
                launcher_path,
            )
            capture_path = Path(temporary_dir) / "opened reports.txt"
            browser_path = Path(temporary_dir) / "browser stub.sh"
            browser_path.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$1\" >> \"$REPORT_CAPTURE\"\n",
                encoding="utf-8",
            )
            browser_path.chmod(0o755)
            environment = dict(os.environ, BROWSER=str(browser_path), REPORT_CAPTURE=str(capture_path))

            subprocess.run([str(launcher_path)], env=environment, check=True, capture_output=True, text=True)

            self.assertTrue(os.access(launcher_path, os.X_OK))
            opened_reports = capture_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(opened_reports))
            self.assertTrue(all(path.endswith("/20260716_140000_000001.html") for path in opened_reports))
            self.assertTrue(all("index.html" not in path for path in opened_reports))


if __name__ == "__main__":
    unittest.main()
