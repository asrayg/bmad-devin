"""bmad-devin additions: autopilot supervisor, headless resolve, plugins."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bmad_loop import autopilot, model, resolve
from bmad_loop.plugins import loader

PLUGINS = Path(autopilot.__file__).parent / "data" / "plugins"


def _state(**kw):
    base = dict(
        run_id="r1",
        finished=False,
        paused=True,
        stopped=False,
        crashed=False,
        paused_stage=None,
        paused_story_key=None,
        paused_reason="why",
        paused_reset_at=None,
        tasks={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    calls: list[tuple[str, ...]] = []
    p = autopilot.Autopilot(project=tmp_path, env_backoff_s=0)
    monkeypatch.setattr(p, "cli", lambda *a: calls.append(a) or 0)
    p.calls = calls  # type: ignore[attr-defined]
    return p


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        (model.PAUSE_ESCALATION, ("resolve", "r1", "--resume", "--force")),
        (model.PAUSE_SPEC_APPROVAL, ("resume", "r1")),
        (model.PAUSE_EPIC_BOUNDARY, ("resume", "r1")),
        (model.PAUSE_PLAN_CHECKPOINT, ("resume", "r1")),
        (model.PAUSE_ENVIRONMENT, ("resume", "r1")),
        ("something-new", ("resume", "r1")),
    ],
)
def test_step_answers_each_pause(pilot, stage, expected):
    assert pilot.step("r1", _state(paused_stage=stage, paused_story_key="1-1-x"))
    assert pilot.calls == [expected]


def test_usage_limit_waits_for_reset(pilot):
    pilot.step("r1", _state(paused_stage=model.PAUSE_ESCALATION, paused_reset_at="2026-11-14T00:00:00Z"))
    assert pilot.calls == [("resolve", "r1", "--at-reset")]


def test_crashed_run_is_resumed(pilot):
    pilot.step("r1", _state(paused=False, crashed=True))
    assert pilot.calls == [("resume", "r1")]


def test_repeated_identical_pause_parks_for_human(pilot):
    s = _state(paused_stage=model.PAUSE_ESCALATION, paused_story_key="1-1-x")
    assert all(pilot.step("r1", s) for _ in range(pilot.max_same_pause))
    assert pilot.step("r1", s) is False
    todo = (pilot.project / autopilot.AUTOPILOT_DIR / autopilot.HUMAN_TODO).read_text()
    assert "keeps pausing at [escalation]" in todo


def test_after_finish_lists_human_work(pilot):
    tasks = {
        "a": SimpleNamespace(phase=model.Phase.AWAITING_OPERATOR, defer_reason=None),
        "b": SimpleNamespace(phase=model.Phase.DEFERRED, defer_reason="plateau"),
        "c": SimpleNamespace(phase=model.Phase.DONE, defer_reason=None),
    }
    pilot.after_finish(_state(finished=True, tasks=tasks))
    todo = (pilot.project / autopilot.AUTOPILOT_DIR / autopilot.HUMAN_TODO).read_text()
    assert "`a`" in todo and "plateau" in todo and "`c`" not in todo


def test_policy_apply_keeps_existing_and_satisfies_check(tmp_path):
    pol = tmp_path / ".bmad-loop" / "policy.toml"
    pol.parent.mkdir()
    pol.write_text('# mine\n[plugins]\nenabled = ["pullo"]\n[gates]\nmode = "per-epic"\n')
    assert autopilot.check_policy(tmp_path)
    autopilot.apply_policy(tmp_path)
    assert autopilot.check_policy(tmp_path) == []
    text = pol.read_text()
    assert "# mine" in text and 'enabled = ["pullo"]' in text
    from bmad_loop import policy

    assert policy.load(pol).gates.mode == "none"


def test_headless_resolve_runs_autoresolve_skill(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    marker = resolve.resolution_path(run_dir, "1-1-x")
    fake = tmp_path / "fake_cli.py"
    fake.write_text(
        "import json,os,sys,pathlib\n"
        "p=pathlib.Path(os.environ['BMAD_LOOP_RUN_DIR'])/'resolve'/os.environ['BMAD_LOOP_STORY_KEY']\n"
        "p.mkdir(parents=True,exist_ok=True)\n"
        "(p/'resolution.json').write_text(json.dumps({'prompt':sys.argv[-1],'mode':os.environ['BMAD_LOOP_MODE']}))\n"
    )
    monkeypatch.setenv(resolve.AUTOPILOT_ENV, "1")
    monkeypatch.setenv(resolve.HEADLESS_CMD_ENV, f"{sys.executable} {fake}")
    adapter = SimpleNamespace(interactive_argv=lambda spec: pytest.fail("interactive path taken"))
    assert resolve.run_session(adapter, tmp_path, run_dir, "1-1-x", generation=0)
    got = json.loads(marker.read_text())
    assert got == {"prompt": "/bmad-devin-autoresolve 1-1-x", "mode": "autopilot"}


def test_headless_argv_adds_model_for_claude(monkeypatch):
    monkeypatch.delenv(resolve.HEADLESS_CMD_ENV, raising=False)
    argv = resolve.headless_argv("/x", model="opus")
    assert argv[0] == "claude" and argv[-3:] == ["--model", "opus", "/x"]


def test_plugins_discovered_with_python_gate():
    found = {m.name: m for m in loader.discover()}
    assert {"openspec", "pullo"} <= found.keys()
    assert [w.name for w in found["pullo"].workflows] == ["pullo"]


def test_pullo_gate_snapshot_leaves_tree_and_index_alone(tmp_path):
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    git("init", "-q", "-b", "main")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "base")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "staged.py").write_text("y = 2\n")
    git("add", "staged.py")
    status_before = git("status", "--porcelain")

    fake = tmp_path.parent / "fake_pullo.py"
    fake.write_text(
        "import sys,pathlib,subprocess\n"
        "a=sys.argv; out=pathlib.Path(a[a.index('--out')+1])/'lbl-1'; out.mkdir(parents=True)\n"
        "d=subprocess.run(['git','diff','--name-only',a[a.index('--base')+1]+'...'+a[2]],capture_output=True,text=True).stdout\n"
        "(out/'review.md').write_text('files:'+d)\n"
    )
    env = {**os.environ, "PULLO_REVIEW_SCRIPT": str(fake), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    proc = subprocess.run(
        [sys.executable, str(PLUGINS / "pullo" / "pullo_gate.py"), "1-1-x", "--base", "HEAD"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    report = (tmp_path / "_bmad-output/autopilot/pullo/1-1-x.md").read_text()
    assert "a.py" in report and "staged.py" in report
    # the only new thing is the report itself; index and tracked state unchanged
    after = [l for l in git("status", "--porcelain").splitlines() if "_bmad-output" not in l]
    assert after == status_before.splitlines()


def test_missed_decisions_take_triage_recommendation(pilot, monkeypatch):
    from bmad_loop import bmadconfig, decisions
    from bmad_loop.sweep import Decision, DecisionOption

    d = Decision(
        id="DW-7",
        question="Cache invalidation?",
        context="",
        options=(
            DecisionOption("a", "Build it", "build", intent="add ttl"),
            DecisionOption("b", "Leave open", "keep-open"),
        ),
        recommendation="a",
    )
    applied = []
    monkeypatch.setattr(bmadconfig, "load_paths", lambda p: SimpleNamespace(deferred_work=p / "dw.md"))
    monkeypatch.setattr(decisions, "pending_missed_decisions", lambda p, paths: [d])
    monkeypatch.setattr(decisions, "apply_pre_answer", lambda p, dec, opt, **kw: applied.append(opt.key))
    assert pilot.answer_missed_decisions() == 1
    assert applied == ["a"]
    log = (pilot.project / autopilot.AUTOPILOT_DIR / "DECISIONS.md").read_text()
    assert "DW-7" in log and "Build it" in log
