from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from maity.runner import plaincall

SRC = Path(plaincall.__file__).resolve().parents[2]


def bash(command: str, tool: str = "Bash") -> dict[str, object]:
    return {"hook_event_name": "PreToolUse", "tool_name": tool,
            "tool_input": {"command": command, "description": "x"}}  # fmt: skip


REFUSED = [
    "maity a > f",
    "maity a >> f",
    "maity a 2>f",
    "maity a ; x",
    "maity a && x",
    "maity a || x",
    "maity a & x",
    "maity a &",
    "maity a | x",
    "maity a $(x)",
    "maity a `x`",
    "maity a <(x)",
    "maity a < f",
    "maity a <<< text",
    "maity say x - <<'EOF'\nhello\nEOF",
    "maity a\nx",
    "maity a $X",
    "maity a ${X@P}",
    "maity a $'x'",
    'maity a "$(x)"',
    'maity a "`x`"',
    'maity a "${X}"',
    "maity a 'unclosed",
    'maity a "unclosed',
    "maity a 'two\nlines'",
    "maity a \\",
    "maity a (x)",
    "maity a {x,y}",
    "maity a *",
    "maity a b",
    "﻿maity a ; x",  # a character the harness may trim before matching
    "\nmaity a > f",
    "  maity\ta | x",
    "MAITY a > f",
    "maity;x",  # stays in the sandbox anyway; refused all the same
]
ALLOWED = [
    "maity task show tsk-x",
    "maity say --to lotse#wtwy 'text with ; & | < > $ ` and (x)'",
    'maity say --to lotse "a \\"quoted\\" word, 50%"',
    "maity files get fil-1 -o out/a.txt",
    "maity a\\;b",  # an escaped character is a literal one
    "  maity resume  \n",
    "maity",
]
NOT_DECIDED = [
    "git status | head",
    "make test && echo ok",
    "FOO=1 maity a > f",  # starts with a variable: not a maity line for the hook
    "env maity a > f",
    "echo maity > f",
]


@pytest.mark.parametrize("command", REFUSED)
def test_a_maity_line_that_is_not_one_plain_call_is_refused(command: str) -> None:
    assert plaincall.refusal(bash(command)) == plaincall.REFUSED


@pytest.mark.parametrize("command", ALLOWED)
def test_one_plain_maity_call_passes(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


@pytest.mark.parametrize("command", NOT_DECIDED)
def test_other_command_lines_are_left_to_the_permission_rules(command: str) -> None:
    assert plaincall.refusal(bash(command)) is None


def test_any_tool_with_a_command_is_checked() -> None:
    assert plaincall.refusal(bash("maity a | x", tool="PowerShell")) == plaincall.REFUSED
    assert plaincall.refusal({"tool_name": "Read", "tool_input": {"file_path": "/x"}}) is None
    assert plaincall.refusal({"tool_name": "Bash", "tool_input": {"command": 3}}) is None


def test_unreadable_input_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert plaincall.refusal([1]) is not None
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"\xff{")))
    assert plaincall.main([]) == 2


def run_hook(payload: bytes) -> subprocess.CompletedProcess[str]:
    """As Claude Code runs it: a separate process, input on stdin, isolated mode."""
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-I", "-c",
         f"import sys; sys.path.insert(0, {str(SRC)!r}); "
         "from maity.runner import plaincall; raise SystemExit(plaincall.main())"],
        input=payload.decode("utf-8", "surrogateescape"), capture_output=True, text=True,
        check=False, timeout=60,
    )  # fmt: skip


def test_the_hook_process_refuses_with_exit_2_and_the_reason_on_stderr() -> None:
    done = run_hook(json.dumps(bash("maity a > f")).encode())
    assert done.returncode == 2 and done.stdout == ""
    assert done.stderr.strip() == plaincall.REFUSED
    done = run_hook(json.dumps(bash("maity task show tsk-x")).encode())
    assert done.returncode == 0 and done.stdout == "" and done.stderr == ""
    assert run_hook(b"not json").returncode == 2
