"""License-free adapter contracts; no assertion about Cadence DB immutability.

The mirror lacks runner dependencies. Exercise the actual adapter AST and CLI
declarations with stdlib doubles, then validate AMS concurrency on the EDA host.
"""
import argparse
import ast
import logging
import os
from pathlib import Path
import shlex
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


def source_tree(path):
    return ast.parse((ROOT / path).read_text(encoding="utf-8"))


class XrunParallelTest(unittest.TestCase):

    def setUp(self):
        cls = next(n for n in source_tree("lib/simulators/xcelium.py").body
                   if isinstance(n, ast.ClassDef) and n.name == "XceliumSimulator")
        self.ns = dict(SimulatorInterface=object, os=os, shlex=shlex, log=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[cls], type_ignores=[]), "xcelium.py", "exec"), self.ns)
        self.backend = object.__new__(self.ns["XceliumSimulator"])
        self.backend.options = SimpleNamespace(xrun_parallel=True,
                                               gui=False,
                                               coverage=None,
                                               mce=False,
                                               msie=None,
                                               msie_href=None,
                                               msie_prim=None,
                                               msie_incr=None,
                                               emulator="",
                                               wave_msv_debug_tcl_call=False)
        self.backend.rcfg = SimpleNamespace(regression_dir="/regression")

    def test_default_releases_resource_and_explicit_disable_serializes_database(self):
        first = SimpleNamespace(job_dir="/run/a", vcomper=SimpleNamespace(job_dir="/compile/db"))
        second = SimpleNamespace(job_dir="/run/b", vcomper=first.vcomper)
        self.assertIsNone(self.backend.get_test_exclusive_resource(first))
        self.assertIsNone(self.backend.get_test_exclusive_resource(second))
        self.assertNotEqual(self.backend.get_sim_working_dir(first), self.backend.get_sim_working_dir(second))
        self.backend.options.xrun_parallel = False
        self.assertIsNotNone(self.backend.get_test_exclusive_resource(first))
        self.assertEqual(self.backend.get_test_exclusive_resource(first),
                         self.backend.get_test_exclusive_resource(second))

    def test_callers_without_new_option_default_to_parallel(self):
        del self.backend.options.xrun_parallel
        test = SimpleNamespace(vcomper=SimpleNamespace(job_dir="/compile/db"))
        self.assertIsNone(self.backend.get_test_exclusive_resource(test))

    def test_special_flows_keep_exclusive_resource_even_if_validation_is_bypassed(self):
        self.backend.options.xrun_parallel = True
        test = SimpleNamespace(vcomper=SimpleNamespace(job_dir="/compile/db"))
        for name in ("gui", "coverage", "mce", "msie", "msie_href", "msie_prim", "msie_incr", "emulator"):
            original = getattr(self.backend.options, name)
            with self.subTest(name=name):
                setattr(self.backend.options, name, "enabled")
                self.assertIsNotNone(self.backend.get_test_exclusive_resource(test))
            setattr(self.backend.options, name, original)

    def test_cross_process_compile_and_runfiles_locks_are_preserved(self):
        self.backend.options.xrun_parallel = True
        first = SimpleNamespace(job_dir="/compile/a",
                                resolve_bazel_runfiles_main=lambda: "/shared/runfiles",
                                acquire_shared_runtime_lock=Mock())
        second = SimpleNamespace(job_dir="/compile/b",
                                 resolve_bazel_runfiles_main=lambda: "/shared/runfiles",
                                 acquire_shared_runtime_lock=Mock())
        self.backend.prepare_regression_runtime({"a": first, "b": second})
        paths = [c.args[0] for job in (first, second) for c in job.acquire_shared_runtime_lock.call_args_list]
        expected = [os.path.normcase(os.path.realpath(p)) for p in ("/compile/a", "/compile/b", "/shared/runfiles")]
        self.assertCountEqual(paths, expected)

    def test_parallel_keeps_run_only_command_and_per_test_logs_and_waves(self):
        self.backend.options.xrun_parallel = True
        self.backend.options.wave_type = "shm"
        for name in ("a", "b"):
            test = SimpleNamespace(job_dir="/run/" + name)
            log_path = test.job_dir + "/stdout.log"
            command = shlex.split(self.backend.get_sim_command(test, "-svseed 123", "/compile/db", log_path))
            self.assertIn("-R", command)
            self.assertNotIn("-elaborate", command)
            self.assertEqual(command[command.index("-xmlibdirname") + 1], "/compile/db")
            self.assertEqual(command[command.index("-l") + 1], log_path)
            self.assertEqual(self.backend.get_wave_artifact_path(test.job_dir, "shm"),
                             os.path.join(test.job_dir, "waves.shm"))

    def test_validator_rejects_unsupported_combinations(self):
        fn = next(n for n in source_tree("lib/simulators/xcelium_options.py").body if isinstance(n, ast.FunctionDef))
        ns = dict(os=os)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "xcelium_options.py", "exec"), ns)
        self.backend.options.xrun_parallel = True
        parser = SimpleNamespace(error=Mock(side_effect=ValueError))
        self.backend.options.xcelium_explicit_switches = ["--xrun-parallel"]
        for name in ("coverage", "mce", "msie", "msie_href", "msie_prim", "msie_incr", "emulator"):
            original = getattr(self.backend.options, name)
            setattr(self.backend.options, name, "enabled")
            with self.subTest(name=name), self.assertRaises(ValueError):
                ns[fn.name](self.backend.options, parser)
            self.assertIn("--xrun-parallel", parser.error.call_args.args[0])
            setattr(self.backend.options, name, original)

    def test_cli_defaults_on_and_rerun_preserves_explicit_disable(self):
        fn = next(n for n in source_tree("bin/args_parse/xcelium.py").body if isinstance(n, ast.FunctionDef))
        declaration = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and n.args
                           and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--xrun-parallel")
        parser = argparse.ArgumentParser()
        expr = ast.fix_missing_locations(ast.Expression(body=declaration))
        eval(compile(expr, "xcelium.py", "eval"), dict(gxrun=parser))
        disable = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and n.args
                       and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--no-xrun-parallel")
        eval(compile(ast.fix_missing_locations(ast.Expression(body=disable)), "xcelium.py", "eval"), dict(gxrun=parser))
        self.assertTrue(parser.parse_args([]).xrun_parallel)
        self.assertTrue(parser.parse_args(["--xrun-parallel"]).xrun_parallel)
        self.assertFalse(parser.parse_args(["--no-xrun-parallel"]).xrun_parallel)
        tree = source_tree("bin/args_parse/parser.py")
        selected = [
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "reproduction_args"
            or isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "_RERUN_OMITTED_OPTIONS"
        ]
        ns = {}
        exec(compile(ast.Module(body=selected, type_ignores=[]), "parser.py", "exec"), ns)
        self.assertEqual(ns["reproduction_args"](["-t", "tb:test", "--xrun-parallel", "--jobs", "2"]),
                         ["--xrun-parallel", "--jobs", "2"])
        assignment = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "options.xcelium_explicit_switches")
        self.assertIn("--xrun-parallel", [n.value for n in ast.walk(assignment) if isinstance(n, ast.Constant)])
        self.assertIn("--no-xrun-parallel", [n.value for n in ast.walk(assignment) if isinstance(n, ast.Constant)])
        self.assertEqual(ns["reproduction_args"](["-t", "tb:test", "--no-xrun-parallel"]), ["--no-xrun-parallel"])

    def test_implicit_parallel_does_not_reject_existing_special_flows(self):
        fn = next(n for n in source_tree("lib/simulators/xcelium_options.py").body if isinstance(n, ast.FunctionDef))
        # Execute the parallel-specific validation branch with implicit defaults.
        # The remaining validation needs unrelated complete-repository options.
        code = compile(ast.Module(body=[fn.body[0]], type_ignores=[]), "xcelium_options.py", "exec")
        parser = SimpleNamespace(error=Mock(side_effect=ValueError))
        self.backend.options.xcelium_explicit_switches = []
        for name in ("coverage", "mce", "msie", "msie_href", "msie_prim", "msie_incr", "emulator"):
            original = getattr(self.backend.options, name)
            setattr(self.backend.options, name, "enabled")
            exec(code, dict(options=self.backend.options, parser=parser))
            self.assertFalse(self.backend._parallel_test_runs_enabled())
            setattr(self.backend.options, name, original)
        parser.error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
