from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import fakehub
import pytest

from maity import cli, state
from maity.runner import commands, config

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="maity runner needs 3.11")

MINIMAL = """\
[hub]
url = "{url}"
state_dir = "{state_dir}"

[limits]
projects = ["maity"]
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
    loaded = config.require_tomllib().loads(text)
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


def test_harness_without_allowlist_is_refused() -> None:
    found = problems(minimal(pi="\n[harness.pi]\n"))
    assert any(p.startswith("harness.pi: has no command allowlist") for p in found)


def test_unknown_harness_and_later_backends() -> None:
    found = problems(minimal(x="\n[harness.vim]\n", b='\n[backend]\nkind = "ssh"\n'))
    assert any(p.startswith("harness.vim: unknown harness") for p in found)
    assert any(p.startswith("backend.ssh: not supported") for p in found)


def test_default_mode_must_be_a_mode() -> None:
    text = '\n[harness.codex]\nmodes = ["supervised"]\ndefault_mode = "interactive"\n'
    assert "harness.codex.default_mode: must be one of its modes" in problems(minimal(c=text))


def test_stop_grace_max_stays_in_the_hub_range() -> None:
    text = minimal().replace("[limits]\n", "[limits]\nstop_grace_max = 901\n")
    assert any(p.startswith("limits.stop_grace_max:") for p in problems(text))


def test_python_310_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maity.runner.config.sys.version_info", (3, 10, 14))
    with pytest.raises(config.ConfigError) as info:
        config.require_tomllib()
    assert "Python 3.11" in info.value.problems[0]


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


# --- check -----------------------------------------------------------------------------------


@pytest.fixture
def paired(tmp_path: Path, home: Path, fake: fakehub.FakeHub) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(
        MINIMAL.format(url=fake.url, state_dir=tmp_path / "st")
        + f'\n[backend.local]\nworkspaces = "{tmp_path / "ws"}"\n'
    )
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
    fake_tool(bin_dir, "codex", "codex-cli 0.40.0")
    paired.write_text(paired.read_text() + "\n[harness.codex]\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert any("codex-cli 0.40.0" in line for line in lines(capsys))


def test_check_warns_about_inherited_claude_settings(
    paired: Path, bin_dir: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "claude", "2.1.308 (Claude Code)")
    fake_tool(bin_dir, "bwrap")
    fake_tool(bin_dir, "socat")
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text(
        '{"permissions": {"allow": ["Bash(rm:*)"]}, "hooks": {"Stop": []}}'
    )
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    warnings = [line for line in lines(capsys) if line.startswith("warn")]
    assert len(warnings) == 2, warnings


def test_check_requires_the_sandbox_when_configured(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("the sandbox prerequisites are checked on Linux")
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "claude", "2.1.308")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\nrequire_sandbox = true\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    assert any("no OS sandbox" in line and line.startswith("error") for line in lines(capsys))


def test_check_refuses_a_loose_state_dir(
    paired: Path, bin_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    os.chmod(tmp_path / "st", 0o755)  # noqa: S103 - the loose mode is the point
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    assert any("chmod 700" in line for line in lines(capsys))


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
