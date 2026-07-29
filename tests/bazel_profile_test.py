import json
import os
import tempfile
import unittest

from lib import bazel_profile


class BazelProfileTest(unittest.TestCase):

    def test_phase_timings_measure_intervals_between_build_phase_markers(self):
        profile = {
            "traceEvents": [
                {
                    "ph": "i",
                    "cat": "build phase marker",
                    "name": "Launch Blaze",
                    "ts": 1_000_000
                },
                {
                    "ph": "i",
                    "cat": "build phase marker",
                    "name": "Analyze",
                    "ts": 3_500_000
                },
                {
                    "ph": "X",
                    "cat": "action",
                    "name": "compile",
                    "ts": 4_000_000,
                    "dur": 1_000_000
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as profile_file:
            json.dump(profile, profile_file)
            profile_path = profile_file.name

        try:
            self.assertEqual(
                [(2.5, "Launch Blaze"), (1.5, "Analyze")],
                bazel_profile.phase_timings(profile_path),
            )
        finally:
            os.remove(profile_path)

    def test_repository_timings_aggregate_real_repository_events(self):
        profile = {
            "traceEvents": [
                {
                    "ph": "X",
                    "cat": "skyframe",
                    "name": "BazelRepositoryModule",
                    "dur": 9_000_000
                },
                {
                    "ph": "X",
                    "cat": "repository",
                    "name": "Repository rule @@rules_python",
                    "dur": 2_000_000
                },
                {
                    "ph": "X",
                    "cat": "action",
                    "name": "fetch external/pip_deps/wheel",
                    "dur": 500_000
                },
                {
                    "ph": "X",
                    "cat": "repository",
                    "name": "fetch",
                    "dur": 250_000,
                    "args": {
                        "repository": "rules_python"
                    }
                },
                {
                    "ph": "i",
                    "cat": "repository",
                    "name": "Repository rule @ignored",
                    "dur": 4_000_000
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as profile_file:
            json.dump(profile, profile_file)
            profile_path = profile_file.name

        try:
            self.assertEqual(
                [(2.25, "rules_python", 2), (0.5, "pip_deps", 1)],
                bazel_profile.repository_timings(profile_path),
            )
        finally:
            os.remove(profile_path)

    def test_repository_timings_merge_overlapping_events_and_ignore_generic_function_name(self):
        profile = {
            "traceEvents": [
                {
                    "ph": "X",
                    "cat": "repository",
                    "name": "Repository rule @rules_python",
                    "ts": 1_000_000,
                    "dur": 4_000_000
                },
                {
                    "ph": "X",
                    "cat": "repository",
                    "name": "fetch",
                    "ts": 2_000_000,
                    "dur": 2_000_000,
                    "args": {
                        "repository": "rules_python"
                    }
                },
                {
                    "ph": "X",
                    "cat": "repository",
                    "name": "Starlark repository function",
                    "ts": 0,
                    "dur": 20_000_000
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as profile_file:
            json.dump(profile, profile_file)
            profile_path = profile_file.name

        try:
            self.assertEqual(
                [(4.0, "rules_python", 2)],
                bazel_profile.repository_timings(profile_path),
            )
        finally:
            os.remove(profile_path)


if __name__ == "__main__":
    unittest.main()
