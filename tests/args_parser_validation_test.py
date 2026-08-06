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


if __name__ == "__main__":
    unittest.main()
