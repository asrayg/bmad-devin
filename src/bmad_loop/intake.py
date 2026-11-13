"""bmad-devin story intake: `bmad-loop assign "<story>"`.

Turns a rough story (a sentence, a ticket paste, a file of them) into work the
loop can build, with no follow-up questions:

1. a headless `bmad-devin-intake` session files it as a BMAD story the run will
   pick (sprint board row / stories.yaml entry, per the project's story source)
   and opens the matching OpenSpec change (`openspec/changes/<story-key>/`);
2. with `--go`, hands straight to the autopilot to build it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from .resolve import AUTOPILOT_ENV, headless_argv

INTAKE_SKILL = "bmad-devin-intake"


def cmd_assign(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    stories: list[str] = list(args.story or [])
    if args.file:
        stories.append(Path(args.file).read_text(encoding="utf-8"))
    if not args.story and not args.file and not sys.stdin.isatty():
        stories.append(sys.stdin.read())
    stories = [s.strip() for s in stories if s and s.strip()]
    if not stories:
        print("error: give a story: assign \"As a user I want…\" (or --file, or stdin)", file=sys.stderr)
        return 2

    inbox = project / "_bmad-output" / "autopilot" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    from .autopilot import _now

    brief = inbox / f"{_now().replace(':', '')}.md"
    brief.write_text("\n\n---\n\n".join(stories) + "\n", encoding="utf-8")

    env = {**os.environ, AUTOPILOT_ENV: "1", "BMAD_LOOP_MODE": "autopilot", "BMAD_DEVIN_BRIEF": str(brief)}
    argv = headless_argv(f"/{INTAKE_SKILL} {brief}", model=args.model or "")
    print(f"intake: filing {len(stories)} stor{'y' if len(stories) == 1 else 'ies'} from {brief}")
    rc = subprocess.run(argv, cwd=str(project), env=env, stdin=subprocess.DEVNULL).returncode
    if rc != 0:
        print(f"intake session failed (rc={rc})", file=sys.stderr)
        return rc
    if not args.go:
        print("filed. build it with: bmad-loop autopilot")
        return 0
    from .autopilot import Autopilot

    return Autopilot(project=project).drive()


def add_parser(add) -> None:
    p = add(
        "assign",
        cmd_assign,
        "bmad-devin: file a story (BMAD story + OpenSpec change) with no questions; --go builds it",
    )
    p.add_argument("story", nargs="*", help="story text (one or more); or use --file / stdin")
    p.add_argument("--file", help="a markdown/text file with one or more stories")
    p.add_argument("--go", action="store_true", help="start the autopilot right after filing")
    p.add_argument("--model", help="model for the intake session (default: CLI default)")
