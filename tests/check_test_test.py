import tempfile
import unittest
from unittest import mock
from pathlib import Path

from bin import check_test


class CheckTestFastPathTest(unittest.TestCase):

    def setUp(self):
        check_test.active_signatures = list(check_test.default_error_signatures)
        check_test.compile_error_regex()

    def _log(self, contents):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "stdout.log"
        path.write_text(contents, encoding="utf-8", newline="")
        return path

    def test_static_log_fast_path_finds_finish_metadata_and_errors(self):
        path = self._log("SVSEED 123\nUVM_ERROR @ 10\n--- UVM Report Summary ---\n")

        errors, seeds, _, finished = check_test.scan_static_log(path, 25)

        self.assertEqual(["UVM_ERROR @ 10\n"], errors)
        self.assertEqual(["SVSEED 123\n"], seeds)
        self.assertTrue(finished)

    def test_dynamic_signature_log_uses_existing_fallback(self):
        path = self._log("TEST_CHECK_DISABLE: UVM_ERROR\n--- UVM Report Summary ---\n")

        self.assertIsNone(check_test.scan_static_log(path, 25))

    def test_uvm_summary_with_nonzero_error_count_fails(self):
        path = self._log("--- UVM Report Summary ---\nUVM_ERROR :    1\nUVM_FATAL :    0\n")

        errors, _, _, finished = check_test.scan_static_log(path, 25)

        self.assertEqual(["UVM_ERROR :    1\n"], errors)
        self.assertTrue(finished)

    def test_ascii_default_signatures_retain_mmap_path(self):
        path = self._log("UVM_ERROR : 1\n--- UVM Report Summary ---\n")

        with mock.patch.object(check_test, "scan_text_log", side_effect=AssertionError("unexpected text scan")):
            errors, _, _, finished = check_test.scan_static_log(path, 25)

        self.assertEqual(["UVM_ERROR : 1\n"], errors)
        self.assertTrue(finished)

    def test_default_unicode_whitespace_matches_decoded_streaming(self):
        path = self._log("UVM_ERROR\u3000:\u30001\u3000\n--- UVM Report Summary ---\n")

        static_result = check_test.scan_static_log(path, 25)
        text_result = check_test.scan_text_log(path, 25)

        self.assertEqual(text_result, static_result)
        self.assertEqual(["UVM_ERROR\u3000:\u30001\u3000\n"], static_result[0])
        self.assertTrue(static_result[3])

    def test_default_invalid_utf8_matches_decoded_replacement_semantics(self):
        path = self._log("")
        path.write_bytes(b"Warning-\xe2\x82FCIBR\n--- UVM Report Summary ---\n")

        static_result = check_test.scan_static_log(path, 25)
        text_result = check_test.scan_text_log(path, 25)

        self.assertEqual(text_result, static_result)
        self.assertEqual(["Warning-\ufffdFCIBR\n"], static_result[0])
        self.assertTrue(static_result[3])

    def test_project_pass_and_fail_patterns_are_configurable(self):
        pass_regex = check_test.compile_patterns([r"^PROJECT PASS$"])
        fail_regex = check_test.compile_patterns([r"^PROJECT FAIL$"])
        path = self._log("PROJECT FAIL\nPROJECT PASS\n")

        errors, _, _, finished = check_test.scan_static_log(
            path,
            25,
            extra_error_regex=fail_regex,
            required_finish_regex=pass_regex,
        )

        self.assertEqual(["PROJECT FAIL\n"], errors)
        self.assertTrue(finished)

    def test_project_patterns_match_crlf_logs_on_static_fast_path(self):
        pass_regex = check_test.compile_patterns([r"^PROJECT PASS$"])
        fail_regex = check_test.compile_patterns([r"^PROJECT FAIL$"])
        path = Path(tempfile.mkdtemp()) / "stdout.log"
        path.write_bytes(b"PROJECT FAIL\r\nPROJECT PASS\r\n")

        errors, _, _, finished = check_test.scan_static_log(
            path,
            25,
            extra_error_regex=fail_regex,
            required_finish_regex=pass_regex,
        )

        self.assertEqual(["PROJECT FAIL\n"], errors)
        self.assertTrue(finished)

    def test_project_unicode_patterns_equal_dynamic_directive_path(self):
        pass_regex = check_test.compile_patterns([r"^PASS \w+$"])
        fail_regex = check_test.compile_patterns([r"\bFAIL\b"])
        for index, (contents, expected_errors) in enumerate((
            ("FAILé\nPASS 中\n", []),
            ("FAIL 中\nPASS 中\n", ["FAIL 中\n"]),
            ("FAILé\r\nPASS 中\r\n", []),
            ("FAILé\rPASS 中\r", []),
        )):
            with self.subTest(contents=contents):
                check_test.active_signatures = list(check_test.default_error_signatures)
                check_test.compile_error_regex()
                path = self._log(contents)
                static_result = check_test.scan_static_log(path, 25, fail_regex, pass_regex)
                directive_path = self._log(f"TEST_CHECK_ENABLE: NEVER_MATCH_THIS_DIRECTIVE_{index}\n" + contents)
                dynamic_result = check_test.scan_text_log(directive_path, 25, fail_regex, pass_regex)

                self.assertEqual(static_result, dynamic_result)
                self.assertEqual(expected_errors, static_result[0])
                self.assertTrue(static_result[3])

    def test_project_patterns_preserve_invalid_utf8_replacement_semantics(self):
        path = self._log("")
        path.write_bytes(b"PASS \xff\n")
        pass_regex = check_test.compile_patterns(["^PASS \ufffd$"])

        self.assertTrue(check_test.scan_static_log(path, 25, required_finish_regex=pass_regex)[3])

    def test_independent_patterns_preserve_global_flags_and_capturing_groups(self):
        patterns = check_test.compile_patterns([r"(?i)FAIL", r"^(PASS) \1$", r"(?P<state>DONE) (?P=state)"])

        self.assertIsNotNone(patterns.search("fail\n"))
        self.assertIsNone(patterns.search("done done\n"))
        self.assertEqual(("PASS", ), patterns.search("PASS PASS\n").groups())
        self.assertEqual({"state": "DONE"}, patterns.search("DONE DONE\n").groupdict())

    def test_single_pattern_preserves_global_flags_and_backreferences(self):
        pattern = check_test.compile_patterns([r"(?i)^(PASS) \1$"])

        self.assertEqual(("PASS", ), pattern.search("PASS pass\n").groups())
        self.assertIsNone(pattern.search("PASS fail\n"))

    def test_independent_patterns_allow_repeated_named_groups_and_keep_match_order(self):
        patterns = check_test.compile_patterns([r"(?P<state>PASS)", r"(?P<state>FAIL)"])

        self.assertEqual("FAIL", patterns.search("FAIL before PASS").group("state"))
        self.assertIsNone(check_test.compile_patterns([]).search("anything"))

    def test_dynamic_signatures_accept_independent_global_flags(self):
        path = self._log("TEST_CHECK_ENABLE: (?i)PROJECT FAIL\nproject fail\n--- UVM Report Summary ---\n")

        errors, _, _, finished = check_test.scan_text_log(path, 25)

        self.assertEqual(["project fail\n"], errors)
        self.assertTrue(finished)

    def test_streamed_project_patterns_preserve_error_limit_and_line_scoping(self):
        path = self._log("FAIL\nDETAIL\nFAIL\nFAIL\nPASS\n")
        fail_regex = check_test.compile_patterns([r"FAIL\nDETAIL", r"^FAIL$"])
        pass_regex = check_test.compile_patterns([r"^PASS$"])

        errors, _, _, finished = check_test.scan_static_log(path, 2, fail_regex, pass_regex)

        self.assertEqual(["FAIL\n", "FAIL\n"], errors)
        self.assertFalse(finished)

    def test_project_patterns_do_not_match_across_lines(self):
        path = self._log("FAIL\nDETAIL\nPASS\n")
        fail_regex = check_test.compile_patterns([r"FAIL\nDETAIL"])
        pass_regex = check_test.compile_patterns([r"^PASS$"])

        errors, _, _, finished = check_test.scan_static_log(path, 25, fail_regex, pass_regex)

        self.assertEqual([], errors)
        self.assertTrue(finished)


if __name__ == "__main__":
    unittest.main()
