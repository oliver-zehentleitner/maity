"""The sandbox probe's own parts that need no model: the runner's settings it starts from, its
variants, reading a run, and its verdicts against a fake `claude` without any sandbox, which
must fail the steps a real sandbox passes (cli/tests/claude_sandbox_probe.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import claude_sandbox_probe as probe
import pytest

FAKE = """#!{python}
import json, re, subprocess, sys
args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.326 (Claude Code)")
    sys.exit(0)
prompt = args[args.index("-p") + 1]
kind, target = re.search(r"<(command|read|write)>(.*?)</\\1>", prompt, re.S).groups()
print(json.dumps({{"type": "system", "subtype": "init"}}))
if "{mode}" == "idle":
    print(json.dumps({{"type": "result", "result": "DONE"}}))
    sys.exit(0)
if kind == "command":
    use = {{"name": "Bash", "input": {{"command": target}}}}
    if "{mode}" == "refuse":
        out, err = "Permission to use Bash has been denied.", True
    else:
        done = subprocess.run(["sh", "-c", target], capture_output=True, text=True)
        out, err = done.stdout + done.stderr, done.returncode != 0
elif kind == "read":
    use = {{"name": "Read", "input": {{"file_path": target}}}}
    out, err = open(target).read(), False
else:
    use = {{"name": "Write", "input": {{"file_path": target, "content": "probe"}}}}
    open(target, "w").write("probe")
    out, err = "written", False
print(json.dumps({{"type": "assistant", "message": {{"content": [
    {{"type": "tool_use", "id": "t1", **use}}]}}}}))
print(json.dumps({{"type": "user", "message": {{"content": [
    {{"type": "tool_result", "tool_use_id": "t1", "content": out, "is_error": err}}]}}}}))
print(json.dumps({{"type": "result", "result": "DONE"}}))
"""


def fake(tmp_path: Path, mode: str = "obey") -> str:
    """A `claude` that makes the asked call itself, unsandboxed and without hooks (`obey`),
    refuses it (`refuse`) or makes none (`idle`)."""
    path = tmp_path / f"claude-{mode}"
    path.write_text(FAKE.format(python=sys.executable, mode=mode))
    path.chmod(0o755)
    return str(path)


def outcomes(output: str) -> dict[str, str]:
    """Step id to status, from the probe's printed lines."""
    found = {}
    for line in output.splitlines():
        words = line.split()
        if words and words[0] in ("PASS", "FAIL", "SKIP", "INCONCLUSIVE"):
            found[words[1]] = words[0]
    return found


def test_steps_cover_the_four_points_once_each() -> None:
    ids = [step.id for step in probe.steps()]
    assert len(ids) == len(set(ids))
    assert {i.split(".")[0] for i in ids} == {"1a", "1b", "2", "3", "4"}
    variants = {step.variant for step in probe.steps()}
    assert variants == {"runner", "open", "detector", "hook-module", "hook-exit1", "hook-timeout"}


def test_the_world_starts_from_the_runners_own_launch(tmp_path: Path) -> None:
    world = probe.build(tmp_path, "/usr/bin/claude")
    assert world.base[0] == "/usr/bin/claude" and "-p" not in world.base
    assert world.base[world.base.index("--permission-mode") + 1] == "dontAsk"
    sandbox = world.settings["sandbox"]
    assert sandbox["enabled"] and sandbox["failIfUnavailable"]
    assert sandbox["excludedCommands"] == ["maity *"]
    assert str(world.cred.parent) in sandbox["filesystem"]["denyRead"]
    assert str(world.other.parent) in sandbox["filesystem"]["denyRead"]  # the other clone's
    hook = world.settings["hooks"]["PreToolUse"][0]["hooks"][0]
    assert probe.PLAINCALL in hook["command"] and hook["onFailure"] == "block"
    assert world.settings["disableAllHooks"] is False
    assert world.env["GIT_COMMON_DIR"] == str(world.clone / ".git")
    assert world.env["PATH"].split(":")[0] == str(world.stub)
    assert world.secret not in (world.stub / "maity").read_text()


def test_variants_change_only_what_they_name(tmp_path: Path) -> None:
    world = probe.build(tmp_path, "/usr/bin/claude")
    marker = tmp_path / "hook-marker"
    base = world.settings
    assert probe.variant_settings(base, "runner", marker) == base
    opened = probe.variant_settings(base, "open", marker)
    assert opened["permissions"]["allow"] == ["Bash", *base["permissions"]["allow"]]
    assert opened["hooks"] == base["hooks"] and opened["sandbox"] == base["sandbox"]
    detector = probe.variant_settings(base, "detector", marker)
    assert detector["hooks"]["PreToolUse"][0] == base["hooks"]["PreToolUse"][0]
    assert str(marker) in detector["hooks"]["PreToolUse"][1]["hooks"][0]["command"]
    assert detector["permissions"] == base["permissions"]

    def runner_hook(variant: str) -> dict[str, object]:
        hook: dict[str, object] = probe.variant_settings(base, variant, marker)["hooks"][
            "PreToolUse"
        ][0]["hooks"][0]
        return hook

    assert "plaincall_absent" in str(runner_hook("hook-module")["command"])
    assert str(runner_hook("hook-module")["command"]).endswith("|| exit 2")
    assert runner_hook("hook-exit1")["command"] == "exit 1"
    assert runner_hook("hook-timeout")["timeout"] == probe.HOOK_TIMEOUT
    assert all(runner_hook(v)["onFailure"] == "block" for v in ("hook-exit1", "hook-timeout"))
    assert base["hooks"]["PreToolUse"][0]["hooks"][0]["command"] != "exit 1"  # not changed
    with pytest.raises(ValueError):
        probe.variant_settings(base, "nope", marker)


def test_a_stream_is_read_into_calls_with_their_results() -> None:
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "running it"},
            {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "a", "is_error": True,
             "content": [{"type": "text", "text": "denied"}]}]}},
    ]  # fmt: skip
    text = "\n".join(json.dumps(e) for e in events) + "\nnot json\n"
    calls = probe.parse_stream(text)
    assert calls == [probe.Call("Bash", {"command": "ls"}, "denied", True)]
    step = probe.Step("x", "x", "Bash", "ls", "runner", "refused")
    assert probe.complied(step, "ls", calls) and probe.complied(step, " ls ", calls)
    assert not probe.complied(step, "ls -a", calls)
    assert not probe.complied(step, "ls", [*calls, *calls])


def test_steps_are_chosen_by_point_part_or_id() -> None:
    steps = probe.steps()
    assert {s.id.split(".")[0] for s in probe.selected(steps, "1")} == {"1a", "1b"}
    assert {s.id.split(".")[0] for s in probe.selected(steps, "1b")} == {"1b"}
    assert [s.id for s in probe.selected(steps, "4.10,2.1")] == ["2.1", "4.10"]
    assert probe.selected(steps, None) == steps


def test_a_harness_without_a_sandbox_fails_the_probe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counter-check: the fake runs every call as itself, as a harness without a sandbox
    would. The controls and git pass; the prefixed call and the credential read fail."""
    only = "1a.1,1a.2,1b.6,4.2,4.3,4.6,4.8,4.9,4.10"
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", only])
    found = outcomes(capsys.readouterr().out)
    assert code == 1
    assert found == {
        "1a.1": "PASS", "1a.2": "FAIL", "1b.6": "FAIL", "4.2": "FAIL", "4.3": "FAIL",
        "4.6": "FAIL", "4.8": "FAIL", "4.9": "PASS", "4.10": "PASS",
    }  # fmt: skip


def test_a_harness_that_refuses_everything_passes_containment_but_not_the_controls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = probe.main(["--claude", fake(tmp_path, "refuse"), "--no-preflight",
                       "--only", "1a.1,1a.2,2.2"])  # fmt: skip
    found = outcomes(capsys.readouterr().out)
    assert code == 1 and found == {"1a.1": "FAIL", "1a.2": "PASS", "2.2": "PASS"}


def test_a_model_that_makes_no_call_is_inconclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = probe.main(["--claude", fake(tmp_path, "idle"), "--no-preflight", "--only", "1a.2"])
    out = capsys.readouterr().out
    assert code == 1 and outcomes(out) == {"1a.2": "INCONCLUSIVE"}
    assert "did not make exactly the call" in out


def test_point_three_is_skipped_without_its_flags(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing outside the scratch directory changes unless the operator asks for it."""
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "3.2,3.4,3.5"])
    out = capsys.readouterr().out
    assert code == 0 and outcomes(out) == {"3.2": "SKIP", "3.4": "SKIP", "3.5": "SKIP"}
    assert "needs --managed" in out and "needs --user-settings" in out
    assert "summary: 0 PASS, 0 FAIL, 3 SKIP, 0 INCONCLUSIVE" in out


def test_the_user_settings_are_put_back(tmp_path: Path) -> None:
    user = probe.user_settings()
    assert user.is_relative_to(tmp_path)  # the test's own home (conftest)
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"theme": "dark"}')
    with probe.changed("user:disableAllHooks"):
        assert json.loads(user.read_text()) == {"theme": "dark", "disableAllHooks": True}
    assert user.read_text() == '{"theme": "dark"}'
    with probe.changed("user:allowManagedHooksOnly"):
        user.unlink()
        user.write_text("{}")
    assert user.read_text() == '{"theme": "dark"}'


def test_the_exit_code_counts_fail_and_inconclusive_only() -> None:
    o = probe.Outcome
    assert probe.exit_code([o("PASS", ""), o("SKIP", "")]) == 0
    assert probe.exit_code([o("PASS", ""), o("FAIL", "")]) == 1
    assert probe.exit_code([o("INCONCLUSIVE", "")]) == 1


def test_the_runners_hook_refuses_every_prefixed_call_the_probe_makes(tmp_path: Path) -> None:
    """1b keeps the runner's hook: each prefixed call must be refused by it before the
    sandbox is asked, and the plain call must pass it."""
    from maity.runner import plaincall

    world = probe.build(tmp_path, "/usr/bin/claude")
    for step in probe.steps():
        if step.tool != "Bash" or step.id.split(".")[0] not in ("1a", "1b"):
            continue
        payload = {"tool_name": "Bash", "tool_input": {"command": world.fill(step.target, "t")}}
        refused = plaincall.refusal(payload)
        assert (refused is None) == (step.expect == "escapes"), step.id
