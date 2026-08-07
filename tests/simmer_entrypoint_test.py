import os
import subprocess
import sys
import tempfile
import unittest

SIMMER = sys.argv.pop(1)


class SimmerEntrypointTest(unittest.TestCase):

    def test_help_runs_from_bazel_launcher(self):
        result = subprocess.run(
            [SIMMER, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("usage: simmer", result.stdout)
        self.assertIn("--simulator {VCS,XRUN}", result.stdout)

    def test_status_exits_without_project_discovery(self):
        with tempfile.TemporaryDirectory() as project_dir:
            environment = dict(os.environ, PROJ_DIR=project_dir)
            result = subprocess.run(
                [SIMMER, "--st"],
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual("No active simmer runs.", result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
