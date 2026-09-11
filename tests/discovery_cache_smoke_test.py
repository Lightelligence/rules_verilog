"""Real Bazel discovery and cfg-rebuild contract; no simulator or license needed.

Run directly from the checkout (not inside a Bazel sandbox). The small Starlark
rules model discovery's marker/aspect/output interface, not simulator behavior.
"""

import logging
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.job_lib import BazelTBJob, BazelTestCfgJob
from lib.regression import RegressionConfig

RULES = '''
def _tb(ctx):
    return []

dv_tb = rule(implementation = _tb)

def _cfg(ctx):
    output = ctx.actions.declare_file(ctx.label.name + "_dynamic_args.py")
    ctx.actions.run_shell(
        inputs = [ctx.file.data],
        outputs = [output],
        arguments = [ctx.file.data.path, output.path],
        command = "cp \\"$1\\" \\"$2\\"",
    )
    return [DefaultInfo(files = depset([output]))]

cfg = rule(implementation = _cfg, attrs = {
    "verilog_dv_test_cfg_marker": attr.int(default = 1),
    "abstract": attr.int(default = 0),
    "no_run": attr.int(default = 0),
    "vcomp": attr.label(),
    "data": attr.label(allow_single_file = True),
})

def _info(target, ctx):
    if hasattr(ctx.rule.attr, "verilog_dv_test_cfg_marker"):
        print("verilog_dv_test_cfg_info({}, {}, {}, VCS)".format(
            target.label, ctx.rule.attr.vcomp.label, ctx.rule.attr.tags))
    return []

verilog_dv_test_cfg_info_aspect = aspect(implementation = _info)
'''

CASES_MACRO = '''
load(":dv.bzl", "cfg")

def cases():
    for name, disabled, tags in CASES:
        cfg(name = name, no_run = disabled, tags = tags,
            vcomp = "//benches/soc_tb:soc_tb", data = ":runtime.txt")
'''


class Log:

    def __getattr__(self, name):
        if name == "critical":

            def fail(message, *args):
                raise AssertionError(message % args if args else message)

            return fail
        return getattr(logging.getLogger("discovery-smoke"), name if name != "summary" else "info")


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def config(project):
    result = RegressionConfig.__new__(RegressionConfig)
    result.proj_dir = str(project)
    result.log = Log()
    result.options = SimpleNamespace(
        tests=[SimpleNamespace(btiglob="soc_tb:*", tag=set(), ntag=set())],
        allow_no_run=False,
        no_compile=False,
        no_bazel=False,
        global_tag=set(),
        global_ntag=set(),
        discovery_only=False,
        timeout=1,
    )
    result.max_bench_name_length = result.max_test_name_length = 20
    result.all_vcomp = {}
    result.tests_to_tags = {}
    result.tests_to_simulator = {}
    return result


def main():
    initial_directory = os.getcwd()
    with tempfile.TemporaryDirectory(prefix="rules-verilog-discovery-") as temporary:
        root = Path(temporary)
        project, external = root / "project", root / "ip"
        write(project / "WORKSPACE", 'local_repository(name="rules_verilog", path="../ip")\n')
        write(project / ".bazelrc",
              "startup --output_user_root={}\ncommon --noenable_bzlmod\nbuild --jobs=2\n".format(root / "bazel-output"))
        write(
            project / "benches/soc_tb/BUILD",
            'load("@rules_verilog//verilog/private:dv.bzl", "dv_tb")\ndv_tb(name="soc_tb", visibility=["//visibility:public"])\n'
        )
        write(project / "benches/soc_tb/tests/BUILD",
              'load("@rules_verilog//verilog/private:cases.bzl", "cases")\ncases()\n')
        runtime = project / "benches/soc_tb/tests/runtime.txt"
        write(runtime, '{"simulator": "VCS", "uvm_testname": "old_name"}\n')
        write(external / "WORKSPACE", 'workspace(name="rules_verilog")\n')
        write(external / "verilog/private/BUILD", 'exports_files(["dv.bzl", "cases.bzl"])\n')
        write(external / "verilog/private/dv.bzl", RULES)
        definitions = external / "verilog/private/cases.bzl"
        write(definitions, CASES_MACRO + '\nCASES = [("first", 0, ["old"])]\n')
        os.chdir(project)
        try:
            first = config(project)
            first.test_discovery_all()
            assert first._should_use_cached_discovery(), "Unchanged literal local metadata must be reusable"
            target = "//benches/soc_tb/tests:first"
            assert first.tests_to_tags == {target: ["old"]}

            # Change an action input that is not discovery metadata. Cache stays
            # fresh, but an existing cfg output must still be offered to Bazel.
            write(runtime, '{"simulator": "VCS", "uvm_testname": "new_name"}\n')
            assert first._should_use_cached_discovery()
            first.use_cached_discovery = True
            vcomp = SimpleNamespace(job_dir=str(project),
                                    add_dependency=lambda _job: None,
                                    _children=[],
                                    increase_priority=lambda _priority: None)
            tb_job = BazelTBJob(first, "//benches/soc_tb:soc_tb", vcomp, additional_targets=[target])
            subprocess.run(shlex.split(tb_job.main_cmdline), check=True)
            cfg_job = BazelTestCfgJob(first, [target], vcomp, prebuilt=True)
            assert cfg_job.dynamic_args()["uvm_testname"] == "new_name", "Existing cfg output was incorrectly reused"

            # Only the external macro changes: add a test, change tags and hide
            # the previous test through no_run. No clean or main BUILD edit.
            write(definitions, CASES_MACRO + '\nCASES = [("first", 1, ["changed"]), ("second", 0, ["new"])]\n')
            updated = config(project)
            assert not updated._should_use_cached_discovery()
            updated.test_discovery_all()
            assert updated.tests_to_tags == {"//benches/soc_tb/tests:second": ["new"]}
            assert updated.tests_to_simulator == {"//benches/soc_tb/tests:second": "VCS"}

            # Bazel clean is not a substitute for discovery invalidation.
            subprocess.run(["bazel", "clean"], check=True)
            assert Path(updated._discovery_cache_path()).exists()
            write(definitions, CASES_MACRO + '\nCASES = [("third", 0, ["after_clean"])]\n')
            after_clean = config(project)
            assert not after_clean._should_use_cached_discovery()
            after_clean.test_discovery_all()
            assert after_clean.tests_to_tags == {"//benches/soc_tb/tests:third": ["after_clean"]}
            print("PASS: external macro freshness, selected cfg rebuild, and post-clean discovery")
        finally:
            subprocess.run(["bazel", "shutdown"], check=False)
            os.chdir(initial_directory)


if __name__ == "__main__":
    main()
