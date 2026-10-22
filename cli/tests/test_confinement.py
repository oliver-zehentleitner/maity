"""The confinement boundary after the post-merge re-verification (cli/context/runner.md).

An agent can write `.git/commondir` from inside a sandbox: git needs `.git` writable for its
lock files. What keeps that from running code outside the sandbox is the session's
`GIT_COMMON_DIR`, set by the runner in the harness's own environment, which a sandboxed
command cannot change. An agent that unsets it for its own git only reaches itself.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import git

from maity.runner import adapters, capabilities, config

RUNNER_SRC = Path(__file__).resolve().parents[1] / "src" / "maity" / "runner"


def planted(tmp_path: Path) -> tuple[Path, Path]:
    """A clone whose `.git/commondir` points at a copy with `core.fsmonitor` set, as an agent
    can leave it; and the file that fsmonitor creates when it runs."""
    clone = tmp_path / "ws" / "maity" / "agent-3"
    clone.mkdir(parents=True)
    git(clone, "init", "-q")
    git(clone, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty",
        "-m", "one")  # fmt: skip
    evil = tmp_path / "evil"
    shutil.copytree(clone / ".git", evil)
    marker = tmp_path / "ran"
    with (evil / "config").open("a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}\n")
    (clone / ".git" / "commondir").write_text(f"{evil}\n")
    return clone, marker


def session_env(clone: Path) -> dict[str, str]:
    """The environment a harness and its own git calls get from the runner."""
    ctx = adapters.Context(
        placement={"id": "plc-0003", "mode": "interactive"},
        harness=config.Harness("stub", ("interactive",), "interactive"),
        binary=None, clone=clone, agent_dir=clone.parent, grant=config.RepositoryGrant(),
        restart=config.Restart(),
    )  # fmt: skip
    return {**os.environ, **adapters.launch(ctx).env}


def test_the_harness_git_ignores_a_planted_commondir(tmp_path: Path) -> None:
    clone, marker = planted(tmp_path)
    done = subprocess.run(["git", "status", "--short"], cwd=clone, env=session_env(clone),
                          capture_output=True, check=False)  # fmt: skip
    assert done.returncode == 0 and not marker.exists()


def test_without_the_pin_the_planted_commondir_runs_code(tmp_path: Path) -> None:
    """What the pin prevents, and what an agent gets by unsetting it: its own git runs the
    planted program, as itself, inside its own sandbox."""
    clone, marker = planted(tmp_path)
    env = {k: v for k, v in session_env(clone).items() if not k.startswith("GIT_")}
    subprocess.run(["git", "status", "--short"], cwd=clone, env=env, capture_output=True,
                   check=False)  # fmt: skip
    assert marker.exists()


def planted_submodule(tmp_path: Path) -> tuple[Path, Path]:
    """A clone with a nested repository registered as a gitlink, whose own configuration
    sets `core.fsmonitor`: what an agent can plant with work-tree and index writes alone.
    The pin on the clone's `.git` does not reach it."""
    clone = tmp_path / "ws" / "maity" / "agent-3"
    sub = clone / "sub"
    sub.mkdir(parents=True)
    git(clone, "init", "-q")
    git(clone, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty",
        "-m", "one")  # fmt: skip
    git(sub, "init", "-q")
    git(sub, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty",
        "-m", "sub")  # fmt: skip
    marker = tmp_path / "ran"
    with (sub / ".git" / "config").open("a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}\n")
    head = git(sub, "rev-parse", "HEAD")
    git(clone, "update-index", "--add", "--cacheinfo", f"160000,{head},sub")
    return clone, marker


def test_a_planted_submodule_runs_nothing_in_the_session(tmp_path: Path) -> None:
    clone, marker = planted_submodule(tmp_path)
    subprocess.run(["git", "status", "--porcelain"], cwd=clone, env=session_env(clone),
                   capture_output=True, check=False)  # fmt: skip
    assert not marker.exists()


def test_maitys_own_git_runs_nothing_from_a_planted_submodule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bin_dir: Path
) -> None:
    """For Claude Code `maity` runs outside the sandbox: `maity report` reads the clone with
    git, so that git has to run nothing the agent planted, whatever its environment."""
    from maity import gitfacts

    clone, marker = planted_submodule(tmp_path)
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)
    facts = gitfacts.collect(clone)
    assert not marker.exists()
    assert facts.dirty  # the staged gitlink still counts as a change


def test_the_control_a_planted_submodule_runs_without_the_settings(tmp_path: Path) -> None:
    clone, marker = planted_submodule(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "status", "--porcelain"], cwd=clone, env=env, capture_output=True,
                   check=False)  # fmt: skip
    assert marker.exists()


def codex_sandbox() -> str | None:
    binary = shutil.which("codex")
    if binary is None or not capabilities._codex_sandbox_starts(binary):
        return None
    return binary


@pytest.mark.skipif(codex_sandbox() is None, reason="needs codex with a working sandbox")
def test_inside_codexs_sandbox_an_agent_reaches_only_itself(tmp_path: Path) -> None:
    codex = codex_sandbox()
    assert codex is not None
    clone, _ = planted(tmp_path)
    (clone / ".git" / "commondir").unlink()
    other = tmp_path / "ws" / "maity" / "agent-4" / ".git" / "maity"
    other.mkdir(parents=True)
    (other / "credential").write_text("another agent's")
    secret = tmp_path / "home" / ".ssh"
    secret.mkdir(parents=True)
    (secret / "id").write_text("key")
    home = tmp_path / "st" / "agents" / "plc-0003" / "codex-home"
    home.mkdir(parents=True)
    ctx = adapters.Context(
        placement={"id": "plc-0003", "mode": "supervised"},
        harness=config.Harness("codex", ("supervised",), "supervised"), binary=codex,
        clone=clone, agent_dir=home.parent, grant=config.RepositoryGrant(),
        restart=config.Restart(), private=(tmp_path / "st", secret),
        workspaces=tmp_path / "ws",
    )  # fmt: skip
    (home / "config.toml").write_text(adapters.codex_config(ctx))
    # TMPDIR is a writable root of Codex's workspace profile; the test's own holds tmp_path.
    scratch = tmp_path / "codex-tmp"
    scratch.mkdir()
    env = {**os.environ, "CODEX_HOME": str(home), "TMPDIR": str(scratch)}

    def sandboxed(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([codex, "sandbox", "--", "sh", "-c", script], cwd=clone, env=env,
                              capture_output=True, text=True, timeout=60, check=False)  # fmt: skip

    (clone / ".git" / "maity").mkdir(exist_ok=True)
    (clone / ".git" / "maity" / "credential").write_text("its own")
    own = sandboxed("cat .git/maity/credential")  # the control: the sandbox runs, reads the clone
    assert own.returncode == 0 and own.stdout == "its own", own.stderr
    for path, content in ((other / "credential", "another agent's"), (secret / "id", "key")):
        denied = sandboxed(f"cat {path}")
        assert denied.returncode == 1 and content not in denied.stdout
    # The agent plants commondir and a config with fsmonitor, and runs git without the pin:
    # the program runs, but in the sandbox, and cannot write outside it.
    # Codex's workspace profile can always write /tmp (where tmp_path may be): the marker
    # goes into another clone, which the profile hides.
    outside = tmp_path / "ws" / "maity" / "agent-4"
    evil = clone / "evil"
    script = (
        f"cp -r .git {evil} && printf '[core]\\n\\tfsmonitor = touch {outside}/ran\\n' >> "
        f"{evil}/config && echo {evil} > .git/commondir && env -u GIT_COMMON_DIR git status"
    )
    sandboxed(script)
    assert (evil / "config").exists() and (clone / ".git" / "commondir").exists()
    assert not (outside / "ran").exists()
    # The harness's own git, outside the sandbox, carries the pin and ignores it.
    done = subprocess.run(["git", "status", "--short"], cwd=clone, env=session_env(clone),
                          capture_output=True, check=False)  # fmt: skip
    assert done.returncode == 0 and not (outside / "ran").exists()


def _git_argv_sites(root: Path) -> set[tuple[str, str]]:
    """(file, function) of every list or tuple that holds the string `git` or a path ending
    in `/git`: the argv of a git call, however it is built."""
    found: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        for node in ast.walk(tree):
            if not isinstance(node, ast.List | ast.Tuple):
                continue
            if not any(
                isinstance(e, ast.Constant) and isinstance(e.value, str)
                and (e.value == "git" or e.value.endswith("/git"))
                for e in node.elts
            ):  # fmt: skip
                continue
            owner = min(
                (f for f in scopes if f.lineno <= node.lineno <= (f.end_lineno or 0)),
                key=lambda f: (f.end_lineno or 0) - f.lineno,
                default=None,
            )
            found.add((str(path.relative_to(root)), owner.name if owner else "<module>"))
    return found


def test_maity_runs_git_only_through_its_guarded_paths() -> None:
    """Every `git` maity and the runner start: maity's own (proc.GIT: no fsmonitor, no hooks,
    not into submodules), a clone into a missing directory (workspace.prepare), and gc's read
    with SAFE_GIT and the pinned environment. A new call site has to use one of them, or be
    added here on purpose."""
    root = RUNNER_SRC.parent
    found = {(f, s) for f, s in _git_argv_sites(root) if not f.endswith("_test.py")}
    assert found == {
        ("proc.py", "<module>"),
        ("runner/workspace.py", "prepare"),
        ("runner/operate.py", "<module>"),
    }
