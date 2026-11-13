"""Run Pullo on the story's uncommitted work, without touching index or tree.

usage: python3 -I pullo_gate.py <story-key> [--base REF]

Snapshots the working tree (tracked + untracked, respecting .gitignore) into a
throwaway commit built on a private index file, points `refs/bmad-devin/pullo/<key>`
at it, runs `pullo_review.py review <snapshot> --base <base>`, and copies the
result to `_bmad-output/autopilot/pullo/<key>.{md,json}`. Prints the markdown path.
Pullo itself is NOT bundled (it carries no license); install it per its README:
  cp -r integrations/claude-code/skills/pullo-review ~/.claude/skills/
or point $PULLO_REVIEW_SCRIPT at pullo_review.py.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_SCRIPT = Path.home() / ".claude" / "skills" / "pullo-review" / "scripts" / "pullo_review.py"


def git(*args: str, env: dict | None = None) -> str:
    # LC_ALL=C + a timeout, mirroring bmad_loop.verify._run_git (not importable here).
    env = {**(env or os.environ), "LC_ALL": "C"}
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True, env=env, timeout=120
    ).stdout.strip()


def snapshot(key: str) -> str:
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}
        git("read-tree", "HEAD", env=env)
        git("add", "-A", env=env)
        tree = git("write-tree", env=env)
    sha = git("commit-tree", tree, "-p", "HEAD", "-m", f"bmad-devin pullo snapshot {key}")
    git("update-ref", f"refs/bmad-devin/pullo/{key}", sha)
    return sha


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("story_key")
    ap.add_argument("--base", help="base ref (default: merge-base with the default branch, else HEAD)")
    a = ap.parse_args()

    script = Path(os.environ.get("PULLO_REVIEW_SCRIPT") or DEFAULT_SCRIPT)
    if not script.is_file():
        print(f"PULLO_MISSING: {script} not found — install Pullo's pullo-review skill", file=sys.stderr)
        return 3
    base = a.base
    if not base:
        for cand in ("origin/HEAD", "main", "master"):
            try:
                base = git("merge-base", "HEAD", cand)
                break
            except subprocess.CalledProcessError:
                continue
        base = base or git("rev-parse", "HEAD")
    snap = snapshot(a.story_key)
    if git("rev-parse", f"{snap}^{{tree}}") == git("rev-parse", f"{base}^{{tree}}"):
        print("PULLO_EMPTY: no changes against base")
        return 0

    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(
            [sys.executable, "-I", str(script), "review", snap, "--base", base, "--repo", ".", "--out", out],
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            print(f"PULLO_FAILED rc={proc.returncode}", file=sys.stderr)
            return proc.returncode
        runs = sorted(Path(out).glob("*/review.md"))
        if not runs:
            print("PULLO_FAILED: no review.md produced", file=sys.stderr)
            return 4
        dest = Path("_bmad-output") / "autopilot" / "pullo"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(runs[-1], dest / f"{a.story_key}.md")
        if (runs[-1].parent / "review.json").is_file():
            shutil.copy(runs[-1].parent / "review.json", dest / f"{a.story_key}.json")
    print(dest / f"{a.story_key}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
