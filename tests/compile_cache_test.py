import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lib import compile_cache
from lib.compile_cache import (CompileDirectoryLock, can_reuse_compile, compile_fingerprint, discover_filelist_inputs,
                               invalidate_compile_fingerprint, normalize_compile_script_paths,
                               validate_compile_fingerprint, write_compile_fingerprint)


class CompileCacheTest(unittest.TestCase):

    def test_extra_input_streaming_preserves_identity_and_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            large = root / "large.cfg"
            large.write_bytes(b"\x00\xffx" * (1024 * 1024 + 17))
            empty = root / "empty.cfg"
            empty.write_bytes(b"")
            paths = [large, None, root / "missing.cfg", empty, large]
            expected = hashlib.sha256()
            content_hashes = []
            for path in sorted(os.path.abspath(os.fspath(path)) for path in paths if path):
                content = Path(path).read_bytes() if Path(path).exists() else b"<missing>"
                expected.update(path.encode("utf-8") + b"\0" + content + b"\0")
                content_hashes.append(hashlib.sha256(content + b"\0").hexdigest())
            content = hashlib.sha256(b"".join(value.encode("ascii") + b"\0" for value in sorted(content_hashes)))
            self.assertEqual((expected.hexdigest(), content.hexdigest()), compile_cache._extra_input_digests(paths))

    def test_extra_input_read_failure_discards_partial_bytes(self):
        path = os.path.abspath("unreadable.cfg")
        stream = mock.MagicMock()
        stream.__enter__.return_value.read.side_effect = [b"partial data", OSError("read failure")]
        expected_path = hashlib.sha256(path.encode("utf-8") + b"\0<missing>\0").hexdigest()
        expected_content = hashlib.sha256(hashlib.sha256(b"<missing>\0").hexdigest().encode("ascii") +
                                          b"\0").hexdigest()
        with mock.patch("lib.compile_cache.open", return_value=stream):
            self.assertEqual((expected_path, expected_content), compile_cache._extra_input_digests([path]))

    def test_repeated_directory_inputs_walk_once_but_refresh_between_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            includes = root / "inc"
            includes.mkdir()
            header = includes / "arbitrary.header_name"
            header.write_text("`define VALUE 1\n", encoding="utf-8")
            source = includes / "top.sv"
            source.write_text('`include "arbitrary.header_name"\n', encoding="utf-8")
            nested = root / "nested.f"
            nested.write_text("+incdir+inc\n", encoding="utf-8")
            filelist = root / "compile.f"
            filelist.write_text("+incdir+inc\n-incdir ./inc\n-y inc\n-f nested.f\n", encoding="utf-8")
            with mock.patch.object(compile_cache, "_directory_inputs", wraps=compile_cache._directory_inputs) as walk:
                inputs = discover_filelist_inputs(filelist, root)
                self.assertEqual(1, walk.call_count)
            self.assertEqual(sorted(map(str, (filelist, nested, source, header))), inputs)
            original = compile_fingerprint(root, "vcs", filelist, extra_input_paths=inputs)
            added = includes / "new.extension"
            added.write_text("new header\n", encoding="utf-8")
            header.write_text("`define VALUE 2\n", encoding="utf-8")
            with mock.patch.object(compile_cache, "_directory_inputs", wraps=compile_cache._directory_inputs) as walk:
                refreshed = discover_filelist_inputs(filelist, root)
                self.assertEqual(1, walk.call_count)
            self.assertIn(str(added), refreshed)
            self.assertNotEqual(original, compile_fingerprint(root, "vcs", filelist, extra_input_paths=refreshed))

    def _project(self):
        path = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
        source = path / "top.sv"
        source.write_text("module top; endmodule\n", encoding="utf-8")
        subprocess.run(["git", "add", "top.sv"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
        compile_args = path / "compile.f"
        compile_args.write_text("top.sv\n", encoding="utf-8")
        return path, source, compile_args

    def test_fingerprint_changes_with_source_or_compile_mode(self):
        project, source, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)

        source.write_text("module top; logic changed; endmodule\n", encoding="utf-8")
        source_changed = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)
        mode_changed = compile_fingerprint(project, "vcs -debug_access -f compile.f", compile_args, inventory, project)

        self.assertNotEqual(initial, source_changed)
        self.assertEqual(initial["compile_inputs_manifest_sha256"], source_changed["compile_inputs_manifest_sha256"])
        self.assertNotEqual(source_changed, mode_changed)

    @unittest.skipUnless(os.name == "posix", "fcntl locks require POSIX")
    def test_compile_directory_lock_serializes_independent_processes(self):
        lock_path = Path(tempfile.mkdtemp()) / "vcomp.compile.lock"
        first = CompileDirectoryLock(lock_path)
        probe = ("import fcntl, sys\n"
                 "with open(sys.argv[1], 'a+', encoding='utf-8') as filep:\n"
                 "    try:\n"
                 "        fcntl.flock(filep, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                 "    except BlockingIOError:\n"
                 "        sys.exit(1)\n")

        self.assertTrue(first.acquire(blocking=False))
        self.assertEqual(1, subprocess.run([sys.executable, "-c", probe, str(lock_path)], check=False).returncode)
        first.release()
        self.assertEqual(0, subprocess.run([sys.executable, "-c", probe, str(lock_path)], check=False).returncode)

    def test_fingerprint_ignores_unrelated_tracked_changes(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)

        (project / "README.md").write_text("documentation only\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
        subprocess.run(["git", "commit", "-qm", "docs"], cwd=project, check=True)

        self.assertEqual(initial, compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project))

    def test_fingerprint_ignores_untracked_runtime_artifacts(self):
        project, _, compile_args = self._project()
        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args)

        (project / ".last_sim").write_text("sim/run\n", encoding="utf-8")
        (project / "simmer.log").write_text("runtime log\n", encoding="utf-8")

        self.assertEqual(initial, compile_fingerprint(project, "vcs -f compile.f", compile_args))

    def test_changed_inputs_invalidate_only_the_dependent_bench(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("first", "second"):
                bench = root / name
                bench.mkdir()
                (bench / "top.sv").write_text("module top; endmodule\n", encoding="utf-8")
                (bench / "compile.f").write_text(name + "/top.sv\n", encoding="utf-8")
                (bench / "inputs.txt").write_text("source\t" + name + "/top.sv\n", encoding="utf-8")

            def fingerprint(name):
                bench = root / name
                return compile_fingerprint(root, "compiler", bench / "compile.f", bench / "inputs.txt", root)

            for name in ("first", "second"):
                write_compile_fingerprint(root / name, fingerprint(name))
            (root / "first/top.sv").write_text("module top; logic changed; endmodule\n", encoding="utf-8")
            self.assertFalse(can_reuse_compile(root / "first", fingerprint("first"), lambda: None)[0])
            self.assertTrue(can_reuse_compile(root / "second", fingerprint("second"), lambda: None)[0])

    def test_manifest_rejects_incompatible_reuse(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        write_compile_fingerprint(job_dir, fingerprint)

        validate_compile_fingerprint(job_dir, fingerprint)
        with self.assertRaises(RuntimeError):
            validate_compile_fingerprint(job_dir, dict(fingerprint, compile_script="changed"))

    def test_fingerprint_normalizes_host_specific_runfiles_root(self):
        project, _, compile_args = self._project()
        first_root = project / "host-a" / "bazel-bin" / "tb.runfiles" / "__main__"
        second_root = project / "host-b" / "bazel-bin" / "tb.runfiles" / "__main__"
        first_script = "cd {}\nvcs -file {}/tb_compile_args.f\n".format(first_root, first_root)
        second_script = "cd {}\nvcs -file {}/tb_compile_args.f\n".format(second_root, second_root)

        first = normalize_compile_script_paths(first_script, {"BAZEL_RUNFILES_MAIN": first_root})
        second = normalize_compile_script_paths(second_script, {"BAZEL_RUNFILES_MAIN": second_root})

        self.assertEqual(first, second)
        self.assertEqual(
            compile_fingerprint(project, first, compile_args),
            compile_fingerprint(project, second, compile_args),
        )

    def test_fingerprint_mismatch_reports_changed_fields(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            environment={"PATH": "/tools/vcs/bin"},
        )
        write_compile_fingerprint(job_dir, fingerprint)
        changed = compile_fingerprint(
            project,
            "vcs -debug_access -f compile.f",
            compile_args,
            environment={"PATH": "/different/tools/vcs/bin"},
        )

        with self.assertRaisesRegex(RuntimeError, r"compile_script_sha256, environment\.PATH"):
            validate_compile_fingerprint(job_dir, changed)

    def test_automatic_reuse_turns_validation_failure_into_cache_miss(self):
        project, _, compile_args = self._project()
        job_dir = project / "vcomp"
        job_dir.mkdir()
        fingerprint = compile_fingerprint(project, "vcs -f compile.f", compile_args)
        write_compile_fingerprint(job_dir, fingerprint)

        self.assertEqual((True, None), can_reuse_compile(job_dir, fingerprint, lambda: None))
        hit, reason = can_reuse_compile(job_dir, fingerprint, lambda: (_ for _ in ()).throw(OSError("no simv")))
        self.assertFalse(hit)
        self.assertIn("no simv", reason)

        invalidate_compile_fingerprint(job_dir)
        hit, reason = can_reuse_compile(job_dir, fingerprint, lambda: None)
        self.assertFalse(hit)
        self.assertIn("requires", reason)

    def test_fingerprint_tracks_bazel_runfile_content(self):
        project, _, compile_args = self._project()
        runfiles = Path(tempfile.mkdtemp())
        external_source = runfiles / "external" / "generated.sv"
        external_source.parent.mkdir()
        external_source.write_text("module generated; endmodule\n", encoding="utf-8")
        inventory = runfiles / "compile_inputs.txt"
        inventory.write_text("source\texternal/generated.sv\n", encoding="utf-8")

        initial = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)
        external_source.write_text("module generated; logic changed; endmodule\n", encoding="utf-8")
        changed = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)

        self.assertNotEqual(initial, changed)

    def test_precomputed_compile_input_digest_matches_direct_hash(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        direct = compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, project)
        digest = project / "compile_inputs.sha256"
        digest.write_text(direct["compile_inputs_sha256"] + "\n", encoding="ascii")

        precomputed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            inventory,
            project,
            compile_inputs_digest_path=digest,
        )

        self.assertEqual(direct, precomputed)

    def test_precomputed_compile_input_digest_rejects_malformed_content(self):
        project, _, compile_args = self._project()
        inventory = project / "compile_inputs.txt"
        inventory.write_text("source\ttop.sv\n", encoding="utf-8")
        digest = project / "compile_inputs.sha256"
        digest.write_text("not-a-digest\n", encoding="ascii")

        with self.assertRaisesRegex(RuntimeError, "Malformed Bazel compile input digest"):
            compile_fingerprint(
                project,
                "vcs -f compile.f",
                compile_args,
                inventory,
                project,
                compile_inputs_digest_path=digest,
            )

    def test_fingerprint_rejects_missing_inventory_input(self):
        project, _, compile_args = self._project()
        runfiles = Path(tempfile.mkdtemp())
        inventory = runfiles / "compile_inputs.txt"
        inventory.write_text("source\texternal/missing.sv\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "missing file"):
            compile_fingerprint(project, "vcs -f compile.f", compile_args, inventory, runfiles)

    def test_fingerprint_tracks_external_config_content_and_tool_environment(self):
        project, _, compile_args = self._project()
        config = project.parent / "coverage_hier.cfg"
        config.write_text("+tree top\n", encoding="utf-8")
        initial = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )

        config.write_text("+tree dut\n", encoding="utf-8")
        config_changed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )
        environment_changed = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[config],
            environment={"VCS_HOME": "/tools/vcs/Z-2027.03"},
        )

        self.assertNotEqual(initial, config_changed)
        self.assertNotEqual(config_changed, environment_changed)

        equivalent_config = Path(tempfile.mkdtemp()) / "coverage_hier.cfg"
        equivalent_config.write_text("+tree dut\n", encoding="utf-8")
        equivalent = compile_fingerprint(
            project,
            "vcs -f compile.f",
            compile_args,
            extra_input_paths=[equivalent_config],
            environment={"VCS_HOME": "/tools/vcs/Y-2026.03"},
        )
        self.assertEqual(config_changed["extra_inputs_content_sha256"], equivalent["extra_inputs_content_sha256"])

    def test_filelist_input_discovery_tracks_nested_sources_and_include_directories(self):
        runfiles = Path(tempfile.mkdtemp())
        external = Path(tempfile.mkdtemp())
        source = external / "external.sv"
        source.write_text("module external; endmodule\n", encoding="utf-8")
        include_dir = external / "include"
        include_dir.mkdir()
        header = include_dir / "external.svh"
        header.write_text("`define EXTERNAL 1\n", encoding="utf-8")
        nested = runfiles / "nested.f"
        nested.write_text("{}\n+incdir+{}\n".format(source, include_dir), encoding="utf-8")
        root = external / "compile.f"
        root.write_text("-f nested.f\n", encoding="utf-8")

        inputs = discover_filelist_inputs(root, runfiles)

        self.assertEqual(sorted(map(str, (root, nested, source, header))), inputs)

        with mock.patch("lib.compile_cache.open", wraps=open) as read_file:
            compile_fingerprint(
                external,
                "vcs -f {}".format(root),
                root,
                extra_input_paths=inputs,
            )

        read_paths = [
            os.path.abspath(os.fspath(call.args[0])) for call in read_file.call_args_list
            if len(call.args) > 1 and call.args[1] == "rb"
        ]
        self.assertEqual(2, read_paths.count(str(root))) # Compile args plus one external-input read.
        for path in (nested, source, header):
            self.assertEqual(1, read_paths.count(str(path)))

    def test_filelist_input_discovery_unquotes_paths_with_spaces(self):
        root_dir = Path(tempfile.mkdtemp())
        source = root_dir / "source files" / "dut.sv"
        source.parent.mkdir()
        source.write_text("module dut; endmodule\n", encoding="utf-8")
        root = root_dir / "compile.f"
        root.write_text('"{}"\n'.format(source), encoding="utf-8")

        self.assertEqual(sorted(map(str, (root, source))), discover_filelist_inputs(root, root_dir))

    def test_filelist_input_discovery_uses_nested_file_directory_for_dash_capital_f(self):
        working_dir = Path(tempfile.mkdtemp())
        filelist_dir = Path(tempfile.mkdtemp())
        nested_dir = working_dir / "nested"
        nested_dir.mkdir()
        source = nested_dir / "relative.sv"
        source.write_text("module relative; endmodule\n", encoding="utf-8")
        nested = nested_dir / "nested.f"
        nested.write_text("relative.sv\n", encoding="utf-8")
        root = filelist_dir / "compile.f"
        root.write_text("-F nested/nested.f\n", encoding="utf-8")

        inputs = discover_filelist_inputs(root, working_dir)

        self.assertEqual(sorted(map(str, (root, nested, source))), inputs)

    def test_filelist_input_discovery_tracks_dash_incdir_contents(self):
        root_dir = Path(tempfile.mkdtemp())
        include_dir = root_dir / "include"
        include_dir.mkdir()
        header = include_dir / "definitions.svh"
        header.write_text("`define VALUE 1\n", encoding="utf-8")
        root = root_dir / "compile.f"
        root.write_text("-incdir include\n", encoding="utf-8")

        initial_inputs = discover_filelist_inputs(root, root_dir)
        initial = compile_fingerprint(root_dir, "vcs -f compile.f", root, extra_input_paths=initial_inputs)
        header.write_text("`define VALUE 2\n", encoding="utf-8")
        changed_inputs = discover_filelist_inputs(root, root_dir)
        changed = compile_fingerprint(root_dir, "vcs -f compile.f", root, extra_input_paths=changed_inputs)

        self.assertEqual(sorted(map(str, (root, header))), initial_inputs)
        self.assertNotEqual(initial, changed)

    def test_filelist_attached_configuration_changes_reject_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "configuration with spaces.cfg"
            filelist = root / "compile.f"
            for option in ("-xprop", "-gfile", "-cm_hier", "-libmap", "+optconfigfile+"):
                with self.subTest(option=option):
                    config.write_text("first configuration\n", encoding="utf-8")
                    filelist.write_text('{}{}"{}"\n'.format(option, "" if option.startswith("+") else "=", config),
                                        encoding="utf-8")
                    initial = compile_fingerprint(root,
                                                  "vcs",
                                                  filelist,
                                                  extra_input_paths=discover_filelist_inputs(filelist, root))
                    write_compile_fingerprint(root / "build", initial)
                    config.write_text("changed configuration\n", encoding="utf-8")
                    changed = compile_fingerprint(root,
                                                  "vcs",
                                                  filelist,
                                                  extra_input_paths=discover_filelist_inputs(filelist, root))
                    self.assertFalse(can_reuse_compile(root / "build", changed, lambda: None)[0])
                    with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
                        validate_compile_fingerprint(root / "build", changed)

    def test_external_source_transitive_includes_reject_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = root / "sources"
            sources.mkdir()
            source = sources / "top.sv"
            header = sources / "definitions.svh"
            nested = root / "nested.svh"
            filelist = root / "compile.f"
            source.write_text('`include /* dependency */ "definitions.svh"\nmodule top; endmodule\n', encoding="utf-8")
            header.write_text('`include "{}"\n'.format(nested.as_posix()), encoding="utf-8")
            # A cycle must terminate without missing either header.
            nested.write_text('`include "{}"\n`define VALUE 1\n'.format(header.as_posix()), encoding="utf-8")
            filelist.write_text('{}\n'.format(source), encoding="utf-8")
            inputs = discover_filelist_inputs(filelist, root)
            self.assertEqual(sorted(map(str, (filelist, source, header, nested))), inputs)
            initial = compile_fingerprint(root, "vcs", filelist, extra_input_paths=inputs)
            write_compile_fingerprint(root / "build", initial)
            nested.write_text('`define VALUE 2\n', encoding="utf-8")
            changed = compile_fingerprint(root,
                                          "vcs",
                                          filelist,
                                          extra_input_paths=discover_filelist_inputs(filelist, root))
            self.assertFalse(can_reuse_compile(root / "build", changed, lambda: None)[0])

    def test_statically_compiled_dpi_source_tracks_local_c_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dpi.c"
            header = root / "dpi.h"
            filelist = root / "compile.f"
            source.write_text('#include "dpi.h"\nint dpi_fn(void) { return VALUE; }\n', encoding="utf-8")
            header.write_text("#define VALUE 1\n", encoding="utf-8")
            filelist.write_text("dpi.c\n", encoding="utf-8")
            initial = compile_fingerprint(root,
                                          "vcs",
                                          filelist,
                                          extra_input_paths=discover_filelist_inputs(filelist, root))
            header.write_text("#define VALUE 2\n", encoding="utf-8")
            changed = compile_fingerprint(root,
                                          "vcs",
                                          filelist,
                                          extra_input_paths=discover_filelist_inputs(filelist, root))
            self.assertNotEqual(initial, changed)

    def test_source_runtime_data_and_output_files_do_not_invalidate_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "top.sv"
            runtime = root / "memory.hex"
            output = root / "simv"
            filelist = root / "compile.f"
            source.write_text(
                '// `include "memory.hex"\n/* `include "memory.hex" */\nmodule top; initial $readmemh("memory.hex", memory); endmodule\n',
                encoding="utf-8")
            filelist.write_text('{}\n-o {}\n-l {}\n-o={}\n'.format(source, output, runtime, output), encoding="utf-8")
            runtime.write_text("00\n", encoding="utf-8")
            output.write_text("existing executable", encoding="utf-8")
            initial = compile_fingerprint(root,
                                          "vcs",
                                          filelist,
                                          extra_input_paths=discover_filelist_inputs(filelist, root))
            runtime.write_text("ff\n", encoding="utf-8")
            output.write_text("updated executable", encoding="utf-8")
            changed = compile_fingerprint(root,
                                          "vcs",
                                          filelist,
                                          extra_input_paths=discover_filelist_inputs(filelist, root))
            self.assertEqual(initial, changed)

    def test_attached_capital_f_retains_relative_nested_filelist_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested_dir = root / "nested"
            nested_dir.mkdir()
            source = nested_dir / "top.sv"
            source.write_text("module top; endmodule\n", encoding="utf-8")
            nested = nested_dir / "sources.f"
            nested.write_text("top.sv\n", encoding="utf-8")
            filelist = root / "compile.f"
            filelist.write_text("-F=nested/sources.f\n", encoding="utf-8")
            self.assertEqual(sorted(map(str, (filelist, nested, source))), discover_filelist_inputs(filelist, root))

    def test_same_filelist_in_both_relative_contexts_tracks_and_invalidates_both_sources(self):
        for switches in ("-f sub/common.f\n-F sub/common.f\n", "-F=sub/common.f\n-f=sub/common.f\n"):
            with self.subTest(switches=switches), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                sub = root / "sub"
                sub.mkdir()
                sources = (root / "top.sv", sub / "top.sv")
                for source in sources:
                    source.write_text("module top; endmodule\n", encoding="utf-8")
                nested = sub / "common.f"
                nested.write_text("top.sv\n-F common.f\n", encoding="utf-8")
                filelist = root / "compile.f"
                filelist.write_text(switches, encoding="utf-8")
                inputs = discover_filelist_inputs(filelist, root)
                self.assertEqual(sorted(map(str, (filelist, nested, *sources))), inputs)
                initial = compile_fingerprint(root, "vcs", filelist, extra_input_paths=inputs)
                write_compile_fingerprint(root / "build", initial)
                for source in sources:
                    source.write_text("module changed; endmodule\n", encoding="utf-8")
                    changed = compile_fingerprint(root,
                                                  "vcs",
                                                  filelist,
                                                  extra_input_paths=discover_filelist_inputs(filelist, root))
                    self.assertFalse(can_reuse_compile(root / "build", changed, lambda: None)[0])
                    with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
                        validate_compile_fingerprint(root / "build", changed)
                    source.write_text("module top; endmodule\n", encoding="utf-8")

    def test_compiler_include_flags_track_only_named_transitive_headers(self):
        for flags, include_name in (('-CFLAGS "-I."', "."), ('-CFLAGS="-I ."', "."),
                                    ('-CFLAGS \'-I"include dir"\'', "include dir"), ('-CFLAGS \'-I "include dir"\'',
                                                                                     "include dir")):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                includes = root / include_name
                includes.mkdir(exist_ok=True)
                source = root / "dpi.c"
                header = includes / "dpi.h"
                quoted = includes / "quoted.h"
                nested = includes / "nested.h"
                unrelated = includes / "unrelated.h"
                source.write_text(
                    '#include /* dependency */ <dpi.h>\n'
                    '// #include <unrelated.h>\n'
                    'const char *text = "#include <unrelated.h>";\n',
                    encoding="utf-8")
                header.write_text('#include "quoted.h"\n', encoding="utf-8")
                quoted.write_text('#include <nested.h>\n', encoding="utf-8")
                nested.write_text('#include <dpi.h>\n#define VALUE 1\n', encoding="utf-8")
                unrelated.write_text("unused SDK header\n", encoding="utf-8")
                filelist = root / "compile.f"
                filelist.write_text("{}\ndpi.c\n".format(flags), encoding="utf-8")
                with mock.patch.object(compile_cache, "_directory_inputs",
                                       wraps=compile_cache._directory_inputs) as walk:
                    inputs = discover_filelist_inputs(filelist, root)
                    walk.assert_not_called()
                self.assertEqual(sorted(map(str, (filelist, source, header, quoted, nested))), inputs)
                initial = compile_fingerprint(root, "vcs", filelist, extra_input_paths=inputs)
                write_compile_fingerprint(root / "build", initial)
                for changed_header in (header, quoted, nested):
                    original = changed_header.read_text(encoding="utf-8")
                    changed_header.write_text(original + "#define CHANGED 1\n", encoding="utf-8")
                    changed = compile_fingerprint(root,
                                                  "vcs",
                                                  filelist,
                                                  extra_input_paths=discover_filelist_inputs(filelist, root))
                    self.assertFalse(can_reuse_compile(root / "build", changed, lambda: None)[0])
                    changed_header.write_text(original, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
