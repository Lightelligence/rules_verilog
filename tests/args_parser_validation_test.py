import contextlib
import io
import unittest

from bin.args_parser import parse_args


class ArgsParserValidationTest(unittest.TestCase):

    def assert_parse_error(self, argv):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                parse_args(argv)
        self.assertEqual(2, raised.exception.code)

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
