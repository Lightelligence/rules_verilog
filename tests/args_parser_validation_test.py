import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

from bin.args_parser import parse_args


class ArgsParserValidationTest(unittest.TestCase):

    def test_simulator_defaults_to_vcs_and_preserves_environment_and_cli_overrides(self):
        script = ("import json, sys; from bin.args_parser import parse_args; "
                  "options = parse_args(sys.argv[1:]); "
                  "print(json.dumps([options.simulator, options.simulator_was_explicit]))")
        for platform, argv, expected in (
            (None, [], "VCS"),
            (None, ["--simulator", "XRUN"], "XRUN"),
            ("XRUN", [], "XRUN"),
            ("XRUN", ["--simulator", "VCS"], "VCS"),
            ("vcs", [], "VCS"),
            ("VCS", ["--simulator", "XRUN"], "XRUN"),
        ):
            with self.subTest(platform=platform, argv=argv):
                env = os.environ.copy()
                env.pop("SIM_PLATFORM", None)
                if platform is not None:
                    env["SIM_PLATFORM"] = platform
                result = subprocess.run([sys.executable, "-B", "-c", script, *argv],
                                        env=env,
                                        capture_output=True,
                                        text=True,
                                        check=True)
                self.assertEqual([expected, bool(argv)], json.loads(result.stdout))

    def test_xrun_parallel_defaults_on_and_can_be_disabled(self):
        self.assertTrue(parse_args([]).xrun_parallel)
        options = parse_args(["--xrun-parallel", "--jobs", "2"])
        self.assertTrue(options.xrun_parallel)
        self.assertEqual(2, options.jobs)
        self.assertIn("--xrun-parallel", options.xcelium_explicit_switches)
        self.assertIn("--xrun-parallel", options.reproduce_args)
        serial = parse_args(["--no-xrun-parallel"])
        self.assertFalse(serial.xrun_parallel)
        self.assertIn("--no-xrun-parallel", serial.xcelium_explicit_switches)
        self.assertIn("--no-xrun-parallel", serial.reproduce_args)

    def assert_parse_error(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                parse_args(argv)
        self.assertEqual(2, raised.exception.code)

    def test_vcs_debug_access_is_unset_by_default_and_accepts_known_levels(self):
        default = parse_args([])
        self.assertIsNone(default.vcs_debug_access)
        self.assertNotIn("--vcs-debug-access", default.vcs_explicit_switches)
        for level in ("full", "r", "none"):
            with self.subTest(level=level):
                options = parse_args(["--vcs-debug-access", level])
                self.assertEqual(level, options.vcs_debug_access)
                self.assertIn("--vcs-debug-access", options.vcs_explicit_switches)
                self.assertIn("--vcs-debug-access", options.reproduce_args)
        self.assertEqual("r", parse_args(["--vcs-debug-access=r"]).vcs_debug_access)

    def test_vcs_debug_access_rejects_unknown_levels(self):
        self.assert_parse_error(["--vcs-debug-access", "all"])
        self.assert_parse_error(["--vcs-debug-access", ""])

    def test_vcs_make_jobs_defaults_to_auto_and_accepts_an_explicit_count(self):
        default = parse_args([])
        self.assertEqual("auto", default.vcs_make_jobs)
        self.assertNotIn("--vcs-make-jobs", default.vcs_explicit_switches)

        explicit = parse_args(["--vcs-make-jobs", "4"])
        self.assertEqual(4, explicit.vcs_make_jobs)
        self.assertIn("--vcs-make-jobs", explicit.vcs_explicit_switches)
        self.assertIn("--vcs-make-jobs", explicit.reproduce_args)
        self.assertEqual("auto", parse_args(["--vcs-make-jobs", "auto"]).vcs_make_jobs)

        serial = parse_args(["--no-vcs-make-jobs"])
        self.assertIsNone(serial.vcs_make_jobs)
        self.assertIn("--no-vcs-make-jobs", serial.vcs_explicit_switches)
        self.assertIn("--no-vcs-make-jobs", serial.reproduce_args)

    def test_vcs_make_jobs_rejects_malformed_counts(self):
        # A non-negative range check and the conflicting partcomp request live in
        # the VCS option validator, covered by the runtime contract test.
        self.assert_parse_error(["--vcs-make-jobs", "many"])
        self.assert_parse_error(["--vcs-make-jobs", "2", "--no-vcs-make-jobs"])

    def test_tag_filter_requires_preceding_test_selector(self):
        self.assert_parse_error(["--tag", "smoke"])
        self.assert_parse_error(["--ntag", "slow"])

    def test_default_wave_end_allows_late_wave_start(self):
        options = parse_args(["--waves", "--wave-start", "100000000"])

        self.assertEqual(99999999, options.wave_end)
        self.assertFalse(options.wave_end_was_explicit)

    def test_default_wave_depth_is_bounded(self):
        self.assertEqual(10, parse_args(["--waves"]).wave_depth)
        self.assertEqual(999, parse_args(["--waves", "--wave-depth", "999"]).wave_depth)

    def test_wave_top_defaults_to_hdl_top_and_accepts_project_override(self):
        self.assertEqual("hdl_top", parse_args(["--waves"]).wave_top)
        self.assertEqual("tb_top", parse_args(["--waves", "--wave-top", "tb_top"]).wave_top)

    def test_wave_msv_debug_tcl_call_is_disabled_by_default_and_can_be_enabled(self):
        self.assertFalse(parse_args(["--waves"]).wave_msv_debug_tcl_call)
        self.assertTrue(parse_args(["--waves", "--wave-msv-debug-tcl-call"]).wave_msv_debug_tcl_call)

    def test_ams_runfiles_links_are_disabled_by_default_and_repeatable(self):
        self.assertEqual([], parse_args([]).ams_runfiles_links)
        options = parse_args([
            "--ams-runfiles-link",
            "digital",
            "--ams-runfiles-link",
            "hw",
        ])
        self.assertEqual(["digital", "hw"], options.ams_runfiles_links)
        self.assertIn("--ams-runfiles-link", options.xcelium_explicit_switches)

    def test_wave_msv_debug_tcl_call_requires_wave_capture(self):
        self.assert_parse_error(["--wave-msv-debug-tcl-call"])

    def test_explicit_wave_end_must_follow_wave_start(self):
        self.assert_parse_error(["--waves", "--wave-start", "20", "--wave-end", "10"])
        self.assert_parse_error(["--waves", "--wave-start", "100000000", "--wave-end", "99999999"])

    def test_uvm_max_quit_count_rejects_negative_values_but_allows_zero(self):
        self.assert_parse_error(["--uvm-max-quit-count", "-1"])
        self.assertEqual(0, parse_args(["--uvm-max-quit-count", "0"]).uvm_max_quit_count)

    def test_timeout_rejects_nonfinite_and_unrepresentable_hours(self):
        for timeout in ("nan", "inf", "-inf", "1e300", "24000000000"):
            with self.subTest(timeout=timeout):
                self.assert_parse_error(["--timeout=" + timeout])

    def test_timeout_preserves_zero_and_representable_fractional_hours(self):
        for timeout in ("0", "0.125", "12", "1e10"):
            with self.subTest(timeout=timeout):
                self.assertEqual(float(timeout), parse_args(["--timeout", timeout]).timeout)

    def test_history_filters_enable_default_history_query(self):
        for option in ("--history-bench", "--his-bench"):
            with self.subTest(option=option):
                options = parse_args([option, "sys_tb"])
                self.assertEqual(10, options.history)
                self.assertEqual("sys_tb", options.history_bench)

        for option in ("--history-fail", "--his-fail"):
            with self.subTest(option=option):
                options = parse_args([option])
                self.assertEqual(10, options.history)
                self.assertTrue(options.history_fail)

    def test_history_filters_preserve_explicit_count_and_combine(self):
        options = parse_args(["--his", "20", "--his-bench", "sys_tb", "--his-fail"])

        self.assertEqual(20, options.history)
        self.assertEqual("sys_tb", options.history_bench)
        self.assertTrue(options.history_fail)

    def test_history_queries_reject_test_selection(self):
        self.assert_parse_error(["--his", "-t", "sys_tb:test"])
        self.assert_parse_error(["--his-bench", "sys_tb", "-t", "sys_tb:test"])

    def test_history_bench_rejects_empty_name(self):
        self.assert_parse_error(["--his-bench", ""])

    def test_status_query_supports_long_and_short_names(self):
        self.assertTrue(parse_args(["--status"]).status)
        self.assertTrue(parse_args(["--st"]).status)

    def test_status_query_rejects_history_and_test_selection(self):
        self.assert_parse_error(["--status", "--his"])
        self.assert_parse_error(["--st", "-t", "sys_tb:test"])

    def test_no_compile_reuses_bazel_outputs_by_default(self):
        options = parse_args(["--no-compile"])

        self.assertTrue(options.no_compile)
        self.assertTrue(options.no_bazel)
        self.assertFalse(options.no_bazel_was_explicit)

    def test_explicit_no_bazel_is_tracked(self):
        options = parse_args(["--no-compile", "--no-bazel"])

        self.assertTrue(options.no_bazel)
        self.assertTrue(options.no_bazel_was_explicit)


if __name__ == "__main__":
    unittest.main()
