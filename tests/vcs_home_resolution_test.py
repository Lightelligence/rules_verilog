import os
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
from lib.simulators.vcs import VcsSimulator


class VcsHomeResolutionTest(unittest.TestCase):
    """Cover every branch of VcsSimulator.get_vcs_home()."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.options = parse_args(["--simulator", "VCS"])
        self.rcfg = SimpleNamespace(options=self.options, regression_dir=str(self.root), proj_dir=str(self.root))

    def _simulator(self, runner=None):
        if runner is not None:
            self.options.vcs_runner = runner
        return VcsSimulator(self.options, self.rcfg, None)

    def _clean_environment(self):
        """Remove VCS_HOME and RV_VCS_RUNNER so resolution actually runs."""
        environment = dict(os.environ)
        environment.pop("VCS_HOME", None)
        environment.pop("RV_VCS_RUNNER", None)
        return mock.patch.dict(os.environ, environment, clear=True)

    def test_environment_home_wins_without_invoking_the_runner(self):
        with mock.patch.dict(os.environ, {"VCS_HOME": "/opt/vcs"}, clear=False), \
             mock.patch("lib.simulators.vcs.subprocess.run") as run:
            self.assertEqual("/opt/vcs", self._simulator(runner="runmod vcs --").get_vcs_home())
        run.assert_not_called()

    def test_falls_back_to_the_runner_when_the_environment_is_empty(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=0,
                                                     stdout="/opt/synopsys/vcs\n")) as run:
            home = self._simulator(runner="runmod vcs --").get_vcs_home()

        self.assertEqual("/opt/synopsys/vcs", home)
        self.assertEqual(["runmod", "vcs", "--", "printenv", "VCS_HOME"], run.call_args.args[0])
        self.assertFalse(run.call_args.kwargs["check"])

    def test_resolution_runs_once_per_simulator_instance(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=0, stdout="/opt/vcs\n")) as run:
            simulator = self._simulator(runner="runmod vcs --")
            self.assertEqual("/opt/vcs", simulator.get_vcs_home())
            self.assertEqual("/opt/vcs", simulator.get_vcs_home())

        self.assertEqual(1, run.call_count)

    def test_empty_runner_still_queries_printenv(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=0, stdout="/opt/vcs\n")) as run:
            self.assertEqual("/opt/vcs", self._simulator(runner="none").get_vcs_home())

        self.assertEqual(["printenv", "VCS_HOME"], run.call_args.args[0])

    def test_failed_runner_leaves_home_empty_and_warns(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=1, stdout="")), \
             mock.patch("lib.simulators.vcs.log") as log:
            home = self._simulator(runner="runmod vcs --").get_vcs_home()

        self.assertEqual("", home)
        log.warning.assert_called_once()

    def test_empty_runner_output_leaves_home_empty_and_warns(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=0, stdout="\n\n")), \
             mock.patch("lib.simulators.vcs.log") as log:
            home = self._simulator(runner="runmod vcs --").get_vcs_home()

        self.assertEqual("", home)
        log.warning.assert_called_once()

    def test_missing_runner_leaves_home_empty_and_warns(self):
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run", side_effect=OSError("no such file")), \
             mock.patch("lib.simulators.vcs.log") as log:
            home = self._simulator(runner="runmod vcs --").get_vcs_home()

        self.assertEqual("", home)
        log.warning.assert_called_once()

    def test_runner_timeout_leaves_home_empty_and_warns(self):
        timeout = subprocess.TimeoutExpired(cmd="runmod", timeout=30)
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run", side_effect=timeout), \
             mock.patch("lib.simulators.vcs.log") as log:
            home = self._simulator(runner="runmod vcs --").get_vcs_home()

        self.assertEqual("", home)
        log.warning.assert_called_once()

    def test_failed_resolution_is_cached(self):
        """A failed probe must not be retried on the next compile step."""
        with self._clean_environment(), \
             mock.patch("lib.simulators.vcs.subprocess.run",
                        return_value=SimpleNamespace(returncode=1, stdout="")) as run, \
             mock.patch("lib.simulators.vcs.log"):
            simulator = self._simulator(runner="runmod vcs --")
            self.assertEqual("", simulator.get_vcs_home())
            self.assertEqual("", simulator.get_vcs_home())

        self.assertEqual(1, run.call_count)


if __name__ == "__main__":
    unittest.main()
