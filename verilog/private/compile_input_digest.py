#!/usr/bin/env python3
"""Generate the content digest used by simmer's compile cache."""

import hashlib
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


def main():
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: compile_input_digest MANIFEST OUTPUT [INVENTORY]")
    generate_digest(*sys.argv[1:])


if __name__ == "__main__":
    main()
