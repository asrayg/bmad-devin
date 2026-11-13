---
name: bmad-devin-autoresolve
description: 'Headless escalation resolution for the bmad-devin autopilot. A bmad-loop run paused on a CRITICAL escalation and NO human is present; you act as the BMAD architect, make the call yourself, record it as an ADR, fix the frozen spec, and write the resolution marker so the run re-arms and continues. Invoked as /bmad-devin-autoresolve <story-key>. Never ask questions.'
---

# bmad-devin Autonomous Escalation Resolution

You are the headless counterpart of `bmad-loop-resolve`. A story escalated
(contradiction, gap, or intent ambiguity in its frozen spec) and the run paused.
**No human is present and none will answer.** `$BMAD_LOOP_MODE` is `autopilot`:
never ask a question, never wait for input, never use AskUserQuestion. Decide.

Your contract with the orchestrator is **identical** to `bmad-loop-resolve`:
read the context, fix the spec, write `resolution.json`. Read
`../bmad-loop-resolve/SKILL.md` (sibling skill folder) once for the full context
schema, the `spec_reaches_the_redrive` / `redrive_base_ref` rules, the
intent-gap patch-restore case, sentinels, and the MUST NOTs. Everything there
applies **except** the parts that say a human decides or a human lands the edit;
this file overrides those.

## Inputs

- `$BMAD_LOOP_RESOLVE_CONTEXT` — `context.json` (read FIRST).
- `$BMAD_LOOP_STORY_KEY`, `$BMAD_LOOP_RUN_DIR`.

## Procedure

1. **Read the context, the frozen spec in full, and the upstream planning docs**
   it derives from: PRD, architecture, epic `SPEC.md` / `stories.yaml`, and any
   OpenSpec change for this story (`openspec/changes/<story-key>/` and
   `openspec/specs/`). Also read prior autopilot decisions in
   `_bmad-output/autopilot/DECISIONS.md` so you stay consistent with them.

2. **Enumerate 2–4 concrete options** for the escalated ambiguity, exactly as
   the interactive skill would present them.

3. **Decide, as the architect.** Pick using this order of precedence:
   1. What the PRD / architecture / OpenSpec specs already imply (cite the line).
   2. Consistency with earlier autopilot decisions and existing code conventions.
   3. The smallest, most reversible option that satisfies the acceptance criteria.
   4. When intent is genuinely silent: the conventional, least-surprising
      behaviour for this stack; prefer safe defaults (validate input, fail closed,
      no data loss, no new external dependencies).

   For a review-stage `intent gap` with a saved patch: if the patch's reading is
   defensible under rule 1–3 and `restore_supported` is true, prefer restoring it
   (cheaper than a re-implementation).

4. **Write an ADR** at
   `_bmad-output/autopilot/decisions/<UTC yyyymmdd-HHMMSS>-<story-key>.md`:

   ```markdown
   # ADR: <one-line title>
   - Story: <story-key> · Run: <run_id> · Decided by: bmad-devin autopilot
   - Status: accepted (autonomous — review welcome)
   ## Context
   <the escalation detail, quoted>
   ## Options
   1. … 2. …
   ## Decision
   <chosen option + the precedence rule that decided it, with citations>
   ## Consequences / how to reverse
   <what changes; what a human would edit to choose differently>
   ```

   Then append one line to `_bmad-output/autopilot/DECISIONS.md`
   (`- <UTC> <story-key>: <decision> → decisions/<file>`), creating it if absent.

5. **Update the frozen spec** with the smallest edit that leaves exactly one
   correct reading (intent block + affected ACs / test matrix). If an OpenSpec
   change exists for this story, mirror the decision into its spec delta as a
   `#### Scenario:` so the two never disagree.

6. **Land the edit where the re-drive reads it — yourself.** In the interactive
   skill this is the human's step; here it is yours:
   - `spec_reaches_the_redrive: true` → nothing more.
   - `false` and `redrive_base_ref` is a **branch** → apply the same edit to that
     branch's copy (use `git worktree add` on a temp path if it is not checked
     out), commit it there with message `autopilot: resolve <story-key> (<ADR file>)`,
     remove the temp worktree.
   - `false` and `redrive_base_ref` is `HEAD` → re-apply the edit in the main
     checkout's copy, uncommitted.

7. **Write `resolution.json`** at `resolution_path` (same schema as the
   interactive skill; `decision` = your one-sentence rule; add
   `"adr": "<path>"`). This is your LAST action.

## Environment-fault escalations

`env_fault_site` non-null means the environment broke, not the story. Try to
repair it non-destructively (start the stopped service/container/emulator the
failing probe checks; install a missing dev dependency already declared in the
project's manifests). Re-run the failing probe. If it now passes, write an ADR
noting the repair and the resolution marker. If it does not, **do not write the
marker** — the autopilot will defer the story and continue the run.

## When you must not resolve

Do not write the marker (the autopilot defers the story and moves on) only if:
the fix needs a PRD-level product change that contradicts an explicit
requirement, or it requires credentials/secrets/paid external accounts you do
not have. Still write the ADR, with `Status: deferred — needs human`, and
append it to `_bmad-output/autopilot/HUMAN-TODO.md`.

## Never

- Ask questions, wait for input, or print "let me know".
- Implement the story, write feature code, or run the test suite.
- Touch `sprint-status.yaml`, the spec's `status:` field, or `result.json`.
- Widen scope beyond the escalated ambiguity.
