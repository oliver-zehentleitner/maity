from __future__ import annotations

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
