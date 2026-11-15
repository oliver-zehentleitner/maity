"""The `antigravity` harness (agy): its adapter, its workspace folder and its checks (docs/api.md
§15.3, §15.5, §15.7; cli/context/runner.md, the Antigravity entry)."""

from __future__ import annotations

import dataclasses
import json
import os
import re
import shlex
import shutil
import subprocess
import tomllib
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from conftest import git
from test_supervisor import FakeTmux

from maity import cli, clonecheck, proc
from maity.runner import (
    adapters,
    capabilities,
    commands,
    config,
    loop,
    operate,
    supervisor,
    targets,
    workspace,
)
from maity.runner.asuser import AsUser

PLACEMENT = {"id": "plc-0003", "mode": "interactive", "model": "gemini-3-pro"}
REPO = "https://github.com/oliver-zehentleitner/maity"


def context(tmp_path: Path, **overrides: Any) -> adapters.Context:
    harness = config.Harness("antigravity", ("interactive", "supervised"), "interactive",
                             ("gemini-3-pro",), binary="agy")  # fmt: skip
    agent_dir = tmp_path / "st" / "agents" / "plc-0003"
    agent_dir.mkdir(parents=True, mode=0o700)
    folder = tmp_path / "ws" / "maity" / "agent-3"
    (folder / "repo" / ".git").mkdir(parents=True)
    data: dict[str, Any] = {
        "placement": PLACEMENT, "harness": harness, "binary": "/usr/bin/agy",
        "clone": folder / "repo", "folder": folder, "agent_dir": agent_dir,
        "grant": config.RepositoryGrant(allow=("python3 -m pytest *", "make test")),
        "restart": config.Restart(), "hosts": ("maity.team", "github.com"),
    }  # fmt: skip
    data.update(overrides)
    return adapters.Context(**data)


def prompt_of(ctx: adapters.Context, start: str) -> str:
    folder = adapters.AGY_FOLDER_PROMPT.format(repo="repo")
    return folder + start + adapters.AGY_MAITY_PROMPT


# --- the adapter: argv per mode ---------------------------------------------------------------


def test_interactive_starts_agy_with_the_start_prompt_in_the_workspace_folder(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path)
    launch = adapters.launch(ctx)
    settings = ctx.agent_dir / "agy-settings.json"
    assert launch.argv == [
        "/usr/bin/agy", "--settings", str(settings), "--model", "gemini-3-pro",
        "-i", prompt_of(ctx, adapters.START_PROMPT),
    ]  # fmt: skip
    assert json.loads(settings.read_text()) == adapters.antigravity_settings(ctx)
    # agy takes the work tree from $PWD: the folder, never the clone (§15.3).
    assert launch.env["PWD"] == str(ctx.folder)
    assert launch.env["GIT_COMMON_DIR"] == str(ctx.clone / ".git")
    assert "MAITY_SUPERVISOR" not in launch.env  # nothing wakes an interactive session
    # The deny of `.git/config` may or may not reach agy's sandbox: git works either way.
    pairs = {(launch.env[f"GIT_CONFIG_KEY_{i}"], launch.env[f"GIT_CONFIG_VALUE_{i}"])
             for i in range(int(launch.env["GIT_CONFIG_COUNT"]))}  # fmt: skip
    assert set(adapters.SANDBOX_GIT_CONFIG) <= pairs
    # The clone is marked as the runner's, as for every harness.
    assert (ctx.clone / ".git" / "maity" / "placement").read_text() == "plc-0003\n"


def test_the_start_prompt_sends_the_agent_into_the_clone(tmp_path: Path) -> None:
    prompt = adapters.launch(context(tmp_path)).argv[-1]
    assert "`cd repo`" in prompt and "`repo/AGENTS.md`" in prompt
    assert "Leave nothing in this folder besides `repo`" in prompt
    assert prompt.index("cd repo") < prompt.index("maity resume")
    assert adapters.GIT_PROMPT not in prompt  # agy's sandbox is not seen to refuse config


def test_interactive_resume_continues_the_folders_conversation(tmp_path: Path) -> None:
    launch = adapters.launch(context(tmp_path, resume=True))
    assert launch.argv[-3:] == ["-c", "-i", adapters.RESUME_PROMPT]
    assert not any(adapters.START_PROMPT in arg for arg in launch.argv)


def test_supervised_runs_agy_headless_and_continues_with_c(tmp_path: Path) -> None:
    ctx = context(tmp_path, placement={"id": "plc-0003", "mode": "supervised"})
    launch = adapters.launch(ctx)
    assert launch.argv[-2] == "--spec"
    spec = json.loads(Path(launch.argv[-1]).read_text())
    base = ["/usr/bin/agy", "--settings", str(ctx.agent_dir / "agy-settings.json")]
    prompt = prompt_of(ctx, adapters.SUPERVISED_PROMPT)
    assert spec["first"] == [*base, "-p", prompt]  # no model named: none passed
    # `-c` is scoped to the working directory, the placement's own folder.
    assert spec["again"] == [*base, "-c", "-p", prompt]
    assert spec["clone"] == str(ctx.clone)  # `maity wait` runs in the clone
    assert spec["env"]["PWD"] == str(ctx.folder)
    assert spec["env"]["MAITY_SUPERVISOR"].startswith("maity-runner/")
    assert spec["limit"]["exit_codes"] == []  # no limit signal seen in a real run yet


def test_supervised_with_a_model(tmp_path: Path) -> None:
    ctx = context(tmp_path, placement={"id": "plc-0003", "mode": "supervised", "model": "m-1"})
    spec = json.loads(Path(adapters.launch(ctx).argv[-1]).read_text())
    for argv in (spec["first"], spec["again"]):
        assert argv[argv.index("--model") + 1] == "m-1"


def test_the_pull_request_line_reaches_the_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir()
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{gh.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    grant = config.RepositoryGrant(pull_requests=True)
    placement = {**PLACEMENT, "workspace": {"repository": REPO}}
    prompt = adapters.launch(context(tmp_path, grant=grant, placement=placement)).argv[-1]
    assert prompt.endswith(adapters.PULL_REQUEST_PROMPT)


# --- the adapter: the settings profile --------------------------------------------------------


def test_the_settings_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    other = tmp_path / "ws" / "maity" / "agent-4" / "repo" / ".git" / "maity"
    ctx = context(tmp_path, private=(tmp_path / "st", home / ".ssh", home / ".gemini", other),
                  grant=config.RepositoryGrant(allow=("python3 -m pytest *", "make test"),
                                               network=("pypi.org",)))  # fmt: skip
    git_dir = ctx.clone / ".git"
    token = home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    hidden = [git_dir / "maity", tmp_path / "st", home / ".ssh", token, other]
    assert adapters.antigravity_settings(ctx) == {
        # Not `auto`, agy 1.5.7's default, whose reviewer may let a command leave the sandbox.
        "agentMode": "",
        "toolPermission": "proceed-in-sandbox",
        "enableTerminalSandbox": True,
        "trustedWorkspaces": [str(ctx.folder)],
        "permissions": {
            # No command grant is applied to agy: `python3 -m pytest *` and `make test` both
            # run in agy's sandbox, so only `command(maity)` and the hosts are allowed.
            "allow": [
                "command(maity)",
                "read_url(github.com)", "read_url(maity.team)", "read_url(pypi.org)",
            ],
            "deny": [
                *(f"{tool}({path})" for path in hidden for tool in ("read_file", "write_file")),
                *(f"write_file({git_dir / name})" for name in adapters.GIT_PROTECTED),
                "command(git -c)", "command(git --config-env)", "command(git --exec-path)",
                "command(gh)",
            ],
        },
    }  # fmt: skip


def test_agys_own_directory_stays_readable_but_its_login(tmp_path: Path) -> None:
    """agy's sandboxed commands keep scratch under `~/.gemini`; only its sign-in is denied."""
    home = tmp_path / "home"
    deny = adapters.antigravity_settings(context(tmp_path, private=(home / ".gemini",)))[
        "permissions"
    ]["deny"]
    assert f"read_file({home / '.gemini'})" not in deny
    assert f"read_file({home / '.gemini' / adapters.AGY_LOGIN.relative_to('.gemini')})" in deny


# --- grants: exact like Claude Code (cli/context/runner.md, the agy grants entry) ------------


# agy 1.5.9 compiles each word of a `regex:` rule with Go's regexp.Compile (syntax.Perl: `.`
# matches every character but a line feed). Python's `.` without DOTALL does the same, so only
# the POSIX classes Go knows and Python does not are written out.
_GO_CLASSES = {"[:ascii:]": "\\x00-\\x7f", "[:^ascii:]": "\\x80-\\U0010ffff"}


def _go_regex(word: str) -> str:
    for go, python in _GO_CLASSES.items():
        word = word.replace(go, python)
    return word


# Go's strings.TrimSpace for ASCII; a non-ASCII space sends agy to its whole-line match.
_GO_ASCII_SPACE = " \t\n\v\f\r"


def _drop_dollar_quotes(line: str) -> str:
    """mvdan/sh reads `$'…'` and `$"…"` as quotes with a `Dollar` flag, and agy's wordLiteral
    takes their raw text, flag ignored: the same as without the `$`."""
    out: list[str] = []
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote == "'":
            quote = "" if c == "'" else quote
        elif c == "\\":
            out.append(line[i : i + 2])
            i += 2
            continue
        elif quote == '"':
            quote = "" if c == '"' else quote
        elif c in "'\"":
            quote = c
        elif c == "$" and line[i + 1 : i + 2] in ("'", '"'):
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# agy's terminal.extractSimpleCommands reads the invoked command from a line: a leading
# environment assignment (terminal.isEnvAssignmentToken) and a leading command wrapper
# (terminal.isCommandWrapper) are stepped over before any `command(...)` rule is compared, so
# no rule ever sees them. `env` consumes the assignments that follow it as well. The wrappers
# agy steps over, read from agy 1.5.9 (the agy grants entry in cli/context/runner.md).
_AGY_WRAPPERS = frozenset({"env", "nohup", "time", "nice", "sudo", "xargs", "timeout"})
_AGY_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _agy_strip_prefixes(words: list[str]) -> list[str]:
    """Drop the leading environment assignments and command wrappers agy steps over before it
    reads the invoked command, so the words left are the ones its rules see. `env GIT_PAGER=x`
    and a bare `GIT_PAGER=x` both fall away, so `GIT_PAGER=x git status` is `git status`."""
    rest = list(words)
    while rest and (rest[0] in _AGY_WRAPPERS or _AGY_ASSIGNMENT.match(rest[0])):
        rest.pop(0)
    return rest


def _agy_words(line: str) -> list[str]:
    """A line split into words like a shell line, as agy 1.5.9 does with mvdan/sh: each word's
    text without its quotes, trimmed at both edges (terminal.wordLiteral ends in
    strings.TrimSpace), a word that comes out empty dropped (extractSimpleCommands.func1 skips
    it), and the leading assignments and wrappers agy steps over removed
    (_agy_strip_prefixes). So `git status ''` and `GIT_PAGER=x git status` are both
    `git status` for agy, though the shell passes the command more than those words."""
    words = (word.strip(_GO_ASCII_SPACE) for word in shlex.split(_drop_dollar_quotes(line)))
    return _agy_strip_prefixes([word for word in words if word])


def _agy_exact(command: str) -> bool:
    """agy's RequiresExactMatch for the characters: a NUL, or a non-ASCII character that is a
    control, format or space character (U+2028 and U+2029 among them), makes agy match the
    whole line instead of its words."""
    return "\0" in command or any(
        ord(c) > 0x7F and (unicodedata.category(c)[0] == "C" or c.isspace()) for c in command
    )


def _agy_rule_matches(rule: str, command: str) -> bool:
    """agy's documented `command(...)` match for a simple command, as agy 1.5.9 does it: the
    rule split into words like a shell line; more words than the command, no match; else the
    command's first words, each equal to the rule's, or for `regex:` each matched as
    `^(?:word)$` with Go's regexp, where a word that does not compile matches nothing. A line
    agy must match exactly is compared whole: char for char, or as `^(?:rule)$`."""
    target = rule.removeprefix("command(").removesuffix(")")
    if target == "*":
        return True
    regex = target.startswith("regex:")
    pattern = target.removeprefix("regex:").strip()
    try:
        if _agy_exact(command):
            if not regex:
                return pattern == command.strip()
            return re.fullmatch(f"(?:{_go_regex(pattern)})", command.strip()) is not None
        words = _agy_words(pattern)
        line = _agy_words(command)
        if len(words) > len(line):
            return False
        for word, given in zip(words, line, strict=False):
            if not regex:
                if word != given:
                    return False
            elif re.fullmatch(f"(?:{_go_regex(word)})", given) is None:
                return False
    except re.error:
        return False
    return True


def agy_decides(settings: dict[str, Any], command: str) -> str:
    """What agy does with `command` under these settings: deny beats allow; a command no rule
    names runs in the sandbox (`proceed-in-sandbox`), never with the grant's reach."""
    rules = settings["permissions"]
    for decision, kind in (("denied", "deny"), ("allowed", "allow")):
        named = [rule for rule in rules[kind] if rule.startswith("command(")]
        if any(_agy_rule_matches(rule, command) for rule in named):
            return decision
    return "sandbox"


def agy_settings(tmp_path: Path, *allow: str) -> dict[str, Any]:
    return adapters.antigravity_settings(
        context(tmp_path, grant=config.RepositoryGrant(allow=allow))
    )


def test_the_matcher_models_agys_prefix_match(tmp_path: Path) -> None:
    """The counter-check: an allow rule alone, as before, lets every longer form through,
    and a deny that does not compile denies nothing."""
    bare = {"permissions": {"allow": ["command(make test)"], "deny": []}}
    assert agy_decides(bare, "make test --anything") == "allowed"
    assert agy_decides(bare, "make") == "sandbox"
    broken = {
        "permissions": {"allow": ["command(make test)"], "deny": ["command(regex:make (test .*)"]}
    }
    assert agy_decides(broken, "make test --anything") == "allowed"


def test_an_exact_grant_is_left_out_and_runs_in_the_sandbox(tmp_path: Path) -> None:
    """An exact entry (no `*`) is not given to agy: no allow rule, named as left out. It runs
    in agy's sandbox like every unlisted command, the entry itself and every longer form."""
    found = adapters.agy_grants(["git status"])
    assert [left for left, _ in found.left_out] == ["git status"]
    settings = agy_settings(tmp_path, "git status")
    assert "command(git status)" not in settings["permissions"]["allow"]
    assert agy_decides(settings, "git status") == "sandbox"
    assert agy_decides(settings, "git status --anything") == "sandbox"
    assert agy_decides(settings, "git log") == "sandbox"  # unrelated: not granted either
    assert agy_decides(settings, "maity status") == "allowed"  # maity stays a prefix


def test_the_matcher_drops_a_leading_assignment_or_wrapper() -> None:
    """agy reads the invoked command after stepping over a leading environment assignment
    (isEnvAssignmentToken) and a command wrapper (isCommandWrapper), `env` eating the
    assignment that follows it; the test matcher models that in _agy_words."""
    assert _agy_words("GIT_PAGER=x git status") == ["git", "status"]
    assert _agy_words("env GIT_PAGER=x git status") == ["git", "status"]
    assert _agy_words("PATH=. git status") == ["git", "status"]
    assert _agy_words("sudo nice timeout git status") == ["git", "status"]
    assert _agy_words("LD_PRELOAD=/tmp/x git push") == ["git", "push"]
    assert _agy_words("git status") == ["git", "status"]  # nothing to step over


@pytest.mark.parametrize(
    "line",
    ["GIT_PAGER=x git status", "env GIT_PAGER=x git status",
     "PATH=. git status", "LD_PRELOAD=/tmp/x git status"],
)  # fmt: skip
def test_a_leading_assignment_does_not_run_an_exact_grant_outside_the_sandbox(
    tmp_path: Path, line: str
) -> None:
    """The regression: a line that puts an environment assignment (or `env` with one) in front
    of what would be an exact grant must not run outside agy's sandbox. agy steps over such a
    prefix before it matches, so a bare `command(git status)` allow would match the line (the
    counter-check); dropping the exact grant is what keeps the real settings from matching it,
    so the line runs in agy's sandbox instead."""
    bare = {"permissions": {"allow": ["command(git status)"], "deny": []}}
    assert agy_decides(bare, line) == "allowed"  # the exact allow would have matched it
    settings = agy_settings(tmp_path, "git status")  # the real settings leave it out
    assert agy_decides(settings, line) == "sandbox"


@pytest.mark.parametrize(
    "line",
    ["LD_PRELOAD=/tmp/x git push", "env LD_PRELOAD=/tmp/x git push",
     "GIT_SSH=/tmp/x git push", "sudo git push"],
)  # fmt: skip
def test_a_leading_assignment_does_not_run_a_prefix_grant_outside_the_sandbox(
    tmp_path: Path, line: str
) -> None:
    """The same regression for a ` *` prefix grant: `git *` would become `command(git)`, and
    agy steps over a leading assignment or wrapper before matching, so a bare `command(git)`
    prefix allow would match the line (the counter-check). The prefix grant is dropped too,
    so the real settings leave it out and the line runs in agy's sandbox instead."""
    bare = {"permissions": {"allow": ["command(git)"], "deny": []}}
    assert agy_decides(bare, line) == "allowed"  # the bare prefix allow would have matched it
    settings = agy_settings(tmp_path, "git *")  # the real settings leave it out
    assert agy_decides(settings, line) == "sandbox"
    assert agy_decides(settings, "git push") == "sandbox"  # the prefix grant no longer stands


def test_a_grant_ending_in_a_star_is_left_out_too(tmp_path: Path) -> None:
    """A ` *` prefix entry is no longer a prefix allow for agy: it is left out and named, and
    runs in agy's sandbox like an unlisted command, just as an exact entry does."""
    found = adapters.agy_grants(["python3 -m pytest *", "ruff *"])
    assert [left for left, _ in found.left_out] == ["python3 -m pytest *", "ruff *"]
    settings = agy_settings(tmp_path, "python3 -m pytest *", "ruff *")
    assert [r for r in settings["permissions"]["allow"] if r.startswith("command(")] == [
        "command(maity)"
    ]
    assert agy_decides(settings, "python3 -m pytest tests/x.py -k y") == "sandbox"
    assert agy_decides(settings, "ruff check .") == "sandbox"


def test_a_star_inside_a_grant_is_left_out_without_a_word(tmp_path: Path) -> None:
    found = adapters.agy_grants(["npm run test:*", "foo *.py", "*"])
    assert found == adapters.AgyGrants()  # an interior `*`: no rule and nothing named
    assert agy_decides(agy_settings(tmp_path, "npm run test:*"), "npm run test:unit") == "sandbox"


@pytest.mark.parametrize(
    "rule",
    ["python3 tests/x.py", "make c++", "pytest -k a.b", "ls ~/x", "git status",
     "cargo build --release", "git *", "ruff *"],
)  # fmt: skip
def test_every_command_grant_is_left_out_and_named(tmp_path: Path, rule: str) -> None:
    """No command grant, exact or ` *` prefix, becomes a rule for agy: none is allowed, each is
    named as left out, and runs in the sandbox, the entry itself and every longer form."""
    found = adapters.agy_grants([rule])
    assert [left for left, _ in found.left_out] == [rule]
    settings = agy_settings(tmp_path, rule) if config.plain_command(rule) else None
    if settings is not None:
        probe = rule.removesuffix(" *")
        assert agy_decides(settings, probe) == "sandbox"
        assert agy_decides(settings, probe + " --more") == "sandbox"


def test_exact_and_prefix_entries_are_all_left_out(tmp_path: Path) -> None:
    """A mix: every exact entry and every ` *` prefix entry is left out and named; only an
    entry with an interior `*` is left out without a word. agy gets no command allow."""
    rules = ("make test", "python3 -m pytest *", "go test ./...", "ruff *",
             "git status", "npm run test:*")  # fmt: skip
    found = adapters.agy_grants(rules)
    assert [left for left, _ in found.left_out] == [
        "make test", "python3 -m pytest *", "go test ./...", "ruff *", "git status"
    ]  # fmt: skip


def test_overlapping_entries_are_each_named(tmp_path: Path) -> None:
    """With prefixes dropped too, an entry a ` *` prefix once covered is named like any other;
    nothing is silently allowed."""
    found = adapters.agy_grants(["git log -1", "git log *", "git log"])
    assert [left for left, _ in found.left_out] == ["git log -1", "git log *", "git log"]
    settings = agy_settings(tmp_path, "git log -1", "git log *")
    assert agy_decides(settings, "git log -1 --stat") == "sandbox"


def test_check_names_every_command_grant_left_out_for_antigravity() -> None:
    grant = (
        '\n[repositories."github.com/oliver-zehentleitner/maity"]\n'
        'allow = ["git status", "git status --short", "pytest tests/x.py", "python3 -m pytest *",'
        ' "npm run test:*"]\n'
    )
    text = CHECK_CONFIG + grant
    report = commands.Report()
    commands._check_repositories(report, config.parse(tomllib.loads(text), Path("runner.toml")))
    texts = [text for level, text in report.lines if level == "warn"]
    # Three exact entries and the ` *` prefix are each named; only the `*`-inside entry is not.
    assert not report.failed and len(texts) == 4
    assert "'git status' is left out for antigravity" in texts[0] and "agy's sandbox" in texts[0]
    assert "'git status --short' is left out" in texts[1]
    assert "'pytest tests/x.py' is left out" in texts[2]
    assert "'python3 -m pytest *' is left out" in texts[3]
    assert all("agy does not match a command grant" in t for t in texts)
    without = text.replace("[harness.antigravity]\n", "")
    quiet = commands.Report()
    commands._check_repositories(quiet, config.parse(tomllib.loads(without), Path("runner.toml")))
    assert quiet.lines == []


CHECK_CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "/srv/state"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]

[harness.antigravity]
"""


def test_no_command_grant_reaches_agy(tmp_path: Path) -> None:
    # No command grant is applied to agy (exact or prefix), and the front-loaded entries are
    # refused by plain_command before that; agy keeps only `command(maity)`.
    refused = ("FOO=1 make test", "env make test", "make test; maity *", "maity.exe *",
               "xargs /tmp/tools:local/maity")  # fmt: skip
    ctx = context(tmp_path, grant=config.RepositoryGrant(allow=("make *", "make test", *refused)))
    allow = adapters.antigravity_settings(ctx)["permissions"]["allow"]
    assert [rule for rule in allow if rule.startswith("command(")] == ["command(maity)"]


def test_agy_accepts_the_settings_profile(tmp_path: Path) -> None:
    """agy refuses an unknown setting or value at start (`--settings`), before any sign-in:
    `agy --settings <file> agents` in a home of its own checks the profile without a session.
    Its permission rules are not checked there; their form is from agy's documentation and
    the runs recorded in cli/context/runner.md."""
    import pwd

    own = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "bin"  # the tests move HOME
    binary = shutil.which("agy") or shutil.which("agy", path=str(own))
    if binary is None:
        pytest.skip("agy is not installed here")
    ctx = context(tmp_path, private=(tmp_path / "home" / ".gemini",))
    path = tmp_path / "agy-settings.json"
    path.write_text(json.dumps(adapters.antigravity_settings(ctx)))
    home = tmp_path / "agy-home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "")}
    ok = subprocess.run([binary, "--settings", str(path), "agents"], cwd=ctx.folder, env=env,
                        capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert ok.returncode == 0, ok.stderr
    path.write_text(json.dumps({**adapters.antigravity_settings(ctx), "agentMode": "nope"}))
    bad = subprocess.run([binary, "--settings", str(path), "agents"], cwd=ctx.folder, env=env,
                         capture_output=True, text=True, timeout=60, check=False)  # fmt: skip
    assert bad.returncode != 0 and "agentMode" in bad.stderr  # the check is real


# --- the supervised loop waits in the clone ---------------------------------------------------


def test_the_loop_waits_in_the_clone_its_spec_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs.get("cwd"))
        return subprocess.CompletedProcess(argv, 3, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert loop._wait(str(tmp_path))[0] == 3
    assert loop._wait()[0] == 3
    assert seen == [str(tmp_path), None]

    waits: list[Any] = []

    def main(self: loop.Loop) -> int:
        waits.append(self.wait)
        return 0

    monkeypatch.setattr(loop.Loop, "main", main)
    spec = tmp_path / "loop.json"
    spec.write_text(json.dumps({"first": [], "again": [], "clone": "/ws/p/c/repo"}))
    assert loop.main(["--spec", str(spec)]) == 0
    called: list[Any] = []

    def wait(cwd: str | None = None) -> tuple[int, str, str]:
        called.append(cwd)
        return 0, "", ""

    monkeypatch.setattr(loop, "_wait", wait)
    waits[0]()
    assert called == ["/ws/p/c/repo"]


# --- what the runner advertises ---------------------------------------------------------------


AGY = config.Harness("antigravity", ("supervised",), "supervised", binary="agy")


@pytest.mark.parametrize("platform", [True, False])
def test_agy_is_advertised_with_its_allowlist_and_its_sandbox_off(
    monkeypatch: pytest.MonkeyPatch, platform: bool
) -> None:
    """§15.3: `sandbox: on` only once the runner has seen agy's sandbox start, which nothing
    checks yet: namespaces that start do not turn it on."""
    ran: list[list[str]] = []

    def fake(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/bin/{name}")
    monkeypatch.setattr(capabilities, "agy_sandbox_platform", lambda p=None: platform)
    monkeypatch.setattr(proc, "run", lambda argv, cwd, timeout: fake(argv))
    monkeypatch.setattr(AsUser, "run", lambda self, argv, **kw: fake(argv))
    assert not capabilities.sandbox_available(AGY)
    assert not capabilities.sandbox_available(AGY, "/usr/bin", AsUser("agents"))
    entry = capabilities.harness_entry(AGY, capabilities.Probe("/usr/bin/agy", "1.5.7", None))
    assert (entry["id"], entry["version"], entry["confinement"], entry["sandbox"]) == (
        "antigravity", "1.5.7", "allowlist", "off"
    )  # fmt: skip
    assert ran == []  # the namespaces are tried by `maity runner check` only


def test_the_namespace_diagnostic_tries_them_as_the_agents_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[list[str]] = []
    code = 0

    def fake(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, code, "/usr/bin/unshare\n", "")

    monkeypatch.setattr("shutil.which", lambda name, path=None: f"/usr/bin/{name}")
    monkeypatch.setattr(proc, "run", lambda argv, cwd, timeout: fake(argv))
    assert capabilities.agy_namespaces("/usr/bin")
    monkeypatch.setattr(AsUser, "run", lambda self, argv, **kw: fake(argv))
    assert capabilities.agy_namespaces("/usr/bin", AsUser("agents"))
    probe = ["/usr/bin/unshare", "--user", "--map-root-user", "--mount", "--pid", "--fork",
             "--net", "true"]  # fmt: skip
    assert [argv for argv in ran if argv[0] != "sh"] == [probe, probe]
    code = 1
    assert not capabilities.agy_namespaces("/usr/bin")
    monkeypatch.setattr("shutil.which", lambda name, path=None: None)
    assert not capabilities.agy_namespaces("/usr/bin")


@dataclass
class Host:
    """An ssh host as `probe_remote` and the check ask it: `command -v`, `--version`, the
    namespaces."""

    namespaces: bool = True
    calls: list[list[str]] = field(default_factory=list)

    def run(self, argv: Sequence[str], env: Any = None, timeout: float = 60, **kw: Any) -> Any:
        argv = list(argv)
        self.calls.append(argv)
        if argv[:2] == ["sh", "-c"]:
            found = {"agy": "/opt/bin/agy", "unshare": "/usr/bin/unshare"}
            names = argv[4:]
            if argv[2] != targets.WHICH:  # capabilities.which
                return subprocess.CompletedProcess(argv, 0, found.get(names[0], "") + "\n", "")
            out = "".join(f"{name}\t{found.get(name, '')}\n" for name in names)
            return subprocess.CompletedProcess(argv, 0, out, "")
        if argv[-1] == "--version":
            return subprocess.CompletedProcess(argv, 0, "1.5.7\n", "")
        return subprocess.CompletedProcess(argv, 0 if self.namespaces else 1, "", "")


@pytest.mark.parametrize("namespaces", [True, False])
def test_an_ssh_host_advertises_agy_sandbox_off_too(namespaces: bool) -> None:
    host = Host(namespaces)
    probes, sandbox, held = targets.probe_remote(host, {"antigravity": AGY}, "/usr/bin")  # type: ignore[arg-type]
    assert probes["antigravity"] == capabilities.Probe("/opt/bin/agy", "1.5.7", None)
    assert sandbox == {"antigravity": False} and held == set()
    assert not any(call[0] == "/usr/bin/unshare" for call in host.calls)


def test_the_configuration_takes_antigravity_with_agy_as_its_binary(tmp_path: Path) -> None:
    cfg = load(tmp_path)
    harness = cfg.harnesses["antigravity"]
    assert (harness.binary, harness.modes) == ("agy", ("supervised", "interactive"))
    assert "antigravity" in adapters.READY


# --- the workspace folder ---------------------------------------------------------------------


CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "{root}/st"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/*"]

[backend.local]
workspaces = "{root}/ws"

[harness.stub]

[harness.antigravity]
modes = ["supervised", "interactive"]
"""


def load(root: Path) -> config.Config:
    path = root / "runner.toml"
    path.write_text(CONFIG.format(root=root))
    (root / "st").mkdir(mode=0o700, exist_ok=True)
    return config.load(path)


@pytest.fixture
def origin_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A local repository; cloning it needs the file transport, which the runner refuses."""
    monkeypatch.setattr(workspace, "PROTOCOLS", ("https", "ssh", "file"))
    monkeypatch.setattr(config, "repository_url_ok", lambda url: True)
    repo = tmp_path / "origin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    return repo


def folder_of(cfg: config.Config, n: int = 3) -> workspace.Workspace:
    assert cfg.local is not None
    return workspace.locate(cfg.local.workspaces, "maity", f"agent-{n}", folder=True)


def test_the_folder_layout_puts_the_clone_into_repo(tmp_path: Path) -> None:
    place = workspace.locate(tmp_path, "maity", "agent-3", folder=True)
    assert place.path == tmp_path.resolve() / "maity" / "agent-3"  # the folder: the record's key
    assert place.repo == place.path / "repo" and place.key == str(place.path)
    assert place.credential == place.repo / ".git" / "maity" / "credential"
    plain = workspace.locate(tmp_path, "maity", "agent-3")
    assert plain.repo == plain.path == place.path and plain.layout == "clone"
    assert workspace.uses_folder("antigravity") and not workspace.uses_folder("claude-code")


def test_prepare_clones_into_the_folder_and_records_its_layout(
    tmp_path: Path, origin_repo: Path
) -> None:
    cfg = load(tmp_path)
    place = folder_of(cfg)
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    assert sorted(os.listdir(place.path)) == ["repo"]
    assert workspace.origin(place.repo) == str(origin_repo)
    assert workspace.records(cfg.state_dir)[str(place.path)]["layout"] == "folder"
    workspace.check_folder(place)  # nothing but the clone: a start may go on
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0005")  # found again
    with pytest.raises(workspace.Refused) as other:
        workspace.prepare(cfg, place, str(origin_repo), "agt-4", "plc-0004")
    assert other.value.detail == "other_agent"


@pytest.mark.parametrize(
    "planted",
    [".agents", ".agent", "_agents", "GEMINI.md", "AGENTS.md", ".gitignore", "notes.txt",
     "repo2"],
)  # fmt: skip
def test_a_start_refuses_a_folder_holding_anything_besides_the_clone(
    tmp_path: Path, origin_repo: Path, planted: str
) -> None:
    """agy loads its start directory's hooks, MCP servers, plugins, skills and rules, so an
    entry a run left beside the clone would load at the next start: refused, by any name,
    and nothing is deleted (§15.5, `workspace_not_bare`)."""
    cfg = load(tmp_path)
    place = folder_of(cfg)
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    entry = place.path / planted
    if planted.startswith((".agent", "_agent")):
        (entry / "hooks").mkdir(parents=True)
        (entry / "hooks.json").write_text("{}")
    else:
        entry.write_text("x")
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place)
    assert (refused.value.reason, refused.value.detail) == (
        "workspace_in_use", "workspace_not_bare"
    )  # fmt: skip
    assert planted in (refused.value.why or "") and "{}" not in (refused.value.why or "")
    assert entry.exists()  # deleted: nothing


def test_repo_as_a_link_is_not_the_clone(tmp_path: Path, origin_repo: Path) -> None:
    cfg = load(tmp_path)
    place = folder_of(cfg)
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    elsewhere = tmp_path / "elsewhere"
    place.repo.rename(elsewhere)
    place.repo.symlink_to(elsewhere)
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place)
    assert refused.value.detail == "workspace_not_bare"
    assert workspace.beside(place) == ["repo"]


def test_a_folder_without_its_clone_is_refused(tmp_path: Path) -> None:
    place = workspace.locate(tmp_path / "ws", "maity", "agent-3", folder=True)
    place.path.mkdir(parents=True)
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place)
    assert refused.value.detail == "workspace_not_bare"


@pytest.mark.parametrize("level", ["parent", "root"])
@pytest.mark.parametrize("kind", ["dir", "file", "dangling"])
def test_a_folder_inside_a_git_work_tree_is_refused(tmp_path: Path, level: str, kind: str) -> None:
    """agy loads every directory's configuration up to the work tree's root: a `.git` entry
    of any kind in the folder's parent or above refuses the start (`workspace_in_repository`)."""
    outer = tmp_path / "outer"
    root = outer / "ws"
    place = workspace.locate(root, "maity", "agent-3", folder=True)
    (place.repo / ".git").mkdir(parents=True)
    above = place.path.parent if level == "parent" else outer
    if kind == "dir":
        (above / ".git").mkdir()
    elif kind == "file":
        (above / ".git").write_text("gitdir: /elsewhere\n")
    else:
        (above / ".git").symlink_to(tmp_path / "gone")
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place)
    assert refused.value.detail == "workspace_in_repository"
    assert str(above) in (refused.value.why or "")


def test_a_folder_whose_path_is_not_its_real_path_is_refused(tmp_path: Path) -> None:
    """agy takes the work tree from $PWD: a link in the path could lead it into a repository
    the physical walk does not see, so the folder's path must be its real path."""
    real = workspace.locate(tmp_path / "ws", "maity", "agent-3", folder=True)
    (real.repo / ".git").mkdir(parents=True)
    (tmp_path / "linked").symlink_to(tmp_path / "ws")
    place = dataclasses.replace(real, path=tmp_path / "linked" / "maity" / "agent-3")
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place)
    assert refused.value.detail == "workspace_in_repository"
    workspace.check_folder(real)


class Agents(AsUser):
    """The agents' user's side, run here: every read goes through its shell templates."""

    @property
    def direct(self) -> bool:
        return False

    def run(self, argv: Sequence[str], env: Any = None, input: Any = None, cwd: Any = None,
            timeout: float = 60) -> subprocess.CompletedProcess[str]:  # fmt: skip
        return subprocess.run(list(argv), capture_output=True, text=True, input=input,
                              timeout=timeout, check=False)  # fmt: skip


def test_the_agents_users_side_reads_the_folder_alike(tmp_path: Path) -> None:
    place = workspace.locate(tmp_path / "outer" / "ws", "maity", "agent-3", folder=True)
    (place.repo / ".git").mkdir(parents=True)
    for name in ("GEMINI.md", ".agents", "line\nbreak", "..odd", ".x"):
        (place.path / name).mkdir()
    (place.path / "dangling").symlink_to(tmp_path / "gone")
    (tmp_path / "outer" / ".git").mkdir()
    agents = workspace.read_folder(place.path, Agents("a"))
    assert workspace.read_folder(place.path) == agents
    assert agents.names == tuple(sorted(("GEMINI.md", ".agents", "line\nbreak", "..odd", ".x",
                                         "dangling", "repo")))  # fmt: skip
    assert agents.in_repository == (str(tmp_path / "outer"),) and agents.repo_dir
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place, Agents("a"))
    assert refused.value.detail == "workspace_in_repository"
    shutil.rmtree(tmp_path / "outer" / ".git")
    with pytest.raises(workspace.Refused) as refused:
        workspace.check_folder(place, Agents("a"))
    assert refused.value.detail == "workspace_not_bare"
    assert "line?break" in (refused.value.why or "")  # printable in the log


def test_no_clone_moves_between_the_layouts(tmp_path: Path, origin_repo: Path) -> None:
    """A path recorded in the other layout is `workspace_in_use` (§15.5)."""
    cfg = load(tmp_path)
    assert cfg.local is not None
    plain = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    workspace.prepare(cfg, plain, str(origin_repo), "agt-3", "plc-0003")
    with pytest.raises(workspace.Refused) as refused:
        workspace.prepare(cfg, folder_of(cfg), str(origin_repo), "agt-3", "plc-0004")
    assert (refused.value.reason, refused.value.detail) == ("workspace_in_use",
                                                            "workspace_unrecorded")  # fmt: skip
    place = folder_of(cfg, 5)
    workspace.prepare(cfg, place, str(origin_repo), "agt-5", "plc-0005")
    moved = workspace.locate(cfg.local.workspaces, "maity", "agent-5")
    with pytest.raises(workspace.Refused) as refused:
        workspace.inspect(cfg, moved, str(origin_repo), "agt-5", "plc-0006")
    assert refused.value.detail == "workspace_unrecorded"


def test_an_existing_folder_takes_the_clone_only_when_empty(
    tmp_path: Path, origin_repo: Path
) -> None:
    cfg = load(tmp_path)
    place = folder_of(cfg)
    place.path.mkdir(parents=True)  # an earlier start made it, then its clone failed
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    assert workspace.origin(place.repo) == str(origin_repo)
    stray = folder_of(cfg, 4)
    stray.path.mkdir(parents=True)
    (stray.path / ".agents").mkdir()
    with pytest.raises(workspace.Refused) as refused:
        workspace.prepare(cfg, stray, str(origin_repo), "agt-4", "plc-0004")
    assert refused.value.detail == "workspace_not_bare"
    assert (stray.path / ".agents").is_dir() and not stray.repo.exists()


@pytest.mark.parametrize("direct", [True, False])
def test_other_folders_credentials_are_private(tmp_path: Path, direct: bool) -> None:
    ws = tmp_path / "ws"
    own = ws / "maity" / "agent-3" / "repo"
    for clone in (own, ws / "maity" / "agent-4" / "repo", ws / "maity" / "agent-5"):
        (clone / ".git" / "maity").mkdir(parents=True)
    found = supervisor.other_credentials(ws, own, AsUser() if direct else Agents("a"))
    assert found == [ws / "maity" / "agent-4" / "repo" / ".git" / "maity",
                     ws / "maity" / "agent-5" / ".git" / "maity"]  # fmt: skip


def test_the_agents_home_hides_agys_directory_from_other_sandboxes(tmp_path: Path) -> None:
    clone = tmp_path / "ws" / "maity" / "agent-3"
    assert tmp_path / "home" / ".gemini" in supervisor.private_paths(None, tmp_path / "home", clone)


# --- the supervisor ---------------------------------------------------------------------------


@dataclass
class Backend(FakeTmux):
    """The supervisor's fake tmux, keeping the directory each session starts in."""

    cwds: list[Path] = field(default_factory=list)

    def start(self, name: str, cwd: Path, argv: Sequence[str], env: dict[str, str],
              placement: str, generation: int) -> None:  # fmt: skip
        self.cwds.append(cwd)
        super().start(name, cwd, argv, env, placement, generation)


def placement(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "plc-0003", "project": "oliver/maity", "project_id": "maity",
        "generation": 1, "desired": "running",
        "agent": {"id": "agt-3", "handle": "agent-3", "member": True,
                  "credential_expected": True},
        "harness": "antigravity", "mode": "supervised", "model": None, "target": None,
        "workspace": {"clone": "agent-3", "branch": None, "repository": REPO},
        "rejoin": False, "stop_grace_seconds": 120, "seq": 0,
    }  # fmt: skip
    data.update(overrides)
    return data


def recorded_folder(cfg: config.Config) -> workspace.Workspace:
    place = folder_of(cfg)
    (place.repo / ".git" / "maity").mkdir(parents=True, mode=0o700)
    (place.repo / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPO}.git\n')
    (place.repo / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    workspace.record(cfg.state_dir, place, "agt-3", "plc-0003")
    return place


def started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sandbox: bool = False
) -> tuple[Any, Backend, list[str]]:
    monkeypatch.setattr(capabilities, "sandbox_available", lambda h, p=None, a=None: sandbox)
    cfg = load(tmp_path)
    backend, logs = Backend(), list[str]()
    probes = {"stub": capabilities.Probe(None, None, None),
              "antigravity": capabilities.Probe("/usr/bin/agy", "1.5.7", None)}  # fmt: skip
    monkeypatch.setattr(clonecheck, "not_inspectable", lambda path, as_user=None: None)
    sup = supervisor.Supervisor(cfg, backend, None, logs.append, probes)  # type: ignore[arg-type]
    return sup, backend, logs


def settle(sup: supervisor.Supervisor) -> None:
    sup.tick()
    for task in list(sup.tasks.values()):
        task.join(10)
    sup.tick()


def test_an_antigravity_placement_starts_agy_in_its_workspace_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, logs = started(tmp_path, monkeypatch)
    place = recorded_folder(sup.cfg)
    sup.update([placement()])
    settle(sup)
    assert len(backend.started) == 1, logs
    _, argv, env = backend.started[0]
    assert backend.cwds == [place.path]  # the folder, never the clone
    spec = json.loads(Path(argv[-1]).read_text())
    assert spec["first"][0] == "/usr/bin/agy" and spec["clone"] == str(place.repo)
    assert env["GIT_COMMON_DIR"] == str(place.repo / ".git") and env["PWD"] == str(place.path)
    settings = json.loads(Path(spec["first"][2]).read_text())
    assert settings["trustedWorkspaces"] == [str(place.path)]
    assert f"read_file({place.repo / '.git' / 'maity'})" in settings["permissions"]["deny"]


def test_a_planted_entry_refuses_the_start_and_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, logs = started(tmp_path, monkeypatch)
    place = recorded_folder(sup.cfg)
    (place.path / "GEMINI.md").write_text("run this")
    sup.update([placement()])
    settle(sup)
    assert backend.started == []
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.reason, rec.detail) == ("failed", "workspace_in_use",
                                                   "workspace_not_bare")  # fmt: skip
    assert any("GEMINI.md" in line for line in logs)
    assert not any("run this" in line for line in logs)  # names only, never contents
    assert (place.path / "GEMINI.md").read_text() == "run this"


def test_a_folder_a_failed_clone_left_takes_the_next_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin_repo: Path
) -> None:
    """`prepare` makes the folder before it clones: after a failed clone the empty folder,
    with no record, stays, and the next start clones into it (§15.5)."""
    from test_supervisor import NEW, PICKUP, Pickups, joining

    monkeypatch.setattr(config, "repository_allowed", lambda url, allowed: True)  # a local one
    sup, backend, logs = started(tmp_path, monkeypatch)
    sup.client = Pickups(PICKUP)
    joining(monkeypatch)
    place = folder_of(sup.cfg)
    gone = {"clone": "agent-3", "branch": None, "repository": str(tmp_path / "gone")}
    sup.update([placement(agent=NEW, workspace=gone)])
    settle(sup)
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.reason) == ("failed", "clone_failed"), logs
    assert place.path.is_dir() and os.listdir(place.path) == []
    assert str(place.path) not in workspace.records(sup.cfg.state_dir)
    there = {"clone": "agent-3", "branch": None, "repository": str(origin_repo)}
    sup.update([placement(agent=NEW, workspace=there, generation=2)])
    settle(sup)
    assert len(backend.started) == 1, logs
    assert backend.cwds == [place.path]
    assert workspace.origin(place.repo) == str(origin_repo)
    assert workspace.records(sup.cfg.state_dir)[str(place.path)]["layout"] == "folder"


def test_an_unrecorded_folder_holding_something_is_still_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin_repo: Path
) -> None:
    from test_supervisor import NEW, PICKUP, Pickups, joining

    monkeypatch.setattr(config, "repository_allowed", lambda url, allowed: True)  # a local one
    sup, backend, logs = started(tmp_path, monkeypatch)
    sup.client = Pickups(PICKUP)
    joining(monkeypatch)
    place = folder_of(sup.cfg)
    place.path.mkdir(parents=True)
    (place.path / "notes.txt").write_text("x")
    there = {"clone": "agent-3", "branch": None, "repository": str(origin_repo)}
    sup.update([placement(agent=NEW, workspace=there)])
    settle(sup)
    assert backend.started == []
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.reason, rec.detail) == ("failed", "workspace_in_use",
                                                   "workspace_not_bare")  # fmt: skip
    assert (place.path / "notes.txt").read_text() == "x" and not place.repo.exists()


@pytest.mark.parametrize("recorded_as", ["other_agent", "clone"])
def test_a_recorded_folder_not_this_agents_is_refused_before_its_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recorded_as: str
) -> None:
    sup, backend, _ = started(tmp_path, monkeypatch)
    place = folder_of(sup.cfg)
    place.path.mkdir(parents=True)
    if recorded_as == "other_agent":
        workspace.record(sup.cfg.state_dir, place, "agt-4", "plc-0004")
    else:
        plain = dataclasses.replace(place, folder=False)
        workspace.record(sup.cfg.state_dir, plain, "agt-3", "plc-0003")
    sup.update([placement()])
    sup.tick()
    assert backend.started == [] and sup.tasks == {}
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.reason) == ("failed", "workspace_in_use")
    assert rec.detail == ("other_agent" if recorded_as == "other_agent"
                          else "workspace_unrecorded")  # fmt: skip


def test_the_loop_checks_the_folder_before_every_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """47me F1: an entry planted between two runs of the supervised loop stops it with the
    supervisor's refusal; the next run never starts, and only the name is logged."""
    sup, backend, _ = started(tmp_path, monkeypatch)
    place = recorded_folder(sup.cfg)
    sup.update([placement()])
    settle(sup)
    _, argv, _ = backend.started[0]
    spec = json.loads(Path(argv[-1]).read_text())
    assert spec["folder"] == str(place.path)
    ran: list[list[str]] = []
    logs: list[str] = []

    def run(argv: list[str], env: dict[str, str]) -> int:
        ran.append(argv)
        (place.path / "GEMINI.md").write_text("run this")  # what the run leaves behind
        return 0

    events = iter([(0, '{"seq": 5}', "")])
    the_loop = loop.Loop(spec, run, lambda: next(events), sleep=lambda s: None, log=logs.append)
    assert the_loop.main() == loop.EXIT_FOLDER["workspace_not_bare"] == 24
    assert ran == [spec["first"]]  # the second run was refused before it started
    assert any("GEMINI.md" in line for line in logs)
    assert not any("run this" in line for line in logs)
    assert (place.path / "GEMINI.md").read_text() == "run this"  # nothing deleted
    # The runner maps the loop's exit to the refusal it reports before a start.
    backend.exit(next(iter(backend.live)), 24)
    sup.tick()
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.reason, rec.detail, rec.retry_at) == (
        "failed", "workspace_in_use", "workspace_not_bare", None
    )  # fmt: skip


def test_the_loop_checks_the_folder_after_a_failed_run_too(tmp_path: Path) -> None:
    folder = tmp_path.resolve() / "ws"
    (folder / "repo").mkdir(parents=True)
    spec = {"first": ["agy"], "again": ["agy", "-c"], "folder": str(folder),
            "restart": {"initial": 1, "factor": 2, "max": 4, "crash_window": 600,
                        "crash_cap": 9, "quick_exit": 0}}  # fmt: skip
    ran: list[list[str]] = []

    def run(argv: list[str], env: dict[str, str]) -> int:
        ran.append(argv)
        (tmp_path / ".git").mkdir()  # a work tree above the folder appears
        return 1

    the_loop = loop.Loop(spec, run, lambda: (3, "", ""), sleep=lambda s: None, log=lambda _: None)
    assert the_loop.main() == loop.EXIT_FOLDER["workspace_in_repository"]
    assert ran == [["agy"]]


def test_a_loop_without_a_folder_checks_nothing() -> None:
    spec = {"first": ["claude"], "again": ["claude"], "restart": {}}
    checked: list[str] = []
    the_loop = loop.Loop(spec, lambda argv, env: 0, lambda: (3, "", ""), check=checked.append)
    assert the_loop.refused() is None and checked == []


def test_an_interactive_restart_checks_the_folder_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restart of an interactive session (after an exit, or after the idle check ended it,
    `-c -i`) is a new start: the folder is checked before it, as before the first."""
    sup, backend, logs = started(tmp_path, monkeypatch)
    place = recorded_folder(sup.cfg)
    clock = [1_800_000_000.0]
    sup.now = lambda: clock[0]
    sup.update([placement(mode="interactive")])
    settle(sup)
    assert len(backend.started) == 1, logs
    backend.exit(next(iter(backend.live)), 1)
    sup.tick()
    rec = sup.records["plc-0003"]
    assert rec.state == "exited" and rec.retry_at is not None
    rec.resume = True  # as after the idle check's end: the restart is `-c -i`
    (place.path / "GEMINI.md").write_text("run this")
    clock[0] = rec.retry_at + 1
    settle(sup)
    assert len(backend.started) == 1  # no second start
    assert (rec.state, rec.reason, rec.detail) == ("failed", "workspace_in_use",
                                                   "workspace_not_bare")  # fmt: skip
    (place.path / "GEMINI.md").unlink()  # with the entry gone, the same restart is `-c -i`
    rec.enter(clock[0], "exited", retry_at=clock[0])
    clock[0] += 1
    settle(sup)
    assert len(backend.started) == 2, logs
    assert backend.started[1][1][-3:-1] == ["-c", "-i"]


def test_running_without_agys_sandbox_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _ = started(tmp_path, monkeypatch, sandbox=False)
    recorded_folder(sup.cfg)
    clock = [1_800_000_000.0]
    sup.now = lambda: clock[0]
    sup.update([placement()])
    settle(sup)
    clock[0] += supervisor.RUNNING_AFTER + 1
    sup.tick()
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.detail) == ("running", "sandbox_unavailable")


# --- removal and claim ------------------------------------------------------------------------


def test_gc_lists_what_lies_beside_the_clone_and_removes_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = load(tmp_path)
    path = tmp_path / "runner.toml"
    place = folder_of(cfg)
    place.repo.mkdir(parents=True)
    git(place.repo, "init", "-q")
    (place.repo / "draft.txt").write_text("unsaved")
    (place.path / "notes.md").write_text("left beside")
    workspace.record(cfg.state_dir, place, "agt-g", "plc-0007")
    monkeypatch.setattr(operate, "credential_revoked", lambda place, as_user: True)
    monkeypatch.setattr(operate, "_active", lambda cfg: (set(), set()))
    assert cli.main(["runner", "gc", "--revoked", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "?? draft.txt" in out and "notes.md (beside the clone)" in out
    assert place.path.exists()
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert not place.path.exists()  # the folder as a whole, on the operator's --yes
    assert str(place.path) not in workspace.records(cfg.state_dir)


def test_gc_leaves_a_folder_whose_repo_is_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = load(tmp_path)
    place = folder_of(cfg)
    place.path.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    git(elsewhere, "init", "-q")
    place.repo.symlink_to(elsewhere)
    workspace.record(cfg.state_dir, place, "agt-g", "plc-0007")
    monkeypatch.setattr(operate, "credential_revoked", lambda place, as_user: True)
    monkeypatch.setattr(operate, "_active", lambda cfg: (set(), set()))
    path = tmp_path / "runner.toml"
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert "not removed" in capsys.readouterr().out
    assert place.path.exists() and elsewhere.exists()


def test_claim_records_a_workspace_folder_as_one(tmp_path: Path) -> None:
    cfg = load(tmp_path)
    place = folder_of(cfg)
    place.repo.mkdir(parents=True)
    git(place.repo, "init", "-q")
    path = tmp_path / "runner.toml"
    assert cli.main(["runner", "workspace", "claim", "maity/agent-3", "--agent", "agt-3",
                     "--config", str(path)]) == 0  # fmt: skip
    assert workspace.records(cfg.state_dir)[str(place.path)]["layout"] == "folder"


# --- maity runner check -----------------------------------------------------------------------


def checked(
    monkeypatch: pytest.MonkeyPatch, namespaces: bool, home: Path,
    harness: config.Harness = AGY, platform: bool = True,
) -> list[tuple[str, str]]:  # fmt: skip
    monkeypatch.setattr(AsUser, "home", lambda self: home)
    monkeypatch.setattr(capabilities, "agy_sandbox_platform", lambda p=None: platform)
    monkeypatch.setattr(capabilities, "agy_namespaces", lambda path, as_user=None: namespaces)
    report = commands.Report()
    commands._check_antigravity(report, harness, AsUser(), "/usr/bin")
    return report.lines


OFF = "harness antigravity: sandbox reported off: the runner has not seen agy's sandbox start"


def test_check_reports_agys_sandbox_off_and_the_namespaces_as_a_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§15.3: namespaces that start are a diagnostic; the sandbox stays reported off."""
    login = tmp_path / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    login.parent.mkdir(parents=True)
    login.write_text("secret")
    lines = checked(monkeypatch, True, tmp_path)
    assert lines == [
        ("ok", "harness antigravity: the namespaces agy's terminal sandbox needs start; agy's "
               "sandbox start not verified"),
        ("warn", OFF + "; agents run as `sandbox_unavailable`"),
    ]  # fmt: skip
    login.unlink()
    lines = checked(monkeypatch, False, tmp_path)
    assert [level for level, _ in lines] == ["warn", "warn", "warn"]
    assert "do not start" in lines[0][1] and OFF in lines[1][1] and "no sign-in" in lines[2][1]
    strict = dataclasses.replace(AGY, require_sandbox=True)
    for namespaces in (True, False):  # refused whether the namespaces start or not
        found = checked(monkeypatch, namespaces, tmp_path, strict)
        assert found[1] == ("error", OFF + "; agents run as `sandbox_unavailable`, and "
                                           "require_sandbox = true refuses them")  # fmt: skip
    assert "on this platform" in checked(monkeypatch, True, tmp_path, platform=False)[0][1]
    assert not any("secret" in text for _, text in lines)


def test_check_warns_about_the_agents_users_own_agy_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_dir = tmp_path / ".gemini" / "antigravity-cli"
    cli_dir.mkdir(parents=True)
    (cli_dir / "antigravity-oauth-token").write_text("x")
    (cli_dir / "settings.json").write_text(json.dumps({"permissions": {"allow": ["command(*)"]}}))
    (tmp_path / ".gemini" / "config").mkdir()
    (tmp_path / ".gemini" / "config" / "mcp_config.json").write_text('{"mcpServers": {"x": {}}}')
    lines = checked(monkeypatch, True, tmp_path)
    assert [level for level, _ in lines] == ["ok", "warn", "warn", "warn"]
    assert "allows 1 rule(s)" in lines[2][1] and "MCP servers" in lines[3][1]
    (tmp_path / ".gemini" / "config" / "mcp_config.json").write_text("")  # as agy creates it
    (cli_dir / "settings.json").write_text(json.dumps({"trustedWorkspaces": ["/x"]}))
    assert [level for level, _ in checked(monkeypatch, True, tmp_path)] == ["ok", "warn"]


def test_check_refuses_workspaces_inside_a_work_tree(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    report = commands.Report()
    commands._check_agy_workspaces(report, tmp_path / "ws", AsUser())
    assert report.failed and "workspace_in_repository" in report.lines[0][1]
    shutil.rmtree(tmp_path / ".git")
    clean = commands.Report()
    commands._check_agy_workspaces(clean, tmp_path / "ws", AsUser())
    assert not clean.failed
