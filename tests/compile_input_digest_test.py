"""Deferred inventory generation must retain the legacy content fingerprint."""

import hashlib
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
