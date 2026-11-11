"""Every file the image's wheel build reads gets through deploy/Dockerfile.dockerignore.

The ignore file is an allowlist: `*` first, then `!` lines for what the build needs. A new build
input that nobody adds there is missing from the image's context, and only the image job in CI
noticed (hub/hatch_build.py in #1424). This test names it before a push: it collects what the
build stage reads, from the same files the build reads it from (deploy/Dockerfile's requirements,
hub/pyproject.toml's readme, packages and build hook, hatch_build.py's BUNDLED table), and runs
every tracked file of those through a port of Docker's matching rules (hub/context/packaging.md).
A pyproject key through which hatchling would read more, and which this test does not read, fails
the test instead of passing unseen.
"""

from __future__ import annotations

import ast
import posixpath
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
HUB = REPO / "hub"
DOCKERFILE = REPO / "deploy" / "Dockerfile"
IGNORE = REPO / "deploy" / "Dockerfile.dockerignore"

# Characters Docker's patternmatcher escapes because they mean something in a regular expression.
SPECIAL = set(".+()|{}$")

Matcher = Callable[[str], bool]


def compile_pattern(pattern: str) -> Matcher:
    """One cleaned .dockerignore pattern, as moby/patternmatcher (v0.6) compiles it: `*` and `?`
    stop at `/`, `**` crosses directories and `**/` may match none. A pattern without wildcards
    is compared whole, one ending in `**` (and nothing else wild) by prefix, and one starting with
    `**` by suffix, the way patternmatcher sorts them before it falls back to a regular expression.
    """
    out, kind, i = "^", "exact", 0
    while i < len(pattern):
        ch = pattern[i]
        i += 1
        if ch == "*":
            if pattern[i : i + 1] == "*":
                i += 1
                if pattern[i : i + 1] == "/":
                    i += 1
                if i >= len(pattern):
                    if kind == "exact":
                        kind = "prefix"
                    else:
                        out += ".*"
                        kind = "regexp"
                else:
                    out += "(.*/)?"
                    kind = "regexp"
                if i <= 3 and pattern.startswith("**"):
                    kind = "suffix"
            else:
                out += "[^/]*"
                kind = "regexp"
        elif ch == "?":
            out += "[^/]"
            kind = "regexp"
        elif ch in SPECIAL:
            out += "\\" + ch
        elif ch == "\\":
            if i >= len(pattern):
                raise ValueError(f"{pattern!r} ends in a backslash")
            out += re.escape(pattern[i])
            i += 1
            kind = "regexp"
        elif ch in "[]":
            out += ch
            kind = "regexp"
        else:
            out += ch
    if kind == "exact":
        return lambda path: path == pattern
    if kind == "prefix":
        return lambda path: path.startswith(pattern[:-2])
    if kind == "suffix":
        suffix = pattern[2:]
        return lambda path: path.endswith(suffix) or (suffix[:1] == "/" and path == suffix[1:])
    regex = re.compile(out + "$")
    return lambda path: regex.match(path) is not None


def read_ignore(text: str) -> list[tuple[bool, Matcher]]:
    """The patterns in order, (is an exception, matcher), read as moby's ignorefile does: a BOM
    dropped, a `#` in the first column a comment, the rest trimmed, the path cleaned (`.` and `..`
    resolved) and a leading `/` dropped. A lone `!` is refused, as Docker refuses it."""
    patterns = []
    for raw in text.removeprefix("﻿").splitlines():
        if raw.startswith("#"):
            continue
        line = raw.strip()
        if not line:
            continue
        exception = line.startswith("!")
        if exception:
            line = line[1:].strip()
            if not line:
                raise ValueError("a lone `!` is not a pattern")
        line = posixpath.normpath(line)
        if len(line) > 1 and line.startswith("/"):
            line = line.lstrip("/") or "/"
        patterns.append((exception, compile_pattern(line)))
    return patterns


def excluded(path: str, patterns: list[tuple[bool, Matcher]]) -> bool:
    """Docker's rule: every pattern is tried in order and the last one that matches the path,
    or one of its parent directories, decides."""
    parts = path.split("/")
    parents = ["/".join(parts[: i + 1]) for i in range(len(parts) - 1)]
    verdict = False
    for exception, matches in patterns:
        if matches(path) or any(matches(p) for p in parents):
            verdict = not exception
    return verdict


def bundled_sources(hatch_build: str) -> list[str]:
    """The keys of hatch_build.py's BUNDLED, read from its syntax tree: the hook imports
    hatchling, which the test environment need not have."""
    for node in ast.parse(hatch_build).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "BUNDLED":
            value = ast.literal_eval(node.value)
            assert isinstance(value, dict)
            return [str(key) for key in value]
    raise AssertionError("hatch_build.py has no BUNDLED table")


def unread_keys(project: dict[str, Any]) -> list[str]:
    """Keys of pyproject.toml through which hatchling reads files when it builds the wheel, and
    which build_inputs() does not follow: present, each is a build input this test cannot see."""
    unread = []
    if "license-files" in project.get("project", {}):
        unread.append("project.license-files")
    hatch = project.get("tool", {}).get("hatch", {})
    if "path" in hatch.get("version", {}):
        unread.append("tool.hatch.version.path")
    build = hatch.get("build", {})
    unread += [f"tool.hatch.build.{k}" for k in build if k not in ("targets", "hooks", "exclude")]
    unread += [f"tool.hatch.build.hooks.{k}" for k in build.get("hooks", {}) if k != "custom"]
    wheel = build.get("targets", {}).get("wheel", {})
    unread += [
        f"tool.hatch.build.targets.wheel.{k}" for k in wheel if k not in ("packages", "exclude")
    ]
    return unread


def build_inputs() -> list[str]:
    """Paths below the repository root that the image's build stage reads: files, or
    directories it reads whole."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    inputs = sorted(set(re.findall(r"\bhub/requirements/[\w.-]+\.txt\b", dockerfile)))
    assert inputs, "deploy/Dockerfile names no hub/requirements/*.txt: where is its lock?"
    assert re.search(
        r"pip wheel\b.*\./hub\b", dockerfile
    ), "deploy/Dockerfile no longer builds the wheel from ./hub"
    project = tomllib.loads((HUB / "pyproject.toml").read_text(encoding="utf-8"))
    unread = unread_keys(project)
    assert not unread, (
        "hub/pyproject.toml makes hatchling read files through keys this test does not follow; "
        "teach build_inputs() to collect them: " + ", ".join(unread)
    )
    inputs.append("hub/pyproject.toml")
    readme = project["project"].get("readme")
    if isinstance(readme, str):
        inputs.append(f"hub/{readme}")
    elif isinstance(readme, dict) and "file" in readme:
        inputs.append(f"hub/{readme['file']}")
    hatch = project.get("tool", {}).get("hatch", {}).get("build", {})
    packages = hatch.get("targets", {}).get("wheel", {}).get("packages")
    assert packages, "hub/pyproject.toml names no wheel packages (tool.hatch.build.targets.wheel)"
    inputs += [f"hub/{package}" for package in packages]
    hook = hatch.get("hooks", {}).get("custom")
    if hook is not None:
        script = hook.get("path", "hatch_build.py")
        inputs.append(f"hub/{script}")
        inputs += bundled_sources((HUB / script).read_text(encoding="utf-8"))
    return inputs


def tracked(paths: list[str]) -> list[str]:
    """Every tracked file at or below each path, so a file the working tree lacks does not hide
    a gap and an untracked one does not add one."""
    result = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z", "--", *paths],
        capture_output=True,
        check=True,
    )
    return sorted(name for name in result.stdout.decode("utf-8").split("\0") if name)


def git_checkout() -> bool:
    try:
        subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--git-dir"], capture_output=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


@pytest.mark.skipif(not git_checkout(), reason="needs the repository's git checkout (not an sdist)")
def test_every_wheel_build_input_passes_the_image_allowlist() -> None:
    assert DOCKERFILE.is_file(), "deploy/Dockerfile is gone: point this test at the image's build"
    assert (
        IGNORE.is_file()
    ), "deploy/Dockerfile.dockerignore is gone: point this test at its allowlist"
    patterns = read_ignore(IGNORE.read_text(encoding="utf-8"))
    inputs = build_inputs()
    files = tracked(inputs)
    for path in inputs:
        assert any(
            f == path or f.startswith(path + "/") for f in files
        ), f"{path} is a build input with no tracked file"
    missing = [f for f in files if excluded(f, patterns)]
    assert not missing, (
        "deploy/Dockerfile.dockerignore keeps these build inputs out of the image's context; "
        "add a `!` line for them: " + ", ".join(missing)
    )


@pytest.mark.parametrize(
    ("lines", "path", "out"),
    [
        # The allowlist's own shape: everything out, then exceptions, then exclusions inside them.
        (["*", "!hub/src"], "hub/src/maity_hub/app.py", False),
        (["*", "!hub/src"], "hub/hatch_build.py", True),
        (["*", "!hub/requirements/*.txt"], "hub/requirements/build.txt", False),
        (["*", "!hub/requirements/*.txt"], "hub/requirements/build.in", True),
        (["*", "!web", "web/tools"], "web/tools/check.py", True),
        (["*", "!web", "web/tools"], "web/js/app.js", False),
        # `**/` matches no directory or any number; `.*` is a dotfile or a dot directory's content.
        (["*", "!hub/src", "**/__pycache__"], "hub/src/maity_hub/__pycache__/a.pyc", True),
        (["*", "!web", "**/.*"], "web/.keep", True),
        (["*", "!web", "**/.*"], "web/vendor/.cache/x.js", True),
        (["*", "!web", "**/.*"], "web/js/a.b.js", False),
        # The last matching line decides, wherever the earlier ones pointed.
        (["!web", "*"], "web/js/app.js", True),
        (["# a comment", "", "*", "!/docs/join-page.md"], "docs/join-page.md", False),
        (["*", "!docs/join-page.md"], "docs/api.md", True),
        (["*"], ".github/workflows/ci.yml", True),
        # A leading `**` without wildcards after it is a suffix: `**_build.py` hits hatch_build.py.
        (["*", "!hub", "**_build.py"], "hub/hatch_build.py", True),
        (["*", "!hub", "**_build.py"], "hub/build.py", False),
        (["*", "!hub", "**/build.py"], "build.py", True),
        # A path is cleaned first: `.` and `..` inside a pattern resolve.
        (["*", "!hub/src/../hatch_build.py"], "hub/hatch_build.py", False),
        (["*", "!hub/./src"], "hub/src/maity_hub/app.py", False),
        # A `#` is a comment in the first column only; an indented one is a pattern.
        (["*", "!#x", " #x"], "#x", True),
        (["*", "!web", "#web/js"], "web/js/app.js", False),
        # A trailing `**` is a prefix, and `?` stops at `/`.
        (["*", "!web/j**"], "web/js/app.js", False),
        (["*", "!web/j?"], "web/js", False),
        (["*", "!web/j?"], "web/j/s", True),
    ],
)
def test_the_matcher_follows_dockers_rules(lines: list[str], path: str, out: bool) -> None:
    assert excluded(path, read_ignore("\n".join(lines))) is out


def test_a_bom_is_dropped_as_docker_drops_it() -> None:
    """With a BOM read as part of the first line, `*` would never match and the allowlist would
    let everything through."""
    assert excluded("hub/hatch_build.py", read_ignore("﻿*\n!hub/src\n")) is True


@pytest.mark.parametrize("text", ["*\n!\n", "*\n!   \n", "*\nweb\\"])
def test_patterns_docker_refuses_are_refused(text: str) -> None:
    with pytest.raises(ValueError):
        read_ignore(text)


def test_unread_pyproject_keys_are_named() -> None:
    project = {
        "project": {"license-files": ["LICENSE"]},
        "tool": {
            "hatch": {
                "version": {"path": "src/maity_hub/__init__.py"},
                "build": {
                    "include": ["x"],
                    "exclude": ["y"],
                    "hooks": {"custom": {}, "vcs": {}},
                    "targets": {"wheel": {"packages": ["src/a"], "force-include": {"../L": "L"}}},
                },
            }
        },
    }
    assert unread_keys(project) == [
        "project.license-files",
        "tool.hatch.version.path",
        "tool.hatch.build.include",
        "tool.hatch.build.hooks.vcs",
        "tool.hatch.build.targets.wheel.force-include",
    ]
    assert unread_keys(tomllib.loads((HUB / "pyproject.toml").read_text(encoding="utf-8"))) == []
