"""Every file the image's wheel build reads gets through deploy/Dockerfile.dockerignore.

The ignore file is an allowlist: `*` first, then `!` lines for what the build needs. A new build
input that nobody adds there is missing from the image's context, and only the image job in CI
noticed (hub/hatch_build.py in #1424). This test names it locally: it collects what the build
stage reads, from the same files the build reads it from (deploy/Dockerfile's requirements,
hub/pyproject.toml's readme, packages and build hook, hatch_build.py's BUNDLED table), and runs
every tracked file of those through Docker's matching rules (hub/context/packaging.md).
"""

from __future__ import annotations

import ast
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HUB = REPO / "hub"
DOCKERFILE = REPO / "deploy" / "Dockerfile"
IGNORE = REPO / "deploy" / "Dockerfile.dockerignore"


def pattern_regex(pattern: str) -> re.Pattern[str]:
    """A .dockerignore pattern as Docker's patternmatcher compiles it: `*` and `?` stop at `/`,
    `**` crosses any number of directories, and `**/` may match none."""
    out, i = "", 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i + 1 : i + 2] == "*":
                i += 2
                if pattern[i : i + 1] == "/":
                    i += 1
                out += ".*" if i >= len(pattern) else "(.*/)?"
                continue
            out += "[^/]*"
        elif ch == "?":
            out += "[^/]"
        elif ch == "\\" and i + 1 < len(pattern):
            i += 1
            out += re.escape(pattern[i])
        elif ch == "[":
            end = pattern.find("]", i + 1)
            if end < 0:
                out += re.escape(ch)
            else:
                out += "[" + pattern[i + 1 : end].replace("\\", "\\\\") + "]"
                i = end
        else:
            out += re.escape(ch)
        i += 1
    return re.compile("^" + out + "$")


def read_ignore(text: str) -> list[tuple[bool, re.Pattern[str]]]:
    """The patterns in order: (is an exception, compiled). Comments and blank lines are skipped,
    a leading `/` and `./` are dropped, as Docker does."""
    patterns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        exception = line.startswith("!")
        line = line[1:].strip() if exception else line
        line = re.sub(r"/+", "/", line).lstrip("/")
        while line.startswith("./"):
            line = line[2:]
        line = line.rstrip("/")
        if line:
            patterns.append((exception, pattern_regex(line)))
    return patterns


def excluded(path: str, patterns: list[tuple[bool, re.Pattern[str]]]) -> bool:
    """Docker's rule: every pattern is tried in order and the last one that matches the path,
    or one of its parent directories, decides."""
    parts = path.split("/")
    candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    verdict = False
    for exception, regex in patterns:
        if regex.match(path) or any(regex.match(c) for c in candidates[:-1]):
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


def build_inputs() -> list[str]:
    """Paths below the repository root that the image's build stage reads: files, or
    directories it reads whole."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    inputs = sorted(set(re.findall(r"\bhub/requirements/[\w.-]+\.txt\b", dockerfile)))
    assert (
        inputs
    ), "deploy/Dockerfile names no hub/requirements/*.txt: where does the build get its lock?"
    assert re.search(
        r"pip wheel\b.*\./hub\b", dockerfile
    ), "deploy/Dockerfile no longer builds the wheel from ./hub"
    project = tomllib.loads((HUB / "pyproject.toml").read_text(encoding="utf-8"))
    inputs.append("hub/pyproject.toml")
    readme = project["project"].get("readme")
    if isinstance(readme, str):
        inputs.append(f"hub/{readme}")
    elif isinstance(readme, dict) and "file" in readme:
        inputs.append(f"hub/{readme['file']}")
    hatch = project.get("tool", {}).get("hatch", {}).get("build", {})
    inputs += [f"hub/{package}" for package in hatch["targets"]["wheel"]["packages"]]
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


@pytest.mark.skipif(
    not (DOCKERFILE.is_file() and IGNORE.is_file() and git_checkout()),
    reason="needs the repository's deploy/ and git (not in an sdist)",
)
def test_every_wheel_build_input_passes_the_image_allowlist() -> None:
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
        (
            ["*", "!hub/src", "**/__pycache__"],
            "hub/src/maity_hub/__pycache__/app.cpython-312.pyc",
            True,
        ),
        (["*", "!web", "**/.*"], "web/.keep", True),
        (["*", "!web", "**/.*"], "web/vendor/.cache/x.js", True),
        (["*", "!web", "**/.*"], "web/js/a.b.js", False),
        # The last matching line decides, wherever the earlier ones pointed.
        (["!web", "*"], "web/js/app.js", True),
        (["# a comment", "", "*", "!/docs/join-page.md"], "docs/join-page.md", False),
        (["*", "!docs/join-page.md"], "docs/api.md", True),
        (["*"], ".github/workflows/ci.yml", True),
    ],
)
def test_the_matcher_follows_dockers_rules(lines: list[str], path: str, out: bool) -> None:
    assert excluded(path, read_ignore("\n".join(lines))) is out
