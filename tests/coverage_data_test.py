import tempfile
import unittest
from pathlib import Path

from lib.coverage_data import aggregate_coverage_metrics, parse_coverage_summary


class CoverageDataTest(unittest.TestCase):

    def _report(self, contents):
        path = Path(tempfile.mkdtemp()) / "coverage.txt"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_parses_vcs_urg_summary_table(self):
        path = self._report("""
SCORE LINE COND TOGGLE FSM BRANCH ASSERT GROUP
87.50 90.00 80.00 70.00 100.00 85.00 95.00 76.00
""")

        self.assertEqual(
            {
                "Overall": "87.50%",
                "Line": "90.00%",
                "Condition": "80.00%",
                "Toggle": "70.00%",
                "FSM": "100.00%",
                "Branch": "85.00%",
                "Assertion": "95.00%",
                "CoverGroup": "76.00%",
            },
            parse_coverage_summary(path),
        )

    def test_parses_imc_cumulative_summary_table(self):
        path = self._report("""
Metric Overall Block Expression FSM Toggle Assertion CoverGroup
Cumulative 82.00% 81.00% 80.00% 79.00% 78.00% 77.00% 76.00%
""")

        self.assertEqual("82.00%", parse_coverage_summary(path)["Overall"])
        self.assertEqual("76.00%", parse_coverage_summary(path)["CoverGroup"])

    def test_missing_report_is_unavailable(self):
        self.assertEqual({}, parse_coverage_summary("/missing/coverage.txt"))

    def test_partial_summary_keeps_available_columns_aligned(self):
        reports = [
            "SCORE LINE COND TOGGLE FSM BRANCH ASSERT GROUP\n"
            "N/A 90.00 N/A 70.00 100.00 80.00 95.00 N/A\n",
            "Metric Overall Line Expression Toggle FSM Branch Assertion CoverGroup\n"
            "Cumulative N/A 90.00% N/A 70.00% 100.00% 80.00% 95.00% N/A\n",
        ]
        for contents in reports:
            with self.subTest(contents=contents):
                metrics = parse_coverage_summary(self._report(contents))
                self.assertEqual(
                    {
                        "Overall": "N/A",
                        "Line": "90.00%",
                        "Expression" if "Expression" in contents else "Condition": "N/A",
                        "Toggle": "70.00%",
                        "FSM": "100.00%",
                        "Branch": "80.00%",
                        "Assertion": "95.00%",
                        "CoverGroup": "N/A",
                    }, metrics)
                coverage = aggregate_coverage_metrics(metrics)
                self.assertEqual("85.00%", coverage["cc"]["Overall"])
                self.assertEqual("90.00%", coverage["total"])
                self.assertEqual("N/A", coverage["vendor_score"])
                self.assertEqual("N/A", coverage["cc"]["Expression" if "Expression" in contents else "Condition"])
                self.assertNotIn("CoverGroup", coverage["cf"])

    def test_unavailable_summary_does_not_read_values_from_a_later_table(self):
        metrics = parse_coverage_summary(self._report("SCORE LINE COND\nN/A N/A N/A\n\n10.00 20.00 30.00\n"))
        self.assertEqual({"Overall": "N/A", "Line": "N/A", "Condition": "N/A"}, metrics)

    def test_aggregates_coverage_like_opentitan_dvsim(self):
        metrics = {
            "Overall": "87.50%",
            "Line": "90.00%",
            "Condition": "80.00%",
            "Toggle": "70.00%",
            "FSM": "100.00%",
            "Branch": "85.00%",
            "Assertion": "95.00%",
            "CoverGroup": "76.00%",
        }

        coverage = aggregate_coverage_metrics(metrics)

        self.assertEqual("85.00%", coverage["cc"]["Overall"])
        self.assertEqual("85.33%", coverage["total"])
        self.assertEqual("87.50%", coverage["vendor_score"])

    def test_aggregation_omits_missing_metrics_and_excludes_block(self):
        coverage = aggregate_coverage_metrics({
            "Block": "1.00%",
            "Line": "80.00%",
            "Branch": "60.00%",
            "Assertion": "70.00%",
        })

        self.assertEqual("70.00%", coverage["cc"]["Overall"])
        self.assertEqual("70.00%", coverage["total"])
        self.assertEqual("1.00%", coverage["cc"]["Block"])

    def test_aggregation_returns_unavailable_for_empty_metrics(self):
        self.assertEqual(
            {
                "total": None,
                "vendor_score": None,
                "cc": {},
                "cf": {},
            },
            aggregate_coverage_metrics({}),
        )


if __name__ == "__main__":
    unittest.main()
