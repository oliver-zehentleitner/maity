from __future__ import annotations

import json
import os
import stat
import sys
import tomllib
from pathlib import Path

import fakehub
import pytest

from maity import cli, state
from maity.runner import commands, config

MINIMAL = """\
[hub]
url = "{url}"
state_dir = "{state_dir}"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]
"""


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A HOME of its own: the default configuration and state directory live under it."""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("HOME", str(path))
    monkeypatch.delenv("MAITY_RUNNER_CONFIG", raising=False)
    return path


def parse(text: str) -> config.Config:
    loaded = tomllib.loads(text)
    return config.parse(loaded, Path("runner.toml"))


def problems(text: str) -> list[str]:
    with pytest.raises(config.ConfigError) as info:
        parse(text)
    return info.value.problems


def minimal(**extra: str) -> str:
    return MINIMAL.format(url="https://hub.example", state_dir="/srv/state") + "".join(
        extra.values()
    )


# --- configuration ---------------------------------------------------------------------------


def test_minimal_configuration_takes_the_defaults() -> None:
    cfg = parse(minimal())
    assert cfg.backend == "local"
    assert cfg.limits.max_agents == 4
    assert cfg.limits.stop_grace_max == 120
    assert cfg.limits.log_keep_bytes == 10 * 1024 * 1024
    assert (cfg.limits.restart.initial, cfg.limits.restart.max) == (10, 300)
    assert (cfg.limits.restart.crash_cap, cfg.limits.restart.crash_window) == (5, 1800)
    assert cfg.local is not None
    assert cfg.local.tmux_socket == Path("/srv/state/tmux.sock")
    assert cfg.local.agent_path is None
    assert cfg.local.layout == "single"
    assert cfg.harnesses["stub"].modes == ("supervised",)


def test_tilde_is_expanded(home: Path) -> None:
    cfg = parse(MINIMAL.format(url="https://hub.example", state_dir="~/st"))
    assert cfg.state_dir == home / "st"
    assert cfg.local is not None
    assert cfg.local.workspaces == home / "maity-workspaces"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            'url = "https://hub.example"\n',
            'url = "https://hub.example"\ncolour = 1\n',
            "hub.colour",
        ),
        ("[limits]\n", "[limits]\nmax_agent = 2\n", "limits.max_agent"),
        ("[harness.stub]\n", "[harness.stub]\nmodel = 1\n", "harness.stub.model"),
        ("[hub]\n", "surprise = true\n[hub]\n", "surprise"),
    ],
)
def test_unknown_keys_are_named(old: str, new: str, expected: str) -> None:
    assert f"{expected}: unknown key" in problems(minimal().replace(old, new, 1))


def test_unknown_key_in_backend_local() -> None:
    assert "backend.local.tmux: unknown key" in problems(minimal(b="\n[backend.local]\ntmux = 1\n"))


def test_required_keys() -> None:
    found = problems('[hub]\nstate_dir = "/s"\n')
    assert "hub.url: required" in found
    assert "limits: required" in found
    assert "harness: required" in found


@pytest.mark.parametrize(
    ("given", "normal"),
    [
        ("https://GitHub.com/o/n.git", "github.com/o/n"),
        ("https://github.com/o/n/", "github.com/o/n"),
        ("http://user@Git.Example:8443/o/n.git/", "git.example:8443/o/n"),
        ("github.com/o/n", "github.com/o/n"),
        ("github.com/O/N", "github.com/O/N"),
        ("github.com/o/*", "github.com/o/*"),
    ],
)
def test_normalise_repository(given: str, normal: str) -> None:
    assert config.normalise_repository(given) == normal


def test_repositories_are_normalised_and_matched_alike() -> None:
    cfg = parse(
        minimal().replace(
            "github.com/oliver-zehentleitner/maity",
            "https://GitHub.com/oliver-zehentleitner/maity.git",
        )
    )
    allowed = cfg.limits.repositories
    assert allowed == ("github.com/oliver-zehentleitner/maity",)
    assert config.repository_allowed("https://github.com/oliver-zehentleitner/maity.git", allowed)
    assert not config.repository_allowed("https://github.com/oliver-zehentleitner/other", allowed)
    owner = ("github.com/oliver-zehentleitner/*",)
    assert config.repository_allowed("https://GITHUB.com/oliver-zehentleitner/other/", owner)
    assert not config.repository_allowed("https://github.com/someone/other", owner)


@pytest.mark.parametrize(
    "entry", ["github.com/*/n", "github.com/o/n*", "*/o/n", "github.com/o", "github.com/o/n/x"]
)
def test_only_the_owner_wide_glob_is_accepted(entry: str) -> None:
    found = problems(minimal().replace("github.com/oliver-zehentleitner/maity", entry))
    assert any(p.startswith("limits.repositories:") for p in found), found


@pytest.mark.parametrize(
    "rule",
    [
        "FOO=1 make test",
        "FOO+=1 make test",
        "env make test",
        "/usr/bin/env FOO=1 make test",
        "make test && maity report *",
        "make test; ./maity report",
        "maity *",
        "maity:*",
        "maity.exe *",
        "MAITY.CMD report",
        "/home/a/.local/bin/maity report",
        "xargs maity",
        "xargs /tmp/tools:local/maity",
        "cmd /c C:/tools/maity.exe",
        "xargs C:/bin/MAITY.CMD",
        "cmd /c C:maity.exe",
        "find . -exec=maity",
        "make $TARGET",
        "make `id`",
        "make test | tee out",
        "make\ttest",
        "* make",
        '"maity" *',
        "'maity' report",
        'make "a b"',
    ],
)
def test_a_repository_grant_allows_only_plain_commands(rule: str) -> None:
    """A program and plain arguments only: nothing set in front of it, no quotes, variables
    or shell operators, and not maity in any spelling, which is granted on its own and runs
    outside the harness's sandbox."""
    allow = json.dumps(rule)  # a JSON string is a TOML basic string
    grant = f'\n[repositories."github.com/oliver-zehentleitner/maity"]\nallow = [{allow}]\n'
    found = problems(minimal(grant=grant))
    assert any("not a plain command" in p and repr(rule) in p for p in found), found


@pytest.mark.parametrize("rule", ["make  test", " make test", "make test "])
def test_a_grant_with_a_run_of_spaces_says_single_spaces(rule: str) -> None:
    """The grammar takes single spaces between words; a run of them is refused, and the
    message says why instead of leaving the empty word to be guessed."""
    grant = (
        f'\n[repositories."github.com/oliver-zehentleitner/maity"]\nallow = [{json.dumps(rule)}]\n'
    )
    found = problems(minimal(grant=grant))
    assert any("single spaces" in p and repr(rule) in p for p in found), found


def test_a_refused_grant_without_extra_spaces_names_no_spacing() -> None:
    grant = '\n[repositories."github.com/oliver-zehentleitner/maity"]\nallow = ["make $TARGET"]\n'
    found = problems(minimal(grant=grant))
    assert any("not a plain command" in p for p in found) and not any(
        "single spaces" in p for p in found
    )


def test_a_plain_repository_grant_is_kept() -> None:
    grant = (
        '\n[repositories."github.com/oliver-zehentleitner/maity"]\n'
        'allow = ["make test", "uv run pytest *", "./gradlew build --info", "pip show maity-hub"]\n'
    )
    cfg = parse(minimal(grant=grant))
    assert cfg.repositories["github.com/oliver-zehentleitner/maity"].allow == (
        "make test",
        "uv run pytest *",
        "./gradlew build --info",
        "pip show maity-hub",
    )


def test_harness_without_allowlist_is_refused() -> None:
    found = problems(minimal(pi="\n[harness.pi]\n"))
    assert any(p.startswith("harness.pi: has no command allowlist") for p in found)


def test_unknown_harness_and_later_backends() -> None:
    found = problems(minimal(x="\n[harness.vim]\n", b='\n[backend]\nkind = "k8s"\n'))
    assert any(p.startswith("harness.vim: unknown harness") for p in found)
    assert any(p.startswith("backend.k8s: not supported") for p in found)


def test_default_mode_must_be_a_mode() -> None:
    text = '\n[harness.codex]\nmodes = ["supervised"]\ndefault_mode = "interactive"\n'
    assert "harness.codex.default_mode: must be one of its modes" in problems(minimal(c=text))


def test_stop_grace_max_stays_in_the_hub_range() -> None:
    text = minimal().replace("[limits]\n", "[limits]\nstop_grace_max = 901\n")
    assert any(p.startswith("limits.stop_grace_max:") for p in problems(text))


def test_hub_url_follows_the_join_rule() -> None:
    found = problems(minimal().replace("https://hub.example", "http://hub.example"))
    assert any(p.startswith("hub.url: refusing plain HTTP") for p in found), found
    assert "hub.url" not in " ".join(
        problems(minimal().replace("https://hub.example", "http://127.0.0.1:8090") + "x = 1\n")
    )


def test_harness_modes_and_models() -> None:
    assert "harness.stub.modes: name at least one mode" in problems(
        minimal().replace("[harness.stub]\n", "[harness.stub]\nmodes = []\n")
    )
    assert "harness.stub.default_model: must be one of its models" in problems(
        minimal().replace("[harness.stub]\n", '[harness.stub]\ndefault_model = "m"\n')
    )


def test_every_bad_repository_is_named() -> None:
    bad = ", ".join(f'"x/{n}"' for n in range(5))
    found = problems(minimal().replace('"github.com/oliver-zehentleitner/maity"', bad))
    (line,) = [p for p in found if p.startswith("limits.repositories:")]
    assert all(f"'x/{n}'" in line for n in range(5))


def test_backend_local_is_not_judged_under_another_kind() -> None:
    found = problems(minimal(b='\n[backend]\nkind = "ssh"\n[backend.local]\nlayout = "x"\n'))
    assert not any(p.startswith("backend.local") for p in found), found


def test_the_runner_ignores_maity_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAITY_STATE_DIR", str(tmp_path / "agent"))
    cfg = parse(minimal())
    assert cfg.state_dir == Path("/srv/state")


# --- pair ------------------------------------------------------------------------------------


def pair_url(fake: fakehub.FakeHub) -> str:
    return f"{fake.url}/r/{fakehub.PAIR_TOKEN}"


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_pair_without_configuration_writes_one_and_never_prints_the_credential(
    home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE])
    assert code == 0
    out = capsys.readouterr()
    assert fakehub.SECRET not in out.out + out.err
    assert "rnr-0002" in out.err and "maity, sample" in out.err
    written = home / ".config" / "maity-runner" / "runner.toml"
    assert mode(written) == 0o600 and mode(written.parent) == 0o700
    url, state_dir = commands._hub_table(written)
    assert url == fake.url
    assert state_dir == home / ".local" / "state" / "maity-runner"
    credential = state_dir / "credential"
    assert credential.read_text() == fakehub.RUNNER_CREDENTIAL
    assert mode(credential) == 0o600 and mode(state_dir) == 0o700
    saved = state.load_state(state_dir, name=commands.STATE_FILE)
    assert saved == {
        "hub": fake.url,
        "runner_id": "rnr-0002",
        "credential_id": fakehub.RUNNER_CREDENTIAL_ID,
    }
    assert not (state_dir / state.STATE_FILE).exists()


def test_pair_refuses_a_hub_url_off_the_pair_host(
    home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.hub_header = "https://evil.example"
    code = cli.main(["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE])
    assert code == cli.EXIT_ERROR
    assert "nothing was stored" in capsys.readouterr().err
    assert not (home / ".config").exists() and not (home / ".local").exists()


def test_pair_reads_the_code_from_stdin(
    home: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO(fakehub.PAIR_CODE + "\n"))
    assert cli.main(["runner", "pair", pair_url(fake), "--code-file", "-"]) == 0


def test_pair_uses_the_configured_state_dir(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(MINIMAL.format(url=fake.url, state_dir=tmp_path / "st"))
    code = cli.main(
        ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
    )
    assert code == 0
    assert (tmp_path / "st" / "credential").read_text() == fakehub.RUNNER_CREDENTIAL
    assert not (home / ".config").exists()


def test_pair_refuses_a_configuration_for_another_hub(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(MINIMAL.format(url="https://other.example", state_dir=tmp_path / "st"))
    code = cli.main(
        ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
    )
    assert code == cli.EXIT_USAGE
    assert "--config" in capsys.readouterr().err
    assert not fake.pair_used


def test_pair_refuses_an_existing_credential(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(MINIMAL.format(url=fake.url, state_dir=tmp_path / "st"))
    state.write_credential(tmp_path / "st", state.Secret(fakehub.RUNNER_CREDENTIAL))
    code = cli.main(
        ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
    )
    assert code == cli.EXIT_USAGE
    assert not fake.pair_used


def test_wrong_code_writes_nothing(home: Path, fake: fakehub.FakeHub) -> None:
    code = cli.main(["runner", "pair", pair_url(fake), "--code", "AAAA-BBBB-CCCC"])
    assert code == cli.EXIT_ERROR
    assert not (home / ".config").exists()
    assert not (home / ".local").exists()


@pytest.mark.parametrize(
    "url", ["https://h/r/", "https://h/j/abc", "https://h/r/a/b", "https://h/api/v1/join/a"]
)
def test_pair_token_refuses(url: str) -> None:
    from maity import hub

    with pytest.raises(hub.HubError):
        hub.pair_token(url)


def test_pair_token_accepts_both_forms() -> None:
    from maity import hub

    assert hub.pair_token("https://h/r/Xb7") == "Xb7"
    assert hub.pair_token("https://h/api/v1/runners/pair/Xb7/") == "Xb7"


def test_pair_refuses_plain_http_off_loopback(home: Path) -> None:
    assert cli.main(["runner", "pair", "http://hub.example/r/x", "--code", "c"]) == cli.EXIT_ERROR


def test_pair_accepts_a_config_directory_the_operator_made(
    home: Path, fake: fakehub.FakeHub
) -> None:
    directory = home / ".config" / "maity-runner"
    directory.mkdir(parents=True)
    directory.chmod(0o775)  # noqa: S103 - an operator's directory, no secret in it
    assert cli.main(["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE]) == 0
    assert mode(directory / "runner.toml") == 0o600 and mode(directory) == 0o775


def test_pair_refuses_a_loose_state_dir_before_sending(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(MINIMAL.format(url=fake.url, state_dir=tmp_path / "st"))
    (tmp_path / "st").mkdir(mode=0o775)
    (tmp_path / "st").chmod(0o775)  # noqa: S103 - the loose mode is the point
    code = cli.main(
        ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
    )
    assert code == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert "chmod 700" in err and "revoke the runner" in err and "session" not in err
    assert not fake.pair_used


def test_pair_refuses_a_state_dir_it_cannot_create(
    tmp_path: Path, home: Path, fake: fakehub.FakeHub
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    path = tmp_path / "runner.toml"
    path.write_text(MINIMAL.format(url=fake.url, state_dir=locked / "st"))
    try:
        code = cli.main(
            ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
        )
    finally:
        locked.chmod(0o700)
    assert code == cli.EXIT_USAGE
    assert not fake.pair_used


def test_a_config_that_cannot_be_written_keeps_the_credential(
    home: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip

    def fail(path: Path, text: str) -> Path:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(state, "write_file", fail)
    code = cli.main(["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE])
    assert code == cli.EXIT_ERROR
    credential = home / ".local" / "state" / "maity-runner" / "credential"
    assert credential.read_text() == fakehub.RUNNER_CREDENTIAL
    err = capsys.readouterr().err
    assert "the credential is stored" in err and f'url = "{fake.url}"' in err
    assert fakehub.SECRET not in err


# --- check -----------------------------------------------------------------------------------


@pytest.fixture
def paired(tmp_path: Path, home: Path, fake: fakehub.FakeHub) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(
        MINIMAL.format(url=fake.url, state_dir=tmp_path / "st")
        + f'\n[backend.local]\nworkspaces = "{tmp_path / "ws"}"\n'
    )
    path.chmod(0o644)  # whatever the umask: the operator's file, writable by them only
    assert (
        cli.main(
            ["runner", "pair", pair_url(fake), "--code", fakehub.PAIR_CODE, "--config", str(path)]
        )
        == 0
    )
    return path


def fake_tool(bin_dir: Path, name: str, output: str = "") -> None:
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\necho '{output}'\n")
    script.chmod(0o755)


def lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_check_passes_on_a_paired_runner(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    capsys.readouterr()
    code = cli.main(["runner", "check", "--config", str(paired)])
    out = lines(capsys)
    assert code == 0, out
    assert all(line.startswith("ok") for line in out), out
    assert any("answers" in line for line in out)


def test_check_reports_every_problem_and_exits_1(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paired.write_text(paired.read_text() + '\n[harness.codex]\nbinary = "codex-missing"\n')
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    out = lines(capsys)
    assert any(line.startswith("error  tmux is not installed") for line in out)
    assert any("codex-missing" in line and line.startswith("error") for line in out)


def test_check_finds_the_harness_and_its_version(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "codex", "codex-cli 0.40.0")
    paired.write_text(paired.read_text() + "\n[harness.codex]\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert any("(0.40.0)" in line for line in lines(capsys))


def test_check_warns_about_inherited_claude_settings(
    paired: Path, bin_dir: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", "2.1.318 (Claude Code)")  # the checked one: no warning for it
    fake_tool(bin_dir, "bwrap")
    fake_tool(bin_dir, "socat")
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}, "hooks": {"Stop": []}}'
    )
    paired.write_text(
        paired.read_text()
        + '\n[harness.claude-code]\n\n[git]\nname = "Your Team"\nemail = "team@example.org"\n'
    )
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    warnings = [line for line in lines(capsys) if line.startswith("warn")]
    assert len(warnings) == 2, warnings


@pytest.mark.parametrize(("version", "warned"), [("2.1.318", False), ("2.1.330", True)])
def test_check_warns_when_claude_code_is_not_the_checked_version(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], version: str, warned: bool
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", f"{version} (Claude Code)")
    fake_tool(bin_dir, "bwrap")
    fake_tool(bin_dir, "socat")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0  # no block
    found = [line for line in lines(capsys) if "sandbox was checked with 2.1.318" in line]
    assert bool(found) is warned, found
    assert all(line.startswith("warn") for line in found)


def test_check_requires_the_sandbox_when_configured(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("the sandbox prerequisites are checked on Linux")
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", "2.1.308")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\nrequire_sandbox = true\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    assert any("no OS sandbox" in line and line.startswith("error") for line in lines(capsys))


@pytest.mark.parametrize(
    ("platform", "tools", "said", "code"),
    [
        ("linux", ("bwrap", "socat"), "ok     harness claude-code: OS sandbox (bwrap, socat)", 0),
        ("darwin", ("sandbox-exec",), "ok     harness claude-code: OS sandbox (sandbox-exec)", 0),
        ("darwin", ("bwrap", "socat"), "error  harness claude-code: no OS sandbox "
         "(sandbox-exec missing)", 1),
        ("freebsd14", ("bwrap", "socat", "sandbox-exec"), "error  harness claude-code: no OS "
         "sandbox on freebsd14; agents run unsandboxed", 1),
    ],
)  # fmt: skip
def test_check_names_claude_codes_sandbox_for_the_platform(
    paired: Path,
    bin_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    tools: tuple[str, ...],
    said: str,
    code: int,
) -> None:
    """Seatbelt on macOS, bubblewrap and socat on Linux; anywhere else `check` says that the
    agents run unsandboxed, and `require_sandbox` makes that an error."""
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", "2.1.318")
    for tool in tools:
        fake_tool(bin_dir, tool)
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\nrequire_sandbox = true\n")
    monkeypatch.setattr(sys, "platform", platform)
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    found = [line for line in lines(capsys) if "sandbox" in line and "checked" not in line]
    assert found == [said], found


def test_check_refuses_a_loose_state_dir(
    paired: Path, bin_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    os.chmod(tmp_path / "st", 0o755)  # noqa: S103 - the loose mode is the point
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    assert any("chmod 700" in line for line in lines(capsys))


def test_check_warns_about_a_config_others_can_change(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    paired.chmod(0o664)
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert any("chmod go-w" in line and line.startswith("warn") for line in lines(capsys))


def test_check_lists_configuration_problems(
    tmp_path: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "runner.toml"
    path.write_text('[hub]\nurl = "https://h"\ntypo = 1\n')
    assert cli.main(["runner", "check", "--config", str(path)]) == 1
    out = lines(capsys)
    assert "error  hub.typo: unknown key" in out
    assert "error  limits: required" in out


def test_check_explain_names_every_default(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["runner", "check", "--explain"]) == 0
    out = capsys.readouterr().out
    for key in ("stop_grace_max", "log_keep_bytes", "tmux_socket", "agent_path", "workspaces"):
        assert key in out


def test_default_config_path(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.path_of(None) == home / ".config" / "maity-runner" / "runner.toml"
    monkeypatch.setenv("MAITY_RUNNER_CONFIG", "/etc/maity-runner/runner.toml")
    assert config.path_of(None) == Path("/etc/maity-runner/runner.toml")
    assert config.path_of("~/x.toml") == home / "x.toml"


def test_opencode_is_not_offered_yet() -> None:
    found = problems(minimal(o="\n[harness.opencode]\n"))
    assert any(p.startswith("harness.opencode: not offered yet") for p in found), found


@pytest.mark.parametrize(
    ("projects", "said"),
    [
        ('["maity"]', "a project is named <owner>/<slug> now: write 'maity'"),
        ('["oliver/maity", "../x"]', "not a project full name: '../x'"),
    ],
)
def test_the_configured_projects_are_full_names(projects: str, said: str) -> None:
    text = MINIMAL.replace('projects = ["oliver/maity"]', f"projects = {projects}")
    with pytest.raises(config.ConfigError) as info:
        parse(text.format(url="https://hub.example", state_dir="/srv/state"))
    assert any(said in problem for problem in info.value.problems)


# --- pull requests through `maity gh` (cli/context/runner.md 9f43804d) ---------------------


def test_a_gh_rule_in_a_grant_is_set_aside_and_the_rest_kept() -> None:
    """No placed session runs gh, so a gh entry is not applied. It is kept as refused, for
    `maity runner check` to name, and is never a reason to refuse the configuration."""
    grant = (
        '\n[repositories."github.com/oliver-zehentleitner/maity"]\n'
        'allow = ["make test", "gh pr create *", "/usr/bin/gh pr view"]\n'
        "pull_requests = true\n"
    )
    found = parse(minimal(grant=grant)).repositories["github.com/oliver-zehentleitner/maity"]
    assert found.allow == ("make test",)
    assert found.refused == ("gh pr create *", "/usr/bin/gh pr view")
    assert found.pull_requests is True


def test_pull_requests_default_to_off_and_take_only_a_boolean() -> None:
    plain = '\n[repositories."github.com/oliver-zehentleitner/maity"]\nallow = ["make test"]\n'
    found = parse(minimal(grant=plain)).repositories["github.com/oliver-zehentleitner/maity"]
    assert found.pull_requests is False and found.refused == ()
    wrong = '\n[repositories."github.com/oliver-zehentleitner/maity"]\npull_requests = "yes"\n'
    assert any("pull_requests" in p for p in problems(minimal(grant=wrong)))


def test_runner_check_names_a_refused_gh_rule_and_an_api_host_as_warnings() -> None:
    grant = (
        '\n[repositories."github.com/oliver-zehentleitner/maity"]\n'
        'allow = ["gh pr create *"]\nnetwork = ["api.github.com"]\npull_requests = true\n'
    )
    report = commands.Report()
    commands._check_repositories(report, parse(minimal(grant=grant)))
    assert not report.failed
    texts = [text for level, text in report.lines if level == "warn"]
    assert len(texts) == 2
    assert "'gh pr create *' is not applied" in texts[0] and "pull_requests = true" in texts[0]
    assert "maity gh pr create" in texts[0]
    assert "api.github.com" in texts[1]


# --- the agents' git identity (cli/context/runner.md, tsk-z27pwcfr03wm) --------------------


def test_the_git_table_names_the_agents_identity_and_has_a_generic_default() -> None:
    cfg = parse(minimal())
    assert (cfg.git.name, cfg.git.email, cfg.git.configured) == (
        "Maity agent", "maity-agent@invalid", False,
    )  # fmt: skip
    team = parse(minimal(git='\n[git]\nname = "Your Team"\nemail = "team@example.org"\n'))
    assert (team.git.name, team.git.email, team.git.configured) == (
        "Your Team", "team@example.org", True,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("table", "said"),
    [
        ('name = "Your Team"\n', "git.email: required"),
        ('name = "A <b>"\nemail = "team@example.org"\n', "git.name: a name of 1 to 200"),
        ('name = " Team"\nemail = "team@example.org"\n', "git.name: a name of 1 to 200"),
        ('name = "Team"\nemail = "team example.org"\n', "git.email: an address like"),
        ('name = "Team"\nemail = "a@b"\nsigning_key = "x"\n', "git.signing_key: unknown key"),
    ],
)
def test_the_git_table_refuses_what_git_would_change_or_not_take(table: str, said: str) -> None:
    found = problems(minimal(git=f"\n[git]\n{table}"))
    assert any(p.startswith(said) for p in found), found


def test_runner_check_warns_while_agents_commit_as_the_default() -> None:
    harness = "\n[harness.claude-code]\n"
    report = commands.Report()
    commands._check_git(report, parse(minimal(h=harness)))
    assert not report.failed
    assert [level for level, _ in report.lines] == ["warn"]
    assert "Maity agent <maity-agent@invalid>" in report.lines[0][1]
    assert "[git]" in report.lines[0][1]
    named = commands.Report()
    git = '\n[git]\nname = "Your Team"\nemail = "team@example.org"\n'
    commands._check_git(named, parse(minimal(h=harness, git=git)))
    assert named.lines == [("ok", "agents commit as Your Team <team@example.org>")]
    stub_only = commands.Report()  # the stub commits nothing: no default in use
    commands._check_git(stub_only, parse(minimal()))
    assert stub_only.lines == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "team\\u0000@example.org"),  # NUL: no process could get it in its environment
        ("email", "team\\u001b@example.org"),  # ESC
        ("email", "team\\u007f@example.org"),  # DEL
        ("email", "team\\u0085@example.org"),  # NEL, a C1 control
        ("email", "team\\u200b@example.org"),  # a format character, invisible in a commit
        ("name", "Your\\u0080Team"),  # a C1 control
        ("name", "Your\\u0000Team"),
        ("name", "Your\\u001bTeam"),
        ("name", "Your\\u2028Team"),  # a line separator
    ],
)
def test_the_git_table_refuses_what_is_not_printable(field: str, value: str) -> None:
    """Review of #1735: a control character passed the first validator, and a NUL then failed
    only when a session was started. Everything `str.isprintable()` refuses is refused when
    the configuration is read (the values are TOML escapes, decoded by tomllib)."""
    other = {"name": '"Your Team"', "email": '"team@example.org"'}
    other[field] = f'"{value}"'
    found = problems(minimal(git=f"\n[git]\nname = {other['name']}\nemail = {other['email']}\n"))
    assert any(p.startswith(f"git.{field}: ") and "printable" in p for p in found), found


def test_printable_letters_beyond_ascii_are_kept() -> None:
    cfg = parse(minimal(git='\n[git]\nname = "Zoë Équipe"\nemail = "équipe@example.org"\n'))
    assert (cfg.git.name, cfg.git.email) == ("Zoë Équipe", "équipe@example.org")


def test_a_nul_in_the_git_email_fails_when_the_file_is_loaded(tmp_path: Path) -> None:
    """Not when a session starts: `load` refuses the file and names the field."""
    path = tmp_path / "runner.toml"
    path.write_text(
        minimal(h="\n[harness.claude-code]\n")
        + '\n[git]\nname = "Your Team"\nemail = "team\\u0000@example.org"\n',
        encoding="utf-8",
    )
    assert "\\u0000" in path.read_text(encoding="utf-8")  # the escape, decoded only by tomllib
    with pytest.raises(config.ConfigError) as info:
        config.load(path)
    assert any(p.startswith("git.email: ") for p in info.value.problems), info.value.problems
