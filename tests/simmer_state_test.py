import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from lib import simmer_state


class SimmerStateTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.project_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _lsf_environment(job_id="851247"):
        return {
            "LSB_JOBID": job_id,
            "LSB_QUEUE": "syn",
            "LSB_SUB_HOST": "login02",
        }

    def test_lsf_context_builds_reproducible_submission_command(self):
        environment = self._lsf_environment()
        context = simmer_state.capture_lsf_context(
            environment=environment,
            hostname="sh-cloud17",
            interactive=True,
        )

        self.assertEqual(
            "bsub -I -q syn simmer.py -t 'usb_tb:*@20' --jobs 4",
            simmer_state.format_submission_command(
                ["/tools/simmer.py", "-t", "usb_tb:*@20", "--jobs", "4"],
                lsf=context,
                environment=environment,
            ),
        )
        self.assertEqual(
            "job 851247 | queue syn | host sh-cloud17 | submit login02 | bkill 851247",
            simmer_state.format_lsf_summary(context, include_bkill=True),
        )

    def test_explicit_submit_command_is_preserved(self):
        environment = self._lsf_environment()
        environment["SIMMER_SUBMIT_CMD"] = "bs simmer -t sys_tb:test --waves"

        self.assertEqual(
            environment["SIMMER_SUBMIT_CMD"],
            simmer_state.format_submission_command(["simmer", "-t", "sys_tb:test"], environment=environment),
        )

    def test_status_lists_all_runs_oldest_first_and_latest_as_one(self):
        first = simmer_state.ActiveRun(
            self.project_dir,
            ["simmer", "-t", "usb_tb:*@20"],
            environment=self._lsf_environment("851247"),
            hostname="local-host",
            interactive=True,
            now=1000,
        )
        second = simmer_state.ActiveRun(
            self.project_dir,
            ["simmer", "-t", "sys_tb:test"],
            environment=self._lsf_environment("852106"),
            hostname="local-host",
            interactive=True,
            now=2000,
        )
        try:
            first.update(
                status="RUNNING",
                planned_tests=20,
                finished_tests=7,
                active_tests=4,
                queued_tests=9,
                compile_logs=["/results/usb_tb/cmp.log"],
                regression_log="/results/usb_tb/regression.log",
            )
            second.update(
                status="RUNNING",
                planned_tests=1,
                active_tests=1,
                compile_logs=["/results/sys_tb/cmp.log"],
                result_log="/results/sys_tb/stdout.log",
            )

            output = simmer_state.format_status(self.project_dir, now=3000, hostname="local-host")

            self.assertLess(output.index("[2] "), output.index("[1] "))
            self.assertLess(output.index("usb_tb:*@20"), output.index("sys_tb:test"))
            self.assertIn("RUNNING  7/20 finished, 4 active, 9 queued | elapsed 00:33:20", output)
            self.assertIn("regression: /results/usb_tb/regression.log", output)
            self.assertIn("result:     /results/sys_tb/stdout.log", output)
            self.assertNotIn("usb_sanity_test", output)
            self.assertEqual(1, output.count(simmer_state.STATUS_SEPARATOR))
        finally:
            first.close()
            second.close()

    def test_close_removes_active_state(self):
        active_run = simmer_state.ActiveRun(self.project_dir, ["simmer"])
        path = Path(active_run.path)
        self.assertTrue(path.exists())

        active_run.close()

        self.assertFalse(path.exists())
        self.assertEqual("No active simmer runs.", simmer_state.format_status(self.project_dir))

    def test_close_prevents_late_update_from_recreating_state(self):
        active_run = simmer_state.ActiveRun(self.project_dir, ["simmer"])
        path = Path(active_run.path)

        active_run.close()

        self.assertFalse(active_run.update(status="RUNNING"))
        self.assertFalse(path.exists())

    def test_posix_permission_error_still_means_process_exists(self):
        with mock.patch.object(simmer_state.os, "kill", side_effect=PermissionError):
            self.assertTrue(simmer_state._posix_process_exists(1234))

    def test_windows_process_probe_does_not_use_posix_kill(self):
        with mock.patch.object(simmer_state, "_windows_process_exists", return_value=True) as probe:
            self.assertTrue(simmer_state._process_exists(1234, platform_name="nt"))

        probe.assert_called_once_with(1234)

    def test_stopped_watcher_drops_late_snapshot(self):
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()
        active_run = simmer_state.ActiveRun(self.project_dir, ["simmer"])

        def delayed_snapshot():
            snapshot_started.set()
            release_snapshot.wait(2)
            return {"status": "RUNNING"}

        try:
            active_run.start_watching(delayed_snapshot, interval_seconds=60)
            self.assertTrue(snapshot_started.wait(1))
            stop_event = active_run._stop_event
            stopper = threading.Thread(target=active_run.stop_watching)
            stopper.start()
            self.assertTrue(stop_event.wait(1))
            release_snapshot.set()
            stopper.join(2)
            self.assertFalse(stopper.is_alive())

            state = json.loads(Path(active_run.path).read_text(encoding="utf-8"))
            self.assertEqual("DISCOVERING", state["status"])
        finally:
            release_snapshot.set()
            active_run.close()

    def test_dead_local_process_state_is_removed(self):
        active_run = simmer_state.ActiveRun(self.project_dir, ["simmer"], hostname="local-host")
        path = Path(active_run.path)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["process"]["pid"] = 999999999
        path.write_text(json.dumps(state), encoding="utf-8")
        active_run._enabled = False

        self.assertEqual(
            "No active simmer runs.",
            simmer_state.format_status(self.project_dir, hostname="local-host"),
        )
        self.assertFalse(path.exists())

    def test_remote_completed_lsf_job_state_is_removed(self):
        active_run = simmer_state.ActiveRun(
            self.project_dir,
            ["simmer"],
            environment=self._lsf_environment(),
            hostname="compute17",
        )
        path = Path(active_run.path)

        def completed_job(*_args, **_kwargs):
            return SimpleNamespace(returncode=0, stdout="851247 user DONE syn login compute job now\n")

        self.assertEqual(
            [],
            simmer_state.load_active_runs(
                self.project_dir,
                hostname="login02",
                lsf_runner=completed_job,
            ),
        )
        self.assertFalse(path.exists())

    def test_state_writes_only_when_snapshot_changes(self):
        active_run = simmer_state.ActiveRun(self.project_dir, ["simmer"])
        try:
            original_mtime = os.stat(active_run.path).st_mtime_ns
            self.assertFalse(active_run.update(status="DISCOVERING"))
            self.assertEqual(original_mtime, os.stat(active_run.path).st_mtime_ns)
            self.assertTrue(active_run.update(status="COMPILING"))
        finally:
            active_run.close()


if __name__ == "__main__":
    unittest.main()
