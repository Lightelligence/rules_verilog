# VCS cache and scheduler review, 2026-10-11

## Result

Prebuilt Bazel nodes could serialize otherwise independent cached benches.
`BazelTBJob` and `BazelTestCfgJob` inherited the exclusive execution class even
when their commands only acknowledged existing outputs. A running simulation
therefore blocked the next bench's dependency chain despite spare simulation
capacity. Allowing VCS fingerprint preparation to overlap simulations alone did
not remove these barriers before and after the compile job.

These nodes now use the scheduler's single preparation slot when no Bazel build
is needed. Actual builds, including a partially prebuilt target list, remain
exclusive. Compile fingerprints, artifact checks, cache-miss admission,
dependency failure propagation and explicit concurrency settings are unchanged.
The common Bazel nodes apply to both simulator backends.

## Evidence

Baseline: `8eaaa8880edb1e2c7c7a9005d12107450174d55f`.
Tested implementation: `9ca3f537ff5a0da884fa157c0b0ec28dfcdc3b30`.

An event-driven test holds one simulation active, then adds a second bench's
prebuilt Bazel -> cached compile -> prebuilt config -> simulation chain with a
parallel limit of two. It fails on the baseline because the second simulation
never starts while the first is held. It passes after the change, with the
dependency chain completed and compile preparation performed once.

A separate controlled queue measurement used the real scheduler and subprocess
runner on one Linux compute node. Two `sleep 2` subprocesses represent running
jobs; a `true` command represents an already verified cached compile. The Bazel
acknowledgment jobs are the actual production classes. Three alternating pairs
gave these medians:

| Controlled queue metric | Baseline | Changed |
| --- | ---: | ---: |
| Total elapsed | 5.486812 s | 2.984128 s |
| Second simulation substitute's start delay | 3.187845 s | 0.892461 s |

The queue saved 2.502684 seconds, or 45.6%, in this constructed case. This proves
removal of the admission barrier, not an improvement in real VCS simulation
throughput. A single-bench regression has no such cross-bench overlap to recover.

## Compile cache findings

The retained real input inventory contains 7,355 records totaling 447,792,837
bytes. Five alternating measurements of the current fingerprint function gave:

| Fingerprint path | Median | Observed range |
| --- | ---: | ---: |
| Read existing Bazel digest and inventory | 0.002463 s | 0.002345–0.006943 s |
| Verify current input bytes | 4.251195 s | 2.402062–9.913382 s |

These are different validation paths, not interchangeable implementations.
Skipping Bazel still requires current-byte verification. The retained stored
digest differs from the current verifier's result; each result stayed stable
across repetitions. The cause of that preexisting difference was not established.
This snapshot cannot prove an automatic executable-cache hit, and no fingerprint
or artifact was rewritten to make reuse succeed.

A historical approximately 119-second incremental invocation explicitly disabled
automatic compile reuse. It measures VCS incremental compilation, not a cache hit.
The isolated project's repository override also deliberately disables discovery
caching because provenance cannot be established by the bounded parser. Neither
observation justifies weakening cache validation. Host-CPU-based default
simulation concurrency remains the explicit policy established by PR #44.

The next compile-side evidence needed is a fresh-build, unchanged-input replay
that separates discovery/Bazel work, fingerprint preparation, cache decision and
actual VCS execution. Transitive input-index composition remains an unmeasured
candidate; no production savings are assigned to it.

## Validation and limits

- Native Python 3.12: 90 focused portable tests, 82 passed and 8 platform skips.
- An exploratory broader native invocation encountered nine unsupported POSIX
  API errors (`killpg` and signal constants). The Linux CI scheduler suite passed.
- Four implementation-head CI checks passed: Bazel, formatting, Windows Python
  and Red Hat-compatible smoke.
- The compute-node measurement completed successfully with unchanged source data.
  It invoked no Bazel build, VCS, simv, URG or DUT regression.
- The initial measurement dispatch used an incorrect revision and was rejected
  before compute submission. A subsequent harness assumed stored/current digest
  equality and stopped at that assertion. Both attempts are excluded; the accepted
  run explicitly records the difference and measures the controlled queue.

Actual licensed compilation, multi-bench DUT throughput and full-regression
performance for this change are **NOT RUN**. Existing failed regression cases and
the unresolved Verdi GUI issue were outside this stage.
