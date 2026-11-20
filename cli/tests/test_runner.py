from __future__ import annotations

import json
import os
import stat
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import fakehub
import pytest

from maity import cli, clonecheck, state
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


def test_check_finds_opencode_and_its_version(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `maity runner check` accepts a configuration naming opencode (req-g4d2cskx6zxv) and names
    # the harness with its version, like codex; opencode has no OS sandbox the runner switches
    # on, so nothing refuses it here.
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "opencode", "0.5.3")
    paired.write_text(paired.read_text() + '\n[harness.opencode]\nmodels = ["xai/grok"]\n')
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    out = lines(capsys)
    assert any("opencode" in line and "(0.5.3)" in line for line in out), out
    assert not any(line.startswith("error") for line in out), out


def test_check_warns_opencode_is_unsandboxed_under_single_layout(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # opencode never has a runner-switched OS sandbox, so under the single layout an opencode
    # agent runs as the operator's own user and can run any command as it, including reading the
    # runner's state, the other clones and logins (docs/runners.md#opencode-grok,
    # tsk-nynpvag9zvhh). `check` keeps the ok line and adds the warning; `paired` leaves
    # backend.local.layout at its "single" default.
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "opencode", "0.5.3")
    paired.write_text(paired.read_text() + '\n[harness.opencode]\nmodels = ["xai/grok"]\n')
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    out = lines(capsys)
    assert any(
        line.startswith("ok") and "harness opencode" in line and "(0.5.3)" in line for line in out
    ), out
    warning = [line for line in out if line.startswith("warn") and "harness opencode" in line]
    assert len(warning) == 1, out
    assert "no OS sandbox" in warning[0]
    assert "under layout single" in warning[0]
    assert "run any command as the runner's own user" in warning[0]
    assert "the runner's state, the other clones and logins" in warning[0]
    assert "tsk-nynpvag9zvhh" in warning[0]


@pytest.mark.parametrize(
    ("extra", "level", "failed"),
    [("", "warn", False), ("\nrequire_sandbox = true", "error", True)],
)
def test_check_refuses_opencode_when_a_sandbox_is_required(
    bin_dir: Path, extra: str, level: str, failed: bool
) -> None:
    # opencode never has a runner-switched OS sandbox, so every placement is unsandboxed. Like
    # claude-code and antigravity (capabilities.sandbox_refused), `require_sandbox = true` under
    # [harness.opencode] turns the residual-risk warning into an error (exit 1); without it the
    # local check through `_check_harness` only warns.
    fake_tool(bin_dir, "opencode", "0.5.3")
    cfg = parse(minimal(h=f'[harness.opencode]\nmodels = ["xai/grok"]{extra}\n'))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="single")
    found = [
        (lvl, t) for lvl, t in report.lines if "harness opencode" in t and "no OS sandbox" in t
    ]
    assert len(found) == 1, report.lines
    assert found[0][0] == level, report.lines
    assert report.failed is failed


def test_check_warns_opencode_generically_under_the_agent_user_layout(bin_dir: Path) -> None:
    # The local check threads backend.local.layout into `_check_opencode`. Under agent_user the
    # warning takes the generic wording ("as the agents' user"), not single's "the runner's own
    # user": this fails if the call site hard-codes the layout to "single".
    fake_tool(bin_dir, "opencode", "0.5.3")
    cfg = parse(minimal(h='[harness.opencode]\nmodels = ["xai/grok"]\n'))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    warning = [t for level, t in report.lines if level == "warn" and "harness opencode" in t]
    assert len(warning) == 1, report.lines
    assert "an agent can run any command as the agents' user" in warning[0]
    assert "under layout single" not in warning[0]


def test_check_warns_about_inherited_claude_settings(
    paired: Path, bin_dir: Path, home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", "2.1.325 (Claude Code)")  # the checked one: no warning for it
    for tool in ("bwrap", "socat", "unshare", "true"):  # the nesting probe passes: no warning
        fake_tool(bin_dir, tool)
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


@pytest.mark.parametrize(("version", "warned"), [("2.1.325", False), ("2.1.330", True)])
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
    found = [line for line in lines(capsys) if "sandbox was checked with 2.1.325" in line]
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
    ("version", "code"),
    [("2.1.294", 1), ("2.1.295", 0), ("2.1.325", 0), ("dev build", 1)],
)
def test_check_refuses_a_required_sandbox_on_a_claude_code_older_than_its_hook_policy(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], version: str, code: int
) -> None:
    """The runner's hook refuses a call when it fails only from 2.1.295 (`onFailure`); an
    older or unknown version gets no sandbox, so `require_sandbox` refuses it."""
    if not sys.platform.startswith("linux"):
        pytest.skip("the sandbox prerequisites are checked on Linux")
    for tool in ("tmux", "maity", "bwrap", "socat"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", f"{version} (Claude Code)")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\nrequire_sandbox = true\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    said = [line for line in lines(capsys) if "is older than 2.1.295 or unknown" in line]
    assert [line.split()[0] for line in said] == (["error"] if code else [])


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
    fake_tool(bin_dir, "claude", "2.1.325")
    for tool in tools:
        fake_tool(bin_dir, tool)
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\nrequire_sandbox = true\n")
    monkeypatch.setattr(sys, "platform", platform)
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    found = [line for line in lines(capsys) if "sandbox" in line and "checked" not in line]
    assert found == [said], found


REFUSED_MAP = "unshare: write failed /proc/self/uid_map: Operation not permitted"


@pytest.mark.parametrize(
    ("exit_code", "stderr", "level", "code"),
    [
        (0, "", "ok", 0),
        (1, REFUSED_MAP, "error", 1),
        (1, "bwrap: No permissions to create a new namespace", "warn", 0),
        (127, "sh: 1: unshare: not found", "warn", 0),
    ],
)  # fmt: skip
def test_check_starts_a_nested_user_namespace_inside_bubblewrap(
    paired: Path,
    bin_dir: Path,
    capsys: pytest.CaptureFixture[str],
    exit_code: int,
    stderr: str,
    level: str,
    code: int,
) -> None:
    """Ubuntu's bwrap-userns-restrict lets bwrap start but takes every capability from what it
    starts: Claude Code's seccomp step opens a second user namespace and fails, so every
    sandboxed command does. Only that refused mapping is an error; a probe that fails some
    other way could not tell, and says so as a warning."""
    if not sys.platform.startswith("linux"):
        pytest.skip("Claude Code's bubblewrap sandbox is Linux only")
    for tool in ("tmux", "maity", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    bwrap = bin_dir / "bwrap"  # records its arguments, then answers as the host would
    bwrap.write_text(
        f'#!/bin/sh\necho "$@" > "{bin_dir}/bwrap.args"\n'
        f'echo "$PATH $LC_ALL" > "{bin_dir}/bwrap.env"\necho "{stderr}" >&2\nexit {exit_code}\n'
    )
    bwrap.chmod(0o755)
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    said = [line for line in lines(capsys) if "inside bubblewrap" in line]
    assert [line.split()[0] for line in said] == [level], said
    if level == "error":
        assert "uid_map" in said[0]
    args = (bin_dir / "bwrap.args").read_text().split()
    assert args[-4:] == [str(bin_dir / "unshare"), "--user", "--map-root-user",
                         str(bin_dir / "true")]  # fmt: skip
    assert "--unshare-user" in args


def test_the_nested_probe_runs_with_the_agents_path_not_the_runners(
    bin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's own PATH may hold other tools, or none: the probe looks every command up
    on the agents' PATH, starts it by its absolute path and passes that PATH on."""
    from maity.runner import capabilities

    agents = tmp_path / "agents-bin"
    agents.mkdir()
    for tool in ("unshare", "true"):
        fake_tool(agents, tool)
    bwrap = agents / "bwrap"
    bwrap.write_text(f'#!/bin/sh\necho "$PATH|$LC_ALL" > "{tmp_path}/env"\nexit 0\n')
    bwrap.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))  # the runner's: no bwrap, no unshare
    found = capabilities.claude_nested_userns(str(agents))
    assert found.outcome == "ok"
    assert (tmp_path / "env").read_text().strip() == f"{agents}|C"


def test_the_nested_probe_names_missing_tools_and_cannot_tell_on_a_launch_error(
    bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing tool is `missing`, with its name; a probe that times out or does not start
    is `inconclusive`, never `refused`."""
    import subprocess

    from maity.runner import capabilities
    from maity.runner.asuser import AsUser

    path = str(bin_dir)
    found = capabilities.claude_nested_userns(path)
    assert (found.outcome, found.detail) == ("missing", "bwrap, unshare, true")
    for tool in ("bwrap", "unshare", "true"):
        fake_tool(bin_dir, tool)
    assert capabilities.claude_nested_userns(path).outcome == "ok"

    def timeout(self: AsUser, argv: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("bwrap", 30)

    monkeypatch.setattr(AsUser, "run", timeout)
    assert capabilities.claude_nested_userns(path).outcome == "inconclusive"

    def broken(self: AsUser, argv: object, **kwargs: object) -> None:
        raise OSError(8, "Exec format error")

    monkeypatch.setattr(AsUser, "run", broken)
    found = capabilities.claude_nested_userns(path)
    assert (found.outcome, found.detail) == (
        "inconclusive",
        "the probe did not start: Exec format error",
    )


def test_check_runs_no_bubblewrap_probe_under_seatbelt(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """On macOS the sandbox is Seatbelt: unrelated bwrap and unshare on PATH are not asked."""
    for tool in ("tmux", "maity", "sandbox-exec", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    bwrap = bin_dir / "bwrap"
    bwrap.write_text(f'#!/bin/sh\ntouch "{bin_dir}/bwrap.ran"\nexit 1\n')
    bwrap.chmod(0o755)
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "darwin")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert not any("inside bubblewrap" in line for line in lines(capsys))
    assert not (bin_dir / "bwrap.ran").exists()


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


def test_opencode_is_offered() -> None:
    # Offered (req-g4d2cskx6zxv): a configuration naming opencode is accepted, no longer refused
    # as "not offered yet" (cli/context/runner.md). Its modes and the Grok model are read, and
    # NOT_OFFERED_YET is now empty.
    text = (
        "\n[harness.opencode]\n"
        'modes = ["supervised", "interactive"]\n'
        'models = ["xai/grok"]\n'  # opencode names a model as <provider>/<model>
        'default_model = "xai/grok"\n'
    )
    cfg = parse(minimal(o=text))
    harness = cfg.harnesses["opencode"]
    assert harness.modes == ("supervised", "interactive")
    assert harness.models == ("xai/grok",) and harness.default_model == "xai/grok"
    assert harness.binary == "opencode"
    assert config.NOT_OFFERED_YET == ()


def test_antigravity_is_offered() -> None:
    # Re-offered (req-9spwe33neh1z): a configuration naming antigravity is accepted, no longer
    # refused as "not offered yet" (cli/context/runner.md, 28ac82c8). The residual command(maity)
    # risk is accepted by the owner; re-offering did not widen agy's grants.
    cfg = parse(minimal(a="\n[harness.antigravity]\n"))
    assert "antigravity" in cfg.harnesses


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


def test_runner_check_names_what_codex_starts_without_only_with_codex_configured() -> None:
    grant = (
        '\n[repositories."github.com/oliver-zehentleitner/maity"]\n'
        'allow = ["make test"]\npull_requests = true\n'
    )
    report = commands.Report()
    commands._check_repositories(report, parse(minimal(c="\n[harness.codex]\n", grant=grant)))
    assert not report.failed  # said, never an error: the placement starts
    texts = [text for level, text in report.lines if level == "warn"]
    assert len(texts) == 2, texts
    assert "'make test' is not applied to codex" in texts[0] and "its sandbox" in texts[0]
    assert "pull_requests is not given to codex" in texts[1] and "maity gh" in texts[1]
    assert "refused without the sandbox" in texts[0]
    quiet = commands.Report()
    commands._check_repositories(quiet, parse(minimal(grant=grant)))
    assert quiet.lines == []


def test_runner_check_passes_when_codex_home_lies_under_the_workspaces_root() -> None:
    cfg = parse(minimal(c="\n[harness.codex]\n",
                        ws='\n[backend.local]\nworkspaces = "/srv/ws"\n'))  # fmt: skip
    report = commands.Report()
    commands._check_codex_home(report, cfg)
    assert not report.failed
    assert any("CODEX_HOME lies in each placement's scratch under /srv/ws" in text
               for level, text in report.lines if level == "ok")  # fmt: skip


def test_runner_check_errors_when_codex_home_would_be_hidden_under_the_state_dir() -> None:
    # state_dir is /srv/state; a workspaces root under it would hide every codex-home (the
    # misconfiguration card tsk-hv7jbgy75zjt fixes).
    cfg = parse(minimal(c="\n[harness.codex]\n",
                        ws='\n[backend.local]\nworkspaces = "/srv/state/ws"\n'))  # fmt: skip
    report = commands.Report()
    commands._check_codex_home(report, cfg)
    assert report.failed
    assert any("inside the state directory" in text
               for level, text in report.lines if level == "error")  # fmt: skip


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


@pytest.mark.parametrize("placement", ["plc-0003", ""])
@pytest.mark.parametrize(
    "argv",
    [["scratchop", "remove", "--under", "/", "/maity/.scratch/plc-0003"],
     ["limitread", "--under", "/", "/etc/hostname"], ["trust", "/h", "/c"], ["status"],
     ["gc"], ["check"]],
)  # fmt: skip
def test_the_runner_commands_are_refused_in_a_placed_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    placement: str, argv: list[str],
) -> None:  # fmt: skip
    """With `MAITY_PLACEMENT` set, even empty, `maity runner` refuses all but what the
    runner's own launch runs in the session, before anything is read or done."""
    monkeypatch.setenv("MAITY_PLACEMENT", placement)
    called: list[str] = []
    monkeypatch.setattr("maity.runner.scratchop.run", lambda *a: called.append("scratchop"))
    assert cli.main(["runner", *argv]) == cli.EXIT_REFUSED
    assert "does not run for a placed agent" in capsys.readouterr().err
    assert called == []


IN_SESSION_ARGV = {
    "loop": ["loop", "--spec", "/nowhere/spec.json"],
    "stub": ["stub", "--exit-code", "0", "--run-seconds", "0"],
    "plaincall": ["plaincall"],
    "logcap": ["logcap", "/nowhere/log", "1"],
    "trust": ["trust", "/nowhere/home", "/nowhere/clone"],
}


@pytest.mark.parametrize("name", sorted(IN_SESSION_ARGV))
def test_only_what_runs_in_a_placed_session_gets_past_the_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """With valid arguments and handlers that do nothing: the commands the runner starts in
    the session reach their handler under a placement, any other one (`trust`) does not."""
    from maity.runner import logcap, loop, plaincall, stub, trust

    reached: list[str] = []

    def handler(name: str) -> Callable[[object], int]:
        def run(argv: object) -> int:
            reached.append(name)
            return 0

        return run

    for module in (loop, stub, plaincall, logcap, trust):
        monkeypatch.setattr(module, "main", handler(module.__name__))
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    code = cli.main(["runner", *IN_SESSION_ARGV[name]])
    if name in commands.IN_SESSION:
        assert code == 0 and reached == [f"maity.runner.{name}"]
    else:
        assert code == cli.EXIT_REFUSED and reached == []
        assert "for a placed agent" in capsys.readouterr().err


def test_the_runner_calls_on_the_agents_side_carry_no_placement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through sudo and over ssh the runner's own calls run without `MAITY_PLACEMENT`, so
    the refusal never meets them: sudo passes only the variables named, ssh none but those."""
    import subprocess

    from maity.runner.asuser import AsUser, Ssh

    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")  # even were it the runner's own
    seen: list[tuple[list[str], object]] = []

    def run(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        seen.append((list(argv), kw.get("env")))
        return subprocess.CompletedProcess(argv, 0, '{"result": "missing"}', "")

    monkeypatch.setattr(subprocess, "run", run)
    room = Path("/ws/maity/.scratch/plc-0003")
    for side in (AsUser("agents"), Ssh(name="h", address="h", login="agents")):
        side.scratch("size", Path("/ws"), room)
    assert len(seen) == 2
    for argv, env in seen:
        assert not any("MAITY_PLACEMENT" in word for word in argv)
        assert env is None or "MAITY_PLACEMENT" not in env  # type: ignore[operator]
    assert seen[0][0][:4] == ["sudo", "-n", "-u", "agents"] and "env" not in seen[0][0][:6]


# --- S201/S202: an in-session command's file must be the runner's ----------------------------


def _placed_clone(root: Path) -> Path:
    clone = root / "ws" / "maity" / "agent-3"
    (clone / ".git" / "maity").mkdir(parents=True)
    (clone / clonecheck.MARKER_PATH).write_text("plc-0003\n")
    return clone


@pytest.mark.parametrize("name", sorted(commands.IN_SESSION_FILE))
@pytest.mark.parametrize("where", ["clone", "relative", "scratch", "agy", "temp", "link"])
def test_a_placed_agent_cannot_hand_an_in_session_command_its_own_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    name: str,
    where: str,
) -> None:
    """`maity` runs outside the agent's sandbox, so `loop --spec` (what it runs) and `logcap`
    (what it cuts) refuse a file the agent could have written: in its clone, its scratch, a
    temporary directory, or reached through a link; the handler is never called."""
    from maity.runner import logcap, loop

    monkeypatch.setattr(commands, "TEMP_ROOTS", (str(tmp_path / "tmp"),))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    clone = _placed_clone(tmp_path)
    runner_own = tmp_path / "state" / "agents" / "plc-0003" / "loop.json"
    runner_own.parent.mkdir(parents=True)
    runner_own.write_text("{}")
    target = {
        "clone": clone / "s.json",
        "relative": Path("s.json"),
        "scratch": tmp_path / "ws" / "maity" / ".scratch" / "plc-0003" / "s.json",
        "agy": tmp_path / "maity-scratch-1000" / "x" / "s.json",
        "temp": tmp_path / "tmp" / "s.json",
        "link": tmp_path / "state" / "link.json",
    }[where]
    if where == "link":
        (clone / "s.json").write_text("{}")
        target.symlink_to(clone / "s.json")
    monkeypatch.chdir(clone)
    reached: list[str] = []
    for module in (loop, logcap):
        monkeypatch.setattr(module, "main", lambda argv, m=module: reached.append(m.__name__) or 0)
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    argv = {"loop": ["loop", "--spec", str(target)], "logcap": ["logcap", str(target), "1"]}
    assert cli.main(["runner", *argv[name]]) == cli.EXIT_REFUSED
    assert "only the runner's own file" in capsys.readouterr().err
    assert reached == []
    # The runner's own file in its state directory still gets through.
    own = {"loop": ["loop", "--spec", str(runner_own)], "logcap": ["logcap", str(runner_own), "1"]}
    assert cli.main(["runner", *own[name]]) == 0 and reached == [f"maity.runner.{name}"]


def test_outside_a_placement_the_file_is_not_checked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from maity.runner import loop

    monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    clone = _placed_clone(tmp_path)
    reached: list[str] = []
    monkeypatch.setattr(loop, "main", lambda argv: reached.append("loop") or 0)
    assert cli.main(["runner", "loop", "--spec", str(clone / "s.json")]) == 0
    assert reached == ["loop"]
