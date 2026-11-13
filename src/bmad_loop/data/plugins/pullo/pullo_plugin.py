"""bmad-devin Pullo plugin: readiness check + commit-message trailer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from bmad_loop.plugins.model import Plugin, PluginError

DEFAULT_SCRIPT = Path.home() / ".claude" / "skills" / "pullo-review" / "scripts" / "pullo_review.py"


def _script() -> Path:
    return Path(os.environ.get("PULLO_REVIEW_SCRIPT") or DEFAULT_SCRIPT)


class PulloPlugin(Plugin):
    fail_closed = False

    def validate(self, policy: Any) -> None:
        if self.settings.get("require_pullo") and not _script().is_file():
            raise PluginError(
                f"plugin 'pullo': {_script()} not found. Install Pullo's pullo-review skill "
                "(see https://github.com/arj873/Pullo) or set PULLO_REVIEW_SCRIPT, or set "
                "require_pullo = false under [plugins.pullo]."
            )

    def on_pre_commit(self, ctx) -> None:
        if not ctx.story_key or not ctx.proposed_commit_message:
            return
        root = Path(ctx.worktree or ctx.repo_root or ".")
        report = root / "_bmad-output" / "autopilot" / "pullo" / f"{ctx.story_key}.md"
        if report.is_file():
            ctx.proposed_commit_message = (
                ctx.proposed_commit_message.rstrip()
                + f"\n\nReviewed-by: Pullo consensus review (_bmad-output/autopilot/pullo/{ctx.story_key}.md)"
            )
