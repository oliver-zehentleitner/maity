"""The confinements a runner advertises (docs/api.md §15.3): the CLI, the hub and the contract
name the same values, so a value one side sends cannot be refused by the other at hello.

The CLI is not installed beside the hub, so its `harness_entry` is read as source: the values it
can put into `confinement` are the string values of that one expression.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import get_args

from maity_hub.routes.runner import Confinement

ROOT = Path(__file__).parents[2]
CAPABILITIES = ROOT / "cli/src/maity/runner/capabilities.py"
CONTRACT = ROOT / "docs/api.md"


def _cli_confinements() -> set[str]:
    """The values `harness_entry` can put into `confinement`: a constant, or
    `{harness: value}.get(harness.id, default)`; any other form fails, so the test is
    looked at again."""
    tree = ast.parse(CAPABILITIES.read_text(encoding="utf-8"))
    entry = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "harness_entry"
    )
    found = [
        value
        for node in ast.walk(entry)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values, strict=True)
        if isinstance(key, ast.Constant) and key.value == "confinement"
    ]
    assert len(found) == 1, "harness_entry sets `confinement` once"
    expression = found[0]
    if isinstance(expression, ast.Constant):
        return {str(expression.value)}
    assert isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute)
    assert expression.func.attr == "get" and isinstance(expression.func.value, ast.Dict)
    values = [*expression.func.value.values, expression.args[1]]
    strings = [v.value for v in values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    assert len(strings) == len(values), "every value is a string constant"
    return {str(v) for v in strings}


def _contract_confinements() -> set[str]:
    """The values §15.3 lists after "`confinement`:", up to the sentence on advertising."""
    text = CONTRACT.read_text(encoding="utf-8")
    start = text.index("`confinement`: `allowlist`")
    end = text.index("A runner advertises the confinement", start)
    return set(re.findall(r"`(\w+)`\s+\(", text[start:end]))


def test_the_hub_accepts_every_confinement_the_cli_advertises() -> None:
    hub = set(get_args(Confinement))
    assert _cli_confinements() <= hub
    assert "sandbox" in _cli_confinements()  # codex: the reason this test exists


def test_the_hub_takes_the_contracts_confinements() -> None:
    assert set(get_args(Confinement)) == _contract_confinements()
