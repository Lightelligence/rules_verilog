# rules_verilog task handoff

Use this file only as a short template when moving unfinished work to a fresh
Codex task. Keep the completed handoff under 50 lines and replace the prompts
below with current, non-sensitive facts.

## Scope

- Checkout: `<absolute Windows checkout path>`
- Branch / PR: `<feature branch>` / `<public PR URL and state>`
- Goal: `<one complete feature, bug, review, or validation objective>`
- Authority: `<edit, test, commit, push, update PR>`

## Current state

- Completed: `<implemented and reviewed work>`
- Remaining: `<unresolved work or decision>`
- Workspace: `<relevant modified or untracked files to preserve>`
- Evidence: `<last validation command and result; link artifacts instead of logs>`

## Constraints

- Use the Windows checkout and PowerShell for repository work.
- Preserve unrelated user changes and keep commits scoped to this task.
- Licensed simulator work must follow the repository DV execution workflow.
- Confirm that any shared validation checkout is free before accessing it.
- Do not merge a source PR; the user makes the merge decision.

## Next action

`<single concrete next step and its acceptance check>`

## Do not include

- Credentials, tokens, license values, or environment dumps.
- Internal hostnames, filesystem paths, private repository URLs, or job IDs.
- Proprietary source, copied chat history, or full build/simulator logs.
