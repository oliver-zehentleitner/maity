"""The sandbox probe's own parts that need no model: the runner's settings it starts from, its
variants, reading a run, and its verdicts against a fake `claude` without any sandbox, which
must fail the steps a real sandbox passes (cli/tests/claude_sandbox_probe.py)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import claude_sandbox_probe as probe
import pytest

FAKE = """#!{python}
import json, os, re, subprocess, sys
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
    elif "{mode}" == "sandbox":  # the credential directory hidden and unwritable, as inside
        os.rename(".git/maity", ".git/maity-hidden")
        open(".git/maity", "w").close()
        try:
            done = subprocess.run(["sh", "-c", target], capture_output=True, text=True)
        finally:
            os.remove(".git/maity")
            os.rename(".git/maity-hidden", ".git/maity")
        out, err = done.stdout + done.stderr, done.returncode != 0
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
    """A `claude` that makes the asked call itself, unsandboxed and without hooks (`obey`), or
    with the clone's credential directory hidden and unwritable, as the sandbox has it
    (`sandbox`, for Bash only), refuses it (`refuse`) or makes none (`idle`)."""
    path = tmp_path / f"claude-{mode}"
    path.write_text(FAKE.format(python=sys.executable, mode=mode))
    path.chmod(0o755)
    return str(path)


def outcomes(output: str) -> dict[str, str]:
    """Step id to status, from the probe's printed lines."""
    found = {}
    for line in output.splitlines():
        words = line.split()
        if words and words[0] in ("PASS", "FAIL", "SKIP", "INCONCLUSIVE", "NOT-TESTABLE"):
            found[words[1]] = words[0]
    return found


@pytest.fixture
def short() -> Iterator[Path]:
    """A scratch root short enough that the placement's TMPDIR fits a Unix socket, as the
    probe's own under /tmp does; pytest's tmp_path may be too long for it."""
    root = Path(tempfile.mkdtemp(prefix="mp-", dir="/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_steps_cover_the_four_points_once_each() -> None:
    ids = [step.id for step in probe.steps()]
    assert len(ids) == len(set(ids))
    assert {i.split(".")[0] for i in ids} == {"1a", "1b", "2", "3", "4"}
    titles = {step.title for step in probe.steps() if step.expect == "refused"}
    assert {"hook refuses: MAITY_WAIT_TIMEOUT in front", "hook refuses: maity runner"} <= titles
    variants = {step.variant for step in probe.steps()}
    assert variants == {"runner", "open", "detector", "hook-module", "hook-exit1", "hook-timeout"}


def test_the_world_starts_from_the_runners_own_launch(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
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


def test_the_world_is_started_as_the_supervisor_starts_a_placement(short: Path) -> None:
    """The installed version and a scratch with its TMPDIR, as a placement gets them: the
    settings carry the worktree hook that version takes, and the session's TMPDIR lies in the
    scratch the sandbox may write."""
    world = probe.build(short, "/usr/bin/claude", "2.1.330")
    scratch = short / "ws" / "probe" / ".scratch" / "plc-probe"
    assert world.env["TMPDIR"] == str(scratch.resolve() / "tmp")
    assert world.env["MAITY_SCRATCH"] == str(scratch.resolve())
    assert str(scratch.resolve()) in world.settings["sandbox"]["filesystem"]["allowWrite"]
    assert "WorktreeCreate" in world.settings["hooks"]
    (short / "old").mkdir()
    assert "WorktreeCreate" not in probe.build(short / "old", "/usr/bin/claude").settings["hooks"]
    assert probe.version_of("2.1.330 (Claude Code)") == "2.1.330"


def test_variants_change_only_what_they_name(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    marker = short / "hook-marker"
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
    assert not probe.complied(step, "ls  ", [probe.Call("Bash", {"command": "l s"})])
    cat = probe.Step("x", "x", "Bash", "cat /a b", "open", "hidden")
    for changed in ("cat\n/a b", "cat /a  b", "cat\t/a b", "cat /a\nb"):
        assert not probe.complied(cat, "cat /a b", [probe.Call("Bash", {"command": changed})])
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
    assert "summary: 0 PASS, 0 FAIL, 3 SKIP, 0 INCONCLUSIVE, 0 NOT-TESTABLE" in out


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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the probe runs on Linux only")
def test_the_probe_does_not_run_where_the_runner_would_not_start_the_placement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host without what Claude Code's seccomp step needs starts no sandboxed placement, so
    the probe does not run there either; on one that has it, the preflight passes."""
    from maity.runner import capabilities

    monkeypatch.setattr(capabilities, "claude_sandbox_tools", lambda platform=None: ())
    monkeypatch.setattr(capabilities, "claude_seccomp",
                        lambda as_user=None: capabilities.ClaudeSeccomp("ok", "x64"))  # fmt: skip
    assert probe.preflight(fake(tmp_path)) is None
    off = capabilities.ClaudeSeccomp("unsupported_arch", "ia32", "machine i686")
    monkeypatch.setattr(capabilities, "claude_seccomp", lambda as_user=None: off)
    assert probe.preflight(fake(tmp_path)) == capabilities.claude_seccomp_line(off)


# A synthetic list for `--extra-lines`, harmless and not the private one: the real list stays
# out of the repository.
SYNTHETIC = """# a comment, skipped

true && maity probe {T}
cat {script} | sh
echo ${HOME:-none} > /dev/null; maity probe {T}
echo nothing here
"""


def test_extra_lines_are_read_one_per_line(tmp_path: Path) -> None:
    path = tmp_path / "lines.txt"
    path.write_text(SYNTHETIC)
    assert probe.read_extra_lines(path) == [
        "true && maity probe {T}", "cat {script} | sh",
        "echo ${HOME:-none} > /dev/null; maity probe {T}", "echo nothing here",
    ]  # fmt: skip
    for bad in ("", "# only a comment\n\n", "maity probe\0 {T}\n", "maity probe {T}\r\n"):
        path.write_text(bad)
        with pytest.raises(ValueError):
            probe.read_extra_lines(path)


def test_each_extra_line_is_a_containment_step_of_its_own(short: Path) -> None:
    steps = probe.extra_steps(["true && maity probe {T}", "echo ${HOME:-none}"])
    assert [s.id for s in steps] == ["5.1", "5.2"]
    assert {(s.tool, s.variant, s.expect) for s in steps} == {("Bash", "open", "unescaped")}
    assert [s.id for s in probe.selected([*probe.steps(), *steps], "5.2")] == ["5.2"]
    world = probe.build(short, "/usr/bin/claude")
    # Only the placeholders are replaced; the line's own braces stay as they are.
    assert world.fill(steps[1].target, "t") == "echo ${HOME:-none}"
    assert world.fill("{script} {stub} {T}", "t") == f"{world.script} {world.stub} t"


def test_a_harness_without_a_sandbox_fails_the_extra_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counter-check for point 5: run unsandboxed, every line that runs the stub `maity`
    escapes and fails, whatever token it passes; a line that runs no `maity` even without a
    sandbox tests nothing and is NOT-TESTABLE, never PASS."""
    path = tmp_path / "lines.txt"
    path.write_text(SYNTHETIC)
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "5",
                       "--extra-lines", str(path)])  # fmt: skip
    found = outcomes(capsys.readouterr().out)
    assert code == 1
    assert found == {"5.1": "FAIL", "5.2": "FAIL", "5.3": "FAIL", "5.4": "NOT-TESTABLE"}


def test_a_line_that_did_not_run_is_inconclusive_not_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused (or failed to start): no marker of the stub at all, so no evidence that the line
    ran inside the sandbox."""
    path = tmp_path / "lines.txt"
    path.write_text(SYNTHETIC)
    code = probe.main(["--claude", fake(tmp_path, "refuse"), "--no-preflight", "--only", "5",
                       "--extra-lines", str(path)])  # fmt: skip
    assert code == 1
    assert outcomes(capsys.readouterr().out) == {
        "5.1": "INCONCLUSIVE", "5.2": "INCONCLUSIVE", "5.3": "INCONCLUSIVE",
        "5.4": "NOT-TESTABLE",
    }  # fmt: skip


def test_a_sandboxed_harness_passes_the_reachable_extra_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stub ran (its marker in the clone) and could neither write nor read the credential
    directory: positive evidence that the line ran inside the sandbox."""
    path = tmp_path / "lines.txt"
    path.write_text(SYNTHETIC.replace("echo nothing here\n", ""))
    code = probe.main(["--claude", fake(tmp_path, "sandbox"), "--no-preflight", "--only", "5",
                       "--extra-lines", str(path)])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert outcomes(out) == {"5.1": "PASS", "5.2": "PASS", "5.3": "PASS"}
    assert "ran inside the sandbox" in out


def test_a_run_with_only_untestable_lines_does_not_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "lines.txt"
    path.write_text("echo nothing here\n")
    code = probe.main(["--claude", fake(tmp_path, "sandbox"), "--no-preflight", "--only", "5",
                       "--extra-lines", str(path)])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 1 and outcomes(out) == {"5.1": "NOT-TESTABLE"}
    assert "0 PASS, 0 FAIL, 0 SKIP, 0 INCONCLUSIVE, 1 NOT-TESTABLE" in out


@pytest.mark.parametrize(
    ("escape", "ran", "status"),
    [
        ("cred=no", None, "FAIL"),  # outside, whatever it read
        (None, "cred=ok", "FAIL"),  # inside, but it read the credential
        (None, "cred=no", "PASS"),  # inside, credential hidden: the positive evidence
        (None, None, "INCONCLUSIVE"),  # no marker: no evidence it ran
    ],
)
def test_an_extra_line_is_judged_by_both_markers(
    short: Path, escape: str | None, ran: str | None, status: str
) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = probe.extra_steps(["true && maity probe {T}"])
    if escape is not None:
        (world.clone / ".git" / "maity" / "probe" / "none").write_text(escape)
    if ran is not None:
        (world.clone / ".probe-ran" / "none").write_text(ran)
    call = probe.Call("Bash", {"command": world.fill(step.target, "t")})
    run = probe.Run([call], "", 0)
    assert probe.judge(step, world, "t", run, short / "no-marker", {}).status == status


def test_the_precondition_runs_each_line_without_sandbox_or_hook(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    reach, unreach = probe.extra_steps(["cat {script} | sh", "echo nothing here"])
    assert probe.reachable(reach, world)[0] is True
    assert probe.reachable(unreach, world)[0] is False
    # It leaves no marker behind for the live run to read.
    assert not any((world.clone / ".probe-ran").iterdir())
    assert not any((world.clone / ".git" / "maity" / "probe").iterdir())


def test_extra_lines_that_only_selects_none_of_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "lines.txt"
    path.write_text(SYNTHETIC)
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "1a.1",
                       "--extra-lines", str(path)])  # fmt: skip
    assert code == 2 and "add 5" in capsys.readouterr().err
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight",
                       "--extra-lines", str(tmp_path / "missing.txt")]) == 2  # fmt: skip


def test_the_exit_code_counts_fail_and_inconclusive_only() -> None:
    o = probe.Outcome
    assert probe.exit_code([o("PASS", ""), o("SKIP", "")]) == 0
    assert probe.exit_code([o("PASS", ""), o("FAIL", "")]) == 1
    assert probe.exit_code([o("INCONCLUSIVE", "")]) == 1


def test_the_runners_hook_refuses_every_prefixed_call_the_probe_makes(short: Path) -> None:
    """1b and point 2 keep the runner's hook: each prefixed call and each line point 2 expects
    refused must be refused by it before the sandbox is asked, and the plain call must pass
    it."""
    from maity.runner import plaincall

    world = probe.build(short, "/usr/bin/claude")
    for step in probe.steps():
        if step.tool != "Bash" or step.variant not in ("runner", "open"):
            continue
        if step.id.split(".")[0] not in ("1a", "1b", "2"):
            continue
        payload = {"tool_name": "Bash", "tool_input": {"command": world.fill(step.target, "t")}}
        refused = plaincall.refusal(payload)
        assert (refused is None) == (step.expect == "escapes"), step.id
