"""The routes that ask for the second factor (docs/api.md §2.8.4) are the ones the dashboard
knows: web/tools/step-up-routes.json, which web/tools/check.py holds the dashboard's calls to
(tsk-6dk86ej9s0fq). The hub's set is read from its source: every route whose handler reaches
`second_factor.require_step_up`, directly, in a lambda it hands on, or through the hub's own
functions it calls."""

from __future__ import annotations

import ast
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "maity_hub"
LIST = Path(__file__).resolve().parents[2] / "web" / "tools" / "step-up-routes.json"
METHODS = {"get", "post", "put", "patch", "delete"}

Key = tuple[str, str]  # (module, function)


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _aliases(tree: ast.Module, module: str) -> dict[str, str]:
    """Each name a module imports another hub module as: `from maity_hub.auth import
    second_factor` gives second_factor -> maity_hub.auth.second_factor."""
    found: dict[str, str] = {}
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join(
                    package.split(".")[: len(package.split(".")) - node.level + 1]
                    + ([base] if base else [])
                )
            for alias in node.names:
                found[alias.asname or alias.name] = f"{base}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
    return found


def _callee(call: ast.Call, module: str, aliases: dict[str, str]) -> Key | None:
    fn = call.func
    if isinstance(fn, ast.Name):
        target = aliases.get(fn.id)
        if target and "." in target:  # `from maity_hub.x import f`
            mod, name = target.rsplit(".", 1)
            return (mod, name)
        return (module, fn.id)
    if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id in aliases:
        return (aliases[fn.value.id], fn.attr)
    return None


def hub_step_up_routes() -> set[str]:
    calls: dict[Key, set[Key]] = {}
    seeds: set[Key] = set()
    routes: list[tuple[Key, str, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        module = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = _aliases(tree, module)
        # The prefix of each router the module makes: `router = APIRouter(prefix="/auth")`.
        prefixes: dict[str, str] = {}
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "APIRouter"
            ):
                prefix = next(
                    (
                        k.value.value
                        for k in node.value.keywords
                        if k.arg == "prefix" and isinstance(k.value, ast.Constant)
                    ),
                    "",
                )
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefixes[target.id] = str(prefix)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = (module, node.name)
            calls[key] = set()
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    if (
                        isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "require_step_up"
                    ) or (isinstance(inner.func, ast.Name) and inner.func.id == "require_step_up"):
                        seeds.add(key)
                    callee = _callee(inner, module, aliases)
                    if callee:
                        calls[key].add(callee)
            for deco in node.decorator_list:
                if (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in METHODS
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id in prefixes
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                ):
                    routes.append(
                        (
                            key,
                            deco.func.attr.upper(),
                            prefixes[deco.func.value.id] + str(deco.args[0].value),
                        )
                    )
    seeds.discard(("maity_hub.auth.second_factor", "require_step_up"))
    asking = set(seeds)
    while True:
        more = {key for key, callees in calls.items() if key not in asking and callees & asking}
        if not more:
            break
        asking |= more
    return {f"{method} {path}" for key, method, path in routes if key in asking}


def listed_routes() -> set[str]:
    return {entry["route"] for entry in json.loads(LIST.read_text(encoding="utf-8"))["routes"]}


def test_the_dashboards_list_is_the_hubs_step_up_routes() -> None:
    hub = hub_step_up_routes()
    listed = listed_routes()
    assert hub - listed == set(), "asks for the factor, missing in web/tools/step-up-routes.json"
    assert listed - hub == set(), "listed in web/tools/step-up-routes.json, the hub does not ask"


def test_the_reading_finds_a_route_through_a_helper() -> None:
    """The ones only a helper module asks for are found too: account deletion, the second
    factor's own routes, an instance admin's reset."""
    hub = hub_step_up_routes()
    assert {
        "POST /me/deletion",
        "POST /auth/second-factor/totp",
        "DELETE /auth/second-factor",
        "POST /admin/users/{human_id}/second-factor/reset",
        "POST /requests/{request_id}/answer",
    } <= hub
    assert "GET /me" not in hub and "GET /runners/enrollments" not in hub
