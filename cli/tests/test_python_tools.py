"""A repository's own Python tools for a sandboxed Claude Code session (`python_tools`):
the grant key, the rules the runner writes, and the hook that holds such a line to
`python3 <dir>/<name>.py …` from the clone's root (plaincall.python_tool)."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from test_adapters import context
from test_runner import minimal, parse, problems

from maity.runner import adapters, config, plaincall
from maity.runner.asuser import Ssh

REPO = "github.com/oliver-zehentleitner/maity"


def grant(lines: str) -> str:
    return f'\n[repositories."{REPO}"]\n{lines}\n'


# --- the grant key -----------------------------------------------------------------------------


def test_python_tools_is_empty_by_default_and_takes_plain_directories_of_the_clone() -> None:
    plain = parse(minimal(grant=grant('allow = ["make test"]')))
    assert plain.repositories[REPO].python_tools == ()
    cfg = parse(minimal(grant=grant('python_tools = ["tools", "web/tools", "tools"]')))
    assert cfg.repositories[REPO].python_tools == ("tools", "web/tools")  # once each
    bad = ['".."', '"../tools"', '"tools/.."', '"/tools"', '"tools/"', '".tools"', '"to ols"',
           '"tools/*"', '""', '"a/b/c/d/e"', '"tools\\\\x"']  # fmt: skip
    for value in bad:
        found = problems(minimal(grant=grant(f"python_tools = [{value}]")))
        assert any(p.startswith(f"repositories.{REPO}.python_tools:") for p in found), value


def test_the_full_configuration_in_the_runner_docs_parses() -> None:
    """docs/runners.md shows a whole runner.toml with python_tools: it parses as written."""
    docs = Path(__file__).resolve().parents[2] / "docs" / "runners.md"
    section = docs.read_text().split("### Letting agents run the repository's own Python tools")[1]
    example = section.split("```toml\n", 1)[1].split("```", 1)[0]
    cfg = parse(example)
    assert cfg.repositories[REPO].python_tools == ("tools", "web/tools")


def test_the_hook_reads_tool_directories_as_the_configuration_does() -> None:
    """The hook imports nothing from the configuration, so its pattern is a copy: held equal."""
    assert plaincall._TOOL_DIR.pattern == config.PYTHON_TOOLS_DIR.pattern


# --- the rules the runner writes ---------------------------------------------------------------


def tools_ctx(tmp_path: Path, **overrides: Any) -> adapters.Context:
    data: dict[str, Any] = {
        "sandbox": True,
        "grant": config.RepositoryGrant(allow=("make test",), python_tools=("tools", "web/tools")),
        "scratch": tmp_path / "ws" / ".scratch" / "maity" / "plc-0003",
    }
    data.update(overrides)
    return context(tmp_path, **data)


def hook_words(settings: dict[str, object]) -> list[str]:
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    command = hooks["PreToolUse"][0]["hooks"][0]["command"]
    assert command.endswith(" || exit 2")
    return shlex.split(command[: -len(" || exit 2")])


def test_a_sandboxed_session_gets_the_rules_and_the_hook_gets_the_clone_and_the_directories(
    tmp_path: Path,
) -> None:
    ctx = tools_ctx(tmp_path)
    settings = adapters.claude_settings(ctx)
    allow = settings["permissions"]["allow"]
    for tool_dir in ("tools", "web/tools"):
        assert f"Bash(python3 {tool_dir}/*.py)" in allow
        assert f"Bash(python3 {tool_dir}/*.py *)" in allow
    assert not [rule for rule in allow if rule.startswith("Bash(python3 /")]  # no absolute form
    words = hook_words(settings)
    assert words[words.index("--clone") + 1] == str(ctx.clone)
    assert [words[i + 1] for i, w in enumerate(words) if w == "--python-tools"] == [
        "tools",
        "web/tools",
    ]
    assert str(ctx.scratch) in [words[i + 1] for i, w in enumerate(words) if w == "--writable"]
    # The hook reads its own arguments back as given.
    tools = plaincall._tools(words[words.index("--clone") :])
    assert ctx.scratch is not None
    assert tools == plaincall.PythonTools(
        clone=ctx.clone, dirs=("tools", "web/tools"), writable=(ctx.scratch,)
    )


def test_with_its_own_tmpdir_the_hook_gets_the_whole_leaf_and_refuses_a_python3_beside_its_tmp(
    tmp_path: Path, clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no room for a socket under the scratch, the session's TMPDIR is `<leaf>/tmp` and
    Claude Code's own CLAUDE_CODE_TMPDIR is the leaf, where Claude Code opens `claude-<uid>/`
    to the session's commands. The hook gets the leaf, so a python3 there is refused (A2541)."""
    # Paths only for the settings, short enough for a socket, as test_adapters has them.
    deep = Path("/") / ("w" * 60) / "maity" / ".scratch" / "plc-0000000000000003"
    parent = Path("/tmp/maity-scratch-1002")  # noqa: S108 - a path only
    leaf = parent / ("a" * 32)
    own = leaf / "tmp"
    ctx = tools_ctx(tmp_path, scratch=deep, tmpdir=own, tmp_scratch_parent=parent)
    assert adapters.own_tmpdir_in_use(ctx) == own
    words = hook_words(adapters.claude_settings(ctx))
    writable = [words[i + 1] for i, w in enumerate(words) if w == "--writable"]
    assert writable == [str(deep), str(leaf)]  # the leaf, which holds its `tmp`, not `tmp`
    # The hook, on real directories of that shape.
    real_leaf = tmp_path / "leaf"
    sibling = real_leaf / "claude-1001"
    sibling.mkdir(parents=True)
    (real_leaf / "tmp").mkdir()
    program = sibling / "python3"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(sibling))
    tools = plaincall.PythonTools(clone=clone, dirs=("tools",), writable=(real_leaf,))
    reason = decide("python3 tools/changelog.py", str(clone), tools)
    assert reason is not None and "can write" in reason
    # The `tmp` alone, as before this fix, would not cover the sibling.
    tools = plaincall.PythonTools(clone=clone, dirs=("tools",), writable=(real_leaf / "tmp",))
    assert decide("python3 tools/changelog.py", str(clone), tools) is None


def test_a_python3_link_in_a_writable_root_under_a_linked_ancestor_is_refused(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A writable root under a linked ancestor (macOS's /tmp) reads as given in the PATH and
    resolved in the hook's arguments, or the other way round. A python3 there that links to an
    interpreter outside every root is still the session's own: refused (A2541)."""
    real = tmp_path / "private" / "tmp"
    real.mkdir(parents=True)
    (tmp_path / "tmp").symlink_to(real)
    system = tmp_path / "usr" / "bin"
    system.mkdir(parents=True)
    (system / "python3").write_text("#!/bin/sh\n")
    (system / "python3").chmod(0o755)
    scratch_real = real / "scratch"
    scratch_real.mkdir()
    (scratch_real / "python3").symlink_to(system / "python3")
    for on_path, given in ((tmp_path / "tmp" / "scratch", scratch_real),
                           (scratch_real, tmp_path / "tmp" / "scratch")):  # fmt: skip
        monkeypatch.setenv("PATH", str(on_path))
        reason = decide("python3 tools/changelog.py", str(clone), tools_for(clone, given))
        assert reason is not None and "can write" in reason, (on_path, given)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sandbox": False},  # no sandbox: no hook to hold the form
        {"grant": config.RepositoryGrant(allow=("make test",))},  # nothing configured
        {"as_user": Ssh(name="h", maity_path="/usr/bin/maity")},  # the host's own hook
    ],
)
def test_no_rule_and_no_hook_argument_without_sandbox_directories_or_the_runners_own_hook(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    settings = adapters.claude_settings(tools_ctx(tmp_path, **overrides))
    assert not [r for r in settings["permissions"]["allow"] if r.startswith("Bash(python3")]
    if "hooks" in settings and "PreToolUse" in settings["hooks"]:
        assert "--python-tools" not in hook_words(settings)


# --- the hook ----------------------------------------------------------------------------------


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    root = tmp_path / "clone"
    (root / "tools").mkdir(parents=True)
    (root / "web" / "tools").mkdir(parents=True)
    (root / "tools" / "changelog.py").write_text("")
    (root / "web" / "tools" / "check.py").write_text("")
    (root / "tools" / "x.sh").write_text("")
    return root


@pytest.fixture
def system_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A python3 outside the clone and every writable path, alone on the PATH."""
    bin_dir = tmp_path / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    program = bin_dir / "python3"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    return program


def tools_for(clone: Path, *writable: Path) -> plaincall.PythonTools:
    return plaincall.PythonTools(clone=clone, dirs=("tools", "web/tools"), writable=writable)


def decide(command: str, cwd: object, tools: plaincall.PythonTools | None) -> str | None:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
    return plaincall.refusal(payload, tools)


@pytest.mark.parametrize(
    "command",
    [
        "python3 tools/changelog.py",
        "python3 tools/changelog.py check",
        "python3 web/tools/check.py --write",
        "python3 tools/changelog.py add --kind Fixed 'a message, with words' x.md",
        "python3 tools/changelog.py ../outside/file.md",  # an argument: the sandbox decides
    ],
)
def test_the_exact_form_from_the_clone_root_passes(
    clone: Path, system_python: Path, command: str
) -> None:
    assert decide(command, str(clone), tools_for(clone)) is None


@pytest.mark.parametrize(
    "command",
    [
        # an interpreter option before the script
        "python3 -c tools/changelog.py",
        "python3 -m tools/changelog.py",
        "python3 -I tools/changelog.py",
        # the script's path
        "python3 tools/../tools/changelog.py",
        "python3 tools/sub/changelog.py",
        "python3 tools/x.sh",
        "python3 ./tools/changelog.py",
        "python3 tools/.hidden.py",
        # the program
        "python3.12 tools/changelog.py",
        "/usr/bin/python3 tools/changelog.py",
        "./python3 tools/changelog.py",
        "env python3 tools/changelog.py",
        "PATH=. python3 tools/changelog.py",
        "timeout 5 python3 tools/changelog.py",
        "PYTHON3 tools/changelog.py",
        "'python3' tools/changelog.py",
        "pyth\\on3 tools/changelog.py",
        # more than one plain call
        "python3 tools/changelog.py; rm -rf x",
        "python3 tools/changelog.py && echo",
        "python3 tools/changelog.py || echo",
        "python3 tools/changelog.py | cat",
        "python3 tools/changelog.py > out",
        "python3 tools/changelog.py < in",
        "python3 tools/changelog.py &",
        "python3 tools/changelog.py $(id)",
        "python3 tools/changelog.py `id`",
        "python3 tools/changelog.py $HOME",
        'python3 tools/changelog.py "$HOME"',
        "python3 tools/changelog.py\npython3 tools/changelog.py",
        "python3\ttools/changelog.py",
        "python3 tools/changelog.py *",
        "python3 tools/changelog.py ~",
        "echo; python3 tools/changelog.py",
        "bash -c 'python3 tools/changelog.py'",
        "(python3 tools/changelog.py)",
    ],
)
def test_any_other_form_is_refused(clone: Path, system_python: Path, command: str) -> None:
    """Refused by the tool rule, or earlier for a reason of its own (`bash -c` with quoted
    text is a construct the hook does not read exactly)."""
    reason = decide(command, str(clone), tools_for(clone))
    assert reason is not None, command
    if not command.startswith("bash -c"):
        assert reason.startswith("A repository tool runs here only as"), command


def test_a_line_that_names_no_tool_directory_is_left_to_the_permission_rules(
    clone: Path, system_python: Path
) -> None:
    """Only a line that could match a `python_tools` rule is the hook's: the rest is decided by
    the allow list, which allows no other python3 line."""
    for command in ("python3 -c 'print(1)'", "python3 other/x.py", "git grep python3",
                    "cli/.venv/bin/python -m pytest cli/tests", "make -C web check",
                    # the first word after python3 that is no option is no tool directory, so
                    # no python_tools rule can match: left to the grant (A2541)
                    "python3 -m pytest tools/test_changelog.py",
                    "python3 -m unittest tools/test_changelog.py",
                    "python3 -W ignore tools/x.py"):  # fmt: skip
        assert decide(command, str(clone), tools_for(clone)) is None, command


def test_a_tool_directory_right_after_a_python3_word_is_held_whatever_the_line(
    clone: Path, system_python: Path
) -> None:
    """The side effect the candidate check keeps on purpose: a tool directory right after a
    python3 word, past its options, is held to the exact form even where it is no call."""
    for command in ("git grep python3 tools/", "git grep -e python3 tools/"):
        reason = decide(command, str(clone), tools_for(clone))
        assert reason is not None, command
    # The way around it that docs/runners.md names.
    for command in ("git grep python3 -- tools", "git grep python3 -- web"):
        assert decide(command, str(clone), tools_for(clone)) is None, command


def test_a_script_or_directory_that_is_a_link_is_refused(
    clone: Path, system_python: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text("")
    (clone / "tools" / "evil.py").symlink_to(outside / "evil.py")
    assert decide("python3 tools/evil.py", str(clone), tools_for(clone)) is not None
    (clone / "web" / "tools").rename(clone / "web" / "tools-real")
    (clone / "web" / "tools").symlink_to(outside)
    assert decide("python3 web/tools/evil.py", str(clone), tools_for(clone)) is not None


def test_a_script_that_does_not_exist_is_refused(clone: Path, system_python: Path) -> None:
    assert decide("python3 tools/missing.py", str(clone), tools_for(clone)) is not None


@pytest.mark.parametrize("cwd", [None, "", 42])
def test_no_readable_working_directory_is_refused(
    clone: Path, system_python: Path, cwd: object
) -> None:
    reason = decide("python3 tools/changelog.py", cwd, tools_for(clone))
    assert reason is not None and "no working directory" in reason


def test_another_working_directory_is_refused(
    clone: Path, system_python: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other"
    (other / "tools").mkdir(parents=True)
    (other / "tools" / "changelog.py").write_text("")
    for cwd in (str(other), str(clone / "tools"), str(tmp_path / "gone")):
        reason = decide("python3 tools/changelog.py", cwd, tools_for(clone))
        assert reason is not None and "clone's root" in reason, cwd


def test_no_python3_on_the_path_is_refused(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    reason = decide("python3 tools/changelog.py", str(clone), tools_for(clone))
    assert reason is not None and "not on the PATH" in reason


def test_a_python3_the_session_can_write_is_refused(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    for where in (clone / "bin", scratch / "bin"):
        where.mkdir(parents=True)
        program = where / "python3"
        program.write_text("#!/bin/sh\n")
        program.chmod(0o755)
        monkeypatch.setenv("PATH", str(where))
        reason = decide("python3 tools/changelog.py", str(clone), tools_for(clone, scratch))
        assert reason is not None and "can write" in reason, where


def test_a_python3_that_links_into_a_writable_path_is_refused(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (clone / "bin").mkdir()
    real = clone / "bin" / "python3"
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    outside = tmp_path / "usr" / "bin"
    outside.mkdir(parents=True)
    (outside / "python3").symlink_to(real)
    monkeypatch.setenv("PATH", str(outside))
    reason = decide("python3 tools/changelog.py", str(clone), tools_for(clone))
    assert reason is not None and "can write" in reason


def test_a_lookup_that_fails_is_refused(
    clone: Path, system_python: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(path: object) -> os.stat_result:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "lstat", broken)
    reason = decide("python3 tools/changelog.py", str(clone), tools_for(clone))
    assert reason is not None and "cannot check it" in reason


def test_without_tool_directories_the_hook_does_not_look_at_python_lines(clone: Path) -> None:
    for tools in (None, replace(tools_for(clone), dirs=())):
        assert decide("python3 tools/../x.py; id", str(clone), tools) is None


def test_the_hook_refuses_every_call_on_arguments_it_cannot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad arguments make the hook fail, and a hook that fails refuses the call."""
    unreadable = [
        ["--clone"],
        ["--python-tools", "tools"],
        ["--clone", "rel", "--python-tools", "tools"],
        ["--clone", "/c", "--python-tools", "../x"],
        ["--other", "x"],
    ]
    for args in unreadable:
        with pytest.raises(ValueError):
            plaincall._tools(args)
        monkeypatch.setattr(sys, "stdin", _Stdin(b'{"tool_input": {"command": "ls"}}'))
        assert plaincall.main(args) == 2, args


class _Stdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = _Buffer(data)


class _Buffer:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data
