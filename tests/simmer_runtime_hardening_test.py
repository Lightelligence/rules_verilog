import contextlib
import datetime
import os
import multiprocessing
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = REPO_ROOT / "bin"
if str(BIN_DIR) not in sys.path:
    sys.path.insert(0, str(BIN_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from args_parser import parse_args
import simmer
from lib import compile_cache
from lib.job_lib import JobCancelledError, JobStatus
from lib.runtime_options import normalize_test_runtime_options


def _replace_symlink_in_process(link_path, target_path, start, result_queue):
    start.wait(5.0)
    try:
        simmer.replace_symlink(link_path, target_path)
    except Exception as exc:
        result_queue.put(repr(exc))
    else:
        result_queue.put(None)


class _FatalLog:

    def critical(self, message, *args):
        if args:
            message = message % args
        raise SystemExit(message)


class SimmerRuntimeHardeningTest(unittest.TestCase):

    def test_simulation_directory_name_bounds_overlong_utf8_component(self):
        suffix = "_report_rerun_20260808_120000_0123456789abcdef"
        test_name = "long_" + ("测" * 100)

        directory_name = simmer._format_simulation_directory_name("unit_tb", "VCS", test_name, 42, 1, suffix)
        other_name = simmer._format_simulation_directory_name("unit_tb", "VCS", test_name + "x", 42, 1, suffix)

        self.assertLessEqual(len(directory_name.encode("utf-8")), 255)
        self.assertTrue(directory_name.endswith(suffix))
        self.assertNotEqual(directory_name, other_name)
        self.assertEqual(
            directory_name,
            simmer._format_simulation_directory_name("unit_tb", "VCS", test_name, 42, 1, suffix),
        )

    def test_directory_suffix_is_normalized_and_rejects_traversal(self):
        self.assertEqual("_sdf_wc", parse_args(["--dir-suffix", "sdf_wc"]).dir_suffix)
        self.assertEqual("_sdf_wc", parse_args(["--dir-suffix", "_sdf_wc"]).dir_suffix)
        for unsafe_suffix in ("/../../../escape", r"..\..\escape", "../escape", "bad suffix", ".hidden"):
            with self.subTest(unsafe_suffix=unsafe_suffix), self.assertRaises(SystemExit):
                parse_args(["--dir-suffix", unsafe_suffix])

    def test_regression_child_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as regression_dir:
            expected = os.path.realpath(os.path.join(regression_dir, "safe_run"))
            self.assertEqual(expected, simmer._contained_child_path(regression_dir, "safe_run"))
            for component in ("../escape", r"..\escape", ".", ".."):
                with self.subTest(component=component), self.assertRaises(ValueError):
                    simmer._contained_child_path(regression_dir, component)

    def test_bounded_component_retains_collision_suffix(self):
        component = simmer._bounded_filesystem_component("测" * 100, "__run_p1234_2")

        self.assertLessEqual(len(component.encode("utf-8")), 255)
        self.assertTrue(component.endswith("__run_p1234_2"))

    def test_simulator_statistics_are_parsed_independently(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            log_path = Path(temporary_dir) / "stdout.log"
            log_path.write_text(
                "Test Duration: 01:02:03\n"
                "unrelated output\n"
                "Average cycles/sec: 1.25e+06\n",
                encoding="utf-8",
            )
            test_job = simmer.TestJob.__new__(simmer.TestJob)
            test_job._log_path = str(log_path)

            self.assertEqual(("01:02:03", "1.25e+06"), test_job._get_stats_from_log_file())
            self.assertEqual(3723, test_job.net_time)

            log_path.write_text("Average cycles/sec: 1,250\n", encoding="utf-8")
            self.assertEqual((None, "1,250"), test_job._get_stats_from_log_file())

    def test_missing_simulator_statistics_are_omitted(self):
        self.assertEqual(
            "(00:00:31 sim_time / 00:00:30 total_time)",
            simmer._format_time_stats(None, None, "00:00:31", "00:00:30"),
        )

    def test_active_run_snapshot_aggregates_multi_test_state(self):
        finished = mock.Mock(jobstatus=JobStatus.PASSED, job_start_time=datetime.datetime.now())
        active = mock.Mock(jobstatus=JobStatus.NOT_STARTED, job_start_time=datetime.datetime.now())
        queued = mock.Mock(jobstatus=JobStatus.NOT_STARTED, job_start_time=None)
        rcfg = SimpleNamespace(
            all_vcomp={"//tb:tb": ([SimpleNamespace(jobs=[finished, active, queued])], [])},
            options=SimpleNamespace(no_run=False),
        )
        manager = mock.Mock()
        manager.status_snapshot.return_value = {
            "paused": False,
            "queued": (queued, ),
            "launching": (),
            "active": (active, ),
            "finalizing": (),
            "done": (finished, ),
            "skipped": (),
        }
        vcomp = mock.Mock(log_path="/sim/tb/cmp.log")

        state = simmer._active_run_snapshot(rcfg, {"//tb:tb": vcomp}, manager, 3, "/sim/regression.log")

        self.assertEqual("RUNNING", state["status"])
        self.assertEqual(1, state["finished_tests"])
        self.assertEqual(1, state["active_tests"])
        self.assertEqual(1, state["queued_tests"])
        self.assertEqual("/sim/regression.log", state["regression_log"])
        self.assertIsNone(state["result_log"])

    def test_compile_reuse_miss_messages_name_the_selected_simulator(self):
        self.assertEqual(
            "Compile inputs changed (compile_inputs_sha256, compile_script_sha256)",
            simmer.describe_compile_reuse_miss(
                "Compile build fingerprint mismatch in /tmp/vcomp "
                "(changed: compile_inputs_sha256, compile_script_sha256). Recompile this testbench.",
                "XRUN",
            ),
        )
        self.assertEqual(
            "No reusable XRUN compile fingerprint exists",
            simmer.describe_compile_reuse_miss(
                "--no-compile requires /tmp/vcomp/.compile_fingerprint.json. Recompile this testbench first.",
                "XRUN",
            ),
        )
        self.assertEqual(
            "Reusable VCS compile artifacts are missing or incomplete",
            simmer.describe_compile_reuse_miss(
                "VCS --no-compile requires an existing elaborated executable at '/tmp/vcomp/simv'",
                "VCS",
            ),
        )

    def test_get_bazel_bin_fallback_runs_from_project_directory(self):
        completed = SimpleNamespace(returncode=0, stdout="/output/bazel-bin\n", stderr="")
        with mock.patch("simmer.os.path.isdir", return_value=False), \
             mock.patch("simmer.subprocess.run", return_value=completed) as run:
            self.assertEqual("/output/bazel-bin", simmer.get_bazel_bin("/repo"))

        run.assert_called_once_with(
            ["bazel", "info", "bazel-bin"],
            cwd="/repo",
            capture_output=True,
            text=True,
        )

    def test_scheduler_numeric_options_reject_invalid_values(self):
        for arguments in (
            ["--jobs", "0"],
            ["--quit-count", "0"],
            ["--idle-print-seconds", "-1"],
            ["--timeout", "-0.5"],
            ["--history", "0"],
        ):
            with self.subTest(arguments=arguments), self.assertRaises(SystemExit):
                parse_args(arguments)

        self.assertEqual(0, parse_args(["--timeout", "0"]).timeout)

    def test_default_scheduler_limit_uses_host_capacity_not_batch_allocation(self):
        options = SimpleNamespace(gui=False, jobs=None)
        rcfg = SimpleNamespace(
            all_vcomp={"//tb:tb": ([SimpleNamespace(target=100)], [])},
            log=mock.Mock(),
        )
        simulator = SimpleNamespace(get_scheduler_threads_per_test=lambda: 2)

        with mock.patch("simmer.os.cpu_count", return_value=16), \
             mock.patch("simmer.job_lib.detect_allocated_cpus") as detect_allocated_cpus:
            self.assertEqual(8, simmer.get_active_job_limit(options, rcfg, simulator))

        detect_allocated_cpus.assert_not_called()
        rcfg.log.info.assert_called_once_with(
            "Scheduler host CPU capacity: %d; threads per test: %d; parallel job limit: %d",
            16,
            2,
            8,
        )

    def test_history_persistence_failure_is_fatal(self):
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run={
                "run_id": "test",
                "tests": [{
                    "status": "PASSED"
                }]
            },
            log=_FatalLog(),
        )
        with mock.patch("simmer.simmer_results.save_run", side_effect=OSError("disk full")), \
             self.assertRaisesRegex(SystemExit, "Failed to write simmer results"):
            simmer.persist_simmer_results(rcfg)

    def test_interrupted_run_without_started_test_does_not_persist_history(self):
        with tempfile.TemporaryDirectory() as project_dir:
            run = {
                "planned_tests": 1,
                "tests": [],
                "compile": [],
                "launch_failures": [],
            }
            rcfg = SimpleNamespace(
                proj_dir=project_dir,
                simmer_results_run=run,
                log=mock.Mock(),
            )
            simulator = mock.Mock()

            with mock.patch("simmer.simmer_results.save_run") as save_run:
                simmer.finalize_interrupted_run(rcfg, simulator, {"//tb:tb": object()})

            simulator.cleanup_shared_runtime_artifacts.assert_called_once()
            self.assertEqual("FAILED", run["status"])
            self.assertIsNotNone(run["finished_at"])
            save_run.assert_not_called()

    def test_interrupted_history_persistence_failure_is_nonfatal(self):
        run = {
            "planned_tests": 1,
            "tests": [{
                "status": "INTERRUPTED"
            }],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            log=mock.Mock(),
        )

        with mock.patch("simmer.simmer_results.save_run", side_effect=ValueError("invalid history")):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {})

        self.assertEqual("FAILED", run["status"])
        rcfg.log.error.assert_called_once_with("Failed to write interrupted simmer results: %s", mock.ANY)
        messages = "\n".join(str(call) for call in rcfg.log.info.call_args_list)
        self.assertIn("Interrupted run summary", messages)
        self.assertIn("SIGINT", messages)

    def test_interrupted_run_skips_cleanup_until_every_job_stops(self):
        rcfg = SimpleNamespace(simmer_results_run=None, log=mock.Mock())
        simulator = mock.Mock()

        simmer.finalize_interrupted_run(rcfg, simulator, {}, cleanup_shared_runtime=False)

        simulator.cleanup_shared_runtime_artifacts.assert_not_called()
        rcfg.log.warning.assert_called_once()

    def test_interrupted_active_test_is_not_reported_as_skipped(self):
        run = {
            "planned_tests": 2,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            options=SimpleNamespace(waves=None),
            log=mock.Mock(),
        )
        vcomper = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            job_dir="/compile",
            log_path="/compile/cmp.log",
        )
        test_job = simmer.TestJob.__new__(simmer.TestJob)
        test_job.rcfg = rcfg
        test_job.vcomper = vcomper
        test_job.name = "test"
        test_job.target = "//tb:test"
        test_job.iteration = 1
        test_job.seed = 7
        test_job.job_dir = "/sim"
        test_job._log_path = "/sim/stdout.log"
        test_job.job_start_time = datetime.datetime.now() - datetime.timedelta(seconds=2)
        test_job.job_stop_time = datetime.datetime.now()
        test_job.error_message = None
        test_job._jobstatus = simmer.JobStatus.NOT_STARTED
        manager = SimpleNamespace(interrupted_jobs=(test_job, ))

        with mock.patch("simmer.simmer_results.save_run"):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {}, jm=manager)

        self.assertEqual("INTERRUPTED", run["tests"][0]["status"])
        self.assertEqual(1, run["summary"]["interrupted"])
        self.assertEqual(1, run["summary"]["skipped"])

    def test_interrupted_compile_without_started_test_is_not_persisted(self):
        run = {
            "planned_tests": 1,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            log=mock.Mock(),
        )
        vcomp = simmer.VCompJob.__new__(simmer.VCompJob)
        vcomp.name = "tb"
        vcomp.bazel_vcomp_target = "//tb:tb"
        vcomp.job_dir = "/compile"
        vcomp.log_path = "/compile/cmp.log"
        vcomp.job_start_time = None
        vcomp.job_stop_time = None
        vcomp._jobstatus = simmer.JobStatus.NOT_STARTED
        manager = SimpleNamespace(interrupted_jobs=(vcomp, ))

        with mock.patch("simmer.simmer_results.save_run") as save_run:
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {"//tb:tb": vcomp}, jm=manager)

        self.assertEqual("INTERRUPTED", run["compile"][0]["status"])
        save_run.assert_not_called()
        messages = "\n".join(str(call) for call in rcfg.log.info.call_args_list)
        self.assertIn("compile details", messages)
        self.assertIn("/compile/cmp.log", messages)

        rcfg.simmer_results_run = None
        with mock.patch("simmer.simmer_results.save_run") as save_run:
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {"//tb:tb": vcomp}, jm=manager, reason="SIGTERM")
        save_run.assert_not_called()
        self.assertIsNone(rcfg.simmer_results_run)
        messages = "\n".join(str(call) for call in rcfg.log.info.call_args_list)
        self.assertIn("SIGTERM", messages)

    def test_interrupt_cleanup_temporarily_ignores_sigint_and_sigterm(self):
        previous_sigint = object()
        previous_sigterm = object()
        with mock.patch("simmer.signal.signal", side_effect=[previous_sigint, previous_sigterm, None,
                                                             None]) as set_handler:
            with simmer._IgnoreAdditionalInterrupts():
                pass

        self.assertEqual(
            [
                mock.call(simmer.signal.SIGINT, simmer.signal.SIG_IGN),
                mock.call(simmer.signal.SIGTERM, simmer.signal.SIG_IGN),
                mock.call(simmer.signal.SIGINT, previous_sigint),
                mock.call(simmer.signal.SIGTERM, previous_sigterm),
            ],
            set_handler.call_args_list,
        )

    def test_post_processing_interrupt_cleans_once_and_persists_failed_history(self):
        phases = ("waiting", "backend", "coverage", "report", "cleanup", "history")
        for interrupted_phase, signum in ((phase, sig) for phase in phases for sig in (signal.SIGINT, signal.SIGTERM)):
            with self.subTest(interrupted_phase=interrupted_phase,
                              signum=signum), tempfile.TemporaryDirectory() as project_dir:
                interruption = KeyboardInterrupt() if signum == signal.SIGINT else simmer._TerminationRequested(signum)
                run = {
                    "planned_tests": 1,
                    "tests": [{
                        "status": "PASSED"
                    }],
                    "compile": [],
                    "launch_failures": [],
                }
                options = SimpleNamespace(
                    category_cfg=None,
                    gui=False,
                    idle_print_seconds=60,
                    no_bazel=False,
                    no_compile=False,
                    no_run=False,
                    python_seed=None,
                    quit_count=1,
                    report=interrupted_phase in ("coverage", "report"),
                    report_dir=None,
                    seed=None,
                    simmer_argv=["simmer"],
                )
                rcfg = SimpleNamespace(
                    all_vcomp={},
                    deferred_messages=[],
                    log=mock.Mock(warn_count=0, error_count=0, handlers=[]),
                    proj_dir=project_dir,
                    regression_dir=project_dir,
                )
                rcfg._profile_step = mock.Mock(return_value=False)
                simulator = mock.Mock()
                simulator.get_name.return_value = "VCS"
                simulator.uses_dynamic_test_plan.return_value = False
                simulator.create_regression_jobs.return_value = []
                simulator.finalize_regression_workflow.return_value = False
                simulator.coverage_enabled.return_value = interrupted_phase == "coverage"
                manager = mock.Mock(shutdown_incomplete=False, interrupted_jobs=())
                report = mock.Mock()
                lifecycle_events = []
                manager.flush_output_streams.side_effect = lambda: lifecycle_events.append("flush")

                def cleanup_shared_runtime(_vcomp_jobs):
                    lifecycle_events.append("cleanup")
                    if interrupted_phase == "cleanup":
                        raise interruption

                simulator.cleanup_shared_runtime_artifacts.side_effect = cleanup_shared_runtime

                if interrupted_phase == "waiting":
                    manager.wait.side_effect = interruption
                elif interrupted_phase == "backend":
                    simulator.finalize_regression_workflow.side_effect = interruption
                elif interrupted_phase == "coverage":
                    rcfg._profile_step.side_effect = interruption
                elif interrupted_phase == "report":
                    report.prepare.side_effect = interruption

                with mock.patch("simmer.os.uname", return_value=("", "test-host"), create=True), \
                     mock.patch("simmer.log", rcfg.log), \
                     mock.patch("simmer.resolve_run_simulator"), \
                     mock.patch("simmer.get_simulator", return_value=simulator), \
                     mock.patch("simmer.get_active_job_limit", return_value=1), \
                     mock.patch("simmer.job_lib.JobManager", return_value=manager), \
                     mock.patch("simmer.rv_utils.print_summary", return_value="/tmp/regression.log"), \
                     mock.patch("simmer.rv_utils.get_report_header", return_value={"project_name": "unit"}), \
                     mock.patch("simmer.rv_utils.print_simmer_profile"), \
                     mock.patch("simmer.regression_report.RegressionReport", return_value=report), \
                     mock.patch("simmer.simmer_results.create_run", return_value=run), \
                     mock.patch("simmer.simmer_results.save_run") as save_run, \
                     mock.patch("simmer._prompt_interrupt_action", return_value="stop") as prompt, \
                     mock.patch("simmer._IgnoreAdditionalInterrupts", return_value=mock.MagicMock()), \
                     self.assertRaises(SystemExit) as raised:
                    save_calls = []

                    def save_results(*_args):
                        save_calls.append(True)
                        if interrupted_phase == "history" and len(save_calls) == 1:
                            raise interruption
                        lifecycle_events.append("save")

                    save_run.side_effect = save_results
                    simmer.main(rcfg, options)

                self.assertEqual(128 + signum, raised.exception.code)
                simulator.cleanup_shared_runtime_artifacts.assert_called_once_with({})
                if interrupted_phase == "waiting":
                    manager.kill.assert_called_once_with()
                else:
                    manager.kill.assert_not_called()
                    self.assertLess(lifecycle_events.index("flush"), lifecycle_events.index("save"))
                manager.flush_output_streams.assert_called_once_with()
                if interrupted_phase not in ("cleanup", "waiting", "history"):
                    self.assertLess(lifecycle_events.index("flush"), lifecycle_events.index("cleanup"))
                if signum == signal.SIGTERM:
                    prompt.assert_not_called()
                messages = "\n".join(str(call) for call in rcfg.log.info.call_args_list)
                self.assertIn(signal.Signals(signum).name, messages)
                self.assertEqual("FAILED", run["status"])
                self.assertEqual(2 if interrupted_phase == "history" else 1, save_run.call_count)
                save_run.assert_called_with(project_dir, run)

    def test_sigterm_handler_raises_distinct_stop_request_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(simmer._TerminationRequested) as raised:
            with simmer._HandleTermination():
                handler = signal.getsignal(signal.SIGTERM)
                handler(signal.SIGTERM, None)
        self.assertEqual(signal.SIGTERM, raised.exception.signum)
        self.assertIs(previous, signal.getsignal(signal.SIGTERM))

    def test_startup_interrupt_reports_snapshot_and_closes_active_state(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum):
                interruption = KeyboardInterrupt() if signum == signal.SIGINT else simmer._TerminationRequested(signum)
                options = SimpleNamespace(discovery_only=False, proj_dir="/repo", simmer_argv=["simmer"])
                logger = mock.Mock()
                active = mock.Mock()
                with mock.patch("simmer.regression.RegressionConfig", side_effect=interruption), \
                     mock.patch("simmer.simmer_state.ActiveRun", return_value=active), \
                     self.assertRaises(SystemExit) as raised:
                    simmer._run_regression_cli(options, logger)
                self.assertEqual(128 + signum, raised.exception.code)
                active.close.assert_called_once_with()
                messages = "\n".join(str(call) for call in logger.info.call_args_list)
                self.assertIn(signal.Signals(signum).name, messages)
                self.assertIn("discovery/startup", messages)

    @unittest.skipUnless(os.name == "posix", "POSIX subprocess signal delivery")
    def test_real_cli_signals_print_after_cleanup_and_preserve_wave_paths(self):
        for signum in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signum=signum), tempfile.TemporaryDirectory() as project_dir:
                project = Path(project_dir)
                environment = os.environ.copy()
                environment["PYTHONPATH"] = os.pathsep.join(sys.path)
                process = subprocess.Popen(
                    [sys.executable,
                     str(REPO_ROOT / "tests" / "simmer_interrupt_probe.py"),
                     str(project)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                    env=environment,
                )
                try:
                    deadline = time.monotonic() + 10
                    while not (project / "ready").exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    if not (project / "ready").exists():
                        if process.poll() is None:
                            process.kill()
                        output, _ = process.communicate(timeout=5)
                        self.fail("probe did not reach scheduler wait:\n" + output)
                    process.send_signal(signum)
                    output, _ = process.communicate(timeout=10)
                    self.assertEqual(128 + signum, process.returncode, output)
                    self.assertIn("KILL_JOBS", output)
                    self.assertIn("CLEANUP_DONE", output)
                    self.assertIn("ACTIVE_STATE_CLOSED", output)
                    self.assertIn(signal.Signals(signum).name, output)
                    self.assertIn(str(project / "stdout.log"), output)
                    self.assertIn(str(project / "run_waves.sh"), output)
                    self.assertLess(output.index("CLEANUP_DONE"), output.index(str(project / "run_waves.sh")))
                    self.assertEqual("partial wave data", (project / "waves.fsdb").read_text(encoding="utf-8"))
                    self.assertNotIn("Select [s]", output)
                    self.assertNotIn("Traceback", output)
                    history = simmer.simmer_results.load_store(project_dir)["last_run"]
                    self.assertEqual(1, history["summary"]["interrupted"])
                    self.assertEqual(1, history["summary"]["passed"])
                    self.assertEqual(1, history["summary"]["failed"])
                    self.assertEqual(1, history["summary"]["skipped"])
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=5)

    def test_noninteractive_interrupt_stops_without_prompting(self):
        rcfg = SimpleNamespace(log=mock.Mock(handlers=[]))
        manager = mock.Mock()

        action = simmer._prompt_interrupt_action(
            rcfg,
            manager,
            input_fn=mock.Mock(side_effect=AssertionError("prompted")),
            interactive=False,
        )

        self.assertEqual("stop", action)
        manager.flush_output_streams.assert_called_once_with()

    def test_interrupt_menu_can_show_status_and_continue(self):
        rcfg = SimpleNamespace(log=mock.Mock(handlers=[]))
        manager = mock.Mock()
        manager.status_snapshot.return_value = {
            "paused": False,
            "queued": (),
            "launching": (),
            "active": (),
            "finalizing": (),
            "done": (),
            "skipped": (),
        }
        choices = iter(["status", "continue"])

        action = simmer._prompt_interrupt_action(rcfg, manager, input_fn=lambda _: next(choices), interactive=True)

        self.assertEqual("continue", action)
        manager.status_snapshot.assert_called_once_with()
        manager.pause.assert_not_called()

    def test_interrupt_menu_pauses_and_resumes_jobs(self):
        rcfg = SimpleNamespace(log=mock.Mock(handlers=[]))
        manager = mock.Mock()
        manager.pause.return_value = 2
        manager.resume.return_value = 2
        manager.status_snapshot.return_value = {
            "paused": True,
            "queued": (object(), ),
            "launching": (),
            "active": (),
            "finalizing": (),
            "done": (),
            "skipped": (),
        }
        choices = iter(["pause", "resume"])

        action = simmer._prompt_interrupt_action(rcfg, manager, input_fn=lambda _: next(choices), interactive=True)

        self.assertEqual("continue", action)
        manager.pause.assert_called_once_with()
        manager.resume.assert_called_once_with()

    def test_wait_for_jobs_retries_after_continue(self):
        rcfg = SimpleNamespace(log=mock.Mock(handlers=[]))
        manager = mock.Mock()
        manager.wait.side_effect = [KeyboardInterrupt, None]

        with mock.patch("simmer._prompt_interrupt_action", return_value="continue") as prompt:
            simmer._wait_for_jobs(manager, rcfg)

        self.assertEqual(2, manager.wait.call_count)
        prompt.assert_called_once_with(rcfg, manager)

    def test_wait_for_jobs_reraises_after_stop(self):
        rcfg = SimpleNamespace(log=mock.Mock(handlers=[]))
        manager = mock.Mock()
        manager.wait.side_effect = KeyboardInterrupt

        with mock.patch("simmer._prompt_interrupt_action", return_value="stop"), self.assertRaises(KeyboardInterrupt):
            simmer._wait_for_jobs(manager, rcfg)

    def test_launching_test_without_log_path_is_persisted_as_interrupted(self):
        run = {
            "planned_tests": 1,
            "tests": [],
            "compile": [],
            "launch_failures": [],
        }
        rcfg = SimpleNamespace(
            proj_dir="/repo",
            simmer_results_run=run,
            options=SimpleNamespace(waves=None),
            log=mock.Mock(),
        )
        vcomper = SimpleNamespace(
            name="tb",
            bazel_vcomp_target="//tb:tb",
            job_dir="/compile",
            log_path="/compile/cmp.log",
        )
        test_job = simmer.TestJob.__new__(simmer.TestJob)
        test_job.rcfg = rcfg
        test_job.vcomper = vcomper
        test_job.name = "test"
        test_job.target = "//tb:test"
        test_job.iteration = 1
        test_job.job_dir = None
        test_job._log_path = None
        test_job.job_start_time = datetime.datetime.now() - datetime.timedelta(seconds=2)
        test_job.job_stop_time = datetime.datetime.now()
        test_job.error_message = None
        test_job._jobstatus = simmer.JobStatus.NOT_STARTED
        manager = SimpleNamespace(interrupted_jobs=(test_job, ))

        with mock.patch("simmer.simmer_results.save_run"):
            simmer.finalize_interrupted_run(rcfg, mock.Mock(), {}, jm=manager)

        self.assertEqual("INTERRUPTED", run["tests"][0]["status"])
        self.assertIsNone(run["tests"][0]["stdout_log"])

    def test_rerun_removes_stale_wave_artifact_and_viewer_script(self):
        with tempfile.TemporaryDirectory() as job_dir:
            wave_path = Path(job_dir) / "waves.fsdb"
            wave_path.write_text("stale", encoding="utf-8")
            viewer = Path(job_dir) / "run_waves.sh"
            viewer.write_text("stale", encoding="utf-8")
            test_job = simmer.TestJob.__new__(simmer.TestJob)
            test_job.job_dir = job_dir
            test_job.simulator = SimpleNamespace(get_wave_artifact_path=lambda *_args: str(wave_path))

            test_job._remove_stale_wave_artifacts("fsdb")

            self.assertFalse(wave_path.exists())
            self.assertFalse(viewer.exists())

    def test_wave_viewer_exists_before_simulation_and_survives_interrupt(self):
        formats = (("VCS", "fsdb"), ("XRUN", "vwdb"), ("XRUN", "shm"), ("XRUN", "vcd"), ("VCS", None), ("XRUN", None))
        for backend, wave_type, partial in ((b, w, p) for b, w in formats for p in (False, True)):
            with self.subTest(backend=backend, wave_type=wave_type,
                              partial=partial), tempfile.TemporaryDirectory() as root:
                args = ["--simulator", backend]
                if wave_type:
                    args.extend(["--waves", "--wave-type", wave_type])
                options = parse_args(args)
                run = {"planned_tests": 1, "tests": [], "compile": [], "launch_failures": []}
                rcfg = SimpleNamespace(options=options,
                                       proj_dir=root,
                                       regression_dir=root,
                                       simmer_results_run=run,
                                       log=mock.Mock(),
                                       tidy=False)
                vcomp = simmer.job_lib.Job(rcfg, "tb")
                vcomp.bazel_vcomp_target = "//tb:tb"
                vcomp.job_dir = root
                vcomp.log_path = str(Path(root) / "cmp.log")
                vcomp.bazel_runfiles_main = str(Path(root) / "runfiles")
                Path(vcomp.bazel_runfiles_main).mkdir()
                vcomp.bazel_runtime_args = str(Path(vcomp.bazel_runfiles_main) / "runtime_args.f")
                Path(vcomp.bazel_runtime_args).touch()
                runtime = normalize_test_runtime_options({"simulator": backend, "uvm_testname": "test"})
                simulator_type = simmer.VcsSimulator if backend == "VCS" else simmer.XceliumSimulator
                simulator = simulator_type(options, rcfg, simmer.jinja2_env)
                job = simmer.TestJob(rcfg,
                                     "//tb:test",
                                     vcomp,
                                     SimpleNamespace(jobs=[]),
                                     SimpleNamespace(dynamic_args=lambda _: runtime),
                                     simulator,
                                     iteration=1,
                                     planned_seed=7)
                job_dir = str(Path(root) / "test dir")
                # Match a real invocation from its project directory, including
                # Windows CI where the checkout and temp directory use different drives.
                with contextlib.chdir(root), \
                     mock.patch.object(job, "_claim_run_directory", return_value=("test", job_dir)), \
                     mock.patch("simmer.replace_symlink"), mock.patch("simmer.log", rcfg.log), \
                     mock.patch("subprocess.Popen") as launch:
                    job.pre_run()
                launch.assert_not_called()
                viewer = Path(job_dir) / "run_waves.sh"
                if wave_type is None:
                    self.assertFalse(viewer.exists())
                    self.assertIsNone(job.run_wave_script_path)
                    self.assertIsNone(job.wave_artifact_path)
                    continue
                self.assertTrue(viewer.is_file(), "viewer must exist before the simulator starts")
                if os.name == "posix":
                    self.assertTrue(viewer.stat().st_mode & 0o111)
                original_script = viewer.read_text(encoding="utf-8")
                artifact = Path(simulator.get_wave_artifact_path(job_dir, wave_type))
                self.assertFalse(artifact.exists())
                if partial:
                    if wave_type == "shm":
                        artifact.mkdir()
                    else:
                        artifact.write_text("partial waveform", encoding="utf-8")
                job.cancel()
                with mock.patch("simmer.simmer_results.save_run"):
                    simmer.finalize_interrupted_run(rcfg, simulator, {}, jm=SimpleNamespace(interrupted_jobs=(job, )))
                self.assertEqual(original_script, viewer.read_text(encoding="utf-8"))
                record = run["tests"][0]
                self.assertEqual("INTERRUPTED", record["status"])
                self.assertEqual(str(viewer), record["waves"]["run_script"])
                self.assertEqual(str(artifact), record["waves"]["path"])
                self.assertEqual(partial, record["waves"]["exists"])

    def test_missing_requested_wave_artifact_fails_test_and_preserves_prepared_viewer(self):
        with tempfile.TemporaryDirectory() as job_dir:
            log_path = Path(job_dir) / "stdout.log"
            log_path.write_text("simulation completed\n", encoding="utf-8")
            missing_wave = Path(job_dir) / "waves.fsdb"
            viewer = Path(job_dir) / "run_waves.sh"
            viewer.write_text("prepared viewer\n", encoding="utf-8")
            options = SimpleNamespace(waves=[], wave_type="fsdb")
            rcfg = SimpleNamespace(
                log=mock.Mock(),
                options=options,
                simmer_results_run={},
                table_format=lambda *_args, **_kwargs: "result",
                tidy=False,
            )
            simulator = mock.Mock()
            simulator.get_wave_artifact_path.return_value = str(missing_wave)
            simulator.should_spawn_test_job.return_value = False
            test_job = simmer.TestJob.__new__(simmer.TestJob)
            test_job._jobstatus = simmer.JobStatus.NOT_STARTED
            test_job._log_path = str(log_path)
            test_job.error_message = None
            test_job.iteration = 1
            test_job.job_dir = job_dir
            test_job.run_wave_script_path = str(viewer)
            test_job.wave_artifact_path = str(missing_wave)
            test_job.job_lib = SimpleNamespace(returncode=0, manager=mock.Mock())
            test_job.job_start_time = datetime.datetime.now()
            test_job.job_stop_time = None
            test_job.log = rcfg.log
            test_job.name = "test"
            test_job.rcfg = rcfg
            test_job.simulator = simulator
            test_job.vcomper = SimpleNamespace(name="tb")

            with mock.patch("simmer.log", rcfg.log), \
                 mock.patch("simmer.simmer_results.record_test_job") as record_job, \
                 mock.patch("simmer.sim_artifacts.write_executable_script") as write_viewer:
                test_job.post_run()

            self.assertEqual(simmer.JobStatus.FAILED, test_job.jobstatus)
            self.assertIn(str(missing_wave), test_job.error_message)
            simulator.cleanup_test_coverage.assert_called_once_with(test_job)
            simulator.get_wave_view_command.assert_not_called()
            write_viewer.assert_not_called()
            self.assertEqual("prepared viewer\n", viewer.read_text(encoding="utf-8"))
            self.assertEqual(str(viewer), record_job.call_args.kwargs["waves_script"])

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_shared_runtime_lock_serializes_identical_regressions(self):
        first = simmer.VCompJob.__new__(simmer.VCompJob)
        first._shared_runtime_locks = {}
        first._cancel_event = threading.Event()
        second = simmer.VCompJob.__new__(simmer.VCompJob)
        second._shared_runtime_locks = {}
        second._cancel_event = threading.Event()
        acquired = threading.Event()
        errors = []

        with tempfile.TemporaryDirectory() as root_dir, mock.patch("simmer.log", mock.Mock()):
            first.rcfg = SimpleNamespace(proj_dir=root_dir)
            second.rcfg = SimpleNamespace(proj_dir=root_dir)
            coverage_dir = os.path.join(root_dir, "tb__COV_WORK")
            first.acquire_shared_runtime_lock(coverage_dir)

            def acquire_second():
                try:
                    second.acquire_shared_runtime_lock(coverage_dir)
                    acquired.set()
                except Exception as exc:
                    errors.append(exc)

            waiter = threading.Thread(target=acquire_second)
            waiter.start()
            self.assertFalse(acquired.wait(0.1))
            first.release_shared_runtime_locks()
            self.assertTrue(acquired.wait(1.0))
            waiter.join(1.0)
            second.release_shared_runtime_locks()

        self.assertFalse(errors)

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_symlink_lock_wait_stops_after_cancellation(self):
        with tempfile.TemporaryDirectory() as result_dir:
            link_path = os.path.join(result_dir, ".last_sim")
            cancel_path = os.path.join(result_dir, "cancel")
            waiting_path = os.path.join(result_dir, "waiting")
            holder = compile_cache.CompileDirectoryLock(simmer._symlink_lock_path(link_path))
            self.assertTrue(holder.acquire(blocking=False))
            probe = ("import os, sys\n"
                     "from simmer import replace_symlink\n"
                     "from lib.job_lib import JobCancelledError\n"
                     "def cancel_check():\n"
                     "    open(sys.argv[3], 'a').close()\n"
                     "    if os.path.exists(sys.argv[2]):\n"
                     "        raise JobCancelledError('cancelled')\n"
                     "try:\n"
                     "    replace_symlink(sys.argv[1], 'target', cancel_check=cancel_check)\n"
                     "except JobCancelledError:\n"
                     "    sys.exit(3)\n")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join(
                [str(BIN_DIR), str(REPO_ROOT), environment.get("PYTHONPATH", "")])
            try:
                waiter = subprocess.Popen(
                    [sys.executable, "-c", probe, link_path, cancel_path, waiting_path],
                    env=environment,
                )
                deadline = time.monotonic() + 5.0
                while not os.path.exists(waiting_path) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(os.path.exists(waiting_path), "subprocess did not start waiting for the lock")
                self.assertIsNone(waiter.poll())
                Path(cancel_path).touch()
                self.assertEqual(3, waiter.wait(timeout=2.0))
            finally:
                holder.release()

            self.assertFalse(os.path.lexists(link_path))

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_live_run_directory_collision_gets_suffix_and_releases(self):
        with tempfile.TemporaryDirectory() as result_dir:
            rcfg = SimpleNamespace(regression_dir=result_dir)
            first = simmer.TestJob.__new__(simmer.TestJob)
            first.rcfg = rcfg
            first.log = mock.Mock()
            first._run_directory_lock = None
            second = simmer.TestJob.__new__(simmer.TestJob)
            second.rcfg = rcfg
            second.log = mock.Mock()
            second._run_directory_lock = None
            third = simmer.TestJob.__new__(simmer.TestJob)
            third.rcfg = rcfg
            third.log = mock.Mock()
            third._run_directory_lock = None

            first_name, _ = first._claim_run_directory("tb__VCS__test__7")
            second_name, _ = second._claim_run_directory("tb__VCS__test__7")
            self.assertEqual("tb__VCS__test__7", first_name)
            self.assertRegex(second_name, r"^tb__VCS__test__7__run_p\d+$")

            first._release_run_directory_lock()
            third_name, _ = third._claim_run_directory("tb__VCS__test__7")
            self.assertEqual("tb__VCS__test__7", third_name)

            second._release_run_directory_lock()
            third._release_run_directory_lock()

    @unittest.skipUnless(os.name == "posix", "POSIX advisory-lock behavior")
    def test_compile_lock_wait_stops_after_cancellation(self):
        with tempfile.TemporaryDirectory() as result_dir:
            job_dir = os.path.join(result_dir, "tb__VCS_VCOMP")
            holder = compile_cache.CompileDirectoryLock(job_dir + ".compile.lock")
            self.assertTrue(holder.acquire(blocking=False))
            job = simmer.VCompJob.__new__(simmer.VCompJob)
            job.job_dir = job_dir
            job._compile_lock = None
            job._cancel_event = threading.Event()
            job.bazel_vcomp_target = "//tb:tb"
            job.name = "tb"
            job.simulator = SimpleNamespace(get_name=lambda: "vcs")
            errors = []
            previous_log = simmer.log
            simmer.log = mock.Mock()

            def acquire():
                try:
                    job._acquire_compile_lock()
                except Exception as exc:
                    errors.append(exc)

            waiter = threading.Thread(target=acquire)
            try:
                waiter.start()
                while job._compile_lock is None:
                    waiter.join(0.01)
                job.request_cancel()
                waiter.join(1.0)
            finally:
                holder.release()
                job._release_compile_lock()
                simmer.log = previous_log

            self.assertFalse(waiter.is_alive())
            self.assertEqual(1, len(errors))
            self.assertIsInstance(errors[0], JobCancelledError)

    @unittest.skipUnless(os.name == "posix", "POSIX atomic-symlink behavior")
    def test_shared_symlink_updates_are_atomic_and_cleanup_is_target_aware(self):
        with tempfile.TemporaryDirectory() as result_dir:
            link_path = os.path.join(result_dir, ".last_sim")
            context = multiprocessing.get_context("fork")
            start = context.Event()
            result_queue = context.Queue()
            processes = [
                context.Process(
                    target=_replace_symlink_in_process,
                    args=(link_path, target, start, result_queue),
                ) for target in ("first", "second")
            ]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(5.0)

            self.assertEqual([0, 0], [process.exitcode for process in processes])
            self.assertEqual([None, None], sorted([result_queue.get(timeout=1.0) for _ in processes], key=str))
            final_target = os.readlink(link_path)
            self.assertIn(final_target, ("first", "second"))
            self.assertFalse(os.path.exists(link_path + ".lock"))
            self.assertTrue(os.path.isfile(simmer._symlink_lock_path(link_path)))
            other_target = "second" if final_target == "first" else "first"
            self.assertFalse(simmer.remove_symlink_if_target(link_path, other_target))
            self.assertTrue(os.path.lexists(link_path))
            self.assertTrue(simmer.remove_symlink_if_target(link_path, final_target))
            self.assertFalse(os.path.lexists(link_path))

            job_link_path = os.path.join(result_dir, "job", ".vcomp")
            os.makedirs(os.path.dirname(job_link_path))
            simmer.replace_symlink(job_link_path, "../compile")
            self.assertFalse(os.path.exists(job_link_path + ".lock"))
            self.assertTrue(os.path.isfile(simmer._symlink_lock_path(job_link_path)))


if __name__ == "__main__":
    unittest.main()
