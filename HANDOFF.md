# Multi-Project Handoff: rules_verilog, XinAnRiver, and ETX Validation

## Task-switch checklist

Use this section when moving `rules_verilog` work to a fresh Codex task. Update
it before switching and keep the active handoff under 200 lines. Do not copy the
old chat, resolved debugging history, or full logs into the new task.
Preserve all unresolved decisions, user changes, safety boundaries, root-cause
evidence, and required validation even when that needs a longer handoff.
Accuracy and completeness take priority over token savings.

The user should provide or confirm:

1. **Project and checkout**: repository name and exact Windows checkout path.
2. **Git scope**: current branch, base branch, PR number/URL, and whether the PR
   is draft, open, or already in review.
3. **ETX consumer scope**: XinAnRiver path, required branch, MR number/URL, and
   whether the user is currently using that checkout.
4. **Single goal**: one feature, bug, review, or validation objective for the
   new task.
5. **Current state**: what is complete, what remains, and the latest known
   root cause or blocker.
6. **Workspace state**: relevant modified/untracked files and any user changes
   that must be preserved.
7. **Verification evidence**: last command, GitHub Actions run ID, LSF job ID,
   result, and paths to logs or artifacts. Provide paths instead of pasting
   large logs.
8. **Execution requirements**: simulator/tool versions, Bazel target/profile,
   queue/resources, and tests that are intentionally excluded.
9. **Delivery authority**: whether Codex may edit, run tests, commit, push, and
   update the PR. Project source PRs must not be merged by Codex.
10. **Next action and prohibitions**: the exact next step plus files, IP, or Git
    operations that must not be touched.

Use this starter in the new task:

```text
Project: rules_verilog
Checkout: C:\Users\lwang\Downloads\repo\rules_verilog
Branch/base:
PR:

Single goal:

Completed:
-

Remaining/blocker:
-

Relevant workspace changes to preserve:
-

ETX/XinAnRiver:
- Path: /nfs/workspace/XinAnRiver/lwang/XinAnRiver
- Branch/MR:
- I am / am not currently using this checkout:

Last verification:
- Command or workflow:
- GitHub Actions run ID:
- LSF job ID:
- Result:
- Log/artifact path:

Execution requirements:
- Submit Bazel, simmer, VCS, and EDA workloads as user lwang with bsub to a
  SHICloud execution host.
- Read completed logs directly through the ETX runner; no second bsub is needed.

Authority:
- Inspect/edit/test:
- Commit/push/update PR:
- Merge project source PR: no

Next action:

Do not:
- use direct SSH or an interactive ETX shell
- run EDA workloads directly on the GitHub runner
- rewrite Git history or discard user changes
- modify third-party or encrypted RTL

Read AGENTS.md and this Task-switch checklist first. Verify all live Git, PR,
runner, ETX branch, and MR state before acting. Consult the legacy detailed
reference below only when the current objective needs it.
```

## Legacy detailed reference

This is the canonical handoff for continuing the work from the long Codex chat
that developed VCS support in `rules_verilog`, validated it against XinAnRiver on
ETX, migrated the public repositories into the Lightelligence GitHub
organization, and created a private self-hosted-runner control repository.

Read the Task-switch checklist and repository `AGENTS.md` before acting.
Consult the legacy sections below only as needed. Verify live Git,
pull-request, merge-request, tag, runner, and CI state because the facts below
can change after this handoff. Prefer English technical terms in Chinese
explanations; for example, use `root cause`, `consumer`, `runner`, `workflow`,
`lint`, and `unit test` instead of unclear literal translations.

Last live verification: 2026-07-22 14:55 Asia/Shanghai.

## Immediate startup procedure

1. Inspect the saved `rules_verilog` checkout, GitHub `main`, release `v0.4.0`,
   and any active branches or PRs.
2. Inspect `Lightelligence/etx-validation-lwang` and its runner status.
3. Use the private runner, never SSH, for every ETX operation.
4. Inspect XinAnRiver branch `lw/update_rules_verilog` and GitLab MR !27 before
   changing it.
5. Do not make a speculative UCIe revert. First resolve the open design-intent
   question documented under “MR !27 equivalence review”.
6. Preserve user changes and third-party RTL. Never force-push, rewrite history,
   use `git reset --hard`, or discard unrelated work.

Useful Windows checks:

```powershell
git status --short --branch
git branch --show-current
git remote -v
git log -8 --oneline --decorate
git rev-parse HEAD

gh repo view Lightelligence/rules_verilog --json nameWithOwner,isPrivate,isArchived,defaultBranchRef,url
gh pr view 19 --repo Lightelligence/rules_verilog --json number,state,isDraft,baseRefName,headRefName,headRefOid,mergeCommit,mergedAt,url
gh release view v0.4.0 --repo Lightelligence/rules_verilog --json tagName,targetCommitish,publishedAt,url
gh api repos/Lightelligence/etx-validation-lwang/actions/runners
```

## Project inventory

### Official rules_verilog repository

- Saved Windows checkout:
  `C:\Users\lwang\Downloads\repo\rules_verilog`
- Official GitHub repository:
  <https://github.com/Lightelligence/rules_verilog>
- Internal GitLab-style Git remote:
  `git@idc-code1.int.lightelligence.co:rtl_dv_dev/dv_dev/rules_verilog.git`
- ETX checkout used to synchronize the internal remote:
  `/u/lwang/rules_verilog`
- The old URL `https://github.com/justin371/new_rules_verilog.git` currently
  redirects after repository transfer. Existing local remotes may still display
  the old URL; verify before changing remote configuration.
- The old Lightelligence repository was renamed to
  <https://github.com/Lightelligence/rules_verilog-legacy> and is archived.
- `Lightelligence/rules_verilog` is public and uses `main`.

Live state verified on 2026-07-22:

- PR #19, “Harden simulation workflows and public setup”, is **MERGED**.
- PR URL: <https://github.com/Lightelligence/rules_verilog/pull/19>
- PR base/head: `main` / `codex/v0.3-review-fixes`
- Merge/main commit:
  `fb577c7927f74de98b1e89a382656dd751cbb1a5`
- Merge time: `2026-07-21T14:05:48Z`.
- Annotated tag and release `v0.4.0` point to the same commit `fb577c7`.
- Release URL:
  <https://github.com/Lightelligence/rules_verilog/releases/tag/v0.4.0>
- The old handoff instruction “do not merge PR #19” is obsolete. Do not attempt
  to merge it again.

Saved checkout state at handoff:

```text
branch: codex/v0.3-review-fixes
HEAD:   2f179287721e62d21d9f42bea619751731af3d2d
status: clean and tracking github/codex/v0.3-review-fixes
```

Recent branch commits:

```text
2f17928 Parse native VCS lint source locations
c376d28 Isolate VCS lint compile artifacts
04b9d54 Format VCS SVUnit tests
7ed63cc Add VCS support for bundled SVUnit tests
6344dbf Revert "Allow standalone VCS lint interface tops"
4d71077 Allow standalone VCS lint interface tops
2f13543 Move ETX validation to private repository
d8cd825 Protect licensed ETX logs in public workflows
```

Important: the PR was merged using a merge/squash result whose `main` commit is
`fb577c7`; the old head branch and `main` have different history shapes. Do not
assume that branch ancestry is linear and do not reuse or push the branch
without comparing its tree against current `main`. Start new maintenance work
from updated `main` unless the user explicitly asks to continue the old branch.

The detached Codex worktree from the old chat was:

```text
C:\Users\lwang\.codex\worktrees\f166\rules_verilog
HEAD: 04b9d54b268dd7330c4387fef222f6ba78aee7e3
```

It is not the canonical checkout for future implementation.

### uvmf

- Official GitHub repository after transfer:
  <https://github.com/Lightelligence/uvmf>
- It is public, active, and uses `main`.
- XinAnRiver currently pins internal `uvmf` commit
  `5381f7d321f2e664a16d9dbf8b1a45198fed1657` and describes its update as tag
  `v0.1.0` in branch history.
- The transfer was requested as a direct transfer; do not recreate a duplicate
  repository.

### Private ETX validation repository

- GitHub repository:
  <https://github.com/Lightelligence/etx-validation-lwang>
- Visibility: private.
- Windows checkout:
  `C:\Users\lwang\Downloads\repo\etx-validation-lwang`
- Branch: `main`
- Verified HEAD:
  `0eb66c1124bf61eddc0bff68fcc828bc253a5964`
- Runner installation:
  `/nfs/workspace/XinAnRiver/lwang/actions-runner-lwang`
- Runner name: `sh-etxn8-lwang`
- Runner host: `sh-etxn8.rd.lgt.ai`
- Runner version: `2.336.0`
- Labels: `self-hosted`, `Linux`, `X64`, `etx-vcs`
- Runner Unix account: `lwang`
- XinAnRiver checkout controlled by the workflow:
  `/nfs/workspace/XinAnRiver/lwang/XinAnRiver`

The runner being installed outside the XinAnRiver checkout is correct. Start it
with the project environment loaded explicitly:

```bash
cd /nfs/workspace/XinAnRiver/lwang/XinAnRiver
source env/digital_env.sh

cd /nfs/workspace/XinAnRiver/lwang/actions-runner-lwang
./run.sh
```

Never use the interactive `ss` alias in automation. Always use:

```bash
source env/digital_env.sh
```

All ETX actions must go through this private runner. SSH from the Windows Codex
host does not work and must not be retried. The user explicitly authorized the
runner to modify `/nfs/workspace/XinAnRiver/lwang/XinAnRiver` directly when a
fix is needed, provided that the operation leaves an auditable record: before
and after status, diff, commit, and test logs.

The user also explicitly authorized uploading committed RTL source and the full
committed MR diff to this private GitHub repository when that is the most
efficient review workflow. There is no need to create temporary source-export
logic and delete it after each review.

Latest private automation behavior:

- Workflow: `.github/workflows/etx_vcs.yml`
- Main workflow scopes:
  `all`, `known-failures`, `svunit-fifos`, `sync-fifo`, `rr-arb`,
  `lint-tops`, `lint-regression`, and `ucie-sys`.
- `inspect_only` captures branch/commit/status, working-tree and index diffs,
  the committed `origin/main...HEAD` patch, commit list, file manifest, diff
  stat, whitespace findings, and focused source contexts.
- The workflow verifies the exact XinAnRiver branch and refuses to switch,
  reset, or clean it.
- ETX VCS jobs use asynchronous LSF submission, poll `bjobs`, and stream the LSF
  log. Do not use opaque `bsub -K` while debugging because it hides progress and
  live logs.
- Every Verilog unit-test and lint log is audited for simulator provenance: it
  must contain VCS evidence and must not contain XRUN/Xcelium evidence.
- GitHub actions are pinned by full SHA and repository token permissions are
  read-only unless a workflow specifically needs more.

Recent private automation commits:

```text
0eb66c1 Capture committed XinAnRiver review sources
b6cefe4 Limit ETX inspection artifacts to manifests
ff400ec Capture committed ETX review diff
cc6ca7f Avoid network fetch during ETX inspection
8b2c651 Add merge request manifest to ETX inspection
31cb1a2 Document lwang runner installation
5ae6833 Configure lwang ETX validation repository
```

The intermediate add/remove commits around source capture are historical; the
final behavior at `0eb66c1` intentionally includes the committed MR patch and
source because the user approved it.

### XinAnRiver consumer repository

- ETX path: `/nfs/workspace/XinAnRiver/lwang/XinAnRiver`
- Required branch: `lw/update_rules_verilog`
- GitLab MR !27:
  <https://gitlab.lightelligence.co/rtl_dv_dev/XinAnRiver/-/merge_requests/27>
- Do not create a replacement MR; update the existing MR !27.
- Direct ETX/GitLab access is available through the private runner, not through
  Windows SSH or public web browsing.

Latest private-runner inspection, GitHub Actions run `29898343025`:

```text
project branch: lw/update_rules_verilog
project commit: bb37340fc314c4209924aad1dd83669e181d2f46
tracking:       origin/lw/update_rules_verilog
status:         clean
host:           sh-etxn8.rd.lgt.ai
captured:       2026-07-22T14:55:45+08:00
```

Commits in `origin/main..HEAD` at that inspection:

```text
bb37340 fix: the verilog syntax error
780474d fix: auto format issue for the new added files
5885c5e feat: update the UVMF to tag v0.1.0
8b03c89 fix axi_reg_slice
3e69563 fix: The RTL elaboration by VCS
35454f5 update ucie vcs sim model
3371751 feat: update rules_verilog for the VCS bazel test
```

The committed MR diff currently contains 40 files. Major groups:

- `.bazelrc`, `.gitlab-ci.yml`, and `deps/load_deps.bzl`.
- Equivalent-width/lint cleanup across common CDC, FIFO, ECC, count, APB, SPI,
  NOC, and SRB RTL.
- VCS lint wrapper tops for `i2c_wrapper` and `spi2apb`.
- SVUnit test portability and race/scheduling fixes.
- UCIe production topology, testbench, BUILD, and third-party repository changes.

## MR !27 equivalence review

The long chat completed a full committed diff review using the private runner.
The correct conclusion is:

**The screenshoted CDC width cleanup is equivalent, but MR !27 as a whole is
not functionally equivalent to `main`.**

### Proven-equivalent CDC change

In `hw/rtl/common/cdc/wr_ptr_full.sv`, the declaration is:

```systemverilog
logic [MEM_ADDR_WIDTH-1:0] w_rd_addr_gray2bin;
```

The old assignment was:

```systemverilog
assign w_rd_addr_gray2bin = {
  sync_rd_addr_gray[MEM_ADDR_WIDTH],
  ^sync_rd_addr_gray[MEM_ADDR_WIDTH:MEM_ADDR_WIDTH-1],
  sync_rd_addr_gray[MEM_ADDR_WIDTH-2:0]
};
```

The old RHS is `MEM_ADDR_WIDTH + 1` bits and the LHS is only
`MEM_ADDR_WIDTH` bits, so SystemVerilog discarded the leftmost MSB. The new
assignment explicitly writes exactly the bits that survived the old implicit
truncation:

```systemverilog
assign w_rd_addr_gray2bin = {
  ^sync_rd_addr_gray[MEM_ADDR_WIDTH:MEM_ADDR_WIDTH-1],
  sync_rd_addr_gray[MEM_ADDR_WIDTH-2:0]
};
```

This equivalence also holds for X/Z values because the removed bit never
contributed to the assigned value. The existing design already requires
`MEM_ADDR_WIDTH >= 2` because both versions use
`[MEM_ADDR_WIDTH-2:0]`. The analogous `rd_ptr_empty.sv` change is equivalent for
the same reason.

The `PTR_WIDTH'(AFULL_LEVEL_BUF)` and `PTR_WIDTH'(AMT_LEVEL)` changes replace
implicit sizing with explicit sizing and are equivalent for valid FIFO
parameter ranges. Other reviewed explicit casts and zero extensions in
`crd_count`, `fifo_ctl`, `flop_array_1wNr`, `math_rpkg`, `pop_count`,
`vec_to_idx`, `spi2apb`, and `srb_subscriber` were also equivalent under their
existing valid parameter constraints.

Testbench-only `$asserton` hierarchy changes and `#0` scheduling changes affect
testbench portability/race behavior but do not change DUT RTL behavior.

### Open UCIe design-intent blocker

The UCIe group is not equivalent:

- `hw/rtl/ucie_sys/ucie_sys.sv` changes from five UCIe wrapper instances to one.
- Public ports change from `ucie0_*` through `ucie4_*` to one `ucie_*` group.
- Ten AXI register-slice instances are removed.
- `@axi_slice` is removed from `hw/rtl/ucie_sys/BUILD`.
- `hw/vendor/rtl/BUILD.axi_slice` is deleted.
- The `axi_slice` local repository declaration is removed from
  `hw/vendor/rtl/ip_defs.bzl`.
- `unit_test_top.sv` is reduced consistently from five UCIe groups to one.
- The UCIe unit test is tagged `no_ci_gate`, so the required `//...` VCS
  regression does not exercise it.

This is an architecture and public-interface change, not a lint-only cleanup.
The MR title referenced simulation performance, so it may be intentional, but
the user asked to ensure functionality is unchanged. Before reverting or
preserving it, obtain an explicit answer to:

> Is reducing UCIe from five instances to one an intentional functional scope
> change, or should production UCIe topology and AXI slices be restored while
> keeping only the VCS-compatible encrypted model selection?

Do not silently revert these user changes. If the answer is “restore”, the
minimal intended fix is expected to restore from `main` only:

```text
hw/rtl/ucie_sys/ucie_sys.sv
hw/rtl/ucie_sys/unit_test_top.sv
hw/rtl/ucie_sys/BUILD
hw/vendor/rtl/BUILD.axi_slice
hw/vendor/rtl/ip_defs.bzl
```

Keep `hw/vendor/rtl/BUILD.uvsta_ucie` pointed at the VCS-compatible encrypted
model if that is the confirmed site requirement, and remove the temporary
`no_ci_gate` bypass before declaring the VCS regression complete.

### Other MR review findings

- `.gitlab-ci.yml` changes LSF commands from `bsub -I/-Is` to `bsub -K`.
  This changes live-log behavior. The user explicitly said not to debug with
  `bsub -K`; preserve streaming logs unless delayed logs are intentionally
  required by GitLab CI.
- `deps/load_deps.bzl` pins `rules_verilog` commit `fb577c7` with comment
  `#tag: v0.4.0`, but still includes `shallow_since`. The user explicitly asked
  to use the tag comment instead of updating/retaining `shallow_since`; verify
  and remove that argument if still required by the request.
- The same file pins `uvmf` commit `5381f7d3`.
- `git diff --check origin/main...HEAD` found seven trailing-whitespace lines:
  six in `hw/rtl/ucie_sys/ucie_sys.sv` around lines 168-173 and one in
  `hw/rtl/ucie_sys/unit_test_top.sv` around line 306.
- `hw/rtl/srb/unit_test_srb.sv` guards Cadence-only `$shm_open/$shm_probe` with
  `` `ifndef VCS ``. This is the intended VCS portability fix.
- `i2c_wrapper_lint_top.sv` and `spi2apb_lint_top.sv` are VCS-only lint wrapper
  tops selected by the configured simulator. Their wildcard port connections
  were fixed after the mixed ordered/named port error.
- `noc_vcs_lint.opts` waives third-party NOC warnings that cannot be waived
  inline. Do not modify the third-party RTL to suppress them.

## Third-party RTL policy

- Files referenced using external repository labels such as `@axi_slice` are
  third-party RTL/IP.
- Do not modify third-party RTL or encrypted models.
- The user stated that the encrypted model was replaced with a VCS-compatible
  version; the earlier model was for XRUN.
- If a third-party encrypted-model issue remains, report/bypass it narrowly as
  directed and let the user replace the IP. Do not rewrite the encrypted RTL.
- Ignore encrypted-model failures when specifically authorized, but do not hide
  unrelated failures behind the same bypass.

## Required simulator behavior

The consumer command that must run one-step Verilog tests with VCS is:

```bash
bsub -I -q syn bazel test --config=vcs //... \
  --test_tag_filters=-no_ci_gate \
  --cache_test_results=no \
  --jobs 8 \
  --test_output=all 2>&1
```

For automation/debugging, use the private workflow's asynchronous LSF submit
and log polling rather than an opaque `bsub -K` shell invocation.

Required consumer `.bazelrc` configuration:

```bazelrc
build:vcs --@rules_verilog//:verilog_unit_test_simulator=VCS
build:vcs --@rules_verilog//:verilog_dv_unit_test_command_vcs="runmod vcs -- vcs"
build:vcs --@rules_verilog//:verilog_rtl_lint_test_command_vcs="runmod vcs -- vcs"
build:vcs --@rules_verilog//:verilog_rtl_svunit_test_command_vcs="runmod vcs --"
build:vcs --@rules_verilog//:verilog_rtl_unit_test_command_vcs="runmod vcs -- vcs"
build:vcs --@rules_verilog//:verilog_vcs_unit_test_runner="runmod vcs --"
```

`build:vcs` is correct even for `bazel test`: Bazel test inherits build options.
The simulator-selection build setting must be declared by the pinned
`rules_verilog` version; the earlier “no such target
verilog_unit_test_simulator” failure occurred because XinAnRiver was using an
old local `rules_verilog` checkout at commit `12f471f`.

Important simulator contracts:

- Explicit `simulator = "XRUN"` on a target overrides the configured VCS
  default. Do not remove that compatibility behavior in `rules_verilog`.
- VCS compile uses `runmod vcs -- vcs`.
- Generated `simv` runtime uses `runmod vcs -- "$simv"`.
- DV VCS compile includes `-full64`.
- VCS one-step waveform dumping is intentionally disabled. Wave commands remain
  comments; do not enable waves unless explicitly requested.
- VCS and XRUN must never be mixed in one target/run.
- Do not reuse `partitionlib`, `csrc`, or `simv.daidir` across VCS releases;
  use `--recompile` when changing releases.
- Custom VCS templates retain legacy placeholders such as `FLISTS`, `SIM_ARGS`,
  and `COMPILE_ARGS`.
- Runtime scripts retain diagnostic/cleanup traps and preserve
  `SIMMER_KEEP_TERMINAL` behavior.
- Working simulator release: VCS `X-2025.06-SP2-4`.
- Actual 64-bit compiler installation is under:
  `/global/stools/synopsys/vcs/X-2025.06-SP2-4/linux64/bin`.
  A prior failure incorrectly selected `.../linux/bin`; allow `runmod vcs` and
  the site environment to establish the correct VCS environment.

The user later said not to run or fix XRUN tests for this effort. Final consumer
validation is VCS-only, but `rules_verilog` itself must not regress its existing
XRUN API/behavior unless the user explicitly authorizes that product change.

## rules_verilog compatibility boundaries

- Bazel target version: 7.7.1.
- Python target version: 3.12.
- WORKSPACE-based repository; Bzlmod disabled.
- Licensed simulator validation runs on Red Hat ETX, not Windows.
- Windows is used for Git/code management only; do not add unnecessary Windows
  runtime branches to simulator code.
- Preserve synthesis-aspect compatibility for
  `create_flist_content(..., no_synth=...)`, restored by commits `2dade773` and
  `bff31f7`.
- Keep one simulator per run and preserve XRUN batch/VWDB/xprop behavior.
- PLDM is not a third simulator backend; it emits Xcelium-emulation inputs.

Standard license-free `rules_verilog` checks:

```bash
bazel test --test_output=errors //:buildifier_diff //tests/... //examples/dpi:dpi_c_test
./tests/doc_test.sh
bazel run //bin:simmer -- --help
bazel run //:buildifier_lint
```

Focused generation check previously passed:

```bash
bazel build --config=vcs //examples/apb:test //examples/dpi:test
```

Never claim licensed VCS/XRUN runtime validation unless it actually ran on the
configured ETX host and the logs were audited.

## Git and workspace safety

- Do not force-push, rewrite history, use `git reset --hard`, or discard user
  changes.
- Keep commits scoped. For XinAnRiver, update existing MR !27 rather than
  creating another MR.
- Before every `rules_verilog` push, safely find and remove `__pycache__`
  directories only after verifying each resolved path is inside that repo.
- Ignore and never commit/edit/delete a repository-local untracked `.codex/`
  directory.
- Preserve unrelated dirty-worktree changes.
- The saved Windows `rules_verilog` checkout must stay synchronized with the
  official GitHub repository when rules are changed.
- Internal `origin` synchronization must be performed from ETX when Windows
  cannot reach the internal SSH host.
- Do not expose runner registration/removal tokens. Tokens pasted in the old
  chat must be treated as expired/revoked and must never be copied into files.

## Multi-user runner model and security notes

The chosen model is one private repository and one self-hosted runner per Unix
user/account/path, not one shared organization runner for ten users. Each runner
runs as that user's Unix account and therefore can modify every file that Unix
account can modify. Users' `/nfs/workspace/XinAnRiver/<user>` paths are protected
by Unix permissions from other users.

This reduces cross-user collisions and privilege sharing. Still enforce:

- private control repositories;
- least-privilege collaborators;
- reviewed workflows;
- pinned Actions SHAs;
- read-only `GITHUB_TOKEN` by default;
- no secrets printed into logs;
- no untrusted fork PR execution on self-hosted runners;
- separate work directories and runner services per Unix user;
- organization 2FA and access review when administratively feasible.

## Recommended next-chat behavior

At the start of the new chat:

1. Read this file and `AGENTS.md` fully.
2. Verify the saved checkout and live GitHub state.
3. Use `Lightelligence/etx-validation-lwang` to inspect XinAnRiver and the
   current MR !27 state.
4. Report readiness and the unresolved UCIe intent question.
5. Wait for the user's instruction unless the user already answered that
   question in the new chat.

Do not make a UCIe topology change merely to make VCS tests pass. The final
solution must distinguish real design functionality from VCS portability,
third-party encrypted-model compatibility, lint cleanup, and testbench-only
changes.
