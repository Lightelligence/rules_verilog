import tempfile
import unittest
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))
sys.path.insert(0, str(REPO_ROOT / "lib"))

import lint_parser_ascent
import lint_parser_hal


class LintParserStatsTest(unittest.TestCase):

    def _issue(self, filename):
        return SimpleNamespace(filename=str(filename), waived=False)

    def test_hal_directory_stats_walk_to_rtl_root_and_reset(self):
        root = Path(tempfile.mkdtemp())
        source = root / "rtl" / "block" / "subblock" / "issue.sv"
        source.parent.mkdir(parents=True)
        source.touch()
        parser = lint_parser_hal.HalLintLog.__new__(lint_parser_hal.HalLintLog)
        parser.issues = [self._issue(source)]

        with mock.patch.object(lint_parser_hal, "log", mock.Mock()):
            parser.prep_file_stats()

        self.assertEqual({str(root / "rtl" / "block"): 1}, parser.dirs_with_notes)

        parser.issues = []
        with mock.patch.object(lint_parser_hal, "log", mock.Mock()):
            parser.prep_file_stats()
        self.assertEqual({}, parser.dirs_with_notes)

    def test_ascent_directory_stats_walk_to_rtl_root(self):
        root = Path(tempfile.mkdtemp())
        source = root / "rtl" / "block" / "subblock" / "issue.sv"
        source.parent.mkdir(parents=True)
        source.touch()
        parser = lint_parser_ascent.AscentLintLog.__new__(lint_parser_ascent.AscentLintLog)
        parser.issues = [self._issue(source)]

        parser.prep_file_stats()

        self.assertEqual({str(root / "rtl" / "block"): 1}, parser.dirs_with_notes)

    def test_ascent_report_without_file_definition_table_uses_rendered_path(self):
        root = Path(tempfile.mkdtemp())
        source = root / "rtl" / "block" / "issue.sv"
        source.parent.mkdir(parents=True)
        source.write_text("// no waivers\n", encoding="utf-8")
        report = root / "lint.rpt"
        report.write_text("E RULE_ONE: {}:1 bad message New\n".format(source), encoding="utf-8")

        parsed = lint_parser_ascent.AscentLintLog(str(report), mock.Mock())

        self.assertEqual(1, len(parsed.errors))
        self.assertEqual(str(source), parsed.errors[0].filename)
        self.assertFalse(parsed.errors[0].waived)


if __name__ == "__main__":
    unittest.main()
