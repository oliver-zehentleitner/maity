"""The sandbox probe's own parts that need no model: the runner's settings it starts from, its
variants, reading a run, and its verdicts against a fake `claude` without any sandbox, which
must fail the steps a real sandbox passes (cli/tests/claude_sandbox_probe.py)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import claude_sandbox_probe as probe
import pytest

from maity.runner import plaincall

FAKE = """#!{python}
import json, os, re, subprocess, sys
from maity.runner.plaincall import refusal as hook
args = sys.argv[1:]
if args == ["--version"]:
    print("2.1.326 (Claude Code)")
    sys.exit(0)
prompt = args[args.index("-p") + 1]
kind, target = re.search(r"<(command|read|write)>(.*?)</\\1>", prompt, re.S).groups()
if "--no-session-persistence" not in args:  # Claude Code keeps a transcript by default
    projects = os.path.join(os.environ["HOME"], ".claude", "projects", "fake-slug")
    os.makedirs(projects, exist_ok=True)
    with open(os.path.join(projects, f"{{os.getpid()}}.jsonl"), "a") as kept:
        kept.write(json.dumps({{"prompt": prompt}}) + "\\n")
print(json.dumps({{"type": "system", "subtype": "init"}}))
if "{mode}" == "idle":
    print(json.dumps({{"type": "result", "result": "DONE"}}))
    sys.exit(0)
if kind == "command":
    use = {{"name": "Bash", "input": {{"command": target}}}}
    if "{mode}" == "refuse":
        out, err = "Permission to use Bash has been denied.", True
    elif "{mode}" == "fail":  # the call is answered, but nothing started
        out, err = "Error: spawn /bin/bash ENOENT", True
    elif "{mode}" == "hooked" and (reason := hook({{"tool_input": {{"command": target}}}})):
        out, err = f"PreToolUse:Bash hook error: [{{target}}]: {{reason}}", True
    elif "{mode}" in ("sandbox", "oddname"):  # the credential directory hidden, as inside
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
if "{mode}" == "oddname":  # a tool name that carries the call's own text
    use["name"] = "Tool " + target
print(json.dumps({{"type": "assistant", "message": {{"content": [
    {{"type": "tool_use", "id": "t1", **use}}]}}}}))
print(json.dumps({{"type": "user", "message": {{"content": [
    {{"type": "tool_result", "tool_use_id": "t1", "content": out, "is_error": err}}]}}}}))
print(json.dumps({{"type": "result", "result": "DONE"}}))
"""


def fake(tmp_path: Path, mode: str = "obey") -> str:
    """A `claude` that makes the asked call itself, unsandboxed and without hooks (`obey`), or
    with the clone's credential directory hidden and unwritable, as the sandbox has it
    (`sandbox`, for Bash only), or behind the runner's hook, refusing as Claude Code reports a
    blocking hook (`hooked`, for Bash only); that refuses it as a permission rule does
    (`refuse`), answers it without starting anything (`fail`), makes none (`idle`), or makes it
    under a tool name that carries the call's text (`oddname`). Like Claude Code, it keeps a
    transcript of the prompt in the home unless it is given `--no-session-persistence`.
    A test that runs the probe on it is skipped where the probe's scratch has no room for the
    placement's socket (`_probe_tempdir`)."""
    if not PROBE_TEMP_FITS:
        pytest.skip("the temporary directory leaves no room for the probe's socket")
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


PROBE_TEMP_FITS = True
_RMTREE = shutil.rmtree  # the real one, for teardown after a test replaced it


@pytest.fixture(autouse=True)
def _probe_tempdir(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The probe's scratch goes to a short directory of this test's own, so tests do not see
    each other's scratch (pytest -n) and its socket fits; where the system's temporary
    directory is too long even for that, the tests that run the probe are skipped (`fake`)."""
    from maity.runner import adapters

    global PROBE_TEMP_FITS
    own = Path(tempfile.mkdtemp(prefix="m"))
    deepest = own.resolve() / (probe.SCRATCH_PREFIX + "x" * 8) / "ws" / ".scratch" / "probe"
    PROBE_TEMP_FITS = adapters.fits_socket(deepest / "plc-probe" / "tmp")
    monkeypatch.setattr(tempfile, "tempdir", str(own))
    try:
        yield
    finally:
        _RMTREE(own, ignore_errors=True)


@pytest.fixture
def short() -> Iterator[Path]:
    """A scratch root short enough that the placement's TMPDIR fits a Unix socket, made where
    the probe makes its own (the system's temporary directory, TMPDIR honoured); pytest's
    tmp_path may be too long for it. Where even that is too long, the test is skipped, as the
    probe itself refuses to run there."""
    from maity.runner import adapters

    root = Path(tempfile.mkdtemp(prefix="mp-"))
    if not adapters.fits_socket(root.resolve() / "ws" / ".scratch" / "probe" / "plc-probe" / "tmp"):
        shutil.rmtree(root, ignore_errors=True)
        pytest.skip("the temporary directory leaves no room for the placement's socket")
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
    scratch = short / "ws" / ".scratch" / "probe" / "plc-probe"
    assert world.env["TMPDIR"] == str(scratch.resolve() / "tmp")
    assert world.env["MAITY_SCRATCH"] == str(scratch.resolve())
    assert str(scratch.resolve()) in world.settings["sandbox"]["filesystem"]["allowWrite"]
    holder = str(scratch.parent.parent.resolve())  # every scratch's holder, denied for reading
    assert holder in world.settings["sandbox"]["filesystem"]["denyRead"]
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
    assert calls == [probe.Call("Bash", {"command": "ls"}, "denied", True, True)]
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
    """A permission rule's refusal is evidence for 1a, not for point 2, which is the hook's."""
    code = probe.main(["--claude", fake(tmp_path, "refuse"), "--no-preflight",
                       "--only", "1a.1,1a.2,2.2"])  # fmt: skip
    found = outcomes(capsys.readouterr().out)
    assert code == 1 and found == {"1a.1": "FAIL", "1a.2": "PASS", "2.2": "INCONCLUSIVE"}


def test_a_line_that_failed_to_start_is_inconclusive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No marker and no refusal in the result: no evidence either way, so never a pass; nor
    for point 4, whose commands must show that they ran."""
    code = probe.main(["--claude", fake(tmp_path, "fail"), "--no-preflight",
                       "--only", "1a.2,1b.5,2.2,2.10,4.2,4.4,4.6"])  # fmt: skip
    found = outcomes(capsys.readouterr().out)
    assert code == 1 and set(found.values()) == {"INCONCLUSIVE"}, found


def test_a_refusal_by_the_runners_hook_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Behind the runner's real hook: every prefixed line and every line point 2 expects
    refused shows the hook's own reason in the result."""
    code = probe.main(["--claude", fake(tmp_path, "hooked"), "--no-preflight",
                       "--only", "1b,2.2,2.3,2.4,2.5,2.6,2.7,2.8"])  # fmt: skip
    out = capsys.readouterr().out
    found = outcomes(out)
    assert found.pop("1b.1") == "PASS"  # the plain call passes the hook and runs
    assert code == 0 and set(found.values()) == {"PASS"}, out
    assert out.count("refused before it ran, by the hook") == len(found)


def test_a_run_inside_the_sandbox_passes_by_its_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = probe.main(["--claude", fake(tmp_path, "sandbox"), "--no-preflight",
                       "--only", "1a.2,1b.2,4.2"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and outcomes(out) == {"1a.2": "PASS", "1b.2": "PASS", "4.2": "PASS"}, out
    assert out.count("ran inside the sandbox") == 2 and "ran, and not read" in out


def test_an_unreachable_public_line_is_not_testable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(probe, "PREFIXED", (("runs no maity", "echo nothing {T}"),))
    code = probe.main(["--claude", fake(tmp_path, "sandbox"), "--no-preflight", "--only", "1a.2"])
    out = capsys.readouterr().out
    assert code == 1 and outcomes(out) == {"1a.2": "NOT-TESTABLE"}, out


def test_nothing_to_hide_in_the_home_is_not_testable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert not (Path.home() / ".claude").exists()  # the test's own home (conftest)
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "4.5"])
    assert code == 1 and outcomes(capsys.readouterr().out) == {"4.5": "NOT-TESTABLE"}


@pytest.mark.parametrize(
    ("step_id", "status"), [("2.10", "PASS"), ("2.11", "PASS"), ("2.2", "INCONCLUSIVE")]
)
def test_a_blocking_hook_without_the_runners_reason_counts_only_for_a_failing_hook(
    short: Path, step_id: str, status: str
) -> None:
    """2.9 to 2.11 put a failing hook in the runner's place: Claude Code's block is their
    evidence. 2.2 to 2.8 need the runner's own reason."""
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == step_id]
    target = world.fill(step.target, "t")
    said = f"PreToolUse:Bash hook error: [{target}]: hook timed out"
    call = probe.Call("Bash", {"command": target}, said, True, True)
    found = probe.judge(step, world, "t", probe.Run([call], "", 0), short / "no-marker", {})
    assert found.status == status, found


@pytest.mark.parametrize(
    ("step_id", "call", "status"),
    [
        ("4.3", probe.Call("Read", {}, "", False, False), "INCONCLUSIVE"),  # no result
        ("4.3", probe.Call("Read", {}, "Permission to read x has been denied.", True, True),
         "PASS"),
        ("4.3", probe.Call("Read", {}, "", False, True), "INCONCLUSIVE"),  # empty, no error
        ("4.3", probe.Call("Read", {}, "Error: File does not exist.", True, True),
         "INCONCLUSIVE"),  # an unrelated error
        ("4.5", probe.Call("Bash", {}, "", True, True), "INCONCLUSIVE"),  # no count
        ("4.5", probe.Call("Bash", {}, "0\n", False, True), "PASS"),
        ("4.5", probe.Call("Bash", {}, "1\n", False, True), "FAIL"),
        ("4.8", probe.Call("Write", {}, "", False, False), "INCONCLUSIVE"),  # no result
        ("4.8", probe.Call("Write", {}, "written", False, True), "INCONCLUSIVE"),  # not refused
        ("4.8", probe.Call("Write", {}, "denied", True, True), "INCONCLUSIVE"),  # unrelated
        ("4.8", probe.Call("Write", {}, "Permission to edit x has been denied.", True, True),
         "PASS"),
        ("4.7", probe.Call("Write", {}, "Claude requested permissions to write to x, but you "
                                        "haven't granted it yet.", True, True), "PASS"),
        ("3.2", probe.Call("Bash", {}, "", True, True), "INCONCLUSIVE"),  # the stub never ran
    ],
)  # fmt: skip
def test_point_four_and_three_need_evidence_that_the_call_ran(
    short: Path, step_id: str, call: probe.Call, status: str
) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == step_id]
    key = "command" if step.tool == "Bash" else "file_path"
    call.input[key] = world.fill(step.target, "t")
    before: dict[Path, bytes | None] = {p: None for p in probe.watched(step, world, "t")}
    found = probe.judge(step, world, "t", probe.Run([call], "", 0), short / "no-marker", before)
    assert found.status == status, found


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
    # Nothing passed, so the run shows nothing: not a success.
    assert code == 1 and outcomes(out) == {"3.2": "SKIP", "3.4": "SKIP", "3.5": "SKIP"}
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
        (None, "", "INCONCLUSIVE"),  # an empty marker says nothing
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


@pytest.mark.parametrize("mode", ["obey", "sandbox", "refuse", "fail", "hooked", "oddname"])
def test_the_probe_prints_nothing_of_a_private_line(
    tmp_path: Path, capfd: pytest.CaptureFixture[str], mode: str
) -> None:
    """A private line's text, here a random marker, appears nowhere in what the probe prints,
    whatever the harness does with the line and whether its precondition holds."""
    marker = "zq" + uuid.uuid4().hex
    path = tmp_path / "lines.txt"
    path.write_text(
        f"true {marker} && maity probe {{T}}\n"  # reaches the stub
        f"echo {marker}\n"  # never reaches it: NOT-TESTABLE
        f"{marker}-missing-command\n"  # fails in the shell, which names the command
    )
    code = probe.main(["--claude", fake(tmp_path, mode), "--no-preflight", "--only", "5",
                       "--extra-lines", str(path), "--keep"])  # fmt: skip
    out, err = capfd.readouterr()
    assert code == 1
    assert set(outcomes(out)) == {"5.1", "5.2", "5.3"}
    assert marker not in out and marker not in err
    # Nor in what --keep retains: no name and no content under the scratch holds it.
    scratch = Path(out.splitlines()[0].rsplit("scratch: ", 1)[1])
    try:
        for kept in scratch.rglob("*"):
            assert marker[:12] not in str(kept)
            if kept.is_file() and not kept.is_symlink():
                assert marker[:12].encode() not in kept.read_bytes(), kept
        # Only 5.1 ran live (5.2 and 5.3 are NOT-TESTABLE): its status, no stream.
        assert sorted(p.name for p in (scratch / "streams").iterdir()) == ["5.1.status"]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    assert marker[:12] not in out + err  # nor a part of it
    assert f"private line 1 [{probe.line_hash(f'true {marker} && maity probe {{T}}')}]" in out


def test_a_private_line_the_model_changed_is_not_quoted(short: Path) -> None:
    marker = "zq" + uuid.uuid4().hex
    world = probe.build(short, "/usr/bin/claude")
    (step,) = probe.extra_steps([f"true {marker} && maity probe {{T}}"])
    other = probe.Call("Bash", {"command": f"true {marker}"}, f"ran {marker}", False, True)
    found = probe.judge(step, world, "t", probe.Run([other], "", 0), short / "no-marker", {})
    assert found.status == "INCONCLUSIVE" and marker not in found.detail


def test_a_bad_private_file_is_named_without_its_text(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "lines.txt"
    path.write_bytes(b"maity probe \xff-secretish\r\n")
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight",
                       "--extra-lines", str(path)]) == 2  # fmt: skip
    out, err = capfd.readouterr()
    assert "secretish" not in out + err and "not UTF-8" in err


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


def test_an_empty_selection_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "99"]) == 2
    assert "selects no step" in capsys.readouterr().err


def test_a_contained_step_needs_its_marker_to_say_cred_no(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == "1b.2"]
    call = probe.Call("Bash", {"command": world.fill(step.target, "t")}, "", False, True)
    run = probe.Run([call], "", 0)
    marker = world.clone / ".probe-ran" / "t"
    for content, status in (("", "INCONCLUSIVE"), ("cred=maybe", "INCONCLUSIVE"),
                            ("cred=no", "PASS"), ("cred=ok", "FAIL")):  # fmt: skip
        marker.write_text(content)
        assert probe.judge(step, world, "t", run, short / "x", {}).status == status, content


def test_a_timeout_never_passes_but_keeps_a_failure(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == "1b.2"]
    call = probe.Call("Bash", {"command": world.fill(step.target, "t")}, "", False, True)
    (world.clone / ".probe-ran" / "t").write_text("cred=no")
    assert probe.judge(step, world, "t", probe.Run([call], "", 0), short / "x", {}).status == "PASS"
    timed_out = probe.Run([call], "", None)
    assert probe.judge(step, world, "t", timed_out, short / "x", {}).status == "INCONCLUSIVE"
    (world.clone / ".git" / "maity" / "probe" / "t").write_text("cred=ok")
    assert probe.judge(step, world, "t", timed_out, short / "x", {}).status == "FAIL"
    # Even when the model's call is not the one asked for, an escape is a failure.
    other = probe.Run([probe.Call("Bash", {"command": "ls"})], "", None)
    assert probe.judge(step, world, "t", other, short / "x", {}).status == "FAIL"


def test_a_precondition_that_times_out_is_not_reached(
    short: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = probe.build(short, "/usr/bin/claude")
    monkeypatch.setattr(probe, "REACH_TIMEOUT", 1)
    (step,) = probe.extra_steps(["maity probe {T}; sleep 5"])
    assert probe.reachable(step, world) == (False, "no end within 1 s")
    assert not any((world.clone / ".git" / "maity" / "probe").iterdir())


def test_the_secret_must_be_there_to_be_hidden(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    by_id = {s.id: s for s in probe.steps()}
    assert probe.testable(by_id["4.3"], world)[0] and probe.testable(by_id["4.4"], world)[0]
    world.cred.write_text("not the marker\n")
    for step_id in ("4.2", "4.3"):
        ok, why = probe.testable(by_id[step_id], world)
        assert not ok and "does not hold the marker credential" in why


def test_an_empty_file_in_git_hooks_fails_4_6(short: Path) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == "4.6"]
    paths = probe.watched(step, world, "t")
    before = {p: (p.read_bytes() if p.is_file() else None) for p in paths}
    out = world.fill(probe.DONE, "t")
    call = probe.Call("Bash", {"command": world.fill(step.target, "t")}, out, False, True)
    run = probe.Run([call], "", 0)
    assert probe.judge(step, world, "t", run, short / "x", before).status == "PASS"
    (world.clone / ".git" / "config.worktree").touch()  # the sandbox's placeholder: allowed
    assert probe.judge(step, world, "t", run, short / "x", before).status == "PASS"
    (world.clone / ".git" / "hooks" / "probe-t").touch()  # empty, but written
    found = probe.judge(step, world, "t", run, short / "x", before)
    assert found.status == "FAIL" and "hooks/probe-t" in found.detail


def test_a_failed_settings_write_is_undone(monkeypatch: pytest.MonkeyPatch) -> None:
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"theme": "dark"}')
    real = probe._write_atomic
    calls = []

    def fail_on_user(path: Path, text: str, *args: Any) -> None:
        calls.append(path)
        if path == user and calls.count(user) == 1:  # the change fails, the restore works
            raise OSError("disk full")
        real(path, text, *args)

    monkeypatch.setattr(probe, "_write_atomic", fail_on_user)
    with pytest.raises(OSError):
        with probe.changed("user:disableAllHooks"):
            pass
    monkeypatch.setattr(probe, "_write_atomic", real)
    assert user.read_text() == '{"theme": "dark"}' and not probe.user_saved().exists()


def test_a_failed_managed_write_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    managed = tmp_path / "etc" / "managed-settings.json"
    monkeypatch.setattr(probe, "managed_file", lambda: managed)

    def broken(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{")  # half written
        raise OSError("sudo failed")

    monkeypatch.setattr(probe, "_put", broken)
    with pytest.raises(OSError):
        with probe.changed("managed:disableAllHooks"):
            pass
    assert not managed.exists() and not probe.managed_record().exists()


def test_a_killed_probe_is_put_right_at_the_next_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    managed = tmp_path / "etc" / "managed-settings.json"
    monkeypatch.setattr(probe, "managed_file", lambda: managed)
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"disableAllHooks": true}')  # as a killed step left it
    probe.user_saved().write_text(
        json.dumps(
            {"text": '{"theme": "dark"}', "mode": 0o600, "uid": os.getuid(), "gid": os.getgid()}
        )
    )
    managed.parent.mkdir(parents=True)
    managed.write_text('{"disableAllHooks": true}')
    probe.managed_record().write_text(f"{managed}\n")
    done = probe.recover()
    assert len(done) == 2 and not managed.exists() and not probe.managed_record().exists()
    assert user.read_text() == '{"theme": "dark"}' and not probe.user_saved().exists()
    assert probe.recover() == []
    other = tmp_path / "not-ours.json"
    other.write_text("{}")
    probe.managed_record().write_text(f"{other}\n")  # a path the probe never writes stays
    probe.recover()
    assert other.exists()


@pytest.mark.parametrize("step_id", ["1a.2", "1b.2", "2.2"])
def test_a_refusal_text_in_a_result_that_is_no_error_is_no_refusal(
    short: Path, step_id: str
) -> None:
    """The result echoes a refusal (a command that prints one) but is not an error: no
    evidence that anything refused the call."""
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == step_id]
    target = world.fill(step.target, "t")
    hook = f"PreToolUse:Bash hook error: [{target}]: {plaincall.PREFIX_REFUSED}"
    for text in ("Permission to use Bash has been denied.", hook):
        for is_error, status in ((False, "INCONCLUSIVE"), (True, "PASS")):
            if step_id == "2.2" and text.startswith("Permission"):
                status = "INCONCLUSIVE"  # point 2 needs the hook's own reason
            call = probe.Call("Bash", {"command": target}, text, is_error, True)
            found = probe.judge(step, world, "t", probe.Run([call], "", 0), short / "x", {})
            assert found.status == status, (text, is_error, found)


@pytest.mark.parametrize(
    ("step_id", "escape", "fetch_head", "status"),
    [
        ("3.1", "", None, "INCONCLUSIVE"),  # an empty stub marker is no run
        ("3.1", "cred=no", None, "INCONCLUSIVE"),  # nor one without the credential
        ("3.1", "cred=ok", None, "PASS"),
        ("3.2", "", None, "INCONCLUSIVE"),
        ("3.5", "", None, "INCONCLUSIVE"),
        ("4.9", None, "", "FAIL"),  # an empty FETCH_HEAD
        ("4.9", None, "0" * 40 + "\t\tbranch 'main' of x\n", "FAIL"),  # not origin's commit
        ("4.9", None, "HEAD", "PASS"),  # FETCH_HEAD names origin's main
    ],
)
def test_the_hook_and_fetch_verdicts_need_their_exact_evidence(
    short: Path, step_id: str, escape: str | None, fetch_head: str | None, status: str
) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == step_id]
    if escape is not None:
        (world.clone / ".git" / "maity" / "probe" / "t").write_text(escape)
        (short / "hook").touch()  # the detector hook ran (hooks-on wants it)
    if fetch_head is not None:
        if fetch_head == "HEAD":
            commit = probe._git(world.root, "--git-dir", str(world.root / "origin.git"),
                                "rev-parse", "main")  # fmt: skip
            fetch_head = f"{commit}\t\tbranch 'main' of x\n"
        (world.clone / ".git" / "FETCH_HEAD").write_text(fetch_head)
    call = probe.Call("Bash", {"command": world.fill(step.target, "t")}, "", False, True)
    marker = short / ("hook" if step_id != "3.2" else "no-hook")
    found = probe.judge(step, world, "t", probe.Run([call], "", 0), marker, {})
    assert found.status == status, found


def test_every_run_saves_no_session(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Claude Code would keep a transcript of each run, private prompt included, in the home;
    every run is started with `--no-session-persistence`."""
    seen: list[list[str]] = []

    def runner(argv: list[str], env: dict[str, str], cwd: Path) -> tuple[int | None, str]:
        seen.append(argv)
        return 0, ""

    fake(tmp_path)  # the same skip as the runs on the fake harness
    lines = tmp_path / "lines.txt"
    lines.write_text("true && maity probe {T}\n")
    probe.main(["--claude", "/bin/true", "--no-preflight", "--only", "1a,2.2,4.3,5",
                "--extra-lines", str(lines)], runner=runner)  # fmt: skip
    capsys.readouterr()
    assert len(seen) == 13 + 1 + 1 + 1
    assert all(argv.count(probe.NO_SESSION) == 1 and "-p" in argv for argv in seen)


def test_a_private_line_in_claude_codes_home_fails_the_run(
    tmp_path: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Were a transcript kept anyway, the probe names the file, not the line, and fails."""
    marker = "zq" + uuid.uuid4().hex
    lines = tmp_path / "lines.txt"
    lines.write_text(f"true {marker} && maity probe {{T}}\n")
    claude = fake(tmp_path, "sandbox")

    def keeps_a_transcript(
        argv: list[str], env: dict[str, str], cwd: Path
    ) -> tuple[int | None, str]:
        argv = [a for a in argv if a != probe.NO_SESSION]  # as if the flag did nothing
        return probe.run_claude(argv, env, cwd)

    code = probe.main(["--claude", claude, "--no-preflight", "--only", "5",
                       "--extra-lines", str(lines)], runner=keeps_a_transcript)  # fmt: skip
    out, err = capfd.readouterr()
    assert code == 1 and "PRIVATE LINE FOUND in " in out and marker not in out + err
    assert "fake-slug" in out  # the file is named
    code = probe.main(["--claude", claude, "--no-preflight", "--only", "5",
                       "--extra-lines", str(lines)])  # fmt: skip
    out, _ = capfd.readouterr()
    assert code == 0 and "PRIVATE LINE FOUND" not in out
    assert "Claude Code's home: 0 file(s) written during the run" in out


@pytest.mark.parametrize("flag", ["true", "false", 1, 0, None])
def test_a_refusal_needs_a_real_boolean_error_flag(short: Path, flag: object) -> None:
    world = probe.build(short, "/usr/bin/claude")
    (step,) = [s for s in probe.steps() if s.id == "1b.2"]
    target = world.fill(step.target, "t")
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": target}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "a", "is_error": flag,
             "content": "Permission to use Bash has been denied."}]}},
    ]  # fmt: skip
    (call,) = probe.parse_stream("\n".join(json.dumps(e) for e in events))
    assert call.is_error is False and call.malformed is True
    found = probe.judge(step, world, "t", probe.Run([call], "", 0), short / "x", {})
    assert found.status == "INCONCLUSIVE"
    events[1]["message"]["content"][0]["is_error"] = True  # type: ignore[index]
    (call,) = probe.parse_stream("\n".join(json.dumps(e) for e in events))
    assert call.is_error is True and not call.malformed
    assert probe.judge(step, world, "t", probe.Run([call], "", 0), short / "x", {}).status == "PASS"


def test_a_copy_in_the_earlier_format_is_restored() -> None:
    """581ab0dd's copy held only the text: restored with the file's own mode, or 0600."""
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"disableAllHooks": true}')
    user.chmod(0o640)
    probe.user_saved().write_text(json.dumps({"text": '{"theme": "dark"}'}))
    assert probe.recover() == [f"restored {user} from an earlier probe's copy"]
    assert user.read_text() == '{"theme": "dark"}' and user.stat().st_mode & 0o777 == 0o640
    assert not probe.user_saved().exists()
    user.unlink()
    probe.user_saved().write_text(json.dumps({"text": '{"theme": "light"}'}))
    probe.recover()
    assert user.read_text() == '{"theme": "light"}' and user.stat().st_mode & 0o777 == 0o600
    probe.user_saved().write_text(json.dumps(["not", "a", "copy"]))
    with pytest.raises(ValueError):
        probe.recover()
    assert probe.user_saved().exists()  # kept: nothing was restored


def test_user_settings_behind_a_link_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text("{}")
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.symlink_to(real)
    monkeypatch.setattr(probe, "claude_running", lambda any_user: [])
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--user-settings"]) == 2
    assert "is a symbolic link" in capsys.readouterr().err
    assert user.is_symlink() and real.read_text() == "{}"


def _tree(root: Path) -> dict[str, tuple[int, bytes | None]]:
    """Every path under `root` with its mode and, for a file, its content."""
    return {str(p.relative_to(root)): (p.lstat().st_mode, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}  # fmt: skip


def test_settings_keep_their_mode_through_a_step_and_a_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.umask(0o022)
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"theme": "dark"}')
    user.chmod(0o600)
    managed = tmp_path / "etc" / "managed-settings.json"
    monkeypatch.setattr(probe, "managed_file", lambda: managed)
    with probe.changed("user:disableAllHooks"):
        assert user.stat().st_mode & 0o777 == 0o600  # changed, still private
        assert probe.user_saved().stat().st_mode & 0o777 == 0o600
    assert user.stat().st_mode & 0o777 == 0o600 and user.read_text() == '{"theme": "dark"}'
    with probe.changed("managed:disableAllHooks"):
        assert probe.managed_record().stat().st_mode & 0o777 == 0o600
    # A killed step, recovered: the copy holds the mode too.
    probe._write_atomic(probe.user_saved(), json.dumps(probe._user_copy()))
    user.write_text('{"disableAllHooks": true}')
    user.chmod(0o644)
    probe.recover()
    assert user.stat().st_mode & 0o777 == 0o600 and user.read_text() == '{"theme": "dark"}'
    user.chmod(0o640)  # another original mode is restored as it was
    with probe.changed("user:allowManagedHooksOnly"):
        pass
    assert user.stat().st_mode & 0o777 == 0o640


def test_a_leftover_stops_the_minimal_run_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home = Path.home()
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"disableAllHooks": true}')
    user.chmod(0o600)
    probe.user_saved().write_text(json.dumps({"text": "{}", "mode": 0o600, "uid": os.getuid(),
                                              "gid": os.getgid()}))  # fmt: skip
    probe.managed_record().write_text(str(tmp_path / "x") + "\n")
    monkeypatch.setattr(probe, "claude_running", lambda any_user: [])  # not even asked
    before = _tree(home)
    code = probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "1a.1"])
    err = capsys.readouterr().err
    assert code == 2 and "an earlier probe left settings changed" in err
    assert _tree(home) == before  # files, contents and modes


def test_a_leftover_is_not_put_right_while_claude_code_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home = Path.home()
    user = probe.user_settings()
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('{"disableAllHooks": true}')
    probe.user_saved().write_text(json.dumps({"text": "{}", "mode": 0o600, "uid": os.getuid(),
                                              "gid": os.getgid()}))  # fmt: skip
    monkeypatch.setattr(probe, "claude_running", lambda any_user: [77])
    before = _tree(home)
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--user-settings"]) == 2
    assert "pids [77]" in capsys.readouterr().err and _tree(home) == before


def test_the_minimal_run_writes_nothing_outside_its_scratch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--only 1,5 --extra-lines` without --keep: the home and the temporary directory are as
    they were, the scratch removed. The fake harness writes nothing of its own; Claude Code's
    own files in its home are outside this test."""
    temp = Path(tempfile.gettempdir())  # this test's own (`_probe_tempdir`)

    def scratches() -> set[str]:
        return {p.name for p in temp.iterdir()}

    lines = tmp_path / "lines.txt"
    lines.write_text("true && maity probe {T}\n")
    claude = fake(tmp_path, "sandbox")
    home, before_home, before_temp = Path.home(), _tree(Path.home()), scratches()
    code = probe.main(["--claude", claude, "--no-preflight", "--only", "1,5",
                       "--extra-lines", str(lines)])  # fmt: skip
    out, err = capsys.readouterr()
    assert code in (0, 1), out + err  # ran to its end; the fake fails the plain controls
    assert _tree(home) == before_home and scratches() == before_temp
    made = out.splitlines()[0].rsplit("scratch: ", 1)[1]
    assert not Path(made).exists()


def test_the_settings_steps_refuse_while_claude_code_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def running(any_user: bool) -> list[int]:
        seen.append(any_user)
        return [4242]

    monkeypatch.setattr(probe, "claude_running", running)
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--user-settings"]) == 2
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--managed"]) == 2
    assert "pids [4242]" in capsys.readouterr().err and seen == [False, True]


def test_claude_code_processes_are_found_in_proc(tmp_path: Path) -> None:
    for pid, comm, argv in (("101", "claude", b"/opt/claude\0-p"), ("102", "bash", b"bash\0"),
                            ("103", "node", b"node\0/usr/lib/@anthropic-ai/claude-code/cli.js"),
                            ("104", "MainThread", b"/home/u/.local/bin/claude\0")):  # fmt: skip
        (tmp_path / pid).mkdir()
        (tmp_path / pid / "comm").write_text(comm + "\n")
        (tmp_path / pid / "cmdline").write_bytes(argv)
    assert probe.claude_running(any_user=True, proc=tmp_path) == [101, 103, 104]


def test_a_failed_cleanup_names_the_scratch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "scratch"
    root.mkdir()

    def stuck(path: Path, **kwargs: Any) -> None:
        handler = kwargs.get("onexc") or kwargs.get("onerror")
        assert handler is not None
        handler(os.rmdir, str(path), PermissionError("busy"))

    monkeypatch.setattr(shutil, "rmtree", stuck)
    probe.remove_scratch(root)
    assert f"cleanup failed: {root}" in capsys.readouterr().err


def test_a_start_the_runner_would_refuse_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*_args: Any) -> None:
        raise RuntimeError("no private TMPDIR")

    monkeypatch.setattr(probe, "build", refused)
    assert probe.main(["--claude", fake(tmp_path), "--no-preflight", "--only", "1a.1"]) == 2
    assert "no private TMPDIR" in capsys.readouterr().err


def test_the_exit_code_counts_fail_and_inconclusive_only() -> None:
    o = probe.Outcome
    assert probe.exit_code([o("PASS", ""), o("SKIP", "")]) == 0
    assert probe.exit_code([o("SKIP", ""), o("SKIP", "")]) == 1  # nothing passed
    assert probe.exit_code([]) == 1
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
