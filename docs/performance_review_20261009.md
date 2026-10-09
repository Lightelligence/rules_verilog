# Repository correctness and performance review — 2026-10-09

Reviewed baseline: `github/main@a69c85526b4bba238d4b15e18ad2cad259edbee7`.
The review covered CLI and generated scripts, scheduler lifecycle, discovery and
compile caching, both simulator adapters, result persistence, reports and
coverage, Starlark/runfiles, vendor templates, dependencies, CI and public docs.
VCS validation remains on the two-step flow.

## Behavior findings and revisions

| Trigger | Previous behavior | Revision |
| --- | --- | --- |
| The same nested filelist is consumed with `-f` and `-F` | Path-only deduplication can omit sources resolved from the second base | Deduplicate by filelist and resolution base; test both source mutations |
| A custom DPI source includes `<header.h>` through `-CFLAGS -I...` | Header content can escape compile fingerprints | Resolve named quoted/angle headers through attached/split compiler include paths, including transitive headers |
| A bench selector contains `[12]` or `[!2]` | Discovery rejects matches accepted by final glob selection | Translate the same glob language and escape query delimiters |
| An implicitly selected XRUN XPROP or coverage file changes | Automatic compilation reuse can retain old configuration | Fingerprint the effective files; resolve fallback coverage paths from the project directory |
| A second VCS invocation rebuilds a shared compile directory | Queued simulations can lose or use a replaced `simv` after the compile lock is released | Hold compile-directory ownership through regression cleanup; acquire all runtime paths in consistent order |
| VCS coverage merge fails with a previous dashboard present | Report collection can publish previous-run percentages | Reset generated merge outputs and require successful current merge before collecting metrics |
| A coverage column contains `N/A` | Available columns are discarded or lose their positions | Retain aligned values and exclude unavailable components from averages |
| Different test/log names normalize to the same slug | Archived log copies can overwrite one another | Include the row identity in each archived filename |
| Process monitoring raises after a zero-exit child | Cleanup can leave the job classified as successful | Preserve monitoring failure, fail finalization and skip dependents |
| CLI or per-test timeout is nonfinite or too large | Watchdog disabling or polling exceptions | Reject invalid durations before scheduling; preserve zero, inheritance and explicit CLI precedence |
| Project regex uses Unicode classes or boundaries | Byte scanning disagrees with decoded directive fallback | Stream decoded custom patterns; route non-ASCII/default CRLF logs through the same scanner |
| A regex uses global inline flags or independent captures | Combined wrapper regex can reject valid patterns or change references | Compile patterns independently; use a direct compiled regex for a single pattern |
| A Windows input path is on another drive | `relpath` raises before the outside-path check | Preserve the absolute outside path |

## Standards and documented contracts

| Finding | Revision |
| --- | --- |
| Generated `$(location)` arguments use execution-root paths while consumers run from runfiles | Expand short paths and normalize external runfiles paths; generated main/external consumer fixtures |
| An intermediate RTL library loses dependency `DefaultInfo` runtime files | Merge dependency runfiles; TB → RTL → DV → DPI sidecar fixture |
| Direct lint-waiver regex is interpolated inside shell double quotes | Quote the exact argument once; generated VCS/XRUN launcher tests include quotes, dollar signs, backticks and backslashes |
| GUMI guards contain invalid identifier punctuation | Encode path characters into distinct valid identifiers, with punctuation/underscore collision fixtures |
| XRUN defaults documentation describes opt-in/direct FOX behavior absent from implementation | Document the existing default bench configuration and missing-file behavior; clarify CLI help without changing simulator defaults |

## Measured performance revisions

Native Windows, CPython 3.12.13. Results measure synthetic helpers, excluding
compiler, simulation, coverage and full-regression runtime.

| Fixture | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Report aggregation, 8,000 continuation paths of 206 characters, median of 3 | 1.325357 s | 0.002282 s | 99.83%, approximately 581× |
| Scheduler helper, 4,000 jobs, default INFO console + DEBUG file logger, median of 3 | 6.108259 s | 1.069608 s | 82.49%, approximately 5.7× |
| Scheduler log bytes for that fixture | 281,184,004 | 4,676,234 | 98.34% |
| Scheduler helper, 4,000 jobs, DEBUG disabled, median of 9 | 106.624 ms | 8.620 ms | 91.92%, approximately 12.4× |

Report aggregation collects paths and joins once per row. Scheduler logging
records queue counts and at most 16 jobs per queue; full status snapshots remain
available. Ready admission removes from the list tail while preserving priority,
FIFO, resource constraints, requeue, cancellation and snapshot order. Sorted
insertion and scanning blocked resources remain linear operations.

Correct Unicode/regex scanning has a tradeoff: the latest 2.08 MB custom-regex
fixture took 0.365 → 0.419 s, with approximately 26 KB peak Python allocation.
The sample ran alongside other local work and is not a stable throughput claim.
ASCII LF logs with built-in signatures retain mmap scanning. No full-log decoded
copy is required.

## Verification and remaining investigation

- Hash-pinned native Python 3.12 dependencies; local combined suite: 275 tests,
  11 POSIX-related skips. Scheduler separately passed 32 focused mocked checks.
- New backend regression cases fail against the pinned baseline and pass after
  revision; cache/discovery and monitoring negative reproductions also recorded.
- Project YAPF 0.43.0 and Buildifier 6.4.0 checks; generated lint shell syntax.
- POSIX locking, process behavior and generated Bazel consumer contracts require
  Linux CI. Licensed VCS/XRUN and real full-regression performance were not run
  during this review.

One remaining performance candidate is transitive VCS input-index composition:
each node emits its full closure, so a chain adding one source per node stores
quadratic manifest/hash entries even though source bytes are hashed once.
No production timing impact is established. A future shard-index change should
retain foreign-provider filtering, duplicate-conflict detection and final digest
identity, and be measured on a real dependency graph before replacing this cache
structure.

The GitLab smoke job's execution topology was not verified. Its direct Bazel
invocation requires alignment with the `bsub` policy if it runs on an ETX host;
this conditional observation was not treated as a confirmed product defect.
