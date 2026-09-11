#!/usr/bin/env python3
"""Generate the content digest used by simmer's compile cache."""

import hashlib
import json
import re
import sys


def read_records(manifest_path):
    """Read internal manifest records, retaining their order and identity."""
    with open(manifest_path, "r", encoding="utf-8") as manifest:
        for line in manifest:
            fields = line.rstrip("\n").split("\t", 2)
            if len(fields) != 3:
                raise RuntimeError("Malformed compile input digest entry: {!r}".format(line.rstrip("\n")))
            kind, relative_path, input_path = fields
            yield "{}\t{}".format(kind, relative_path), input_path


def generate_digest(manifest_path, output_path, inventory_path=None):
    """Optionally canonicalize a deferred manifest with legacy inventory semantics.

    Keys include both category and runfiles path; the last matching record wins,
    just as in the analysis-time dictionary. Sorting affects inventory only, not
    the compiler's filelists. The two-argument interface retains ordered hashing.
    """
    records = read_records(manifest_path)
    if inventory_path is not None:
        records = sorted(dict(records).items())

    digest = hashlib.sha256()
    for entry, input_path in records:
        digest.update(entry.encode("utf-8"))
        digest.update(b"\0")
        with open(input_path, "rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")

    with open(output_path, "w", encoding="ascii") as output:
        output.write(digest.hexdigest() + "\n")

    if inventory_path is not None:
        with open(inventory_path, "w", encoding="utf-8", newline="\n") as inventory:
            inventory.write("\n".join(entry for entry, _ in records) + "\n")


def file_digest(path):
    """Hash a file without retaining its contents in memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_index(manifest_path, output_path):
    """Index a dependency closure once, independently of consuming testbenches."""
    paths = sorted({path for _, path in read_records(manifest_path)})
    hashes = {path: file_digest(path) for path in paths}
    with open(output_path, "w", encoding="utf-8", newline="\n") as output:
        json.dump(hashes, output, sort_keys=True)
        output.write("\n")


def merge_digest(manifest_path, output_path, inventory_path, index_list_path):
    """Compose a versioned digest without reopening indexed dependency files.

    Execution paths identify index records but never enter the final hash.
    Category/runfiles-path identity and last-record-wins semantics are retained.
    Only runfiles explicitly in the compile manifest may be read directly.
    """
    hashes = {}
    with open(index_list_path, encoding="utf-8") as indices:
        for index_path in indices:
            with open(index_path.rstrip("\n"), encoding="utf-8") as index:
                entries = json.load(index)
            for path, value in entries.items():
                if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                    raise RuntimeError("Malformed compile input index hash: {!r}".format(path))
                if path in hashes and hashes[path] != value:
                    raise RuntimeError("Conflicting compile input index hashes: {!r}".format(path))
                hashes[path] = value
    records = sorted(dict(read_records(manifest_path)).items())
    digest = hashlib.sha256(b"rules_verilog.compile_inputs.v2\0")
    for entry, path in records:
        if path not in hashes:
            if not entry.startswith("runfile\t"):
                raise RuntimeError("Missing compile input index hash: {!r}".format(path))
            hashes[path] = file_digest(path)
        digest.update(entry.encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(hashes[path]) + b"\0")
    with open(output_path, "w", encoding="ascii") as output:
        output.write(digest.hexdigest() + "\n")
    with open(inventory_path, "w", encoding="utf-8", newline="\n") as inventory:
        inventory.write("\n".join(entry for entry, _ in records) + "\n")


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--index":
        generate_index(*sys.argv[2:])
        return
    if len(sys.argv) == 6 and sys.argv[1] == "--merge":
        merge_digest(*sys.argv[2:])
        return
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: compile_input_digest MANIFEST OUTPUT [INVENTORY]")
    generate_digest(*sys.argv[1:])


if __name__ == "__main__":
    main()
