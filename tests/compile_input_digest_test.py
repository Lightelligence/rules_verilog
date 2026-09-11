"""Legacy inventories and shared VCS indices preserve compile input identity."""

import hashlib
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from verilog.private import compile_input_digest


class CompileInputDigestTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / "manifest.txt"
        self.output = self.root / "digest.txt"
        self.inventory = self.root / "inventory.txt"

    def source(self, name, data=b"module top; endmodule\n"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def generate(self, records):
        self.manifest.write_text("".join("{}\t{}\n".format(entry, path) for entry, path in records), encoding="utf-8")
        compile_input_digest.generate_digest(self.manifest, self.output, self.inventory)
        return self.inventory.read_bytes(), self.output.read_text(encoding="ascii").strip()

    def legacy(self, records):
        # Independent reference for the old analysis-time dict/sort and hash.
        canonical = dict(records)
        digest = hashlib.sha256()
        for entry in sorted(canonical):
            digest.update(entry.encode("utf-8") + b"\0")
            digest.update(canonical[entry].read_bytes() + b"\0")
        return ("\n".join(sorted(canonical)) + "\n").encode("utf-8"), digest.hexdigest()

    def test_unsorted_shared_inputs_match_legacy_bytes(self):
        source = self.source("source with spaces.sv", b"sv\x00\xff\n")
        filelist = self.source("external/vip.f", b"+incdir+external/vip\n")
        records = [
            ("source\tz/top.sv", source),
            ("source\tz/top.sv", source),
            ("filelist\texternal/vip/vip.f", filelist),
            ("runfile\tz/top.sv", source),
            ("source\tunicode/模块.sv", source),
        ]
        expected = self.legacy(records)
        for seed in range(8):
            random.Random(seed).shuffle(records)
            self.assertEqual(expected, self.generate(records))

    def test_last_duplicate_entry_wins(self):
        first = self.source("first.sv", b"old")
        last = self.source("last.sv", b"new")
        records = [("source\ttop.sv", first), ("source\ttop.sv", last)]
        self.assertEqual(self.legacy(records), self.generate(records))

    def test_content_path_category_and_membership_invalidate_digest(self):
        source = self.source("top.sv", b"old")
        records = [("source\ttop.sv", source)]
        _, original = self.generate(records)
        source.write_bytes(b"new")
        self.assertNotEqual(original, self.generate(records)[1])
        source.write_bytes(b"old")
        for changed in [[("source\trenamed.sv", source)], [("runfile\ttop.sv", source)], [],
                        records + [("source\tadded.sv", source)]]:
            self.assertNotEqual(original, self.generate(changed)[1])

    def test_unlisted_runtime_file_does_not_change_digest(self):
        source = self.source("top.sv")
        runtime = self.source("runtime.data", b"first")
        records = [("source\ttop.sv", source)]
        before = self.generate(records)
        runtime.write_bytes(b"second")
        self.assertEqual(before, self.generate(records))

    def test_empty_manifest(self):
        self.assertEqual(self.legacy([]), self.generate([]))

    def test_chunked_file_matches_legacy(self):
        records = [("source\tlarge.sv", self.source("large.sv", b"x" * (2 * 1024 * 1024 + 17)))]
        self.assertEqual(self.legacy(records), self.generate(records))

    def test_missing_input_fails_without_success_outputs(self):
        with self.assertRaises(FileNotFoundError):
            self.generate([("source\tmissing.sv", self.root / "missing.sv")])
        self.assertFalse(self.output.exists())
        self.assertFalse(self.inventory.exists())

    def test_malformed_manifest_is_rejected(self):
        self.manifest.write_text("source\tmissing_path\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Malformed"):
            compile_input_digest.generate_digest(self.manifest, self.output, self.inventory)
        self.assertFalse(self.output.exists())

    def test_legacy_cli_preserves_order_and_duplicates(self):
        source = self.source("top.sv")
        entries = ["source\tz.sv", "source\ta.sv", "source\tz.sv"]
        self.manifest.write_text("".join("{}\t{}\n".format(entry, source) for entry in entries), encoding="utf-8")
        expected = hashlib.sha256()
        for entry in entries:
            expected.update(entry.encode("utf-8") + b"\0" + source.read_bytes() + b"\0")
        subprocess.run(
            [sys.executable, compile_input_digest.__file__,
             str(self.manifest), str(self.output)], check=True)
        self.assertEqual(expected.hexdigest(), self.output.read_text(encoding="ascii").strip())

    def test_deferred_cli_writes_inventory(self):
        self.manifest.write_text("", encoding="utf-8")
        subprocess.run(
            [sys.executable, compile_input_digest.__file__,
             str(self.manifest),
             str(self.output),
             str(self.inventory)],
            check=True)
        self.assertEqual(b"\n", self.inventory.read_bytes())
        self.assertEqual(hashlib.sha256().hexdigest(), self.output.read_text(encoding="ascii").strip())

    def shared(self, records, indices):
        self.manifest.write_text("".join("{}\t{}\n".format(entry, path) for entry, path in records), encoding="utf-8")
        index_list = self.root / "indices.txt"
        index_list.write_text("".join(str(path) + "\n" for path in indices), encoding="utf-8")
        compile_input_digest.merge_digest(self.manifest, self.output, self.inventory, index_list)
        return self.inventory.read_bytes(), self.output.read_text(encoding="ascii").strip()

    def index(self, records, name="index"):
        manifest = self.root / (name + ".txt")
        manifest.write_text("".join("{}\t{}\n".format(entry, path) for entry, path in records), encoding="utf-8")
        index = self.root / (name + ".json")
        compile_input_digest.generate_index(manifest, index)
        return index

    def test_shared_digest_matches_independent_reference_without_source_reads(self):
        source = self.source("space 模块.sv", b"sv\x00\xff")
        filelist = self.source("lib.f", b"+define+ONE\n")
        records = [("source\texternal/ip/top.sv", source), ("filelist\tlib.f", filelist)]
        expected = hashlib.sha256(b"rules_verilog.compile_inputs.v2\0")
        for entry, path in sorted(records):
            expected.update(entry.encode("utf-8") + b"\0" + hashlib.sha256(path.read_bytes()).digest() + b"\0")
        index = self.index(records)
        source.unlink()
        filelist.unlink()
        with mock.patch.object(compile_input_digest, "file_digest", side_effect=AssertionError("unexpected read")):
            inventory, digest = self.shared(records + records, [index, index])
        self.assertEqual(("\n".join(sorted(dict(records))) + "\n").encode(), inventory)
        self.assertEqual(expected.hexdigest(), digest)

    def test_shared_digest_is_independent_of_index_partition_and_exec_paths(self):
        first = self.source("first.sv", b"one")
        second = self.source("second.sv", b"two")
        records = [("source\ta.sv", first), ("source\tb.sv", second)]
        expected = self.shared(records, [self.index(records)])
        self.assertEqual(
            expected,
            self.shared(list(reversed(records)),
                        [self.index(records[:1], "a"), self.index(records[1:], "b")]))
        relocated = self.source("other/config/first.sv", b"one")
        moved = [("source\ta.sv", relocated), records[1]]
        self.assertEqual(expected, self.shared(moved, [self.index(moved, "moved")]))

    def test_shared_digest_invalidates_content_path_category_and_membership(self):
        source = self.source("top.sv", b"old")
        records = [("source\ttop.sv", source)]
        before = self.shared(records, [self.index(records)])
        self.assertNotEqual(before[1], self.generate(records)[1]) # Safe legacy cache miss.
        source.write_bytes(b"new")
        self.assertNotEqual(before[1], self.shared(records, [self.index(records)])[1])
        source.write_bytes(b"old")
        for changed in [[("source\trenamed.sv", source)], [("runfile\ttop.sv", source)], [],
                        records + [("source\tadded.sv", source)]]:
            self.assertNotEqual(before[1], self.shared(changed, [self.index(changed)])[1])

    def test_shared_last_record_wins_and_direct_runfiles_are_hashed(self):
        first = self.source("first.sv", b"first")
        last = self.source("last.sv", b"last")
        extra = self.source("extra.cfg", b"extra")
        records = [("source\ttop.sv", first), ("source\ttop.sv", last)]
        index = self.index(records)
        self.assertEqual(self.shared(records, [index]), self.shared(records[1:], [index]))
        records.append(("runfile\textra.cfg", extra))
        before = self.shared(records, [index])
        extra.write_bytes(b"changed")
        self.assertNotEqual(before[1], self.shared(records, [index])[1])
        runtime = self.source("runtime.data", b"not indexed")
        before = self.shared(records, [index])
        runtime.write_bytes(b"still irrelevant")
        self.assertEqual(before, self.shared(records, [index]))

    def test_shared_missing_corrupt_and_conflicting_indices_fail_closed(self):
        source = self.source("top.sv")
        records = [("source\ttop.sv", source)]
        with self.assertRaisesRegex(RuntimeError, "Missing"):
            self.shared(records, [])
        good = self.index(records)
        bad = self.root / "bad.json"
        bad.write_text(json.dumps({str(source): "corrupt"}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Malformed"):
            self.shared(records, [bad])
        bad.write_text(json.dumps({str(source): "0" * 64}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Conflicting"):
            self.shared(records, [good, bad])
        self.assertFalse(self.output.exists())

    def test_shared_empty_manifest_is_versioned(self):
        self.assertEqual((b"\n", hashlib.sha256(b"rules_verilog.compile_inputs.v2\0").hexdigest()), self.shared([], []))


if __name__ == "__main__":
    unittest.main()
