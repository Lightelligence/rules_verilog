"""License-free subprocess fixture for real CLI interrupt handling."""

import datetime
import logging
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "bin"))

import simmer
from args_parser import parse_args


def main():
    project = Path(sys.argv[1])
    logger = logging.getLogger("interrupt-probe")
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    options = parse_args(["--simulator", "VCS", "--waves", "--wave-type", "fsdb"])
    options.simmer_argv = ["simmer", "--waves"]
    rcfg = SimpleNamespace(options=options,
                           all_vcomp={},
                           proj_dir=str(project),
                           regression_dir=str(project),
                           log=logger)
    rcfg._profile_step = mock.Mock(return_value=False)
    run = {
        "planned_tests": 4,
        "tests": [{
            "status": "PASSED"
        }, {
            "status": "FAILED",
            "bench": "tb",
            "test": "failed"
        }],
        "compile": [],
        "launch_failures": [],
    }
    vcomp = SimpleNamespace(name="tb",
                            bazel_vcomp_target="//tb:tb",
                            job_dir=str(project),
                            log_path=str(project / "cmp.log"))
    job = simmer.TestJob.__new__(simmer.TestJob)
    job.rcfg = rcfg
    job.vcomper = vcomp
    job.name = "active"
    job.target = "//tb:active"
    job.iteration = 1
    job.seed = 7
    job.job_dir = str(project)
    job._log_path = str(project / "stdout.log")
    job.job_start_time = datetime.datetime.now() - datetime.timedelta(seconds=2)
    job.job_stop_time = None
    job._jobstatus = simmer.JobStatus.NOT_STARTED
    job.error_message = None
    job.run_wave_script_path = str(project / "run_waves.sh")
    job.wave_artifact_path = str(project / "waves.fsdb")
    Path(job.run_wave_script_path).write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    Path(job.wave_artifact_path).write_text("partial wave data", encoding="utf-8")
    manager = mock.Mock(interrupted_jobs=(job, ), shutdown_incomplete=False)

    def wait():
        (project / "ready").touch()
        while True:
            time.sleep(0.05)

    def kill_jobs():
        logger.info("KILL_JOBS")
        # A second termination request must not abort cleanup or the summary.
        os.kill(os.getpid(), signal.SIGINT)
        os.kill(os.getpid(), signal.SIGTERM)
        return True

    manager.wait.side_effect = wait
    manager.kill.side_effect = kill_jobs
    simulator = mock.Mock()
    simulator.get_name.return_value = "VCS"
    simulator.uses_dynamic_test_plan.return_value = False
    simulator.create_regression_jobs.return_value = []
    simulator.cleanup_shared_runtime_artifacts.side_effect = lambda _: logger.info("CLEANUP_DONE")
    active_run = mock.Mock()
    active_run.close.side_effect = lambda: logger.info("ACTIVE_STATE_CLOSED")
    with mock.patch("simmer.log", logger), \
         mock.patch("simmer.regression.RegressionConfig", return_value=rcfg), \
         mock.patch("simmer.simmer_state.ActiveRun", return_value=active_run), \
         mock.patch("simmer.resolve_run_simulator"), \
         mock.patch("simmer.get_simulator", return_value=simulator), \
         mock.patch("simmer.get_active_job_limit", return_value=1), \
         mock.patch("simmer.job_lib.JobManager", return_value=manager), \
         mock.patch("simmer.simmer_results.create_run", return_value=run):
        simmer._run_regression_cli(options, logger)


if __name__ == "__main__":
    main()
