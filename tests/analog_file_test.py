"""License-free contracts for the actual runner functions in a partial checkout.

Load the relevant AST nodes because this local mirror omits simmer dependencies.
This does not substitute for Bazel analysis or a licensed XRUN integration run.
Run: python -m unittest discover -s tests -p analog_file_test.py
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "bin/simmer.py").read_text(encoding="utf-8"))
FUNCTIONS = [node for node in TREE.body if isinstance(node, ast.FunctionDef)
             and node.name in {"_analog_profile", "_load_analog_profiles", "_group_analog_tests"}]


class AnalogFileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ns = dict(os=os, json=json, hashlib=hashlib, subprocess=Mock())
        exec(compile(ast.Module(body=FUNCTIONS, type_ignores=[]), "simmer.py", "exec"), self.ns)

    def profile(self, name="dc.scs", extra=()):
        path = self.root / name
        if not path.exists():
            path.write_text("simulator lang=spectre\n", encoding="utf-8")
        return self.ns["_analog_profile"](
            dict(schema_version=1, entry=name, inputs=[name, *extra]), str(self.root))

    def test_same_input_reuses_group_different_file_splits_and_keeps_iterations(self):
        dc = self.profile()
        step = self.profile("step.scs")
        groups = self.ns["_group_analog_tests"](
            {"a": 2, "b": 3, "c": 1, "legacy": 4}, {"a": dc, "b": dc, "c": step})
        self.assertEqual([g[1] for g in groups], [{"a": 2, "b": 3}, {"c": 1}, {"legacy": 4}])

    def test_data_content_invalidates_variant_and_order_does_not(self):
        data = self.root / "wave.txt"
        data.write_text("0 0.85\n", encoding="utf-8")
        first = self.profile(extra=["wave.txt"])
        config = dict(first["config"], inputs=["wave.txt", "dc.scs", "wave.txt"])
        self.assertEqual(first["key"], self.ns["_analog_profile"](config, str(self.root))["key"])
        data.write_text("0 0.90\n", encoding="utf-8")
        self.assertNotEqual(first["key"], self.profile(extra=["wave.txt"])["key"])

    def test_entry_content_invalidates_variant(self):
        first = self.profile()
        (self.root / "dc.scs").write_text("// updated voltage\n", encoding="utf-8")
        self.assertNotEqual(first["key"], self.profile()["key"])

    def test_missing_dependency_and_traversal_fail(self):
        with self.assertRaises(FileNotFoundError):
            self.profile(extra=["missing.dat"])
        with self.assertRaises(ValueError):
            self.profile(extra=["../escape.dat"])

    def test_loader_builds_metadata_and_selects_execution_paths(self):
        self.profile()
        package = self.root / "bench"
        package.mkdir()
        (package / "case_analog_config.json").write_text(json.dumps(
            dict(schema_version=1, entry="dc.scs", inputs=["dc.scs"])), encoding="utf-8")
        self.ns["get_bazel_bin"] = lambda project: str(self.root)
        self.ns["subprocess"].run.return_value = SimpleNamespace(stdout=str(self.root))
        rcfg = SimpleNamespace(proj_dir=str(self.root), all_vcomp={"//bench:tb": {"//bench:case": 1}})
        opts = SimpleNamespace(no_bazel=False, no_compile=False, simulator="XRUN", emulator="")
        result = self.ns["_load_analog_profiles"](rcfg, opts)
        self.assertEqual(result["//bench:case"]["entry"], str(self.root / "dc.scs"))
        self.assertEqual(self.ns["subprocess"].run.call_args_list[0].args[0],
                         ["bazel", "build", "//bench:case"])
        opts.simulator = "VCS"
        with self.assertRaisesRegex(ValueError, "standard XRUN"):
            self.ns["_load_analog_profiles"](rcfg, opts)

    def test_real_scheduler_routes_each_test_to_its_variant(self):
        main = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        loop = next(n for n in main.body if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                    and any(isinstance(c, ast.For) and isinstance(c.target, ast.Tuple)
                            and ast.unparse(c.target) == "(profile, group_tests)" for c in n.body))
        dc, step = self.profile(), self.profile("step.scs")
        rcfg = SimpleNamespace(all_vcomp={"//bench:tb": {"a": 1, "b": 2, "c": 1}})
        def compile_job(rcfg, target, simulator, analog_profile=None):
            return SimpleNamespace(target=target, profile=analog_profile, add_dependency=Mock())
        def test_job(rcfg, target, **kwargs):
            return SimpleNamespace(target=target, **kwargs, add_dependency=Mock())
        ns = dict(self.ns, rcfg=rcfg, analog_profiles={"a": dc, "b": dc, "c": step},
                  VCompJob=compile_job, TestJob=test_job, simulator=object(),
                  job_lib=SimpleNamespace(BazelTBJob=Mock(), BazelTestCfgJob=Mock()),
                  rv_utils=SimpleNamespace(IterationCfg=lambda iterations: iterations),
                  vcomp_jobs={}, runtime_vcomp={}, btbj_jobs=[], btcj_jobs=[], dynamic_test_plan=False,
                  options=SimpleNamespace(seed=7))
        exec(compile(ast.Module(body=[loop], type_ignores=[]), "simmer.py", "exec"), ns)
        tests = [test for _, group in ns["runtime_vcomp"].values() for test in group]
        self.assertEqual(len(ns["vcomp_jobs"]), 2)
        self.assertEqual(len(ns["btbj_jobs"]), 1)
        self.assertEqual(len(tests), 4)
        self.assertIs(tests[0].vcomper, tests[1].vcomper)
        self.assertIsNot(tests[0].vcomper, tests[-1].vcomper)
        self.assertEqual(tests[-1].vcomper.profile, step)
        self.assertEqual(set(ns["runtime_vcomp"]), set(ns["vcomp_jobs"]))
        for key, (_, group) in ns["runtime_vcomp"].items():
            # Reproduce print_summary's lookup, then check it selected the actual
            # compile job of EVERY test, not an alias to the first variant.
            vcomp = ns["vcomp_jobs"][key]
            self.assertTrue(all(test.vcomper is vcomp for test in group))

    def test_summary_keys_for_single_variant_legacy_and_mixed_runs(self):
        main = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        start = next(i for i, n in enumerate(main.body) if isinstance(n, ast.Assign)
                     and ast.unparse(n.targets[0]) == "runtime_vcomp")
        stop = next(i for i, n in enumerate(main.body[start:], start) if isinstance(n, ast.Assign)
                    and ast.unparse(n.targets[0]) == "rcfg.all_vcomp")
        scheduler = compile(ast.Module(body=main.body[start:stop + 1], type_ignores=[]), "simmer.py", "exec")
        dc, step = self.profile(), self.profile("step.scs")
        scenarios = [({"a": 1}, {"a": dc}), ({"a": 1}, {}),
                     ({"a": 2, "b": 1, "c": 1}, {"a": dc, "b": step})]
        for selected, profiles in scenarios:
            with self.subTest(selected=selected, profiles=list(profiles)):
                public_tb = "//bench:tb"
                rcfg = SimpleNamespace(all_vcomp={public_tb: selected})
                def compile_job(rcfg, target, simulator, analog_profile=None):
                    return SimpleNamespace(bazel_vcomp_target=target, profile=analog_profile,
                        jobstatus="FAILED" if analog_profile is step else "PASSED", add_dependency=Mock())
                def test_job(rcfg, target, **kwargs):
                    job = SimpleNamespace(target=target, **kwargs, add_dependency=Mock())
                    kwargs["icfg"].jobs.append(job)
                    return job
                seeds = {(public_tb, test, i): 100 + i for test, count in selected.items()
                         for i in range(1, count + 1)}
                ns = dict(self.ns, rcfg=rcfg, analog_profiles=profiles, VCompJob=compile_job,
                    TestJob=test_job, simulator=object(), vcomp_jobs={}, btbj_jobs=[], btcj_jobs=[],
                    job_lib=SimpleNamespace(BazelTBJob=Mock(), BazelTestCfgJob=Mock()),
                    rv_utils=SimpleNamespace(IterationCfg=lambda n: SimpleNamespace(target=n, jobs=[])),
                    dynamic_test_plan=False, options=SimpleNamespace(seed=None), planned_seeds=seeds)
                exec(scheduler, ns)
                self.assertEqual(set(rcfg.all_vcomp), set(ns["vcomp_jobs"]))
                count = 0
                failed = []
                for key, (icfgs, tests) in rcfg.all_vcomp.items():
                    compile_result = ns["vcomp_jobs"][key]
                    self.assertEqual(compile_result.bazel_vcomp_target, public_tb)
                    self.assertEqual(sum(c.target for c in icfgs), len(tests))
                    count += len(tests)
                    for test in tests:
                        self.assertIs(test.vcomper, compile_result)
                        self.assertEqual(test.planned_seed, seeds[(public_tb, test.target, test.iteration)])
                    if compile_result.jobstatus == "FAILED":
                        failed.extend(test.target for test in tests)
                self.assertEqual(count, sum(selected.values()))
                self.assertEqual(failed, ["b"] if "b" in selected else [])
                if not profiles:
                    self.assertEqual(list(rcfg.all_vcomp), [public_tb])

    def test_actual_compile_wrapper_keeps_common_inputs_and_selects_one_scs(self):
        profile = self.profile("dc space.scs")
        job_dir = self.root / "compile"
        job_dir.mkdir()
        common = self.root / "common.f"
        common.write_text("amscf.scs\n", encoding="utf-8")
        cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "VCompJob")
        pre_run = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "pre_run")
        selected = next(n for n in pre_run.body if isinstance(n, ast.If)
                        and ast.unparse(n.test) == "self.analog_profile")
        job = SimpleNamespace(analog_profile=profile, job_dir=str(job_dir),
                              bazel_compile_args=str(common), name="tb")
        ns = dict(self.ns, self=job, log=Mock())
        code = compile(ast.Module(body=[selected], type_ignores=[]), "simmer.py", "exec")
        exec(code, ns)
        lines = Path(job.bazel_compile_args).read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0][3:]), str(common))
        self.assertEqual(json.loads(lines[1]), profile["entry"])
        self.assertEqual(len(lines), 2)
        self.assertEqual(common.read_text(encoding="utf-8"), "amscf.scs\n")
        self.assertTrue((job_dir / "analog_config.json").is_file())
        (self.root / "dc space.scs").write_text("// changed while scheduled", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "changed during build"):
            exec(code, ns)

    def test_legacy_metadata_without_analog_selection_does_not_split(self):
        self.ns["get_bazel_bin"] = lambda project: str(self.root)
        rcfg = SimpleNamespace(proj_dir=str(self.root), all_vcomp={"//bench:tb": {"//bench:old": 1}})
        opts = SimpleNamespace(no_bazel=True, no_compile=False, simulator="XRUN", emulator="")
        self.assertEqual(self.ns["_load_analog_profiles"](rcfg, opts), {})
        self.ns["subprocess"].run.assert_not_called()

    def test_rule_inherits_and_replaces_analog_inputs(self):
        # Evaluate the pure rule implementation with Bazel value/action doubles.
        # Actual Bazel attr/provider validation still requires the full workspace.
        rule_tree = ast.parse((ROOT / "verilog/private/dv.bzl").read_text(encoding="utf-8"))
        selected = [n for n in rule_tree.body if isinstance(n, ast.FunctionDef)
                    and n.name in {"_build_test_runtime_options", "_verilog_dv_test_cfg_impl"}]
        def depset(files):
            return SimpleNamespace(to_list=lambda: list({getattr(f, "path", str(f)): f for f in files}.values()))
        ns = dict(json=SimpleNamespace(encode=json.dumps), depset=depset,
                  DVTestInfo=SimpleNamespace, DefaultInfo=lambda **kw: kw, DVTBInfo=object(),
                  fail=lambda message: (_ for _ in ()).throw(ValueError(message)))
        exec(compile(ast.Module(body=selected, type_ignores=[]), "dv.bzl", "exec"), ns)
        def configure(entry=None, data=(), parents=(), simulator="XRUN"):
            writes = []
            ctx = SimpleNamespace(
                label="//test:case",
                attr=SimpleNamespace(inherits=[{SimpleNamespace: p} for p in parents],
                    uvm_testname="", tb=None, simulator=simulator, timeout=-1, pre_run="",
                    description="", sim_opts={}, abstract=True, name="case", tags=[], sockets={}),
                file=SimpleNamespace(analog_file=entry), files=SimpleNamespace(analog_data=list(data)),
                outputs=SimpleNamespace(dynamic_args="dynamic", analog_config="analog"),
                actions=SimpleNamespace(write=lambda **kw: writes.append(kw)),
                runfiles=lambda **kw: kw,
            )
            result = ns["_verilog_dv_test_cfg_impl"](ctx)
            manifest = json.loads(next(w["content"] for w in writes if w["output"] == "analog"))
            return result[0], manifest
        dc = SimpleNamespace(path="analog/dc.scs")
        step = SimpleNamespace(path="analog/step.scs")
        wave = SimpleNamespace(path="analog/wave.txt")
        parent, _ = configure(dc, [wave])
        inherited, manifest = configure(parents=[parent])
        self.assertIs(inherited.analog_file, dc)
        self.assertEqual(set(manifest["inputs"]), {dc.path, wave.path})
        replaced, manifest = configure(step, parents=[parent])
        self.assertIs(replaced.analog_file, step)
        self.assertEqual(manifest["inputs"], [step.path])
        with self.assertRaisesRegex(ValueError, "only by XRUN"):
            configure(dc, simulator="VCS")


if __name__ == "__main__":
    unittest.main()
