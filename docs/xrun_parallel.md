# Default same-database XRUN concurrency

Ordinary XRUN tests that share a compile database now run concurrently by
default. `--jobs N` still limits active tests; when omitted, the existing
host-CPU/test-count calculation applies. `--xrun-parallel` is accepted for
compatibility but is no longer required. Use `--no-xrun-parallel` to restore
per-database serialization. If both switches occur, the last one wins.

```sh
sim -t "sys_tia_tb:bias_mode_0_default_test" \
    -t "sys_tia_tb:dcd_mode_0_default_test" \
    --ams-runfiles-link digital --jobs 2 --nt
```

After validating two tests from the same compile group, use the CI selector:

```sh
sim -t "sys_tia_tb:*" --tag ci_gate \
    --ams-runfiles-link digital
```

These commands keep the existing source/elaboration caching policy. Add
`--recompile` only when a rebuild is wanted. The parallel/serial switches are
runner policy, not xrun command-line options or compile inputs. Explicit
switches are retained by rerun.sh. Changing this policy alone does not request
a different analog profile.

## Why serialization existed

The baseline `get_test_exclusive_resource()` uses the canonical compile-directory
path as a scheduler resource. Its comment explicitly says shared XRUN database
immutability had not been established by licensed validation. This is a
conservative restriction, not evidence of a specific observed Cadence failure.

The current runner already gives each test a claimed/locked result directory,
an independent working directory and separate logs/waveform paths. A normal
simulation uses `xrun -R -xmlibdirname <compile-dir>` rather than recompiling.
These features make controlled concurrent runs possible. Cadence confirms that
simulation can run outside the elaboration directory with `-xmlibdirname`:
https://community.cadence.com/cadence_technology_forums/f/functional-verification/59340/xcelium-xrun-simulate-with-multiple-builds
That statement alone does not establish shared-database immutability for every
AMS version, model or project Tcl script.

## Scope and retained protections

Parallel mode only releases the scheduler's per-database test resource. Shared
runfiles/compile-directory locks held against other regression processes remain,
as do compile locks, per-test directory locks, fingerprint checks and cleanup
ownership checks. Other invocations may therefore still wait for those shared
directories. This change does not implement cross-host distribution.

Coverage, MCE, all MSIE stages and emulator modes remain automatically serial.
An explicit `--xrun-parallel` with one of those modes is rejected during option
validation; the implicit default does not reject existing commands. Programmatic
callers that skip validation also retain serialization for these modes. GUI is
already unsupported for XRUN. Both explicit switches are registered as XRUN-only
so the existing VCS backend's explicit-option check can reject them. The shared
parser default does not change VCS execution policy.

## What must be checked on the EDA host

The local mirror lacks the complete JobManager, templates and licensed tools.
Adapter tests verify policy, arguments, paths, retained locks and CLI contracts;
they do not prove actual Xcelium/AMS concurrent execution is safe.

Run the two short cases above against the same database. Both Starting TestJob
messages should appear before either completes. Compare each result and wave
against its serial baseline. Check for lock errors, database corruption, mixed
logs and missing analog waves, and inspect unexpected writes to the compile
database/shared source paths. In particular, per-test CWDs do not isolate
absolute output paths in SCS/Tcl/VA/DPI, save/restore checkpoints or shared AMS
caches. Such writes must be moved into each test directory before using parallel
execution for that project; otherwise pass `--no-xrun-parallel`.

Concurrent runs also need enough licenses, RAM and CPU. Start with two jobs;
the scheduler's host CPU count is not an estimate of available Spectre licenses
or memory. An AMS simulation may use more than one CPU internally.

Register `tests/xrun_parallel_test.py` in the complete repository's existing
tests/BUILD when integrating, and link this page from docs/defs.md. Only patch
the small new CLI declarations into newer upstream parser files rather than
overwriting newer files with an older local mirror.
