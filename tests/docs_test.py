import os
from pathlib import Path
import re
import unittest


def _repo_root():
    test_srcdir = os.environ.get("TEST_SRCDIR")
    if test_srcdir:
        return Path(test_srcdir) / os.environ.get("TEST_WORKSPACE", "rules_verilog")
    return Path(__file__).resolve().parents[1]


REPO_ROOT = _repo_root()


class DocsTest(unittest.TestCase):

    def test_public_rules_are_listed_in_api_docs(self):
        public_defs = (REPO_ROOT / "verilog" / "defs.bzl").read_text(encoding="utf-8")
        api_docs = (REPO_ROOT / "docs" / "defs.md").read_text(encoding="utf-8")
        public_rules = re.findall(r"^(verilog_[a-z0-9_]+) = _", public_defs, flags=re.MULTILINE)

        self.assertTrue(public_rules)
        for rule_name in public_rules:
            self.assertIn('<a id="{}"></a>'.format(rule_name), api_docs)

    def test_local_markdown_links_resolve(self):
        link_pattern = re.compile(r"\[[^\]]+\]\((?![a-z]+:|#)([^)#]+)(?:#[^)]+)?\)")
        for markdown in [REPO_ROOT / "README.md"] + sorted((REPO_ROOT / "docs").glob("*.md")):
            contents = markdown.read_text(encoding="utf-8")
            for target in link_pattern.findall(contents):
                with self.subTest(markdown=markdown.name, target=target):
                    self.assertTrue((markdown.parent / target).resolve().exists())

    def test_dv_test_cfg_macro_parameters_are_documented(self):
        dv_rules = (REPO_ROOT / "verilog" / "private" / "dv.bzl").read_text(encoding="utf-8")
        api_docs = (REPO_ROOT / "docs" / "defs.md").read_text(encoding="utf-8")
        signature = re.search(r"def verilog_dv_test_cfg\(([^)]*)\):", dv_rules)

        self.assertIsNotNone(signature)
        parameters = [entry.split("=", 1)[0].strip() for entry in signature.group(1).split(",")]
        for parameter in parameters:
            self.assertIn('<a id="verilog_dv_test_cfg-{}"></a>'.format(parameter), api_docs)

    def test_setup_docs_use_canonical_repository_and_archive_prefix(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('"https://github.com/Lightelligence/rules_verilog/archive/{}.tar.gz"', readme)
        self.assertIn('strip_prefix = "rules_verilog-{}".format(RULES_VERILOG_COMMIT)', readme)
        self.assertNotIn("justin371/new_rules_verilog", readme)
        self.assertNotIn("LM_LICENESE_FILE", readme)

    def test_documented_configs_select_simulators_without_command_overrides(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        for config, simulator in (("vcs", "VCS"), ("xrun", "XRUN")):
            self.assertIn("build:{} --@rules_verilog//:verilog_unit_test_simulator={}".format(config, simulator),
                          readme)
        settings = re.findall(r"^build:(?:vcs|xrun) --@rules_verilog//:([a-z0-9_]+)=", readme, flags=re.MULTILINE)
        self.assertEqual(["verilog_unit_test_simulator", "verilog_unit_test_simulator"], settings)


if __name__ == "__main__":
    unittest.main()
