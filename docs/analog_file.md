# Per-test analog_file

This change adds an optional `analog_file` label to `verilog_dv_test_cfg`.
Keep the existing common `amscf.scs` in the testbench's `verilog_dv_library`
dependencies. No new `ams_config` attribute or additional public TB target is
required. Remove case-specific input sources from that common file before
selecting another file that drives the same nodes.

```bzl
verilog_dv_test_cfg(
    name = "bias_closed_loop_smoke_ch1_test",
    tb = "//digital/dv/benches/sys_tia_tb:sys_tia_tb",
    analog_file = "//digital/dv/benches/sys_tia_tb/model/veriloga:stim_bias_dc.scs",
    # Keep the existing sequence selection, sim_opts and tags here.
)

verilog_dv_test_cfg(
    name = "bias_closed_loop_step_ch1_test",
    tb = "//digital/dv/benches/sys_tia_tb:sys_tia_tb",
    analog_file = "//digital/dv/benches/sys_tia_tb/model/veriloga:stim_bias_step.scs",
    analog_data = ["//digital/dv/benches/sys_tia_tb/model/veriloga:step_wave_data"],
)
```

Export the SCS files with appropriate Bazel visibility. `analog_data` accepts
files or filegroups and must declare all extra includes, VA models and waveform
data used by the selected SCS. It does not automatically include those files in
the simulator input list or rewrite paths inside SCS. Keep simulator-relative
include/data paths resolvable using the project's AMS search-path conventions.
For initial validation use self-contained SCS files with inline DC/PWL sources.

Inheritance uses the last parent with a selected analog file. An explicit
`analog_file` replaces that selection and its associated data. When inheriting
the file, local `analog_data` extends the inherited data. No implicit mechanism
clears an inherited selection: use a common parent without an analog file for
tests that must use the original configuration.

The public selectors remain, for example:

```text
sys_tia_tb:bias_closed_loop_smoke_ch1_test
sys_tia_tb:bias_closed_loop_step_ch1_test
```

## Execution

The rule emits `<case>_analog_config.json` alongside the existing dynamic options.
Simmer materializes selected test metadata before creating the compile jobs.
It resolves Bazel execution paths, hashes the selected entry and declared data,
and groups tests by that identity within each TB. One Bazel TB preparation job
feeds the compile variants. Seeds and iteration counts do not affect grouping.

Each variant has its own compile directory and normal compile lock. A generated
`analog_compile_args.f` includes the common compile arguments and appends only
the selected SCS. The existing compiler invocation consumes this wrapper;
simulation still runs the corresponding compiled library through `xrun -R`.
The public TB label and seed-plan keys are unchanged. Internal job/directory
names include `__analog_<digest>` to distinguish results.

Runtime result groups use those same variant keys as the compile-job map.
This keeps summary and coverage lookups consistent for single-profile runs,
multiple profiles and legacy tests in one regression. Each group contains only
tests attached to its actual compile job; the public TB is not an alias for an
arbitrary profile. The original TB label is retained by the compile job for
Bazel operations, and seed planning occurs before runtime grouping.

The analog entry/data are also added to the existing compile fingerprint.
Common RTL/AMS inputs remain covered by the original compile-input inventory.
`analog_config.json` in the compile directory records the resolved selection.
Changes to declared analog files after scheduling fail explicitly. Source SCS
files are never overwritten by the runner.

This implementation permits separate compilation/elaboration per analog profile;
it does not promise arbitrary SCS replacement in a shared snapshot. Initial
support is standard XRUN only; VCS, emulation and MSIE selections are rejected
when `analog_file` is present. Existing tests without the field keep their usual
compile directory. `--no-bazel`/`--no-compile` require previously generated test
metadata; old metadata without the sidecar is interpreted as no selection, so
run once with Bazel enabled after migrating or changing test configuration.

## Validation and local mirror

This directory is a partial source mirror, not a complete Bazel workspace.
The implementation was reconciled against the user's exported baseline commit
`5e0256bcd2827f8dbf1be2b6d7abe8c328f479a7`. Unrelated scheduler, compile reuse,
runtime locking/cleanup, wave-viewer and SIGTERM behavior from that baseline is
preserved. Relative to that baseline, `xcelium.py` adds only four fingerprint
lines. The other rule files, BUILD declarations, job library and compile
templates are not present here. Merge the focused changes into the full
repository; do not overwrite any subsequent upstream changes.

Local checks exercise the actual runner helper AST, scheduler grouping and
compile-filelist generation, without importing missing framework modules:

```text
python -m unittest discover -s tests -p analog_file_test.py -v
```

In the full repository, register that test in the existing tests/BUILD and link
this page from docs/defs.md. Validate Bazel analysis (including inheritance,
generated files and filegroups), then run two distinct DC/PWL profiles plus a
legacy case in one regression. Confirm each compile log sees its selected SCS,
parallel runs have independent results, same-profile tests share a compile
job, and waveform voltages differ as configured. Change a declared data file
and confirm the next run selects a new analog variant. Licensed XRUN and Bazel
end-to-end execution have not been performed in this local mirror.

Cadence documents SCS control files as files on the xrun command line:
https://community.cadence.com/cadence_technology_forums/f/mixed-signal-design/65751/calling-ams-control-file-in-ade-ams-simulations
