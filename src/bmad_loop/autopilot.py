"""bmad-devin autopilot: drive a bmad-loop run to the end with no human input.

The engine stays exactly as upstream wrote it: deterministic, pausing whenever it
would have asked a human. The autopilot is a supervisor *around* it. It runs the
engine, and every time the run pauses it classifies the pause and answers it the
way a delegated tech lead would, then resumes:

=====================  ==========================================================
pause                  autopilot answer
=====================  ==========================================================
escalation             headless ``resolve --resume`` (the ``bmad-devin-autoresolve``
                       skill decides as the architect and writes an ADR)
usage limit            ``resolve --at-reset`` (sleeps to the provider's reset)
spec-approval,         ``resume`` (auto-approve; the ADR trail + OpenSpec change
plan/story checkpoint, are the audit record)
epic-boundary,
story-gate, ticket-*
environment            back off and ``resume`` (probes re-run first)
crashed / stopped      ``resume``
=====================  ==========================================================

When the run finishes, deferred-work decisions a sweep left for a human are
answered with the triage agent's own recommendation (logged to DECISIONS.md) and
one more unattended sweep builds them.

Work that genuinely needs a human (an external action a parked story owes, a
resolution the architect refused) never blocks the run: it is written to
``_bmad-output/autopilot/HUMAN-TODO.md`` and the loop moves on. The autopilot
stops only when the run is finished, when a bound is hit (``--max-cycles``,
repeated failure on the same pause), or on Ctrl+C.

The supervisor talks to the engine only through the public CLI (a subprocess of
this same interpreter) and ``state.json``, so it survives upstream refactors.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import model, runs
from .journal import load_state
from .resolve import AUTOPILOT_ENV

AUTOPILOT_DIR = Path("_bmad-output") / "autopilot"
HUMAN_TODO = "HUMAN-TODO.md"
LOG = "autopilot-log.md"

# Policy keys the autopilot needs so the engine itself pauses as little as possible.
# Applied by `bmad-loop autopilot init` (and checked, not rewritten, on every start).
AUTOPILOT_POLICY: dict[str, dict[str, object]] = {
    "gates": {"mode": "none", "retrospective": "auto"},
    "limits": {"usage_limit_action": "relaunch"},
    "review": {"enabled": True, "trigger": "always", "on_timeout": "salvage-if-done"},
    "scm": {"isolation": "worktree", "rollback_on_failure": True},
    "sweep": {"auto": "run-end"},
}

RESUME_STAGES = frozenset(
    {
        model.PAUSE_SPEC_APPROVAL,
        model.PAUSE_PLAN_CHECKPOINT,
        model.PAUSE_STORY_CHECKPOINT,
        model.PAUSE_EPIC_BOUNDARY,
        model.PAUSE_STORY_GATE,
        model.PAUSE_TICKET_HITL,
        model.PAUSE_TICKET_REFINE,
        model.PAUSE_TICKET_TREE,
    }
)


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Autopilot:
    project: Path
    run_args: list[str] = field(default_factory=list)
    max_cycles: int = 200
    max_same_pause: int = 3
    env_backoff_s: float = 60.0
    dry_run: bool = False
    sweeps_left: int = 2
    _strikes: dict[str, int] = field(default_factory=dict)

    # ---- plumbing -------------------------------------------------------------

    @property
    def out_dir(self) -> Path:
        d = self.project / AUTOPILOT_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def log(self, msg: str) -> None:
        line = f"- {_now()} {msg}"
        print(f"autopilot: {msg}", flush=True)
        with (self.out_dir / LOG).open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def human_todo(self, msg: str) -> None:
        path = self.out_dir / HUMAN_TODO
        if not path.exists():
            path.write_text(
                "# Needs a human (non-blocking)\n\n"
                "The autopilot kept going; these items are waiting for you.\n\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- [ ] {_now()} {msg}\n")
        self.log(f"HUMAN-TODO: {msg}")

    def cli(self, *argv: str) -> int:
        cmd = [sys.executable, "-m", "bmad_loop", *argv, "--project", str(self.project)]
        self.log("$ bmad-loop " + " ".join(argv))
        if self.dry_run:
            return 0
        env = {**os.environ, AUTOPILOT_ENV: "1"}
        return subprocess.run(cmd, cwd=str(self.project), env=env, stdin=subprocess.DEVNULL).returncode

    def latest_state(self) -> tuple[Path, model.RunState] | None:
        run_dir, _fault = runs.latest_run_dir(self.project)
        if run_dir is None or not (run_dir / "state.json").is_file():
            return None
        return run_dir, load_state(run_dir)

    def strike(self, key: str) -> bool:
        """Count one more identical pause; False once the bound is exceeded."""
        self._strikes[key] = self._strikes.get(key, 0) + 1
        return self._strikes[key] <= self.max_same_pause

    # ---- the loop -------------------------------------------------------------

    def drive(self) -> int:
        self.log(f"start (project {self.project})")
        policy_warnings = check_policy(self.project)
        for w in policy_warnings:
            self.log(f"policy: {w} (run `bmad-loop autopilot init` to apply)")
        before = self.latest_state()
        prior_id = before[1].run_id if before else None
        if before and not before[1].finished and (before[1].paused or before[1].stopped or before[1].crashed):
            self.log(f"adopting unfinished run {before[1].run_id}")
        else:
            self.cli("run", *self.run_args)
            after = self.latest_state()
            if after is None or after[1].run_id == prior_id:
                self.log("run did not start (see output above); stopping")
                return 1

        for _cycle in range(self.max_cycles):
            got = self.latest_state()
            if got is None:
                self.log("no run state found; stopping")
                return 1
            run_dir, state = got
            rid = state.run_id
            if state.finished:
                self.after_finish(state)
                self.log(f"run {rid} finished")
                if self.answer_missed_decisions() and self.sweeps_left > 0:
                    # answers were recorded: one more unattended sweep builds them
                    self.sweeps_left -= 1
                    self.cli("sweep", "--no-prompt")
                    continue
                return 0
            if not self.step(rid, state):
                return 2
        self.log(f"--max-cycles {self.max_cycles} reached; stopping")
        return 2

    def step(self, rid: str, state: model.RunState) -> bool:
        """Answer one pause/interruption. False = give up (already logged)."""
        stage = state.paused_stage
        key = f"{stage}:{state.paused_story_key or ''}"
        reason = next(iter((state.paused_reason or "").strip().splitlines()), "")
        if state.paused:
            self.log(f"run {rid} paused [{stage}] {reason}")
        if not self.strike(key):
            self.human_todo(
                f"run `{rid}` keeps pausing at [{stage}] after {self.max_same_pause} autonomous "
                f"attempts — inspect with `bmad-loop status {rid}`; reason: {reason}"
            )
            return False

        if state.paused and state.paused_reset_at:
            self.cli("resolve", rid, "--at-reset")
        elif state.paused and stage == model.PAUSE_ESCALATION:
            rc = self.cli("resolve", rid, "--resume", "--force")
            if rc != 0:
                self.log(f"autoresolve rc={rc}; will retry (strike {self._strikes[key]})")
        elif state.paused and stage == model.PAUSE_ENVIRONMENT:
            delay = self.env_backoff_s * self._strikes[key]
            self.log(f"environment fault — waiting {delay:.0f}s for it to recover")
            if not self.dry_run:
                time.sleep(delay)
            self.cli("resume", rid)
        elif state.paused and stage in RESUME_STAGES:
            self.cli("resume", rid)
        elif state.paused:
            self.log(f"unrecognised pause stage {stage!r}; trying a plain resume")
            self.cli("resume", rid)
        else:
            # stopped, crashed, or an interrupted engine: resume clears all three.
            self.cli("resume", rid)
        return True

    def answer_missed_decisions(self) -> int:
        """Take the triage agent's own recommendation for every deferred-work
        decision a sweep left for a human. Returns how many were answered."""
        from . import bmadconfig, decisions

        try:
            paths = bmadconfig.load_paths(self.project)
            pending = decisions.pending_missed_decisions(self.project, paths)
        except Exception as e:  # never let a ledger read stop the autopilot
            self.log(f"could not read pending decisions: {e}")
            return 0
        answered = 0
        today = time.strftime("%Y-%m-%d")
        for d in pending:
            opt = d.option(d.recommendation) or next(
                (o for o in d.options if o.effect == "keep-open"), None
            )
            if opt is None:
                self.human_todo(f"deferred-work decision {d.id} has no usable option: {d.question}")
                continue
            if self.dry_run:
                self.log(f"would answer {d.id} → {opt.key} ({opt.effect})")
                answered += 1
                continue
            decisions.apply_pre_answer(
                self.project, d, opt, date=today, listed_ledger=paths.deferred_work
            )
            self.record_decision(
                f"deferred-work {d.id}: {d.question} → **{opt.label}** ({opt.effect}; "
                f"triage recommendation)"
            )
            answered += 1
        return answered

    def record_decision(self, line: str) -> None:
        path = self.out_dir / "DECISIONS.md"
        if not path.exists():
            path.write_text("# Autopilot decisions\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"- {_now()} {line}\n")
        self.log(f"decided: {line}")

    def after_finish(self, state: model.RunState) -> None:
        for key, task in state.tasks.items():
            phase = str(task.phase)
            if phase == str(model.Phase.AWAITING_OPERATOR):
                self.human_todo(
                    f"story `{key}` is committed but owes external actions — "
                    f"`bmad-loop confirm --list` then `bmad-loop confirm {key}`"
                )
            elif phase == str(model.Phase.DEFERRED):
                self.human_todo(f"story `{key}` deferred: {task.defer_reason or 'no reason recorded'}")
            elif phase == str(model.Phase.ESCALATED):
                self.human_todo(f"story `{key}` still escalated after autoresolve")


# ---- policy -----------------------------------------------------------------


def check_policy(project: Path) -> list[str]:
    """Which AUTOPILOT_POLICY values the project's policy.toml does not carry."""
    import tomllib

    path = project / ".bmad-loop" / "policy.toml"
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        doc = {}
    out = []
    for section, values in AUTOPILOT_POLICY.items():
        have = doc.get(section, {}) if isinstance(doc.get(section), dict) else {}
        for k, v in values.items():
            if have.get(k) != v:
                out.append(f"[{section}] {k} = {v!r} recommended (is {have.get(k)!r})")
    return out


def apply_policy(project: Path) -> Path:
    """Write AUTOPILOT_POLICY into .bmad-loop/policy.toml, keeping everything else."""
    import tomlkit

    path = project / ".bmad-loop" / "policy.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.is_file() else tomlkit.document()
    for section, values in AUTOPILOT_POLICY.items():
        if section not in doc:
            doc[section] = tomlkit.table()
        for k, v in values.items():
            doc[section][k] = v
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return path


# ---- CLI --------------------------------------------------------------------


def cmd_autopilot(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    if args.action == "init":
        path = apply_policy(project)
        print(f"autopilot policy applied to {path}")
        for line in check_policy(project):
            print(f"  still differs: {line}")
        return 0
    os.environ[AUTOPILOT_ENV] = "1"
    pilot = Autopilot(
        project=project,
        run_args=[a for a in (args.run_args or []) if a != "--"],
        max_cycles=args.max_cycles,
        max_same_pause=args.max_same_pause,
        env_backoff_s=args.env_backoff,
        dry_run=args.dry_run,
    )
    try:
        return pilot.drive()
    except KeyboardInterrupt:
        pilot.log("interrupted by operator")
        return 130


def add_parser(add) -> None:
    """Register `bmad-loop autopilot` on the main CLI (`add` is cli.main's helper)."""
    p = add(
        "autopilot",
        cmd_autopilot,
        "bmad-devin: run the dev loop to completion with no human input "
        "(auto-resolves escalations, auto-approves gates, parks human-only work)",
    )
    p.add_argument(
        "action",
        nargs="?",
        choices=("run", "init"),
        default="run",
        help="run (default): drive a run to completion · init: apply the autopilot policy",
    )
    p.add_argument("--max-cycles", type=int, default=200, help="pause/resume cycles before giving up")
    p.add_argument(
        "--max-same-pause",
        type=int,
        default=3,
        help="autonomous attempts at one identical pause before parking it for a human",
    )
    p.add_argument("--env-backoff", type=float, default=60.0, help="seconds × strike to wait on env faults")
    p.add_argument("--dry-run", action="store_true", help="print the CLI calls without running them")
    p.add_argument(
        "run_args",
        nargs=argparse.REMAINDER,
        help="arguments after `--` are passed to `bmad-loop run` (e.g. -- --epic 2)",
    )
