# VCS coverage identity performance — 2026-10-11

Coverage identity checks on the existing 20 passing datasets decreased from
0.438 s to 0.405 s (7.44%). Checking the previous merged VDB decreased from
0.361 s to 0.324 s (10.15%). These are small savings of 33–37 ms per check,
measured on real retained VDBs; they do not establish faster compilation,
simulation, URG execution or a faster complete regression.

Baseline: `ea28fb78192c0c26a315d8c122191ff4bdcefcda`.
Tested implementation: `6ff5a71696805787d3234677c9bc210065c11aaf`.

## Change and correctness

The coverage walker resolved every directory path and separately queried each
entry's directory/file type. It now reuses followed `DirEntry.stat` metadata,
uses device/inode identity for ancestor-cycle detection, and supplies a Windows
fallback when directory entries omit inode numbers. This reduces repeated
filesystem metadata requests on the EDA filesystem.

Hash format, logical relative paths, alias contributions, partition traversal,
static-model exclusions and dataset boundaries are retained. Cyclic directories,
dangling links and unsupported entries still fail rather than permitting reuse.
The traversal keeps each alias under its own logical path; it does not globally
deduplicate files or omit their contents from hashes.

## Method and measurements

Both versions ran in one LSF allocation as `lwang` on `sh-ic10`, using CPython
3.12.5 against unchanged retained storage. Five paired measurements alternated
old/new order after equivalence checks had warmed the data. Each identity
measurement calls `model_digest` and `datasets`, and checks their returned values
against the original implementation. Separate traversal measurements materialize
and compare the directory/file records without hashing file contents. They are
phase measurements, not additional savings to add to the identity result.

| Dataset | Identity before | Identity after | Saved | Reduction |
| --- | ---: | ---: | ---: | ---: |
| 20-case input | 0.437611 s | 0.405060 s | 0.032551 s | 7.44% |
| Previous merged output | 0.361018 s | 0.324357 s | 0.036661 s | 10.15% |

| Dataset | Traversal before | Traversal after | Reduction |
| --- | ---: | ---: | ---: |
| 20-case input | 0.076542 s | 0.064243 s | 16.07% |
| Previous merged output | 0.077167 s | 0.063672 s | 17.49% |

The outer traversal visited 247 directories/656 files for the input and 244
directories/657 files for the merged output, excluding testdata contents.
Input identity checks hashed all 20 datasets. URG represents their previously
merged output as one dataset; that does not mean it contains only one case.

Raw identity times, in paired order (seconds):

| Pair | Input before | Input after | Merged before | Merged after |
| --- | ---: | ---: | ---: | ---: |
| 1 | 0.446021 | 0.405122 | 0.361018 | 0.324357 |
| 2 | 0.437611 | 0.428595 | 0.363843 | 0.338485 |
| 3 | 0.442903 | 0.405060 | 0.356306 | 0.324341 |
| 4 | 0.417302 | 0.394679 | 0.362792 | 0.326529 |
| 5 | 0.432697 | 0.399133 | 0.359659 | 0.321139 |

## Verification and limits

- Native Python 3.12.13: 83 focused coverage tests passed, with 8 platform skips;
  five new tests cover hash compatibility and exclusions, alias paths, ancestor
  cycles, dangling links and missing directory-entry inode numbers.
- Project YAPF 0.43.0 and whitespace checks passed. The implementation commit
  passed Windows Python, Formatting, Bazel and Red Hat-compatible smoke CI.
- Every old/new model and dataset hash, and every outer traversal record, agreed
  in the real-VDB comparison. Independent complete content inventories matched
  before and after for both input and previous merged output.
- LSF reached DONE, the Python payload exited zero, and the explicit benchmark
  pass marker was verified. This was a Python identity/traversal comparison;
  no EDA tools, compilation, simulation or URG were invoked.
- The benchmark's first attempt failed in its summary-print code after the
  comparisons. That attempt is excluded; the corrected harness completed the
  accepted five-pair run. Source implementation was unchanged.

Storage was already warm. Small absolute differences can vary with NFS cache
and load; this is not a cold-storage result, a large-VDB guarantee, or an
end-to-end incremental replay measurement. Prior licensed URG equivalence and
incremental speed measurements remain separate evidence and were not rerun for
this metadata-only change.

The 73-case regression remains incomplete: 20 PASS, 33 FAIL, 4 interrupted and
16 unrun. Existing failures were not diagnosed or rerun. Prior Verdi VDB-reader
crashes remain unresolved; GUI acceptance is NOT RUN for this change.
Transitive compile-input index composition remains a performance candidate
without measured production impact and is unchanged.
