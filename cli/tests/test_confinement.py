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
    env = {k: v for k, v in session_env(clone).items() if k != "GIT_COMMON_DIR"}
    subprocess.run(["git", "status", "--short"], cwd=clone, env=env, capture_output=True,
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
    outside = tmp_path / "outside"
    outside.mkdir()
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


def test_the_runner_runs_git_only_through_its_two_guarded_paths() -> None:
    """Any `git` the runner itself starts: a clone into a missing directory (workspace.py),
    or gc's read with SAFE_GIT and the pinned environment (operate.py). A new call site has
    to come through one of them, or be added here on purpose."""
    found: set[tuple[str, str]] = set()
    for path in sorted(RUNNER_SRC.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        scopes = {node: node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts:
                first = node.elts[0]
                if isinstance(first, ast.Constant) and first.value == "git":
                    owner = next(
                        (name for scope, name in scopes.items()
                         if scope.lineno <= node.lineno <= (scope.end_lineno or 0)),
                        "<module>",
                    )  # fmt: skip
                    found.add((path.name, owner))
    assert found == {("workspace.py", "prepare"), ("operate.py", "<module>")}
