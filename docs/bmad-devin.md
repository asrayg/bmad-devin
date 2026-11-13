# bmad-devin: assign stories, get commits, no questions

bmad-devin is a fork of [bmad-loop](https://github.com/bmad-code-org/bmad-loop) that
combines three tools into one unattended, agile, story-driven coding agent:

| Piece | Source | What it does here |
| --- | --- | --- |
| **BMAD** | [bmad-loop](https://github.com/bmad-code-org/bmad-loop) + [BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | Story board, a fresh-context dev session per story, adversarial review, your tests, one commit per story |
| **OpenSpec** | [Fission-AI/OpenSpec](https://github.com/Fission-AI/OpenSpec) | One change proposal per story (proposal, tasks, spec delta). It is the contract dev and review work against, and it is archived into `openspec/specs/` in the story's own commit |
| **Pullo** | [arj873/Pullo](https://github.com/arj873/Pullo) | Consensus PR review (Opus, confirmed by two Sonnet witnesses) on the exact tree about to commit. Confirmed findings are fixed before the commit |
| **Autopilot** | new in this fork | Answers every pause the engine would have put to a human |

```
assign "story" ─▶ intake (BMAD story + OpenSpec change)
                     │
autopilot ─▶ bmad-loop run ─▶ pick story ─▶ dev (OpenSpec contract) ─▶ review (+ scenario coverage)
                     ▲                    ─▶ verify ─▶ Pullo gate (review → fix → re-review)
                     │                    ─▶ openspec archive ─▶ commit ─▶ next story
                     │
            pause? ──┴─ escalation  → headless architect resolves + writes ADR → resume
                        gates/checkpoints → auto-approve → resume
                        usage limit → wait for reset → resume
                        env fault → back off → resume
                        same pause 3× / human-only work → HUMAN-TODO.md, keep going
```

## Setup

```sh
# 1. the orchestrator (this fork)
uv tool install git+https://github.com/asrayg/bmad-devin

# 2. BMAD in your project (the dev primitive bmad-build-auto ships with it)
npx bmad-method install

# 3. OpenSpec CLI (optional but recommended)
npm i -g @fission-ai/openspec && openspec init --tools none

# 4. Pullo (not bundled: it has no license, so install it yourself)
git clone https://github.com/arj873/Pullo ~/src/Pullo
cp -r ~/src/Pullo/integrations/claude-code/skills/pullo-review ~/.claude/skills/

# 5. wire the project
cd your-project
bmad-loop init                 # hooks + skills (incl. bmad-devin-autoresolve, -intake)
bmad-loop autopilot init       # policy: no approval gates, worktrees, relaunch on limits, auto sweep
```

Enable the plugins in `.bmad-loop/policy.toml`:

```toml
[plugins]
enabled = ["openspec", "pullo"]
```

## Use

```sh
bmad-loop assign "As a user I want to export my notes as markdown"   # file it
bmad-loop assign --file backlog.md --go                               # file several and build
bmad-loop autopilot                                                   # build everything ready
bmad-loop autopilot -- --epic 2                                       # args after -- go to `run`
```

Afterwards, check:

- `_bmad-output/autopilot/DECISIONS.md` and `decisions/*.md`: every call the autopilot made instead of you, written as ADRs with "how to reverse" notes
- `_bmad-output/autopilot/HUMAN-TODO.md`: work that truly needs a person (external accounts, PRD-level conflicts). It never blocks the run
- `_bmad-output/autopilot/pullo/<story>.md`: Pullo's findings and what was fixed or rejected
- `_bmad-output/autopilot/autopilot-log.md`: every pause and how the autopilot answered it
- `openspec/specs/`: the living spec, updated by each story's archived change

## How "never ask" is enforced

- **Engine:** gates are set to `none`, usage limits relaunch, and reviews salvage on timeout.
- **Escalations:** with `BMAD_DEVIN_AUTOPILOT=1`, `bmad-loop resolve` runs the headless
  `bmad-devin-autoresolve` skill instead of an interactive chat. It decides by precedence
  (PRD/architecture/OpenSpec first, then earlier decisions, then the smallest reversible option,
  then the conventional default), edits the frozen spec, writes an ADR and the resolution
  marker, and the run resumes.
- **Override the headless CLI** with `BMAD_DEVIN_HEADLESS_CMD`. The default is
  `claude -p --permission-mode bypassPermissions`.
- **Bounded:** after `--max-same-pause` (default 3) identical pauses, the autopilot records
  the item in HUMAN-TODO and stops instead of looping forever.

## Safety

The autopilot runs agents with permission bypass and commits to your repo. Keep
`[scm] isolation = "worktree"` (the autopilot policy sets it), point it at a repo you can
roll back, and review the ADR trail.
