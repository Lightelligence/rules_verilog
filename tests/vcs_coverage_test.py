import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from args_parser import parse_args
import simmer
from lib import compile_cache
from lib.cmn_logging import CmnLogger
from lib.job_lib import JobStatus
from lib.simulators.vcs import VcsSimulator


class VcsCoverageTest(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.options = parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--no-vcs-partcomp"])
        self.rcfg = SimpleNamespace(options=self.options,
                                    regression_dir=str(self.root),
                                    proj_dir=str(self.root),
                                    log=CmnLogger("vcs-coverage-test"),
                                    deferred_messages=[])
        self.simulator = VcsSimulator(self.options, self.rcfg, None)
        self.vcomp = SimpleNamespace(name="tb",
                                     job_dir=str(self.root / "compile"),
                                     cov_work_dir=str(self.root / "work.vdb"),
                                     coverage_merge_script=str(self.root / "merge.sh"),
                                     merged_coverage_dir=str(self.root / "merged.vdb"),
                                     coverage_report_dir=str(self.root / "report"))

    @staticmethod
    def _model(path):
        model = Path(path) / "snps" / "coverage" / "db" / "design" / "model.xml"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("<coverage-model/>", encoding="utf-8")
        return model

    def _outputs(self, summary="SCORE LINE\n90.00 80.00\n"):
        self._model(self.vcomp.merged_coverage_dir)
        report = Path(self.vcomp.coverage_report_dir)
        report.mkdir(parents=True, exist_ok=True)
        (report / "dashboard.txt").write_text(summary, encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _merge(self):
        return self.simulator.run_report_coverage_merge({"//bench:tb": self.vcomp})

    def _test(self, target, directory="run", run_id=None):
        return SimpleNamespace(name=target.split(":")[1],
                               target=target,
                               iteration=1,
                               vcomper=self.vcomp,
                               job_dir=str(self.root / directory),
                               vso_run_id=run_id)

    def test_distinct_tests_with_equal_vso_seeds_keep_independent_data(self):
        self.options.vso = True
        tests = [self._test("//bench/tests/a:smoke"), self._test("//bench/tests/b:smoke")]
        for index, test in enumerate(tests):
            test.icfg = SimpleNamespace(backend_assignments=[{"run_id": str(index), "seed": "42"}])
            seed = self.simulator.prepare_test_job(test)
            self.simulator.generate_sim_options(test, seed)
            Path(test.coverage_db_path).mkdir(parents=True)
        self.assertNotEqual(tests[0].coverage_db_path, tests[1].coverage_db_path)
        self.simulator.cleanup_test_coverage(tests[1])
        self.assertTrue(Path(tests[0].coverage_db_path).is_dir())
        self.assertFalse(Path(tests[1].coverage_db_path).exists())

    def test_claimed_run_directories_distinguish_otherwise_equal_runs(self):
        first, second = self._test("//bench/tests:smoke", "run"), self._test("//bench/tests:smoke", "run__2")
        self.simulator.generate_sim_options(first, 42)
        self.simulator.generate_sim_options(second, 42)
        self.assertNotEqual(first.coverage_db_path, second.coverage_db_path)

    def test_coverage_name_is_bounded_and_contains_no_path_separator(self):
        test = self._test("//bench/tests:nested/" + "x" * 500)
        argv = shlex.split(self.simulator.generate_sim_options(test, 42))
        name = argv[argv.index("-cm_name") + 1]
        self.assertLess(len(name.encode("utf-8")), 255)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)
        self.assertTrue(name.endswith("_sv42_i1"))

    def test_failed_test_callback_removes_data_and_releases_directory(self):
        test = simmer.TestJob.__new__(simmer.TestJob)
        test.rcfg = SimpleNamespace(simmer_results_run=None)
        test._jobstatus = JobStatus.FAILED
        test.simulator = self.simulator
        test.vcomper = self.vcomp
        test.coverage_db_path = str(self.root / "testdata")
        Path(test.coverage_db_path).mkdir()
        test._run_directory_lock = mock.Mock()
        lock = test._run_directory_lock
        test.post_run_failed(OSError("log statistics unavailable"))
        self.assertFalse(Path(test.coverage_db_path).exists())
        lock.release.assert_called_once()
        self.assertEqual("log statistics unavailable", test.error_message)

    def test_cleanup_permission_error_blocks_merge(self):
        test = self._test("//bench/tests:smoke")
        self.simulator.generate_sim_options(test, 42)
        path = Path(test.coverage_db_path)
        path.mkdir(parents=True)
        (path / "data").write_text("failed test data", encoding="utf-8")
        with mock.patch("os.unlink", side_effect=PermissionError("fixture permission denied")):
            with self.assertRaises(PermissionError):
                self.simulator.cleanup_test_coverage(test)
        self.assertTrue(self.vcomp.coverage_cleanup_failed)
        with mock.patch("lib.simulators.vcs.run_bounded_process") as run:
            self.assertTrue(self._merge())
        run.assert_not_called()
        self.assertTrue(path.exists())

    def test_failed_cleanup_still_records_failure_and_releases_directory(self):
        test = simmer.TestJob.__new__(simmer.TestJob)
        test.rcfg = SimpleNamespace(simmer_results_run={})
        test.simulator = mock.Mock()
        test.simulator.cleanup_test_coverage.side_effect = OSError("cleanup denied")
        test._run_directory_lock = mock.Mock()
        lock = test._run_directory_lock
        with mock.patch("simmer.simmer_results.record_test_job") as record:
            with self.assertRaisesRegex(OSError, "cleanup denied"):
                test.post_run_failed(OSError("statistics failed"))
        record.assert_called_once()
        lock.release.assert_called_once()

    def test_reuse_cleanup_preserves_model_but_removes_previous_testdata(self):
        model = self._model(self.vcomp.cov_work_dir)
        testdata = Path(self.vcomp.cov_work_dir) / "snps" / "coverage" / "db" / "testdata"
        testdata.mkdir()
        (testdata / "previous").write_text("stale coverage", encoding="utf-8")
        self.simulator.prepare_compile_execution(self.vcomp, reusing_compile=True)
        self.assertTrue(model.is_file())
        self.assertFalse(testdata.exists())
        self.assertFalse(self.vcomp.coverage_cleanup_failed)

    def test_reuse_cleanup_error_is_not_silently_accepted(self):
        self._model(self.vcomp.cov_work_dir)
        testdata = Path(self.vcomp.cov_work_dir) / "snps" / "coverage" / "db" / "testdata"
        testdata.mkdir()
        (testdata / "previous").write_text("stale coverage", encoding="utf-8")
        with mock.patch("os.unlink", side_effect=PermissionError("fixture permission denied")):
            with self.assertRaises(PermissionError):
                self.simulator.prepare_compile_execution(self.vcomp, reusing_compile=True)
        self.assertTrue(self.vcomp.coverage_cleanup_failed)
        self.assertTrue(testdata.exists())

    def test_inaccessible_cleanup_path_is_not_treated_as_missing(self):
        with mock.patch("os.lstat", side_effect=PermissionError("fixture permission denied")):
            with self.assertRaises(PermissionError):
                self.simulator.prepare_compile_execution(self.vcomp, reusing_compile=True)
        self.assertTrue(self.vcomp.coverage_cleanup_failed)

    def test_coverage_model_missing_empty_or_testdata_only_rejects_cache(self):
        build = Path(self.vcomp.job_dir)
        build.mkdir()
        (build / "simv").write_text("executable fixture", encoding="utf-8")
        os.chmod(build / "simv", 0o755)
        fingerprint = {"identity": "same"}
        compile_cache.write_compile_fingerprint(str(build), fingerprint)
        for stage in ("absent", "empty", "testdata-only"):
            with self.subTest(stage=stage):
                if stage == "empty":
                    model = self._model(self.vcomp.cov_work_dir)
                    model.write_text("", encoding="utf-8")
                elif stage == "testdata-only":
                    testdata = Path(self.vcomp.cov_work_dir) / "snps" / "coverage" / "db" / "testdata"
                    testdata.mkdir()
                    (testdata / "data").write_text("runtime data", encoding="utf-8")
                with self.assertRaisesRegex(FileNotFoundError, "static design model"):
                    self.simulator.validate_reusable_compile_artifacts(self.vcomp)
                hit, _reason = compile_cache.can_reuse_compile(
                    str(build), fingerprint, lambda: self.simulator.validate_reusable_compile_artifacts(self.vcomp))
                self.assertFalse(hit)
        self._model(self.vcomp.cov_work_dir)
        hit, reason = compile_cache.can_reuse_compile(
            str(build), fingerprint, lambda: self.simulator.validate_reusable_compile_artifacts(self.vcomp))
        self.assertTrue(hit, reason)

    def test_success_exit_without_complete_outputs_is_failure(self):
        for outputs in ("absent", "model-only", "bad-summary"):
            with self.subTest(outputs=outputs):

                def run(*_args, **_kwargs):
                    if outputs != "absent":
                        self._model(self.vcomp.merged_coverage_dir)
                    if outputs == "bad-summary":
                        return self._outputs("SCORE LINE\n100.00\n")
                    return SimpleNamespace(returncode=0)

                with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=run):
                    self.assertTrue(self._merge())
                self.assertFalse(self.vcomp.coverage_merge_succeeded)
                self.assertIsNone(self.simulator.collect_coverage_data({"//bench:tb": self.vcomp})["tb"]["total"])

    def test_success_uses_only_new_outputs_without_default_byte_scans(self):
        old_report = Path(self.vcomp.coverage_report_dir)
        old_report.mkdir()
        (old_report / "dashboard.txt").write_text("SCORE LINE\n100.00 100.00\n", encoding="utf-8")
        old_model = self._model(self.vcomp.merged_coverage_dir)
        marker = old_model.parent / "old-marker"
        marker.write_text("old model", encoding="utf-8")
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=lambda *_a, **_k: self._outputs()), \
             mock.patch.object(self.simulator, "_record_coverage_size") as size:
            self.assertFalse(self._merge())
        size.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertTrue(self.vcomp.coverage_merge_succeeded)
        coverage = self.simulator.collect_coverage_data({"//bench:tb": self.vcomp})
        self.assertEqual("80.00%", coverage["tb"]["cc"]["Overall"])
        self.assertGreaterEqual(self.vcomp.coverage_merge_metrics["urg_duration_s"], 0)

    def test_default_times_cleanup_validation_parse_and_total_with_one_urg_call(self):
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=lambda *_a, **_k: self._outputs()) as run:
            self.assertFalse(self._merge())
        run.assert_called_once_with(["bash", self.vcomp.coverage_merge_script], capture_output=True, text=True)
        metrics = self.vcomp.coverage_merge_metrics
        phases = ("output_cleanup", "urg", "model_validation", "dashboard_parse")
        self.assertGreaterEqual(metrics["coverage_total_duration_s"],
                                sum(metrics[phase + "_duration_s"] for phase in phases))
        self.assertNotIn("urg_merge_duration_s", metrics)
        self.assertNotIn("urg_report_duration_s", metrics)

    def test_profile_runs_merge_then_report_and_records_separate_timings(self):
        self.options.vcs_coverage_profile = "phases"
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=lambda *_a, **_k: self._outputs()) as run:
            self.assertFalse(self._merge())
        self.assertEqual(["merge", "report"], [call.args[0][-1] for call in run.call_args_list])
        metrics = self.vcomp.coverage_merge_metrics
        self.assertGreaterEqual(metrics["urg_duration_s"],
                                metrics["urg_merge_duration_s"] + metrics["urg_report_duration_s"])
        self.assertTrue(self.vcomp.coverage_merge_succeeded)

    def test_profile_phase_failures_and_timeouts_keep_timings_and_stop_merge(self):
        self.options.vcs_coverage_profile = "phases"
        for phase in ("merge", "report"):
            for timeout in (False, True):
                with self.subTest(phase=phase, timeout=timeout):

                    def execute(argv, **_kwargs):
                        if argv[-1] == phase:
                            if timeout:
                                raise subprocess.TimeoutExpired(argv, 1)
                            return SimpleNamespace(returncode=1, stdout="partial output", stderr="fixture failure")
                        return self._outputs()

                    with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=execute) as run:
                        self.assertTrue(self._merge())
                    self.assertEqual(1 if phase == "merge" else 2, run.call_count)
                    self.assertFalse(self.vcomp.coverage_merge_succeeded)
                    metrics = self.vcomp.coverage_merge_metrics
                    for metric in ("urg_duration_s", "coverage_total_duration_s", "urg_{}_duration_s".format(phase)):
                        self.assertGreaterEqual(metrics[metric], 0)
                    self.assertNotIn("dashboard_parse_duration_s", metrics)

    def test_cleanup_failure_keeps_cleanup_and_total_timings_without_running_urg(self):
        Path(self.vcomp.coverage_report_dir).mkdir()
        with mock.patch("lib.simulators.vcs.shutil.rmtree", side_effect=PermissionError("cleanup denied")), \
             mock.patch("lib.simulators.vcs.run_bounded_process") as run:
            self.assertTrue(self._merge())
        run.assert_not_called()
        self.assertIn("output_cleanup_duration_s", self.vcomp.coverage_merge_metrics)
        self.assertIn("coverage_total_duration_s", self.vcomp.coverage_merge_metrics)

    def test_all_unavailable_metrics_are_valid_summary_output(self):
        with mock.patch("lib.simulators.vcs.run_bounded_process",
                        side_effect=lambda *_a, **_k: self._outputs("SCORE LINE\nN/A N/A\n")):
            self.assertFalse(self._merge())
        self.assertTrue(self.vcomp.coverage_merge_succeeded)

    def test_failed_compilation_never_merges_previous_data(self):
        self.vcomp.jobstatus = JobStatus.FAILED
        with mock.patch("lib.simulators.vcs.run_bounded_process") as run:
            self.assertTrue(self._merge())
        run.assert_not_called()

    def test_timeout_records_elapsed_time_and_reports_failure(self):
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=subprocess.TimeoutExpired("urg", 1)):
            self.assertTrue(self._merge())
        self.assertGreaterEqual(self.vcomp.coverage_merge_metrics["urg_duration_s"], 0)
        self.assertFalse(self.vcomp.coverage_merge_succeeded)

    def test_byte_inventory_is_opt_in_and_reports_input_and_merged_bytes(self):
        self.options.vcs_coverage_profile = True
        model = self._model(self.vcomp.cov_work_dir)
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=lambda *_a, **_k: self._outputs()):
            self.assertFalse(self._merge())
        metrics = self.vcomp.coverage_merge_metrics
        self.assertEqual(model.stat().st_size, metrics["input_db_bytes"])
        self.assertEqual(model.stat().st_size, metrics["merged_db_bytes"])
        self.assertGreaterEqual(metrics["input_db_bytes_scan_s"], 0)
        self.assertGreaterEqual(metrics["merged_db_bytes_scan_s"], 0)
        self.assertNotIn("urg_merge_duration_s", metrics)

    def test_byte_inventory_failure_does_not_invalidate_valid_merge(self):
        self.vcomp.coverage_merge_metrics = {}
        self._model(self.vcomp.cov_work_dir)
        with mock.patch("os.walk", side_effect=PermissionError("inventory denied")):
            self.simulator._record_coverage_size(self.vcomp, "input_db_bytes", self.vcomp.cov_work_dir)
        self.assertIsNone(self.vcomp.coverage_merge_metrics["input_db_bytes"])

    def test_report_keys_follow_actual_slash_and_analog_job_names(self):
        self._outputs()
        self.vcomp.name = "tb__analog_1234"
        self.vcomp.coverage_merge_succeeded = True
        coverage = self.simulator.collect_coverage_data({"//bench:nested/tb__analog_1234": self.vcomp})
        self.assertEqual([self.vcomp.name], list(coverage))
        self.assertEqual("80.00%", coverage[self.vcomp.name]["cc"]["Line"])
        self.options.cm = None
        self.assertEqual([self.vcomp.name], list(self.simulator.collect_coverage_data({"//bench:nested/tb":
                                                                                       self.vcomp})))

    def test_profile_option_requires_coverage_and_is_vcs_only(self):
        for arguments in (["--simulator", "VCS",
                           "--vcs-coverage-profile"], ["--simulator", "XRUN", "--vcs-coverage-profile"]):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    options = parse_args(arguments)
                    backend = VcsSimulator if options.simulator == "VCS" else simmer.XceliumSimulator
                    backend(options, self.rcfg, None).validate_resolved_options()
        options = parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--vcs-coverage-profile"])
        VcsSimulator(options, self.rcfg, None).validate_resolved_options()
        self.assertTrue(VcsSimulator(options, self.rcfg, None).options.vcs_coverage_profile)
        self.assertEqual("bytes", options.vcs_coverage_profile)
        options = parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--vcs-coverage-profile", "phases"])
        VcsSimulator(options, self.rcfg, None).validate_resolved_options()
        self.assertEqual("phases", options.vcs_coverage_profile)

    def test_report_format_requires_coverage_and_is_vcs_only(self):
        for arguments in (["--simulator", "VCS"], ["--simulator", "XRUN"]):
            for report_format in ("text", "both"):
                with self.subTest(arguments=arguments, report_format=report_format), self.assertRaises(ValueError):
                    options = parse_args(arguments + ["--vcs-urg-format", report_format])
                    backend = VcsSimulator if options.simulator == "VCS" else simmer.XceliumSimulator
                    backend(options, self.rcfg, None).validate_resolved_options()
        for report_format in ("text", "both"):
            options = parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--vcs-urg-format", report_format])
            VcsSimulator(options, self.rcfg, None).validate_resolved_options()
            self.assertEqual(report_format, options.vcs_urg_format)
        with self.assertRaises(SystemExit):
            parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--vcs-urg-format", "html"])


if __name__ == "__main__":
    unittest.main()
