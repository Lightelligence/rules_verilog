import contextlib
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import jinja2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
from args_parser import parse_args
from lib import vcs_coverage
from lib.job_lib import JobStatus
from lib.simulators.vcs import VcsSimulator
from lib.simulators.xcelium import XceliumSimulator


class VcsCoverageIncrementalTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.options = parse_args(["--simulator", "VCS", "--vcs-cm", "line", "--vcs-coverage-incremental"])
        self.rcfg = SimpleNamespace(regression_dir=str(self.root), deferred_messages=[])
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(ROOT / "bin/templates"),
                                 undefined=jinja2.StrictUndefined)
        env.filters["shell_quote"] = shlex.quote
        self.simulator = VcsSimulator(self.options, self.rcfg, env)
        self.job = SimpleNamespace(name="tb", cov_work_dir=str(self.root / "input.vdb"))
        self.simulator.setup_coverage_merge(self.job)
        self.calls = []
        self.model(self.job.cov_work_dir)

    @staticmethod
    def model(database):
        path = Path(database) / "snps/coverage/db/design/model.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<design-model/>")
        return path

    def inputs(self, **cases):
        path = Path(self.job.cov_work_dir) / "snps/coverage/db/testdata"
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True)
        for name, contents in cases.items():
            directory = path / name
            directory.mkdir()
            (directory / "hits.xml").write_text(contents)

    def fake_urg(self, argv, **_kwargs):
        words = shlex.split(Path(argv[1]).read_text(), comments=True)
        directories = words[words.index("-dir") + 1:words.index("-dbname")]
        recorded = []
        names = set()
        for directory in directories:
            source = Path(directory)
            previous = source / "contributions.json"
            if previous.is_file():
                included = json.loads(previous.read_text())
            else:
                included = sorted(vcs_coverage.datasets(source))
            recorded.append({"path": str(source), "tests": included})
            names.update(included)
        self.calls.append(recorded)
        merged = Path(words[words.index("-dbname") + 1])
        self.model(merged)
        partitions = Path(self.job.cov_work_dir) / "partitionlib"
        if partitions.is_dir():
            shutil.copytree(partitions, merged / "partitionlib", symlinks=True)
        (merged / "contributions.json").write_text(json.dumps(sorted(names)))
        if "-report" in words:
            report = Path(words[words.index("-report") + 1])
            report.mkdir(parents=True, exist_ok=True)
            (report / "dashboard.txt").write_text("SCORE LINE\n90.00 80.00\n")
        return SimpleNamespace(returncode=0)

    def merge(self):
        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=self.fake_urg):
            return self.simulator.run_report_coverage_merge({"//bench:tb": self.job})

    def baseline(self):
        self.inputs(old="one")
        self.assertFalse(self.merge())
        return self.snapshot()

    def snapshot(self):
        paths = [
            Path(self.job.merged_coverage_dir),
            Path(self.job.coverage_report_dir),
            Path(self.job.coverage_view_script_path),
            Path(vcs_coverage.history_path(self.job))
        ]
        result = {}
        for root in paths:
            for path in root.rglob("*") if root.is_dir() else [root]:
                if path.is_file():
                    result[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def test_first_run_then_new_cases_merge_only_previous_aggregate_and_new_input(self):
        self.baseline()
        self.inputs(new="two")
        self.assertFalse(self.merge())
        self.assertEqual(2, len(self.calls))
        self.assertEqual([self.job.merged_coverage_dir, self.job.cov_work_dir], [row["path"] for row in self.calls[-1]])
        self.assertEqual([["old"], ["new"]], [row["tests"] for row in self.calls[-1]])
        summary = json.loads((Path(self.job.coverage_report_dir) / "summary.json").read_text())
        self.assertEqual(["new", "old"], summary["input_tests"])
        self.assertEqual(2, summary["input_test_count"])
        self.assertEqual(["new"], summary["added_tests"])
        self.assertEqual("incremental", summary["merge_mode"])
        self.assertEqual("merged_vdb", summary["scores_from"])
        self.assertEqual(self.job.merged_coverage_dir, summary["merged_vdb"])
        self.assertEqual({"dashboard.txt", "dashboard.html", "summary.json"},
                         {path.name
                          for path in Path(self.job.coverage_report_dir).iterdir()})
        script = Path(self.job.coverage_view_script_path).read_text()
        self.assertNotIn(".vcs-coverage-", script)
        self.assertNotIn(".vcs-coverage-", (Path(self.job.coverage_report_dir) / "dashboard.html").read_text())
        self.assertEqual(1, self.job.coverage_merge_metrics["added_dataset_count"])

    def test_identical_replay_does_not_invoke_urg_or_rewrite_outputs(self):
        before = self.baseline()
        self.assertFalse(self.merge())
        self.assertEqual(1, len(self.calls))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(1, self.job.coverage_merge_metrics["duplicate_dataset_count"])
        self.assertEqual(0, self.job.coverage_merge_metrics["added_dataset_count"])

    @unittest.skipIf(os.name == "nt", "POSIX coverage views use symbolic links")
    def test_partial_replay_filters_old_datasets_from_every_input_view(self):
        self.baseline()
        self.inputs(old="one", new="two")
        before_input = vcs_coverage.datasets(self.job.cov_work_dir)
        self.assertFalse(self.merge())
        self.assertEqual([["old"], ["new"]], [row["tests"] for row in self.calls[-1]])
        self.assertTrue(self.calls[-1][1]["path"].endswith("new-input.vdb"))
        self.assertEqual(before_input, vcs_coverage.datasets(self.job.cov_work_dir))

    def test_changed_replayed_dataset_and_changed_model_preserve_previous_outputs(self):
        before = self.baseline()
        self.inputs(old="changed")
        self.assertTrue(self.merge())
        self.assertEqual(before, self.snapshot())
        self.inputs(new="two")
        self.model(self.job.cov_work_dir).write_text("<different-model/>")
        self.assertTrue(self.merge())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(1, len(self.calls))

    def test_urg_failure_preserves_database_report_viewer_and_history(self):
        before = self.baseline()
        self.inputs(new="two")
        with mock.patch("lib.simulators.vcs.run_bounded_process", return_value=SimpleNamespace(returncode=7)):
            self.assertTrue(self.simulator.run_report_coverage_merge({"//bench:tb": self.job}))
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.job.coverage_merge_succeeded)
        self.assertTrue(Path(self.job.coverage_merge_log).is_file())
        self.assertFalse(list(self.root.glob(".vcs-coverage-*-*")))

    def test_publication_failure_rolls_back_all_outputs(self):
        before = self.baseline()
        self.inputs(new="two")
        original_replace = os.replace
        failed = False

        def replace(source, destination):
            nonlocal failed
            if Path(source).name == "history.json" and not failed:
                failed = True
                raise PermissionError("publication denied")
            return original_replace(source, destination)

        with mock.patch("lib.vcs_coverage.os.replace", side_effect=replace):
            self.assertTrue(self.merge())
        self.assertTrue(failed)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(list(self.root.glob(".vcs-coverage-*-*")))

    def test_input_change_during_urg_does_not_publish(self):
        before = self.baseline()
        self.inputs(new="two")

        def run(argv, **kwargs):
            result = self.fake_urg(argv, **kwargs)
            (Path(self.job.cov_work_dir) / "snps/coverage/db/testdata/new/hits.xml").write_text("changed while merging")
            return result

        with mock.patch("lib.simulators.vcs.run_bounded_process", side_effect=run):
            self.assertTrue(self.simulator.run_report_coverage_merge({"//bench:tb": self.job}))
        self.assertEqual(before, self.snapshot())

    def test_legacy_summary_upgrades_without_reopening_old_case_data(self):
        self.baseline()
        Path(vcs_coverage.history_path(self.job)).unlink()
        self.inputs(new="two")
        self.assertFalse(self.merge())
        history = json.loads(Path(vcs_coverage.history_path(self.job)).read_text())
        self.assertEqual("legacy", history["previous_generation"])
        self.assertIsNone(history["datasets"]["old"])
        self.assertEqual(["new", "old"], sorted(history["datasets"]))
        self.assertEqual([["old"], ["new"]], [row["tests"] for row in self.calls[-1]])

    def test_legacy_duplicate_and_corrupt_history_are_rejected(self):
        before = self.baseline()
        history = Path(vcs_coverage.history_path(self.job))
        history.unlink()
        self.assertTrue(self.merge())
        self.assertEqual(1, len(self.calls))
        history.write_text("{broken")
        self.inputs(new="two")
        self.assertTrue(self.merge())
        self.assertEqual(1, len(self.calls))
        for path, digest in before.items():
            if path != str(history.relative_to(self.root)):
                self.assertEqual(digest, hashlib.sha256((self.root / path).read_bytes()).hexdigest())

    def test_coverage_options_change_and_blocked_compilation_preserve_old_viewer(self):
        before = self.baseline()
        self.inputs(new="two")
        self.options.vcs_cm_line = "svtb"
        self.assertTrue(self.merge())
        self.options.vcs_cm_line = None
        self.job.jobstatus = JobStatus.FAILED
        self.assertTrue(self.merge())
        self.assertEqual(before, self.snapshot())

    def test_full_default_run_also_records_a_future_incremental_baseline(self):
        self.options.vcs_coverage_incremental = False
        self.inputs(old="one")
        self.assertFalse(self.merge())
        self.assertEqual(["old"], sorted(json.loads(Path(vcs_coverage.history_path(self.job)).read_text())["datasets"]))
        self.options.vcs_coverage_incremental = True
        self.inputs(new="two")
        self.assertFalse(self.merge())
        self.assertEqual(2, len(self.calls[-1]))

    def test_failed_legacy_job_without_output_paths_returns_failure(self):
        self.options.vcs_coverage_incremental = False
        job = SimpleNamespace(name="tb", coverage_merge_script=str(self.root / "merge.sh"))
        with mock.patch("lib.simulators.vcs.run_bounded_process", return_value=SimpleNamespace(returncode=1)):
            self.assertTrue(self.simulator.run_report_coverage_merge({"//bench:tb": job}))
        self.assertFalse(job.coverage_merge_succeeded)

    def test_recovery_rolls_back_interrupted_publication_before_retry(self):
        before = self.baseline()
        self.inputs(new="two")
        signature = json.loads(Path(vcs_coverage.history_path(self.job)).read_text())["coverage_options"]
        update = vcs_coverage.CoverageUpdate(self.job, self.root, signature).__enter__()
        journal = update._journal(update.stage)
        journal["phase"] = "publishing"
        vcs_coverage.write_json(update.stage / "transaction.json", journal)
        old = Path(self.job.merged_coverage_dir)
        os.replace(old, update.stage / "backup-0")
        self.model(old).write_text("<incomplete-new-output/>")
        with vcs_coverage.CoverageUpdate(self.job, self.root, signature):
            self.assertEqual(before, self.snapshot())
        self.assertFalse(update.stage.exists())

    def test_concurrent_writer_is_rejected(self):
        with vcs_coverage.merge_lock(self.root, "tb"):
            with self.assertRaisesRegex(OSError, "already active"):
                with vcs_coverage.merge_lock(self.root, "tb"):
                    self.fail("second writer acquired the coverage lock")

    def test_option_requires_coverage_and_is_vcs_only(self):
        for argv in (["--simulator", "VCS", "--vcs-coverage-incremental"],
                     ["--simulator", "XRUN", "--vcs-cm", "line", "--vcs-coverage-incremental"]):
            options = parse_args(argv)
            with self.assertRaises(ValueError):
                backend = VcsSimulator if options.simulator == "VCS" else XceliumSimulator
                backend(options, self.rcfg, self.simulator.env).validate_resolved_options()

    def test_merge_only_supports_incremental_updates_without_a_report(self):
        self.options.vcs_urg_format = "none"
        self.baseline()
        self.inputs(new="two")
        self.assertFalse(self.merge())
        self.assertFalse(list(Path(self.job.coverage_report_dir).iterdir()))
        self.assertEqual(["new", "old"],
                         json.loads((Path(self.job.merged_coverage_dir) / "contributions.json").read_text()))

    def test_model_identity_includes_partition_shapes_and_ignores_urg_metadata(self):
        model = vcs_coverage.model_digest(self.job.cov_work_dir)
        generated = Path(self.job.cov_work_dir) / "snps/coverage/db/design/design.cv.xml"
        generated.write_text("<urg-merge-metadata/>")
        self.assertEqual(model, vcs_coverage.model_digest(self.job.cov_work_dir))
        shape = Path(self.job.cov_work_dir) / "partitionlib/dut.vdb/snps/coverage/db/shape/line.xml"
        shape.parent.mkdir(parents=True)
        shape.write_text("<shape/>")
        changed = vcs_coverage.model_digest(self.job.cov_work_dir)
        self.assertNotEqual(model, changed)
        shape.write_text("<changed-shape/>")
        self.assertNotEqual(changed, vcs_coverage.model_digest(self.job.cov_work_dir))

    @unittest.skipIf(os.name == "nt", "POSIX coverage views use symbolic links")
    def test_filtered_view_excludes_duplicates_inside_partition_databases(self):
        source = Path(self.job.cov_work_dir)
        for location in (source, source / "partitionlib/dut.vdb"):
            self.model(location)
            for name in ("old", "new"):
                case = location / "snps/coverage/db/testdata" / name
                case.mkdir(parents=True)
                (case / "hits.xml").write_text(name)
        destination = self.root / "view.vdb"
        vcs_coverage._filtered_view(source, destination, {"new"})
        for location in (destination, destination / "partitionlib/dut.vdb"):
            self.assertEqual(["new"], [path.name for path in (location / "snps/coverage/db/testdata").iterdir()])
        self.assertEqual(vcs_coverage.model_digest(source), vcs_coverage.model_digest(destination))

    @unittest.skipIf(os.name == "nt", "POSIX coverage partition links")
    def test_publication_preserves_internal_and_external_relative_links(self):
        stage = self.root / "stage/merged.vdb"
        stage.mkdir(parents=True)
        external = self.root / "external.xml"
        external.write_text("outside")
        (stage / "model.xml").write_text("inside")
        (stage / "internal.xml").symlink_to("model.xml")
        (stage / "internal-chain.xml").symlink_to("internal.xml")
        (stage / "external.xml").symlink_to(os.path.relpath(external, stage))
        final = self.root / "final.vdb"
        vcs_coverage._relocate_links(stage, final)
        os.replace(stage, final)
        self.assertEqual("inside", (final / "internal.xml").read_text())
        self.assertEqual("inside", (final / "internal-chain.xml").read_text())
        self.assertEqual("outside", (final / "external.xml").read_text())


class VcsCoverageTraversalTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def file(self, name, contents=b"model"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def link(self, name, target):
        path = self.root / name
        try:
            path.symlink_to(target, target_is_directory=target.is_dir())
        except OSError:
            if os.name == "nt":
                self.skipTest("Windows symlink privilege is unavailable")
            raise
        return path

    def expected_digest(self, paths):
        digest = hashlib.sha256()
        for path in sorted(paths):
            digest.update(os.fsencode(str(path.relative_to(self.root))) + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        return digest.hexdigest()

    def test_model_and_dataset_hashes_keep_path_identity_and_exclusions(self):
        design = self.file("snps/coverage/db/design/top.xml")
        shape = self.file("partition/snps/coverage/db/shape/shape.xml", b"shape")
        self.file("snps/coverage/db/design/design.cv.xml", b"URG metadata")
        self.file("snps/coverage/db/common/runtime.xml", b"runtime")
        hits = self.file("snps/coverage/db/testdata/one/hits.xml", b"hits")
        partition_hits = self.file("partition/snps/coverage/db/testdata/one/hits.xml", b"partition hits")
        self.assertEqual(self.expected_digest([design, shape]), vcs_coverage.model_digest(self.root))
        self.assertEqual({"one": self.expected_digest([hits, partition_hits])}, vcs_coverage.datasets(self.root))
        original_model = vcs_coverage.model_digest(self.root)
        original_datasets = vcs_coverage.datasets(self.root)
        hits.write_bytes(b"new hits")
        self.assertEqual(original_model, vcs_coverage.model_digest(self.root))
        self.assertNotEqual(original_datasets, vcs_coverage.datasets(self.root))
        shape.write_bytes(b"new shape")
        self.assertNotEqual(original_model, vcs_coverage.model_digest(self.root))

    def test_directory_aliases_are_hashed_under_each_logical_path(self):
        model = self.file("partition/snps/coverage/db/design/model.xml")
        alias = self.link("alias", self.root / "partition")
        self.assertEqual(self.expected_digest([model, alias / "snps/coverage/db/design/model.xml"]),
                         vcs_coverage.model_digest(self.root))

    def test_ancestor_directory_link_is_rejected(self):
        self.file("partition/snps/coverage/db/design/model.xml")
        self.link("partition/back", self.root)
        with self.assertRaisesRegex(OSError, "Cyclic coverage directory"):
            vcs_coverage.model_digest(self.root)

    def test_dangling_link_is_rejected(self):
        self.file("snps/coverage/db/design/model.xml")
        self.link("missing", self.root / "not-present")
        with self.assertRaises(OSError):
            vcs_coverage.model_digest(self.root)

    def test_missing_direntry_inode_uses_portable_identity(self):
        model = self.file("snps/coverage/db/design/model.xml")
        original_scandir = os.scandir

        @contextlib.contextmanager
        def entries_without_inodes(path):
            with original_scandir(path) as entries:
                entries = list(entries)
            wrapped = []
            for entry in entries:
                metadata = entry.stat(follow_symlinks=True)
                wrapped.append(
                    SimpleNamespace(name=entry.name,
                                    stat=lambda metadata=metadata, **_kwargs: SimpleNamespace(
                                        st_mode=metadata.st_mode, st_dev=metadata.st_dev, st_ino=0)))
            yield wrapped

        with mock.patch.object(vcs_coverage.os, "scandir", entries_without_inodes):
            self.assertEqual(self.expected_digest([model]), vcs_coverage.model_digest(self.root))


if __name__ == "__main__":
    unittest.main()
