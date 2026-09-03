import datetime
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib import simmer_results


class SimmerResultsTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name
        self.rcfg = SimpleNamespace(
            proj_dir=self.project_dir,
            regression_dir=self.project_dir,
            options=SimpleNamespace(no_compile=False),
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _completed_run(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        run["tests"] = [{
            "status": "PASSED",
            "cmp_log": "cmp.log",
            "stdout_log": "stdout.log",
            "waves": {
                "enabled": False,
            },
        }]
        simmer_results.finalize_run(run)
        return run

    def _save_history_run(self, bench, test, status):
        run = simmer_results.create_run(["simmer", "-t", "{}:{}".format(bench, test)], self.rcfg, 1)
        run["tests"] = [{
            "bench": bench,
            "test": test,
            "status": status,
            "simulation_started": True,
            "cmp_log": "{}/cmp.log".format(bench),
            "stdout_log": "{}/{}.log".format(bench, test),
            "waves": {
                "enabled": False
            },
        }]
        simmer_results.finalize_run(run)
        simmer_results.save_run(self.project_dir, run)
        return run

    def _write_legacy_store(self, runs):
        path = Path(simmer_results.legacy_results_path(self.project_dir))
        path.write_text(
            json.dumps({
                "schema_version": simmer_results.SCHEMA_VERSION,
                "last_run": runs[-1] if runs else None,
                "runs": runs,
            }),
            encoding="utf-8",
        )
        return path

    def test_run_ids_are_unique(self):
        self.assertNotEqual(self._completed_run()["run_id"], self._completed_run()["run_id"])

    def test_current_store_schema_records_interrupted_results(self):
        self.assertEqual(5, simmer_results.SCHEMA_VERSION)
        self.assertEqual(5, simmer_results.load_store(self.project_dir)["schema_version"])

        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        run["tests"] = [{"status": "INTERRUPTED"}]
        simmer_results.finalize_run(run)
        simmer_results.save_run(self.project_dir, run)

        self.assertEqual("INTERRUPTED", run["status"])
        store = simmer_results.load_store(self.project_dir)
        self.assertEqual(5, store["schema_version"])
        self.assertEqual(1, store["last_run"]["summary"]["interrupted"])

    def test_concurrent_saves_preserve_both_runs(self):
        runs = [self._completed_run(), self._completed_run()]
        errors = []

        def save(run):
            try:
                simmer_results.save_run(self.project_dir, run)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=save, args=(run, )) for run in runs]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual([], errors)
        self.assertEqual(2, len(simmer_results.load_store(self.project_dir)["runs"]))

    def test_corrupt_history_is_reported_and_preserved(self):
        path = Path(simmer_results.results_path(self.project_dir))
        path.parent.mkdir(parents=True)
        path.write_text("{broken", encoding="utf-8")

        self.assertIn("Unable to read simmer history", simmer_results.format_history(self.project_dir, 10))
        simmer_results.save_run(self.project_dir, self._completed_run())

        backups = list(path.parent.glob(path.name + ".corrupt.*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("{broken", backups[0].read_text(encoding="utf-8"))
        self.assertEqual(1, len(json.loads(path.read_text(encoding="utf-8"))["runs"]))

    def test_history_tolerates_semantically_invalid_persisted_fields(self):
        run = self._completed_run()
        run.update({
            "planned_tests": "not-an-int",
            "summary": {
                "total": "not-an-int",
                "passed": "also-bad",
                "failed": [],
            },
            "tests": [{
                "bench": [],
                "status": "PASSED",
                "waves": "not-a-mapping",
            }],
            "compile": [{
                "bench": {},
            }],
            "timing": "not-a-mapping",
            "benches": "not-a-list",
        })
        path = Path(simmer_results.results_path(self.project_dir))
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({
                "schema_version": simmer_results.SCHEMA_VERSION,
                "last_run": run,
                "runs": [run],
            }),
            encoding="utf-8",
        )

        history = simmer_results.format_history(self.project_dir, 10, use_color=False)

        self.assertIn(run["command"], history)
        self.assertIn("[compile - | simulate -]", history)
        self.assertEqual(
            "No matching simmer history found.",
            simmer_results.format_history(self.project_dir, 10, use_color=False, bench="missing"),
        )

    def test_history_is_stored_under_simmer_directory(self):
        simmer_results.save_run(self.project_dir, self._completed_run())

        path = Path(simmer_results.results_path(self.project_dir))
        self.assertEqual(Path(self.project_dir) / ".simmer" / "results.json", path)
        self.assertTrue(path.exists())

    def test_legacy_history_migrates_when_read(self):
        run = self._completed_run()
        legacy_path = self._write_legacy_store([run])

        store = simmer_results.load_store(self.project_dir)

        self.assertEqual([run["run_id"]], [item["run_id"] for item in store["runs"]])
        self.assertTrue(Path(simmer_results.results_path(self.project_dir)).exists())
        self.assertFalse(legacy_path.exists())

    def test_legacy_and_current_history_merge_without_duplicate_runs(self):
        older = self._completed_run()
        older["started_at"] = "2026-08-01 10:00:00"
        older["finished_at"] = "2026-08-01 10:01:00"
        current = self._completed_run()
        current["started_at"] = "2026-08-02 10:00:00"
        current["finished_at"] = "2026-08-02 10:01:00"
        simmer_results.save_run(self.project_dir, current)
        duplicate = dict(current)
        duplicate["command"] = "legacy duplicate"
        self._write_legacy_store([older, duplicate])

        store = simmer_results.load_store(self.project_dir)

        self.assertEqual([older["run_id"], current["run_id"]], [run["run_id"] for run in store["runs"]])
        self.assertEqual(current["command"], store["last_run"]["command"])

    def test_corrupt_legacy_history_is_preserved_during_migration(self):
        legacy_path = Path(simmer_results.legacy_results_path(self.project_dir))
        legacy_path.write_text("{broken", encoding="utf-8")

        self.assertEqual([], simmer_results.load_store(self.project_dir)["runs"])

        backups = list(legacy_path.parent.glob(legacy_path.name + ".corrupt.*"))
        self.assertEqual(1, len(backups))
        self.assertEqual("{broken", backups[0].read_text(encoding="utf-8"))

    def test_backend_finalize_failure_takes_precedence_over_partial(self):
        run = self._completed_run()
        run["planned_tests"] = 2

        simmer_results.finalize_run(run, backend_finalize_failed=True)

        self.assertEqual("FAILED", run["status"])

    def test_backend_finalize_failure_with_no_tests_is_failed(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 0)

        simmer_results.finalize_run(run, backend_finalize_failed=True)

        self.assertEqual("FAILED", run["status"])

    def test_result_duration_is_simulator_time_and_retains_job_wall_time(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=SimpleNamespace(
                name="tb",
                bazel_vcomp_target="//tb:tb",
                job_dir="compile",
                log_path="cmp.log",
            ),
            name="test",
            target="//tb:test",
            iteration=1,
            seed=7,
            jobstatus=SimpleNamespace(name="PASSED"),
            duration_s=19.8,
            simulation_duration_s=7,
            job_dir="sim",
            _log_path="stdout.log",
            error_message=None,
        )

        simmer_results.record_test_job(run, test_job)

        self.assertEqual(7, run["tests"][0]["duration_s"])
        self.assertEqual(19.8, run["tests"][0]["wall_duration_s"])

    def test_interrupted_job_wall_duration_uses_live_interval_without_mutating_job(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        started_at = datetime.datetime(2026, 8, 7, 10, 0, 0)
        stopped_at = started_at + datetime.timedelta(seconds=9.5)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=SimpleNamespace(
                name="tb",
                bazel_vcomp_target="//tb:tb",
                job_dir="compile",
                log_path="cmp.log",
            ),
            name="test",
            target="//tb:test",
            iteration=1,
            seed=7,
            jobstatus=SimpleNamespace(name="INTERRUPTED"),
            duration_s=0,
            simulation_duration_s=None,
            job_dir="sim",
            _log_path="stdout.log",
            error_message=None,
            job_start_time=started_at,
            job_stop_time=None,
        )

        class FrozenDateTime(datetime.datetime):

            @classmethod
            def now(cls, tz=None):
                return stopped_at

        with mock.patch.object(simmer_results.datetime, "datetime", FrozenDateTime):
            simmer_results.record_test_job(run, test_job, simulation_started=True)

        self.assertEqual(9.5, run["tests"][0]["wall_duration_s"])
        self.assertIsNone(test_job.job_stop_time)

    def test_interrupted_compile_wall_duration_uses_live_interval(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        started_at = datetime.datetime(2026, 8, 7, 10, 0, 0)
        stopped_at = started_at + datetime.timedelta(seconds=4.25)
        vcomp = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            jobstatus=SimpleNamespace(name="INTERRUPTED"),
            job_dir="compile",
            log_path="cmp.log",
            duration_s=0,
            compile_metrics={},
            error_message=None,
            job_start_time=started_at,
            job_stop_time=None,
        )

        class FrozenDateTime(datetime.datetime):

            @classmethod
            def now(cls, tz=None):
                return stopped_at

        with mock.patch.object(simmer_results.datetime, "datetime", FrozenDateTime):
            simmer_results.record_compile_job(run, vcomp)

        self.assertEqual(4.25, run["compile"][0]["duration_s"])
        self.assertIsNone(vcomp.job_stop_time)

    def test_interrupted_summary_formats_mixed_counts_and_actionable_details(self):
        run = {
            "summary": {
                "total": 4,
                "passed": 1,
                "failed": 1,
                "interrupted": 1,
                "skipped": 1,
            },
            "tests": [
                {
                    "bench": "tb",
                    "test": "pass",
                    "status": "PASSED",
                    "stdout_log": "pass.log",
                },
                {
                    "bench": "tb",
                    "test": "fail",
                    "status": "FAILED",
                    "iteration": 2,
                    "seed": 17,
                    "wall_duration_s": 19.8,
                    "duration_s": 7,
                    "stdout_log": "fail.log",
                    "cmp_log": "cmp-fail.log",
                    "waves": {
                        "enabled": True,
                        "path": "fail.fsdb",
                        "run_script": "fail-wave.sh",
                    },
                },
                {
                    "bench": "tb",
                    "test": "stop",
                    "status": "INTERRUPTED",
                    "iteration": 3,
                    "seed": 23,
                    "wall_duration_s": 4,
                    "duration_s": None,
                    "stdout_log": "stop.log",
                    "cmp_log": "cmp-stop.log",
                    "waves": {
                        "enabled": True,
                        "path": "partial.fsdb",
                        "run_script": "stop-wave.sh",
                    },
                },
            ],
            "compile": [],
            "regression_log":
            "regression.log",
        }

        summary = simmer_results.format_interrupted_summary(run, reason="SIGTERM", shutdown_complete=False)

        self.assertIn("reason: SIGTERM", summary)
        self.assertIn("WARNING: shutdown incomplete", summary)
        self.assertIn("tests: total=4 passed=1 failed=1 interrupted=1 not-run=1", summary)
        self.assertIn("FAILED tb:fail iteration=2 seed=17 wall=00:00:19 sim=00:00:07", summary)
        self.assertIn("INTERRUPTED tb:stop iteration=3 seed=23 wall=00:00:04 sim=-", summary)
        self.assertIn("stdout log: fail.log", summary)
        self.assertIn("cmp log: cmp-fail.log", summary)
        self.assertIn("waves: path=fail.fsdb run_script=fail-wave.sh", summary)
        self.assertIn("waves: path=partial.fsdb run_script=stop-wave.sh", summary)
        self.assertIn("regression log: regression.log", summary)
        self.assertNotIn("pass.log", summary)
        self.assertNotIn("all simulations stopped", summary.lower())
        self.assertNotIn("integrity verified", summary.lower())

    def test_interrupted_summary_includes_compile_failures_without_tests(self):
        run = {
            "planned_tests":
            0,
            "tests": [],
            "compile": [
                {
                    "bench": "tb",
                    "vcomp_target": "//tb:tb",
                    "status": "FAILED",
                    "duration_s": 3,
                    "cmp_log": "compile.log",
                    "error_message": "compile failed",
                },
                {
                    "bench": "tb2",
                    "vcomp_target": "//tb2:tb2",
                    "status": "INTERRUPTED",
                    "duration_s": None,
                    "cmp_log": "compile-stop.log",
                },
            ],
        }

        summary = simmer_results.format_interrupted_summary(run)

        self.assertIn("tests: total=0 passed=0 failed=0 interrupted=0 not-run=0", summary)
        self.assertIn("compile details:", summary)
        self.assertIn("FAILED bench=tb target=//tb:tb elapsed=00:00:03", summary)
        self.assertIn("INTERRUPTED bench=tb2 target=//tb2:tb2 elapsed=-", summary)
        self.assertIn("cmp log: compile.log", summary)
        self.assertIn("cmp log: compile-stop.log", summary)
        self.assertIn("error: compile failed", summary)

    def test_interrupted_summary_handles_none_empty_and_missing_data(self):
        unknown = simmer_results.format_interrupted_summary(None)
        empty = simmer_results.format_interrupted_summary({})
        missing = simmer_results.format_interrupted_summary({
            "tests": [{
                "status": "FAILED",
                "simulation_started": False,
                "_elapsed_interval_s": [0, 12],
            }],
        })

        self.assertIn("tests: total=- passed=- failed=- interrupted=- not-run=-", unknown)
        self.assertIn("tests: total=0 passed=0 failed=0 interrupted=0 not-run=0", empty)
        self.assertIn("FAILED -:- iteration=- seed=- wall=00:00:12 sim=-", missing)
        self.assertIn("stdout log: -", missing)
        self.assertIn("cmp log: -", missing)
        unmeasured = simmer_results.format_interrupted_summary({
            "tests": [{
                "status": "INTERRUPTED",
                "simulation_started": True,
                "_elapsed_interval_s": [0, 12],
            }],
        })
        self.assertIn("wall=00:00:12 sim=-", unmeasured)

    def test_missing_simulator_duration_does_not_report_setup_time_as_simulation(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=SimpleNamespace(
                name="tb",
                bazel_vcomp_target="//tb:tb",
                job_dir="compile",
                log_path="cmp.log",
            ),
            name="test",
            target="//tb:test",
            iteration=1,
            seed=None,
            jobstatus=SimpleNamespace(name="FAILED"),
            duration_s=19.8,
            simulation_duration_s=None,
            job_dir="sim",
            _log_path="stdout.log",
            error_message="setup failed",
        )

        simmer_results.record_test_job(run, test_job)

        self.assertIsNone(run["tests"][0]["duration_s"])
        self.assertEqual(19.8, run["tests"][0]["wall_duration_s"])
        self.assertFalse(run["tests"][0]["simulation_started"])
        simmer_results.finalize_run(run)
        self.assertFalse(simmer_results.save_run(self.project_dir, run))

    def test_compile_failure_without_started_test_is_not_saved(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        run["compile"] = [{
            "bench": "tb",
            "vcomp_target": "//tb:tb",
            "status": "FAILED",
            "compile_dir": "compile",
            "cmp_log": "cmp.log",
        }]
        simmer_results.finalize_run(run)

        saved = simmer_results.save_run(self.project_dir, run)

        self.assertEqual("COMPILE_FAILED", run["status"])
        self.assertFalse(saved)
        self.assertEqual([], simmer_results.load_store(self.project_dir)["runs"])
        self.assertEqual("No simmer history found.", simmer_results.format_history(self.project_dir, 10))

    def test_compile_record_preserves_optional_performance_metrics(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        vcomp = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            jobstatus=SimpleNamespace(name="PASSED"),
            job_dir="compile",
            log_path="cmp.log",
            duration_s=12.8,
            compile_metrics={
                "partcomp_jobs": 4,
                "compile_cache_hit": True
            },
            error_message=None,
        )

        simmer_results.record_compile_job(run, vcomp)

        self.assertEqual(12.8, run["compile"][0]["duration_s"])
        self.assertEqual(4, run["compile"][0]["metrics"]["partcomp_jobs"])

        simmer_results.record_compile_job(run, vcomp, status="INTERRUPTED")
        self.assertEqual("INTERRUPTED", run["compile"][0]["status"])

    def test_history_formats_single_run_elapsed_times(self):
        started_at = datetime.datetime(2026, 8, 6, 10, 30, 0)
        run = simmer_results.create_run(["simmer", "-t", "tb:test"], self.rcfg, 1)
        vcomp = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            jobstatus=SimpleNamespace(name="PASSED"),
            job_dir="compile",
            log_path="cmp.log",
            duration_s=82.8,
            compile_metrics={"compile_cache_hit": False},
            error_message=None,
            job_start_time=started_at,
            job_stop_time=started_at + datetime.timedelta(seconds=82.8),
        )
        test_started_at = started_at + datetime.timedelta(seconds=90)
        test_job = SimpleNamespace(
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            vcomper=vcomp,
            name="test",
            target="//tb:test",
            iteration=1,
            seed=7,
            jobstatus=SimpleNamespace(name="PASSED"),
            duration_s=140.9,
            simulation_duration_s=138.4,
            job_dir="sim",
            _log_path="stdout.log",
            error_message=None,
            job_start_time=test_started_at,
            job_stop_time=test_started_at + datetime.timedelta(seconds=140.9),
        )

        simmer_results.record_compile_job(run, vcomp)
        simmer_results.record_test_job(run, test_job)
        simmer_results.finalize_run(run)
        simmer_results.save_run(self.project_dir, run)

        self.assertEqual(82.8, run["timing"]["compile_elapsed_s"])
        self.assertEqual(140.9, run["timing"]["simulate_elapsed_s"])
        history = simmer_results.format_history(self.project_dir, 10, use_color=False)
        heading = history.splitlines()[0]
        self.assertNotIn("1/1", heading)
        self.assertNotIn("[tests:", heading)
        self.assertIn("[compile 00:01:22 | simulate 00:02:20]", history)

    def test_regression_elapsed_time_unions_parallel_job_intervals(self):
        started_at = datetime.datetime(2026, 8, 6, 10, 30, 0)
        run = simmer_results.create_run(["simmer", "-t", "tb:*@2"], self.rcfg, 2)

        def make_vcomp(name, start_s, stop_s):
            return SimpleNamespace(
                name=name,
                bazel_vcomp_target="//{}:{}".format(name, name),
                jobstatus=SimpleNamespace(name="PASSED"),
                job_dir="compile/{}".format(name),
                log_path="compile/{}/cmp.log".format(name),
                duration_s=stop_s - start_s,
                compile_metrics={"compile_cache_hit": False},
                error_message=None,
                job_start_time=started_at + datetime.timedelta(seconds=start_s),
                job_stop_time=started_at + datetime.timedelta(seconds=stop_s),
            )

        def make_test(vcomp, name, iteration, start_s, stop_s):
            return SimpleNamespace(
                rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
                vcomper=vcomp,
                name=name,
                target="//tests:{}".format(name),
                iteration=iteration,
                seed=iteration,
                jobstatus=SimpleNamespace(name="PASSED"),
                duration_s=stop_s - start_s,
                simulation_duration_s=stop_s - start_s,
                job_dir="sim/{}".format(name),
                _log_path="sim/{}/stdout.log".format(name),
                error_message=None,
                job_start_time=started_at + datetime.timedelta(seconds=start_s),
                job_stop_time=started_at + datetime.timedelta(seconds=stop_s),
            )

        first_vcomp = make_vcomp("tb_a", 0, 10)
        second_vcomp = make_vcomp("tb_b", 5, 15)
        simmer_results.record_compile_job(run, first_vcomp)
        simmer_results.record_compile_job(run, second_vcomp)
        simmer_results.record_test_job(run, make_test(first_vcomp, "first", 1, 20, 50))
        simmer_results.record_test_job(run, make_test(second_vcomp, "second", 2, 30, 70))

        simmer_results.finalize_run(run)

        self.assertEqual(15.0, run["timing"]["compile_elapsed_s"])
        self.assertEqual(50.0, run["timing"]["simulate_elapsed_s"])

    def test_history_labels_multi_test_result_counts(self):
        run = simmer_results.create_run(["simmer", "-t", "tb:*@4"], self.rcfg, 4)
        run["tests"] = [
            {
                "status": "PASSED",
                "simulation_started": True,
                "stdout_log": "pass.log",
            },
            {
                "status": "FAILED",
                "simulation_started": True,
                "stdout_log": "fail.log",
            },
            {
                "status": "INTERRUPTED",
                "simulation_started": True,
                "stdout_log": "interrupted.log",
            },
        ]

        simmer_results.finalize_run(run, regression_log_path="regression.log")
        simmer_results.save_run(self.project_dir, run)

        history = simmer_results.format_history(self.project_dir, 10, use_color=False)
        self.assertIn(
            "FAILED  [tests: 1 passed | 1 failed | 1 interrupted | 1 skipped]  "
            "[compile - | simulate -]",
            history,
        )

    def test_history_preserves_submission_command_and_lsf_location(self):
        run = simmer_results.create_run(
            ["simmer", "-t", "tb:test"],
            self.rcfg,
            1,
            run_context={
                "command": "bsub -I -q syn simmer -t tb:test",
                "lsf": {
                    "job_id": "851247",
                    "display_job_id": "851247",
                    "queue": "syn",
                    "host": "sh-cloud17",
                    "submit_host": "login02",
                },
            },
        )
        run["tests"] = [{
            "status": "PASSED",
            "simulation_started": True,
            "cmp_log": "cmp.log",
            "stdout_log": "stdout.log",
            "waves": {
                "enabled": False
            },
        }]
        simmer_results.finalize_run(run)
        simmer_results.save_run(self.project_dir, run)

        history = simmer_results.format_history(self.project_dir, 10, use_color=False)

        self.assertIn("cmd:     bsub -I -q syn simmer -t tb:test", history)
        self.assertIn("lsf:     job 851247 | queue syn | host sh-cloud17 | submit login02", history)
        self.assertNotIn("bkill", history)

    def test_history_marks_explicit_and_automatic_compile_reuse(self):
        for explicit_reuse in (False, True):
            with self.subTest(explicit_reuse=explicit_reuse), tempfile.TemporaryDirectory() as project_dir:
                rcfg = SimpleNamespace(
                    proj_dir=project_dir,
                    regression_dir=project_dir,
                    options=SimpleNamespace(no_compile=explicit_reuse),
                )
                run = simmer_results.create_run(["simmer", "-t", "tb:test"], rcfg, 1)
                if not explicit_reuse:
                    run["compile"] = [{
                        "status": "PASSED",
                        "metrics": {
                            "compile_cache_hit": True
                        },
                        "cmp_log": "cmp.log",
                    }]
                run["tests"] = [{
                    "status": "PASSED",
                    "cmp_log": "cmp.log",
                    "stdout_log": "stdout.log",
                    "waves": {
                        "enabled": False
                    },
                    "_elapsed_interval_s": [0.0, 43.9],
                }]

                simmer_results.finalize_run(run)
                simmer_results.save_run(project_dir, run)

                history = simmer_results.format_history(project_dir, 10, use_color=False)
                self.assertIn("[compile reused | simulate 00:00:43]", history)

    def test_history_without_timing_fields_remains_readable(self):
        run = self._completed_run()
        run.pop("timing")

        simmer_results.save_run(self.project_dir, run)

        history = simmer_results.format_history(self.project_dir, 10, use_color=False)
        self.assertIn("[compile - | simulate -]", history)

    def test_history_displays_latest_last_with_descending_recency_numbers(self):
        self._save_history_run("tb", "oldest", "PASSED")
        self._save_history_run("tb", "middle", "FAILED")
        self._save_history_run("tb", "newest", "PASSED")

        history = simmer_results.format_history(self.project_dir, 2, use_color=False)
        entries = history.split("\n\n{}\n\n".format(simmer_results.HISTORY_SEPARATOR))

        self.assertEqual(2, len(entries))
        self.assertTrue(entries[0].startswith("[2] "))
        self.assertIn("tb:middle", entries[0])
        self.assertTrue(entries[1].startswith("[1] "))
        self.assertIn("tb:newest", entries[1])
        self.assertNotIn("tb:oldest", history)
        self.assertEqual(1, history.count(simmer_results.HISTORY_SEPARATOR))

    def test_single_history_entry_has_no_separator(self):
        self._save_history_run("tb", "only", "PASSED")

        history = simmer_results.format_history(self.project_dir, 10, use_color=False)

        self.assertTrue(history.startswith("[1] "))
        self.assertNotIn(simmer_results.HISTORY_SEPARATOR, history)

    def test_history_filters_by_bench_and_failure_before_limiting(self):
        failed_a = self._save_history_run("tb_a", "failed_a", "FAILED")
        self._save_history_run("tb_b", "failed_b", "FAILED")
        self._save_history_run("tb_a", "passed_a", "PASSED")

        self.assertEqual(["tb_a"], failed_a["benches"])

        failed_history = simmer_results.format_history(
            self.project_dir,
            1,
            use_color=False,
            failed_only=True,
        )
        self.assertIn("tb_b:failed_b", failed_history)
        self.assertNotIn("tb_a:passed_a", failed_history)
        self.assertNotIn("tb_a:failed_a", failed_history)

        bench_history = simmer_results.format_history(
            self.project_dir,
            10,
            use_color=False,
            bench="tb_a",
        )
        self.assertIn("tb_a:failed_a", bench_history)
        self.assertIn("tb_a:passed_a", bench_history)
        self.assertNotIn("tb_b:failed_b", bench_history)

        combined_history = simmer_results.format_history(
            self.project_dir,
            10,
            use_color=False,
            bench="tb_a",
            failed_only=True,
        )
        self.assertIn("tb_a:failed_a", combined_history)
        self.assertNotIn("tb_a:passed_a", combined_history)
        self.assertNotIn("tb_b:failed_b", combined_history)

    def test_history_bench_filter_falls_back_for_old_records(self):
        run = self._save_history_run("legacy_tb", "smoke", "PASSED")
        store_path = Path(simmer_results.results_path(self.project_dir))
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["last_run"].pop("benches")
        store["runs"][0].pop("benches")
        store_path.write_text(json.dumps(store), encoding="utf-8")

        history = simmer_results.format_history(self.project_dir, 10, use_color=False, bench="legacy_tb")

        self.assertIn(run["command"], history)

    def test_history_filters_report_no_matches(self):
        self._save_history_run("tb", "passed", "PASSED")

        self.assertEqual(
            "No matching simmer history found.",
            simmer_results.format_history(self.project_dir, 10, bench="missing"),
        )
        self.assertEqual(
            "No matching simmer history found.",
            simmer_results.format_history(self.project_dir, 10, failed_only=True),
        )

    def test_multi_test_history_keeps_summary_and_one_representative_test(self):
        run = self._completed_run()
        run["planned_tests"] = 3
        run["tests"] = [
            {
                "status": "PASSED",
                "stdout_log": "pass.log"
            },
            {
                "status": "FAILED",
                "stdout_log": "fail.log"
            },
            {
                "status": "PASSED",
                "stdout_log": "pass2.log"
            },
        ]
        run["summary"] = {"passed": 2, "failed": 1, "skipped": 0, "total": 3}

        simmer_results.save_run(self.project_dir, run)

        stored = simmer_results.load_store(self.project_dir)["last_run"]
        self.assertEqual(run["summary"], stored["summary"])
        self.assertEqual(["fail.log"], [test["stdout_log"] for test in stored["tests"]])

    def test_multi_test_history_prefers_interrupted_test_over_passed_test(self):
        run = self._completed_run()
        run["planned_tests"] = 2
        run["tests"] = [
            {
                "status": "PASSED",
                "stdout_log": "pass.log"
            },
            {
                "status": "INTERRUPTED",
                "stdout_log": "interrupted.log"
            },
        ]

        simmer_results.save_run(self.project_dir, run)

        stored = simmer_results.load_store(self.project_dir)["last_run"]
        self.assertEqual("interrupted.log", stored["tests"][0]["stdout_log"])

    def test_record_test_job_updates_existing_iteration(self):
        run = simmer_results.create_run(["simmer"], self.rcfg, 1)
        test_job = SimpleNamespace(
            duration_s=1,
            error_message=None,
            iteration=2,
            job_dir="sim",
            jobstatus=SimpleNamespace(name="PASSED"),
            name="smoke",
            rcfg=SimpleNamespace(options=SimpleNamespace(waves=None)),
            seed=17,
            simulation_duration_s=1,
            target="//tests:smoke",
            vcomper=SimpleNamespace(
                bazel_vcomp_target="//tb:top",
                job_dir="compile",
                log_path="cmp.log",
                name="top",
            ),
            _log_path="stdout.log",
        )
        simmer_results.record_test_job(run, test_job)
        test_job.error_message = "post-processing failed"
        test_job.jobstatus = SimpleNamespace(name="FAILED")
        simmer_results.record_test_job(run, test_job)

        self.assertEqual(1, len(run["tests"]))
        self.assertEqual("FAILED", run["tests"][0]["status"])
        self.assertEqual("post-processing failed", run["tests"][0]["error_message"])


if __name__ == "__main__":
    unittest.main()
