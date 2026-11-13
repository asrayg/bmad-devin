"""bmad-devin OpenSpec plugin — see plugin.toml for the contract."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from bmad_loop.plugins.model import Plugin, PluginError

DEV_ADDENDUM = """

## OpenSpec contract (bmad-devin)
This project uses OpenSpec. The change for this story lives at
`openspec/changes/{key}/` (proposal.md, tasks.md, specs/<capability>/spec.md).
1. If that folder is missing, create it FIRST from the story's acceptance criteria:
   proposal (Why / What Changes / Impact), a `- [ ]` tasks checklist (tests first),
   and a spec delta with `## ADDED|MODIFIED Requirements`, each `### Requirement:`
   carrying at least one `#### Scenario:` (WHEN/THEN). Read `openspec/specs/` for
   the capability's current requirements before writing the delta.
2. Implement against the scenarios: every scenario gets an automated test.
3. Tick `tasks.md` items as you complete them.
4. If the CLI exists, `openspec validate {key} --strict` must pass before you finish.
Do NOT run `openspec archive` — the orchestrator archives at commit time.
"""

REVIEW_ADDENDUM = """

## OpenSpec check (bmad-devin)
Read `openspec/changes/{key}/`. Flag as a finding: any `#### Scenario:` with no
test exercising it, any behaviour the code adds that no requirement describes,
and any unticked task in tasks.md that the diff claims to have done.
"""


class OpenSpecPlugin(Plugin):
    fail_closed = False

    def validate(self, policy: Any) -> None:
        if self.settings.get("require_cli") and shutil.which("openspec") is None:
            raise PluginError(
                "plugin 'openspec': the `openspec` CLI is not on PATH — "
                "`npm i -g @fission-ai/openspec`, or set require_cli = false "
                "under [plugins.openspec]."
            )

    def on_pre_dev_session(self, ctx) -> None:
        if ctx.story_key and ctx.proposed_prompt is not None:
            ctx.proposed_prompt = ctx.proposed_prompt + DEV_ADDENDUM.format(key=ctx.story_key)

    def on_pre_review_session(self, ctx) -> None:
        if ctx.story_key and ctx.proposed_prompt is not None:
            ctx.proposed_prompt = ctx.proposed_prompt + REVIEW_ADDENDUM.format(key=ctx.story_key)

    def on_pre_commit(self, ctx) -> None:
        if not self.settings.get("archive_on_commit", True) or not ctx.story_key:
            return
        root = Path(ctx.worktree or ctx.repo_root or ".")
        change = root / "openspec" / "changes" / ctx.story_key
        if not change.is_dir():
            ctx.shared.setdefault("openspec", {})[ctx.story_key] = "no change folder"
            return
        cli = shutil.which("openspec")
        if cli is None:
            ctx.shared.setdefault("openspec", {})[ctx.story_key] = "cli missing; not archived"
            return
        proc = subprocess.run(
            [cli, "archive", ctx.story_key, "--yes"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=300,
            stdin=subprocess.DEVNULL,
        )
        outcome = "archived" if proc.returncode == 0 else f"archive failed rc={proc.returncode}"
        ctx.shared.setdefault("openspec", {})[ctx.story_key] = outcome
