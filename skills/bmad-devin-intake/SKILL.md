---
name: bmad-devin-intake
description: 'Headless story intake for bmad-devin. Takes a brief file of rough stories and, with no questions, files each as a BMAD story the bmad-loop run will pick up plus an OpenSpec change proposal. Invoked as /bmad-devin-intake <brief-path>.'
---

# bmad-devin Story Intake

No human is present (`$BMAD_LOOP_MODE=autopilot`). Never ask; decide and record
assumptions. Input: the brief file passed as your argument (also
`$BMAD_DEVIN_BRIEF`). It holds one or more rough stories separated by `---`.

## 1. Learn the project

- Read `.bmad-loop/policy.toml` → `[stories] source`
  (`sprint-status` default · `stories` · `tickets`) and `spec_folder`.
- Read `_bmad/` config to locate planning artifacts (PRD, architecture, epics)
  and `sprint-status.yaml`.
- If an `openspec/` directory is missing and the `openspec` CLI is available,
  run `openspec init --tools none` (non-interactive). Read `openspec/specs/` for
  existing capabilities.

If no BMAD planning exists at all, create the minimum the loop needs:
`_bmad-output/planning-artifacts/epics.md` with one epic
`Epic N: Autopilot backlog` and a `sprint-status.yaml` per BMAD conventions.

## 2. For each story in the brief

1. **Shape it** into a BMAD story: `As a … I want … so that …`, 3–7
   testable acceptance criteria in Given/When/Then, and explicit
   out-of-scope lines. Fill gaps with the least-surprising assumption and list
   every assumption under `### Assumptions (autopilot)`.
2. **Split** anything bigger than ~1 day of focused work into several stories.
3. **Key** it per BMAD (`<epic>-<n>-<kebab-title>`), appended to the current
   last epic (or the autopilot backlog epic).
4. **File it where the run picks it up**:
   - `sprint-status`: add the story under its epic in `epics.md` and its row in
     `sprint-status.yaml` as `ready-for-dev` (prefer the installed
     `bmad-create-story` skill to write the story file if it runs headless;
     otherwise write the story file yourself in the implementation-artifacts
     folder using BMAD's story template).
   - `stories`: append an entry to `<spec_folder>/stories.yaml`
     (`id`, `title`, `description`, `spec_checkpoint: false`,
     `done_checkpoint: false`, `invoke_dev_with`).
   - `tickets`: add a ticket via the project's `tickets.py` the way
     `bmad-agent-po` would, status ready to build.
5. **Open the OpenSpec change** `openspec/changes/<story-key>/`:
   - `proposal.md` — Why / What Changes / Impact.
   - `tasks.md` — a numbered `- [ ]` checklist implementing the ACs (tests first).
   - `specs/<capability>/spec.md` — `## ADDED|MODIFIED Requirements`, each
     `### Requirement:` with at least one `#### Scenario:` mirroring an AC.
   Run `openspec validate <story-key> --strict` if the CLI exists; fix until it
   passes.
6. In the story's dev notes add:
   `OpenSpec change: openspec/changes/<story-key>/ — the spec delta is the contract.`

## 3. Report

Append to `_bmad-output/autopilot/autopilot-log.md` one line per filed story
(`- <UTC> intake: <story-key> — <title>`). Print the keys. Do not implement any
story and do not commit; the autopilot run commits with the story.
