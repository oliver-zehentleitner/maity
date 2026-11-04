from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from maity import proc


def test_prompts_are_off_and_stdin_is_closed(tmp_path: Path) -> None:
    script = 'printf "%s %s " "$GIT_TERMINAL_PROMPT" "$GCM_INTERACTIVE"; cat; echo end'
    result = proc.run(["sh", "-c", script], tmp_path)
    assert result.stdout == "0 never end\n"


def test_a_hanging_command_times_out(tmp_path: Path) -> None:
    with pytest.raises(proc.ToolError, match="did not answer"):
        proc.run(["sleep", "5"], tmp_path, timeout=0.2)


def test_a_missing_tool_is_named(tmp_path: Path) -> None:
    with pytest.raises(proc.ToolError, match="not installed"):
        proc.run(["maity-no-such-tool"], tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="a shell script stands in for the tool")
def test_a_relative_path_entry_is_never_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = tmp_path / "maity-test-tool"
    planted.write_text("#!/bin/sh\necho planted\n")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", "bin"]))
    assert proc.program("maity-test-tool") is None
    with pytest.raises(proc.ToolError, match="not installed"):
        proc.run(["maity-test-tool"], tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert proc.program("maity-test-tool") == str(planted)
    assert proc.run(["maity-test-tool"], tmp_path).stdout == "planted\n"


def test_git_refuses_a_remote_helper_the_clone_allows(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "protocol.ext.allow", "always"], check=True
    )
    result = proc.run([*proc.GIT, "ls-remote", f"ext::sh -c touch% {marker}"], tmp_path, timeout=10)
    assert result.returncode != 0
    assert not marker.exists()
