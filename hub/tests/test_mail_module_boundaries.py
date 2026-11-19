"""Which hub modules the mail and notification helpers may import (hub/context/notifications.md,
"The address lifecycle is a module of its own" and "The text language is a module of its own").
Every import is read from the source, a function-local one too, so a workaround against a cycle
cannot hide in a function body."""

from __future__ import annotations

import ast
from pathlib import Path
from types import ModuleType

from maity_hub import text_language
from maity_hub.mail import text as mail_text
from maity_hub.notifications import address


def imported(module: ModuleType) -> set[str]:
    """Every module `module` imports, at its top or inside a function."""
    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
            # `from maity_hub.notifications import preferences` names the module as an alias.
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_the_address_lifecycle_never_imports_the_settings() -> None:
    found = imported(address)
    assert "maity_hub.notifications.preferences" not in found


# The modules that import `notifications.address` inside a function rather than at their top,
# as they imported `notifications.preferences` before the address moved there (item 16b of
# tsk-xx108ajy287x). Known and kept for now; a new one is a cycle workaround to look at, not
# to add here unasked (hub/context/notifications.md 5829e0a1).
LOCAL_ADDRESS_IMPORTS = {
    "maintenance.py",
    "notifications/retention.py",
    "registration_accounts.py",
    "routes/registration.py",
}


def _imports_address(node: ast.AST) -> bool:
    if not isinstance(node, ast.ImportFrom):
        return False
    if node.module == "maity_hub.notifications.address":
        return True
    return node.module == "maity_hub.notifications" and any(
        alias.name == "address" for alias in node.names
    )


def test_only_the_known_modules_import_the_address_inside_a_function() -> None:
    package = Path(str(address.__file__)).parents[1]  # src/maity_hub
    local: set[str] = set()
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if any(_imports_address(node) for node in ast.walk(function)):
                local.add(path.relative_to(package).as_posix())
    assert local == LOCAL_ADDRESS_IMPORTS


def test_the_text_language_imports_only_the_tables_and_the_languages() -> None:
    hub = {name for name in imported(text_language) if name.startswith("maity_hub")}
    assert hub <= {"maity_hub", "maity_hub.languages", "maity_hub.tables"}, hub


def test_the_mail_text_imports_only_the_headers() -> None:
    hub = {name for name in imported(mail_text) if name.startswith("maity_hub")}
    assert hub <= {"maity_hub.mail", "maity_hub.mail.headers"}, hub
