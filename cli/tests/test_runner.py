from __future__ import annotations

import dataclasses
import json
import os
import re
import stat
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import fakehub
import pytest
from conftest import fake_opencode, posix

from maity import cli, state
from maity.runner import adapters, commands, config
from maity.runner.asuser import RUNNER

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


def test_harness_efforts() -> None:
    """tsk-0fr0xzy2ce95: `efforts` only where the launch passes one, in the hub's shape."""
    with_codex = minimal() + '\n[harness.codex]\nefforts = ["low", "medium"]\n'
    assert parse(with_codex).harnesses["codex"].efforts == ("low", "medium")
    assert "harness.stub.efforts: the runner passes no effort to this harness" in problems(
        minimal().replace("[harness.stub]\n", '[harness.stub]\nefforts = ["low"]\n')
    )
    bad = problems(minimal() + '\n[harness.codex]\nefforts = ["High"]\n')
    assert any(p.startswith("harness.codex.efforts: not an effort") for p in bad), bad
    twice = problems(minimal() + '\n[harness.codex]\nefforts = ["low", "low"]\n')
    assert "harness.codex.efforts: an effort is named twice" in twice
    # What the hub's hello refuses, the check refuses too, since a refused hello stops the
    # whole runner (A1994): a trailing newline, and more than the hub's 16.
    newline = problems(minimal() + '\n[harness.codex]\nefforts = ["low\\n"]\n')
    assert any(p.startswith("harness.codex.efforts: not an effort") for p in newline), newline
    many = ", ".join(f'"{letter}"' for letter in "abcdefghijklmnopq")  # 17 distinct
    over = problems(minimal() + f"\n[harness.codex]\nefforts = [{many}]\n")
    assert "harness.codex.efforts: at most 16, the hub's bound" in over
    sixteen = ", ".join(f'"{letter}"' for letter in "abcdefghijklmnop")
    assert len(parse(minimal() + f"\n[harness.codex]\nefforts = [{sixteen}]\n")
               .harnesses["codex"].efforts) == 16  # fmt: skip


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


def marked(capsys: pytest.CaptureFixture[str], marker: str) -> list[str]:
    """The lines whose words, paths left out, hold `marker`: a test's temporary directory is
    named after the test, so its paths can hold any word of the test's name."""
    return [line for line in lines(capsys) if marker in re.sub(r"/\S*", "", line)]


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
    fake_opencode(bin_dir / "opencode", "0.5.3")
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
    fake_opencode(bin_dir / "opencode", "0.5.3")
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
    fake_opencode(bin_dir / "opencode", "0.5.3")
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
    fake_opencode(bin_dir / "opencode", "0.5.3")
    cfg = parse(minimal(h='[harness.opencode]\nmodels = ["xai/grok"]\n'))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    warning = [t for level, t in report.lines if level == "warn" and "harness opencode" in t]
    assert len(warning) == 1, report.lines
    assert "an agent can run any command as the agents' user" in warning[0]
    assert "under layout single" not in warning[0]


BOTH_MODES = 'modes = ["interactive", "supervised"]\nmodels = ["xai/grok"]\n'


def test_check_finds_the_flags_both_opencode_starts_pass(bin_dir: Path) -> None:
    # OpenCode 2.3: the TUI takes `--standalone` and `--prompt`, `opencode run` takes `--model`
    # and `--continue`, so both modes' starts pass (tsk-daa6e0gfncg0, nte-mmnz3mk1247c).
    fake_opencode(bin_dir / "opencode")
    cfg = parse(minimal(h=f"[harness.opencode]\n{BOTH_MODES}"))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    ok = [t for level, t in report.lines if level == "ok" and "start's flags" in t]
    assert len(ok) == 2, report.lines
    assert any("`opencode` takes the interactive" in t for t in ok), ok
    assert any("`opencode run` takes the supervised" in t for t in ok), ok
    assert not report.failed, report.lines


def test_check_refuses_an_opencode_whose_command_lacks_a_flag_the_start_passes(
    bin_dir: Path,
) -> None:
    # The class of tsk-daa6e0gfncg0: an opencode whose `run` no longer names `--model` (as its
    # 2.3 TUI dropped it) would exit on every supervised start, so `check` says so before one.
    fake_opencode(bin_dir / "opencode", run=("-c, --continue", "--session"))
    cfg = parse(minimal(h='[harness.opencode]\nmodels = ["xai/grok"]\n'))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    errors = [t for level, t in report.lines if level == "error"]
    assert len(errors) == 1, report.lines
    assert "`opencode run --help` does not name --model" in errors[0]
    assert "supervised start" in errors[0] and "tsk-daa6e0gfncg0" in errors[0]
    assert report.failed


def test_check_probes_only_the_configured_opencode_modes(bin_dir: Path) -> None:
    # A supervised-only harness (the default modes) never starts the TUI: a TUI without
    # `--standalone` is no error.
    fake_opencode(bin_dir / "opencode", tui=("--prompt",))
    cfg = parse(minimal(h='[harness.opencode]\nmodes = ["supervised"]\nmodels = ["xai/grok"]\n'))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    assert not report.failed, report.lines
    assert not any("interactive start" in t for _, t in report.lines), report.lines


def test_check_refuses_an_opencode_tui_without_standalone(bin_dir: Path) -> None:
    # Without `--standalone` the TUI would attach to the user's shared service, which ignores
    # the placement's configuration (nte-mmnz3mk1247c): an opencode whose TUI lacks it fails
    # the interactive start's check.
    fake_opencode(bin_dir / "opencode", tui=("--prompt",))
    cfg = parse(minimal(h=f"[harness.opencode]\n{BOTH_MODES}"))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    errors = [t for level, t in report.lines if level == "error"]
    assert len(errors) == 1, report.lines
    assert "`opencode --help` does not name --standalone" in errors[0]
    assert "interactive start" in errors[0]


def test_check_warns_when_opencode_help_cannot_be_read(bin_dir: Path) -> None:
    # A `--help` that fails says nothing about the flags: a warning, not an error.
    script = bin_dir / "opencode"
    script.write_text('#!/bin/sh\n[ "$1" = --version ] && echo 2.3.0 || exit 3\n')
    script.chmod(0o755)
    cfg = parse(minimal(h=f"[harness.opencode]\n{BOTH_MODES}"))
    report = commands.Report()
    commands._check_harness(report, cfg.harnesses["opencode"], str(bin_dir), layout="agent_user")
    warned = [t for level, t in report.lines if level == "warn" and "could not be read" in t]
    assert len(warned) == 2, report.lines
    assert not report.failed, report.lines


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


def test_check_says_the_worktree_guard_is_configured_and_names_a_leftover(
    paired: Path, bin_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`check` says what the runner's settings configure, not that it was seen working, and
    names a recorded clone that holds a worktree; it removes nothing."""
    from maity.runner import workspace

    fake_tool(bin_dir, "tmux")
    fake_tool(bin_dir, "maity")
    fake_tool(bin_dir, "claude", "2.1.325 (Claude Code)")
    for tool in ("bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    clone = tmp_path / "ws" / "prj-1" / "agent-3"
    (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    workspace.record(tmp_path / "st", workspace.Workspace(clone, "prj-1", "agent-3"), "a", "p")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0  # no block
    out = lines(capsys)
    assert f"ok     {commands.WORKTREES_OFF}" in out, out
    assert "not confirmed on this Claude Code version" in commands.WORKTREES_OFF
    found = [line for line in out if f"clone {clone} " in line]
    assert len(found) == 1 and found[0].startswith("warn"), out
    assert (clone / ".claude" / "worktrees" / "agent-x").is_dir()


@pytest.mark.parametrize("sandboxed", [False, True])
def test_check_warns_that_the_worktree_hook_does_not_run_when_hooks_are_off(
    home: Path, sandboxed: bool
) -> None:
    """Settings that switch hooks off (capabilities.claude_hooks_off) leave only the denies:
    the worktree line is a warning, sandbox or not. Under the sandbox the hooks error that
    refuses the starts is `_check_claude_hooks`' own, not repeated here."""
    (home / ".claude").mkdir()
    (home / ".claude" / "settings.json").write_text('{"allowManagedHooksOnly": true}')
    report = commands.Report()
    if sandboxed:
        commands._check_claude_hooks(report, RUNNER, "")
    commands._check_worktree_guard(report, RUNNER, "", "2.1.325")
    assert ("ok", commands.WORKTREES_OFF) not in report.lines
    (warning,) = [t for level, t in report.lines if level == "warn"]
    assert warning.startswith("harness claude-code: ") and "sets allowManagedHooksOnly" in warning
    assert "WorktreeCreate hook does not run" in warning
    assert "EnterWorktree and git worktree denies remain" in warning
    errors = [t for level, t in report.lines if level == "error"]
    assert len(errors) == int(sandboxed)  # the existing refusal only, not a second one


@pytest.mark.parametrize(
    ("version", "ok"),
    [("2.1.325", True), ("2.1.50", True), ("2.1.49", False), ("2.1.50-rc.1", False),
     (None, False), ("dev build", False)],
)  # fmt: skip
def test_check_warns_when_claude_code_has_no_worktree_event(
    home: Path, version: str | None, ok: bool
) -> None:
    """Below 2.1.50 (its release notes, as cited in review A1808), or unknown, the runner writes
    no worktree hook
    (adapters.claude_settings): the line says the denies alone remain."""
    report = commands.Report()
    commands._check_worktree_guard(report, RUNNER, "", version)
    if ok:
        assert report.lines == [("ok", commands.WORKTREES_OFF)]
    else:
        ((level, text),) = report.lines
        assert level == "warn" and "older than 2.1.50 or unknown" in text
        assert f"version {version or 'unknown'} " in text
        assert "writes no WorktreeCreate hook" in text and "denies remain" in text


def _leftover(clone: Path, kind: str) -> None:
    """A clone's worktree state as `check` may find it."""
    (clone / ".git").mkdir(parents=True)
    if kind == "bare directory":
        (clone / ".claude" / "worktrees" / "agent-x").mkdir(parents=True)
    elif kind in ("registered, cleared", "registered, kept"):
        tree = (clone / ".claude" / "worktrees" if kind == "registered, cleared"
                else clone.parent / "elsewhere") / "agent-x"  # fmt: skip
        tree.mkdir(parents=True)
        admin = clone / ".git" / "worktrees" / "agent-x"
        admin.mkdir(parents=True)
        (admin / "gitdir").write_text(f"{tree / '.git'}\n")
    elif kind in ("plain file", "link to a directory"):  # what the prune never removes
        scope = clone / ".claude" / "worktrees"
        scope.mkdir(parents=True)
        if kind == "plain file":
            (scope / "agent-x").write_text("x\n")
        else:
            (clone.parent / "victim").mkdir()
            (scope / "agent-x").symlink_to(clone.parent / "victim", target_is_directory=True)
    elif kind == "empty registration directory":  # the sandbox's placeholder
        (clone / ".git" / "worktrees").mkdir()
    elif kind == "linked .claude":
        target = clone.parent / "target"
        (target / "worktrees" / "agent-x").mkdir(parents=True)
        (clone / ".claude").symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize(
    ("kind", "said"),
    [("none", None), ("empty registration directory", None), ("linked .claude", None),
     # Not a directory the start's prune removes, and nothing that stops maity's git: not named.
     ("plain file", None), ("link to a directory", None),
     ("bare directory", "leftover directory under .claude/worktrees/ with no registration; it "
                        "does not stop maity's git"),
     ("registered, cleared", "of a working tree under .claude/worktrees/, so maity runs no git"),
     ("registered, kept", "the runner's start does not clear"),
     ],
)  # fmt: skip
def test_check_tells_a_registered_worktree_from_a_leftover_directory(
    tmp_path: Path, kind: str, said: str | None
) -> None:
    """A registration stops maity's git; the start clears it only when its working tree is
    under `.claude/worktrees/` (worktree.registrations), else a person removes it. A bare
    directory there does not stop git. A link as `.claude` counts as none. Read-only."""
    from maity.runner import workspace

    cfg = dataclasses.replace(parse(minimal()), state_dir=tmp_path / "st")
    clone = tmp_path / "ws" / "prj-1" / "agent-3"
    clone.mkdir(parents=True)
    _leftover(clone, kind)
    workspace.record(cfg.state_dir, workspace.Workspace(clone, "prj-1", "agent-3"), "a", "p")
    # A clone on an ssh host is that host's check, not this one.
    workspace.record(cfg.state_dir, workspace.Workspace(clone, "prj-1", "agent-4", "b"), "a", "q")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    report = commands.Report()
    commands._check_leftover_worktrees(report, cfg, RUNNER)
    found = [(level, t) for level, t in report.lines if f"clone {clone} " in t]
    if said is None:
        assert found == [], report.lines
    else:
        ((level, text),) = found
        assert level == "warn" and said in text, text
        if kind == "registered, kept":
            assert "a person removes it" in text and "maity runs no git" in text
        else:
            assert "placement's next start" in text
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before  # nothing removed


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


FILTERING = "Name:\tcat\nSeccomp:\t0\nSeccomp_filters:\t0\n"


@pytest.mark.parametrize(
    ("machine", "release", "status", "outcome", "arch"),
    [
        ("x86_64", "6.12.0-1-amd64", FILTERING, "ok", "x64"),
        ("aarch64", "6.8.0", FILTERING, "ok", "arm64"),
        ("arm64", "6.8.0", FILTERING, "ok", "arm64"),
        ("amd64", "6.8.0", FILTERING, "ok", "x64"),
        ("AMD64", "6.8.0", FILTERING, "ok", "x64"),
        ("AArch64", "6.8.0", FILTERING, "ok", "arm64"),
        ("x86_64", "5.4.0-200", "Seccomp:\t0\n", "ok", "x64"),  # before Seccomp_filters
        ("riscv64", "6.12.0", FILTERING, "unsupported_arch", "riscv64"),
        ("i686", "6.12.0", FILTERING, "unsupported_arch", "i686"),
        ("x64", "6.12.0", FILTERING, "unsupported_arch", "x64"),  # Claude Code's name, no uname
        ("ppc64le", "6.12.0", FILTERING, "unsupported_arch", "ppc64le"),
        ("x86_64", "6.12.0", "Name:\tcat\n", "no_seccomp", "x64"),
        ("x86_64", "6.12.0", "Seccomp:\t0\n", "no_seccomp", "x64"),
        ("x86_64", "5.9.0", "Seccomp:\t0\n", "no_seccomp", "x64"),
        ("x86_64", "6.12.0", "Seccomp:\tx\n", "inconclusive", "x64"),
        ("x86_64", "6.12.0", "Seccomp:\t0\nSeccomp_filters:\t\n", "inconclusive", "x64"),
        ("x86_64", "6.12.0", "Seccomp:\t0\nSeccomp_filters:\t?\n", "inconclusive", "x64"),
        ("x86_64", "6.12.0", "Name:\tc�t\nSeccomp:\t2\nSeccomp_filters:\t1\n", "ok", "x64"),
        ("x86_64", "unknown", "Seccomp:\t0\n", "inconclusive", "x64"),
        ("", "6.12.0", FILTERING, "inconclusive", ""),
        ("x86_64", "6.12.0", None, "inconclusive", ""),
    ],
)  # fmt: skip
def test_the_seccomp_preflight_reads_the_machine_and_the_kernels_seccomp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    machine: str,
    release: str,
    status: str | None,
    outcome: str,
    arch: str,
) -> None:
    """A machine Claude Code ships its seccomp helper for, and a kernel with seccomp filtering:
    `Seccomp:` always, `Seccomp_filters:` from Linux 5.9 on. What cannot be read is
    `inconclusive`, never `ok`."""
    import platform

    from maity.runner import capabilities

    proc = tmp_path / "status"
    if status is not None:
        proc.write_text(status)
    monkeypatch.setattr(capabilities, "PROC_STATUS", proc)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(platform, "release", lambda: release)
    found = capabilities.claude_seccomp()
    assert (found.outcome, found.arch) == (outcome, arch)
    if outcome != "ok":
        assert found.detail


def test_the_seccomp_preflight_asks_the_agents_side_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through sudo or ssh: one fixed `sh -c` as the agents' user, its three answers in order;
    a call that fails is `inconclusive`."""
    import subprocess

    from maity.runner import capabilities
    from maity.runner.asuser import AsUser

    calls: list[list[str]] = []
    answer = {"code": 0, "out": "aarch64\n6.12.0\n" + FILTERING}

    def run(self: AsUser, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, int(str(answer["code"])), str(answer["out"]), "")

    monkeypatch.setattr(AsUser, "run", run)
    found = capabilities.claude_seccomp(AsUser("agents"))
    assert (found.outcome, found.arch) == ("ok", "arm64")
    assert calls == [["sh", "-c", capabilities._SECCOMP_HOST, "sh", "/proc/self/status"]]
    assert capabilities._SECCOMP_HOST.startswith("uname -m && uname -r && ")
    answer["code"] = 1
    assert capabilities.claude_seccomp(AsUser("agents")).outcome == "inconclusive"


@pytest.mark.skipif(sys.platform == "win32", reason="the agents' side is a POSIX shell")
def test_the_agents_side_status_read_replaces_bytes_outside_ascii(tmp_path: Path) -> None:
    """The sudo/ssh read decodes as a direct read with `errors="replace"` does: a task name
    with bytes that are no UTF-8 leaves the keys readable, never an exception."""
    import subprocess

    from maity.runner import capabilities

    status = tmp_path / "status"
    status.write_bytes(b"Name:\tc\xc3\xa4t\xff\nSeccomp:\t0\nSeccomp_filters:\t0\n")
    done = subprocess.run(
        ["sh", "-c", capabilities._SECCOMP_HOST, "sh", str(status)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    machine, release, rest = done.stdout.split("\n", 2)
    assert machine and release
    assert rest == "Name:\tc??t?\nSeccomp:\t0\nSeccomp_filters:\t0\n"
    direct = status.read_text(encoding="utf-8", errors="replace")
    assert direct.splitlines()[1:] == rest.splitlines()[1:]


@pytest.mark.parametrize(
    ("outcome", "level", "code"),
    [("ok", "ok", 0), ("unsupported_arch", "error", 1), ("no_seccomp", "error", 1),
     ("inconclusive", "error", 1)],
)  # fmt: skip
def test_check_reports_the_seccomp_preflight_under_bubblewrap(
    paired: Path,
    bin_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    level: str,
    code: int,
) -> None:
    """Every answer but `ok` is an error, as the supervisor refuses the start on it."""
    from maity.runner import capabilities

    answers = {
        "ok": capabilities.ClaudeSeccomp("ok", "x64"),
        "unsupported_arch": capabilities.ClaudeSeccomp("unsupported_arch", "riscv64", "m"),
        "no_seccomp": capabilities.ClaudeSeccomp("no_seccomp", "x64", "no Seccomp line"),
        "inconclusive": capabilities.ClaudeSeccomp("inconclusive", detail="unreadable"),
    }
    monkeypatch.setattr(capabilities, "claude_seccomp", lambda as_user: answers[outcome])
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "linux")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    said = marked(capsys, "seccomp")
    assert [line.split()[0] for line in said] == [level], said
    if outcome == "ok":
        assert said[0].endswith("machine x64, kernel seccomp filtering present")
    else:
        assert said[0].endswith("its placements are not started")


PROBE_APPLIED = "[SandboxDebug] [Sandbox Linux] Applying seccomp filter for Unix socket blocking"
PROBE_MISSING = (
    "[SandboxDebug] [Sandbox Linux] apply-seccomp binary not available - unix socket "
    "blocking disabled."
)


@pytest.mark.parametrize(
    ("answer", "outcome", "detail"),
    [
        ((0, f"start\n{PROBE_APPLIED}\n"), "ok", ""),
        ((0, f"{PROBE_MISSING}\n"), "off", "Claude Code found no seccomp helper"),
        ((1, f"{PROBE_MISSING}\n"), "off", "Claude Code found no seccomp helper"),
        ((0, "[SandboxDebug] something else\n"), "inconclusive",
         "the debug log named neither outcome"),
        ((1, f"{PROBE_APPLIED}\nInvalid API key\n"), "inconclusive",
         "Claude Code exited 1 (its login?)"),
        ("timeout", "inconclusive", "no answer within 180 s"),
        ("oserror", "inconclusive", "Claude Code did not start: No such file or directory"),
        ("undecodable", "inconclusive", "Claude Code's output could not be read"),
        ((0, b"\xff\xfe"), "inconclusive", "Claude Code's output could not be read"),
    ],
)  # fmt: skip
def test_the_socket_probe_reads_the_runtimes_lines_and_fails_closed_otherwise(
    monkeypatch: pytest.MonkeyPatch, answer: object, outcome: str, detail: str
) -> None:
    """One headless run as the agents' user with the sandbox on, socket blocking left on and
    the debug log on; only the runtime's line that it applied the filter is `ok`."""
    import subprocess

    from conftest import REAL_SOCKET_PROBE

    from maity.runner import capabilities
    from maity.runner.asuser import AsUser

    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(
        self: AsUser, argv: list[str], env: dict[str, str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((list(argv), env))
        if answer == "timeout":
            raise subprocess.TimeoutExpired(argv, 180)
        if answer == "oserror":
            raise FileNotFoundError(2, "No such file or directory")
        if answer == "undecodable":  # text-mode decoding of the output failed
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        assert isinstance(answer, tuple)
        return subprocess.CompletedProcess(argv, answer[0], "the model's answer", answer[1])

    monkeypatch.setattr(AsUser, "run", run)
    found = REAL_SOCKET_PROBE("/opt/claude", "/agents/bin", AsUser("agents"))
    assert (found.outcome, found.detail) == (outcome, detail)
    [(argv, env)] = calls
    assert argv[0] == "/opt/claude"
    assert argv[argv.index("-p") + 1] == capabilities.SOCKET_PROBE_PROMPT
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["enabled"] is True
    assert settings["sandbox"]["network"] == {"allowAllUnixSockets": False}
    assert env["SRT_DEBUG"] == "1"
    assert env["PATH"] == "/agents/bin"


@pytest.mark.parametrize(
    ("outcome", "level", "code"),
    [("ok", "ok", 0), ("off", "error", 1), ("inconclusive", "error", 1)],
)
def test_check_runs_the_socket_probe_after_an_ok_preflight(
    paired: Path,
    bin_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    level: str,
    code: int,
) -> None:
    """Under bubblewrap with an `ok` preflight, `check` runs the probe with the probed binary
    and the agents' PATH; anything but `ok` is an error."""
    from maity.runner import capabilities

    asked: list[tuple[str, str]] = []

    def probe(binary: str, path: str, as_user: object) -> capabilities.SocketProbe:
        asked.append((binary, path))
        return capabilities.SocketProbe(outcome, "why")

    monkeypatch.setattr(capabilities, "claude_socket_probe", probe)
    monkeypatch.setattr(
        capabilities, "claude_seccomp", lambda as_user: capabilities.ClaudeSeccomp("ok", "x64")
    )
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "linux")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == code
    assert [binary for binary, _ in asked] == [str(bin_dir / "claude")]
    said = marked(capsys, "probe run")
    assert [line.split()[0] for line in said] == [level], said


def test_check_runs_no_socket_probe_when_the_preflight_refuses(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity.runner import capabilities

    def probe(*args: object) -> object:
        raise AssertionError("not asked")

    monkeypatch.setattr(capabilities, "claude_socket_probe", probe)
    monkeypatch.setattr(
        capabilities,
        "claude_seccomp",
        lambda as_user: capabilities.ClaudeSeccomp("unsupported_arch", "riscv64", "m"),
    )
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "linux")
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1


@pytest.mark.parametrize(
    ("text", "why"),
    [('{"sandbox": {"network": {"allowAllUnixSockets": true}}}',
      "sets sandbox.network.allowAllUnixSockets"),
     ('{"sandbox": {"network": {"allowUnixSockets": ["/x"]}}}',
      "sets sandbox.network.allowUnixSockets"),
     ('{"sandbox": {"seccompConfig": {}}}', "sets sandbox.seccompConfig"),
     ('{"permissions": {}}', None),
     ("{not json", "cannot be read as JSON")],
)  # fmt: skip
def test_check_reports_unix_socket_settings_in_the_agents_user_settings(
    paired: Path,
    bin_dir: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    why: str | None,
) -> None:
    """Every start refuses on them, so `check` names them as an error; a clean file is ok."""
    from maity.runner import capabilities

    monkeypatch.setattr(
        capabilities, "claude_seccomp", lambda as_user: capabilities.ClaudeSeccomp("ok", "x64")
    )
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    user = Path.home() / ".claude" / "settings.json"
    user.parent.mkdir(exist_ok=True)
    user.write_text(text)
    monkeypatch.setattr(sys, "platform", "linux")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == (
        0 if why is None else 1
    )
    said = marked(capsys, "Unix socket setting")
    if why is None:
        assert [s.split()[0] for s in said] == ["ok"], said
    else:
        assert [s.split()[0] for s in said] == ["error"], said
        assert why in said[0]


def test_check_reports_a_unix_socket_setting_in_the_managed_settings(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The managed settings win over the placement's file, so a socket key there is an error
    as well, naming the managed file."""
    from maity.runner import capabilities

    monkeypatch.setattr(
        capabilities, "claude_seccomp", lambda as_user: capabilities.ClaudeSeccomp("ok", "x64")
    )
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    managed = capabilities.CLAUDE_MANAGED["linux"]
    managed.parent.mkdir(parents=True, exist_ok=True)
    managed.write_text('{"sandbox": {"network": {"allowUnixSockets": ["/x"]}}}')
    monkeypatch.setattr(sys, "platform", "linux")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    said = marked(capsys, "Unix socket setting")
    assert [s.split()[0] for s in said] == ["error"], said
    assert str(managed) in said[0] and "sets sandbox.network.allowUnixSockets" in said[0]


def test_check_keeps_the_passed_probe_version_and_warns_on_another(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A passing probe keeps the installed version for the target in the state directory; a
    failing one forgets it and says, as an error, what a start will warn about."""
    from maity import state
    from maity.runner import capabilities

    answer = {"outcome": "ok"}
    monkeypatch.setattr(
        capabilities, "claude_seccomp", lambda as_user: capabilities.ClaudeSeccomp("ok", "x64")
    )
    monkeypatch.setattr(
        capabilities,
        "claude_socket_probe",
        lambda *args: capabilities.SocketProbe(answer["outcome"], "why"),
    )
    for tool in ("tmux", "maity", "bwrap", "socat", "unshare", "true"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "linux")
    state_dir = config.load(paired).state_dir
    # A pass recorded for an older version: this run's pass replaces it before anything is
    # compared, so no line about the probe's version and exit 0.
    state.save_state(state_dir, {"local": "2.1.324"}, name=capabilities.PROBE_FILE)
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert marked(capsys, "probe last passed") == []
    found = state.load_state(state_dir, name=capabilities.PROBE_FILE)
    assert found == {"local": "2.1.325"}
    answer["outcome"] = "inconclusive"
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    assert state.load_state(state_dir, name=capabilities.PROBE_FILE) == {}
    said = marked(capsys, "probe has not passed")
    assert [s.split()[0] for s in said] == ["error"], said
    # A preflight that refuses runs no probe: the record stays, and an older one is an error.
    state.save_state(state_dir, {"local": "2.1.324"}, name=capabilities.PROBE_FILE)
    monkeypatch.setattr(
        capabilities,
        "claude_seccomp",
        lambda as_user: capabilities.ClaudeSeccomp("no_seccomp", "x64", "no Seccomp line"),
    )
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 1
    said = marked(capsys, "probe last passed with 2.1.324, installed 2.1.325")
    assert [s.split()[0] for s in said] == ["error"], said
    assert state.load_state(state_dir, name=capabilities.PROBE_FILE) == {"local": "2.1.324"}


@pytest.mark.parametrize("unclean", [None, "claude_hooks_off", "claude_socket_settings"])
def test_check_reads_the_settings_before_it_runs_and_keeps_the_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unclean: str | None
) -> None:
    """Locally as on a host: the hook and socket settings come first, and the headless probe
    runs, and its pass is kept, only while they are clean; otherwise an older pass is
    forgotten and the stale-version error follows."""
    from maity import state
    from maity.runner import capabilities, commands

    order: list[str] = []
    monkeypatch.setattr(capabilities, "claude_sandbox_tools", lambda: ("bwrap", "socat"))
    monkeypatch.setattr(capabilities, "which", lambda tool, path, as_user: f"/usr/bin/{tool}")
    monkeypatch.setattr(capabilities, "sandbox_version_ok", lambda harness, version: True)
    monkeypatch.setattr(
        capabilities, "claude_nested_userns", lambda path, as_user: capabilities.NestedUserns("ok")
    )
    monkeypatch.setattr(
        capabilities, "claude_seccomp", lambda as_user: capabilities.ClaudeSeccomp("ok", "x64")
    )

    def settings(name: str) -> object:
        def read(as_user: object) -> str | None:
            order.append(name)
            return "~/.claude/settings.json sets x" if name == unclean else None

        return read

    monkeypatch.setattr(capabilities, "claude_hooks_off", settings("claude_hooks_off"))
    monkeypatch.setattr(capabilities, "claude_socket_settings", settings("claude_socket_settings"))

    def probe(*args: object) -> capabilities.SocketProbe:
        order.append("probe")
        return capabilities.SocketProbe("ok")

    monkeypatch.setattr(capabilities, "claude_socket_probe", probe)
    state_dir = tmp_path / "st"
    state_dir.mkdir(mode=0o700)
    state.save_state(state_dir, {"local": "2.1.324"}, name=capabilities.PROBE_FILE)
    harness = config.Harness("claude-code", ("interactive", "supervised"), "interactive")
    report = commands.Report()
    commands._check_claude_code(report, harness, version="2.1.325", binary="/usr/bin/claude",
                                state_dir=state_dir)  # fmt: skip
    kept = state.load_state(state_dir, name=capabilities.PROBE_FILE)
    guard = ["claude_hooks_off"]  # the worktree guard reads the hook setting once more, last
    if unclean is None:
        assert order == ["claude_hooks_off", "claude_socket_settings", "probe", *guard]
        assert kept == {"local": "2.1.325"}
        assert not report.failed, report.lines
    else:
        assert order == ["claude_hooks_off", "claude_socket_settings", *guard]  # no probe
        assert kept == {}
        assert ("warn", "harness claude-code: probe not run: the settings above refuse every "
                "sandboxed start") in report.lines  # fmt: skip
        stale = [lvl for lvl, text in report.lines if "probe has not passed" in text]
        assert stale == ["error"], report.lines


def test_check_runs_no_seccomp_preflight_under_seatbelt(
    paired: Path, bin_dir: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity.runner import capabilities

    def preflight(as_user: object) -> object:
        raise AssertionError("not asked")

    monkeypatch.setattr(capabilities, "claude_seccomp", preflight)
    monkeypatch.setattr(capabilities, "claude_socket_probe", preflight)
    for tool in ("tmux", "maity", "sandbox-exec"):
        fake_tool(bin_dir, tool)
    fake_tool(bin_dir, "claude", "2.1.325")
    paired.write_text(paired.read_text() + "\n[harness.claude-code]\n")
    monkeypatch.setattr(sys, "platform", "darwin")
    capsys.readouterr()
    assert cli.main(["runner", "check", "--config", str(paired), "--offline"]) == 0
    assert marked(capsys, "seccomp") == []


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


@pytest.mark.parametrize(
    "placement", ["plc-0003", "", " ", "plc-0003\n", "PLC-0003", "../plc-0003"]
)
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
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    name: str,
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
    own = _runner_home(monkeypatch, tmp_path)  # loop and logcap take only the runner's file
    argv = _in_session_argv(name, str(own[name])) if name in own else IN_SESSION_ARGV[name]
    code = cli.main(["runner", *argv])
    if name in commands.IN_SESSION:
        assert code == 0 and reached == [f"maity.runner.{name}"]
    else:
        assert code == cli.EXIT_REFUSED and reached == []
        assert "for a placed agent" in capsys.readouterr().err


@pytest.mark.parametrize("placed", ["plc-0003", "plc-0004", None])
def test_pgenv_is_no_maity_command(monkeypatch: pytest.MonkeyPatch, placed: str | None) -> None:
    """The review of #2032: pgenv reads a placement's password and starts any command, and an
    agent's `maity` runs outside its sandbox, so `maity runner pgenv` does not exist, under a
    placement (its own or another's MAITY_PLACEMENT) or without one; nothing is started."""
    from maity.runner import pgenv

    reached: list[object] = []

    def fake(argv: object = None) -> int:
        reached.append(argv)
        return 0

    monkeypatch.setattr(pgenv, "main", fake)
    if placed is None:
        monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    else:
        monkeypatch.setenv("MAITY_PLACEMENT", placed)
    argv = ["runner", "pgenv", "/w", "/w/.maity-pg/plc-0003", "/w/pg", "--", "sh", "-c", "true"]
    with pytest.raises(SystemExit) as usage:
        cli.main(argv)
    assert usage.value.code == 2 and reached == []
    assert "pgenv" not in commands.IN_SESSION


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


def _runner_home(monkeypatch: pytest.MonkeyPatch, root: Path) -> dict[str, Path]:
    """An agents' user's home as on an ssh host, with the runner's two files for plc-0003."""
    home = root / "home"
    files = {
        "loop": home / ".maity-runner" / "agents" / "plc-0003" / "loop.json",
        "logcap": home / ".maity-runner" / "logs" / "plc-0003.log",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        path.chmod(0o600)
    monkeypatch.setattr(commands, "_own_home", lambda: home)
    return files


def _in_session_argv(name: str, path: str) -> list[str]:
    return {"loop": ["loop", "--spec", path], "logcap": ["logcap", path, "1"]}[name]


def _reaching(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from maity.runner import logcap, loop

    reached: list[str] = []

    def reach(name: str) -> Callable[[list[str]], int]:
        def main(argv: list[str]) -> int:
            reached.append(name)
            return 0

        return main

    for module in (loop, logcap):
        monkeypatch.setattr(module, "main", reach(module.__name__))
    return reached


WRONG_FILES = [
    "clone", "relative", "temp", "home-dotdir", "other-name", "not-a-placement", "other-dir",
    "link-out", "link-dir", "hard-link", "group-writable", "missing", "directory", "dotdot",
    "link-to-own", "root-link", "other-writable-dir", "double-slash", "fifo", "foreign",
]  # fmt: skip


@pytest.mark.parametrize("placed", [True, False])
@pytest.mark.parametrize("name", sorted(commands.IN_SESSION_FILE))
@pytest.mark.parametrize("where", WRONG_FILES)
def test_an_in_session_command_takes_only_the_file_the_runner_wrote_for_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    name: str,
    where: str,
    placed: bool,
) -> None:
    """`maity` runs outside the agent's sandbox, so `loop --spec` (what it runs) and `logcap`
    (what it cuts) take only the runner's own file in ~/.maity-runner, on every call: with
    MAITY_PLACEMENT dropped from the environment too. Any other path, a link out of it, a
    file of the wrong shape or mode is refused and the handler never runs."""
    own = _runner_home(monkeypatch, tmp_path)
    root = tmp_path / "home" / ".maity-runner"
    clone = tmp_path / "ws" / "maity" / "agent-3"
    clone.mkdir(parents=True)
    outside = clone / "s.json"
    outside.write_text("{}")
    outside.chmod(0o600)
    shape = {"loop": ("agents/plc-0003", "loop.json"), "logcap": ("logs", "plc-0003.log")}[name]
    targets: dict[str, Path | str] = {
        "clone": outside,
        "relative": "s.json",
        "temp": tmp_path / "tmp" / "s.json",
        "home-dotdir": tmp_path / "home" / ".config" / "s.json",
        "other-name": root / shape[0] / "other.json",
        "not-a-placement": root / ("agents/x/loop.json" if name == "loop" else "logs/x.log"),
        "other-dir": root / ("logs/plc-0003.json" if name == "loop" else "agents/plc-0003.log"),
        "link-out": root / shape[0] / "link",
        "link-dir": root / "linked" / shape[1],
        "hard-link": own[name],
        "link-to-own": clone / "own",
        "fifo": own[name],
        "foreign": own[name],
        "root-link": own[name],
        "other-writable-dir": own[name],
        "double-slash": str(own[name]).replace("/.maity-runner/", "/.maity-runner//"),
        "group-writable": own[name],
        "missing": root / shape[0] / ("plc-0004.log" if name == "logcap" else "loop.json"),
        "directory": own[name],
        "dotdot": f"{root}/{shape[0]}/../../.maity-runner-x/{shape[1]}",
    }
    target = targets[where]
    if where in ("temp", "home-dotdir", "other-name", "not-a-placement", "other-dir"):
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        path.chmod(0o600)
    elif where == "link-out":
        Path(target).symlink_to(outside)
    elif where == "link-dir":
        (root / "linked").symlink_to(outside.parent)
        (outside.parent / shape[1]).write_text("{}")
    elif where == "fifo":
        own[name].unlink()
        os.mkfifo(own[name], 0o600)
    elif where == "foreign":
        mine = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: mine + 1)  # files of another user
    elif where == "link-to-own":
        (clone / "own").symlink_to(own[name])
    elif where == "root-link":
        moved = tmp_path / "real-runner"
        root.rename(moved)
        root.symlink_to(moved)
    elif where == "other-writable-dir":
        own[name].parent.chmod(0o777)
    elif where == "hard-link":
        os.link(own[name], tmp_path / "elsewhere")  # the same inode under another name
    elif where == "group-writable":
        own[name].chmod(0o620)
    elif where == "missing" and name == "loop":
        own["loop"].unlink()
    elif where == "directory":
        own[name].unlink()
        own[name].mkdir()
    monkeypatch.chdir(clone)
    if placed:
        monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    else:
        monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    reached = _reaching(monkeypatch)
    assert cli.main(["runner", *_in_session_argv(name, str(target))]) == cli.EXIT_REFUSED
    assert "only the file the runner wrote for it" in capsys.readouterr().err
    assert reached == []


@pytest.mark.parametrize("placed", [True, False])
@pytest.mark.parametrize("name", sorted(commands.IN_SESSION_FILE))
def test_the_runners_own_file_gets_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, placed: bool
) -> None:
    own = _runner_home(monkeypatch, tmp_path)
    if placed:
        monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    else:
        monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    reached = _reaching(monkeypatch)
    assert cli.main(["runner", *_in_session_argv(name, str(own[name]))]) == 0
    assert reached == [f"maity.runner.{name}"]


def test_under_a_placement_only_that_placements_file_gets_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    own = _runner_home(monkeypatch, tmp_path)
    other = own["loop"].parent.parent / "plc-0004" / "loop.json"
    other.parent.mkdir()
    other.write_text("{}")
    other.chmod(0o600)
    monkeypatch.setenv("MAITY_PLACEMENT", "plc-0003")
    assert commands.runner_own_file("loop", str(own["loop"]))
    assert not commands.runner_own_file("loop", str(other))
    monkeypatch.delenv("MAITY_PLACEMENT")  # the runner's own calls carry none
    assert commands.runner_own_file("loop", str(other))


PLACEMENT_VALUES = [None, "", " ", "plc-0003", "plc-0003\n", "PLC-0003", "../plc-0003", "plc-0004"]


@pytest.mark.parametrize("value", PLACEMENT_VALUES)
@pytest.mark.parametrize("name", sorted(commands.IN_SESSION_FILE))
def test_a_placed_session_owns_only_its_own_placements_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str, value: str | None
) -> None:
    """Set, even empty, MAITY_PLACEMENT is a placed session: plc-0003's file is its own only
    for plc-0003. An empty or malformed id is a placed session of unknown identity and owns
    no file; never read as unplaced, which would take any placement's file. Unset, the
    runner's own calls take it as before."""
    own = _runner_home(monkeypatch, tmp_path)
    if value is None:
        monkeypatch.delenv("MAITY_PLACEMENT", raising=False)
    else:
        monkeypatch.setenv("MAITY_PLACEMENT", value)
    allowed = value in (None, "plc-0003")
    assert commands.runner_own_file(name, str(own[name])) is allowed
    reached = _reaching(monkeypatch)
    code = cli.main(["runner", *_in_session_argv(name, str(own[name]))])
    assert (code == 0) is allowed
    assert reached == ([f"maity.runner.{name}"] if allowed else [])


FIRST_ONLY = "`maity runner` is taken only as the first argument"


@pytest.mark.parametrize(
    "words",
    [
        ["--for", "x", "runner", "loop", "--spec", "/x"],
        ["--for=x", "runner", "status"],
        ["--fo", "x", "runner", "status"],  # argparse takes an abbreviated option too
        ["--", "runner", "loop", "--spec", "/x"],
        ["--", "--", "runner", "status"],
        ["--for", "x", "--", "runner", "status"],
    ],
)
def test_runner_is_refused_anywhere_but_first(
    words: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """argparse takes the `runner` group after `--` or a global option too, past the
    harnesses' rules for `maity runner`: refused before anything runs. Where argparse itself
    refuses a spelling first (some Python versions refuse a `--` before the command, and every
    version refuses `-- --`), that refusal stands, but only for words with a `--` before
    `runner`; either way it is a usage error and nothing runs."""
    reached = _reaching(monkeypatch)
    code: int | str | None
    try:
        code = cli.main(words)
    except SystemExit as exc:  # argparse's own usage error, before the first-argument check
        code = exc.code
        assert "--" in words[: words.index("runner")]  # only a `--` spelling may end here
        assert "invalid choice" in capsys.readouterr().err
    else:
        assert FIRST_ONLY in capsys.readouterr().err
    assert code == cli.EXIT_USAGE
    assert reached == []


def test_runner_as_the_first_argument_still_parses(capsys: pytest.CaptureFixture[str]) -> None:
    """`maity runner …` is unchanged: the first-argument rule lets it through to its own
    checks (here argparse's, for a missing required option)."""
    with pytest.raises(SystemExit):
        cli.main(["runner", "loop"])
    assert FIRST_ONLY not in capsys.readouterr().err


def test_another_command_after_a_global_option_is_not_taken_for_runner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Only the `runner` group is held to the first argument; `--for` before another
    command keeps its own handling (tests/test_bridge_for.py covers those commands)."""
    assert cli.main(["--for", "x", "join", "https://x/j/t", "--code", "c"]) == cli.EXIT_USAGE
    err = capsys.readouterr().err
    assert FIRST_ONLY not in err and "--for applies to project commands" in err


def test_without_a_home_in_the_user_database_nothing_gets_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    own = _runner_home(monkeypatch, tmp_path)
    monkeypatch.setattr(commands, "_own_home", lambda: None)
    assert not commands.runner_own_file("loop", str(own["loop"]))


def test_the_home_comes_from_the_user_database_not_from_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An agent can set HOME for its own `maity`; the allow list does not follow it."""
    pwd = pytest.importorskip("pwd")
    fake = tmp_path / "home" / ".maity-runner" / "agents" / "plc-0003" / "loop.json"
    fake.parent.mkdir(parents=True)
    fake.write_text("{}")
    fake.chmod(0o600)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert commands._own_home() == Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert not commands.runner_own_file("loop", str(fake))


def test_no_harness_lets_an_agent_run_maity_runner_from_its_shell(tmp_path: Path) -> None:
    """Claude Code and opencode deny `maity runner` in their command rules, agy in its
    command list; the boundary stays runner_own_file, these keep the call from starting."""
    assert {"maity runner", "maity runner *"} <= set(adapters.MAITY_RUNNER_DENIED)
    assert "maity runner" in adapters.AGY_DENIED_COMMANDS


@posix  # a link, which needs rights on Windows; the runner is POSIX anyway
def test_check_names_a_hand_installed_keep_the_why_skill_and_refuses_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tsk-172s8y208whg, the review of #2056: the operator's own copy is warned about, since a
    # placed Claude Code session sees it beside the delivered one; never an error.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    report = commands.Report()
    commands._check_user_skill(report, RUNNER)
    assert report.lines == []
    skills_dir = tmp_path / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "keep-the-why").symlink_to(tmp_path / "elsewhere")  # a dangling link counts
    commands._check_user_skill(report, RUNNER)
    [(level, text)] = report.lines
    assert level == "warn" and "keep-the-why:keep-the-why" in text and not report.failed
