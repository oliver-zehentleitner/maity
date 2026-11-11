"""`maity gh`: a placed agent's pull requests on its own clone's repository, nothing else.

The forge login on a runner's machine is the operator's and reaches every repository its
account may. No glob rule on a command line pins gh to one (`gh pr create -dR other/repo`,
a pull request's URL, `-F` with the login file), so no placed session runs gh at all. This
command runs outside the harness's sandbox like every `maity` call, takes only the shapes
below, and starts gh with the repository the runner recorded for the clone, never one the
command line or the environment names (cli/context/runner.md).
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
from pathlib import Path

from maity import clonecheck

# What the runner writes for a clone whose repository's grant has `pull_requests = true`:
# the repository (`host/owner/name`) and the gh it found, one per line. Empty: not granted.
PULL_REQUESTS_PATH = Path(".git", "maity", "pull_requests")
BODY_MAX = 65536  # bytes; the forge's own limit for a pull request's body
JSON_FIELDS = re.compile(r"[A-Za-z]+(,[A-Za-z]+)*")
# A pull request named by its number or its head branch; never a URL or `owner:branch`.
SELECTOR = re.compile(r"[0-9]+|[A-Za-z0-9._][A-Za-z0-9._/-]{0,254}")
REPOSITORY = re.compile(r"[a-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# gh's settings that would name another repository or host, or another login.
DROPPED_ENV = (
    "GH_REPO",
    "GH_HOST",
    "GH_CONFIG_DIR",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)

ALLOWED = (
    "maity gh pr create --title <title> (--body <text> | --body-file <file in this clone>)"
    " [--base <branch>] [--head <branch>] [--draft]; "
    "maity gh pr view [<number> | <branch>] [--json <fields>] [--comments]"
)


class Refused(Exception):
    """The call is not one `maity gh` makes; the text says what it takes."""


def parser(sub: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore[type-arg]
    """The `gh` command's own parser, strict: no abbreviations and only these options, so a
    bundle (`-dR`), another selector or an option gh would read a file with is refused by
    argparse before anything runs."""
    gh: argparse.ArgumentParser = sub.add_parser(
        "gh",
        help="open or read this clone's pull requests (a runner placement with pull requests)",
        description="Pull requests on this clone's repository only, under a runner placement "
        "whose repository's grant has pull_requests = true. " + ALLOWED,
        allow_abbrev=False,
    )
    gh_sub = gh.add_subparsers(dest="gh_group", required=True)
    pr = gh_sub.add_parser("pr", help="pull requests", allow_abbrev=False)
    pr_sub = pr.add_subparsers(dest="gh_command", required=True)
    create = pr_sub.add_parser("create", help="open a pull request", allow_abbrev=False)
    create.add_argument("--title", required=True, help="the pull request's title")
    body = create.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="the body as text")
    body.add_argument("--body-file", help="a file in this clone, read by maity, not by gh")
    create.add_argument("--base", help="the branch to merge into (the default branch if left out)")
    create.add_argument("--head", help="the branch with the changes (the current one if left out)")
    create.add_argument("--draft", action="store_true", help="open it as a draft")
    view = pr_sub.add_parser("view", help="read a pull request", allow_abbrev=False)
    view.add_argument("selector", nargs="?", help="its number or head branch (the current one)")
    view.add_argument("--json", dest="json_fields", help="comma-separated fields, as gh's --json")
    view.add_argument("--comments", action="store_true", help="with its comments")
    return gh


def granted(root: Path) -> tuple[str, str]:
    """The repository and gh the runner recorded for the clone at `root`; Refused when its
    grant has no pull requests or the record is not one the runner writes."""
    where = root / PULL_REQUESTS_PATH
    try:
        mode = where.lstat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_size > 4096:
            raise OSError("not a plain file")
        lines = where.read_bytes().decode("utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeDecodeError):
        raise Refused(f"the runner's record {PULL_REQUESTS_PATH} is not readable") from None
    if not lines:
        raise Refused(
            "this clone's repository grants no pull requests: the runner's operator sets "
            "pull_requests = true in its repositories table"
        )
    if len(lines) != 2 or not REPOSITORY.fullmatch(lines[0]):
        raise Refused(f"the runner's record {PULL_REQUESTS_PATH} is not one it writes")
    program = lines[1]
    if not (os.path.isabs(program) and os.path.isfile(program) and os.access(program, os.X_OK)):
        raise Refused(f"the gh the runner recorded ({program}) is not a program here")
    return lines[0], program


def body_file(root: Path, given: str) -> bytes:
    """The file's content, read here: its real path (links and `..` resolved) is inside the
    clone and not under its `.git`, and it is a plain file of at most BODY_MAX bytes."""
    path = Path(given)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        real = path.resolve(strict=True)
    except (OSError, RuntimeError):
        raise Refused(f"--body-file {given}: no such file") from None
    clone = root.resolve()
    if real == clone or clone not in real.parents:
        raise Refused(f"--body-file {given}: not a file in this clone ({clone})")
    if real == clone / ".git" or (clone / ".git") in real.parents:
        raise Refused(f"--body-file {given}: a file under the clone's .git is not a body")
    try:
        with open(real, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise Refused(f"--body-file {given}: not a plain file")
            data = handle.read(BODY_MAX + 1)
    except OSError as exc:
        raise Refused(f"--body-file {given}: cannot be read ({exc.strerror})") from None
    if len(data) > BODY_MAX:
        raise Refused(f"--body-file {given}: over {BODY_MAX} bytes")
    return data


def command(
    args: argparse.Namespace, root: Path, repository: str, gh: str
) -> tuple[list[str], bytes | None]:
    """gh's argument list, built here option by option (`--name=value`, so no value is read
    as an option), with the recorded repository, and what goes to its standard input."""
    argv = [gh, "pr", args.gh_command, f"--repo={repository}"]
    if args.gh_command == "create":
        argv.append(f"--title={args.title}")
        if args.body_file is not None:
            stdin = body_file(root, args.body_file)
        else:
            stdin = args.body.encode("utf-8")
            if len(stdin) > BODY_MAX:
                raise Refused(f"--body: over {BODY_MAX} bytes")
        argv.append("--body-file=-")  # gh reads the body from maity, never a path
        for name in ("base", "head"):
            value = getattr(args, name)
            if value is not None:
                if not SELECTOR.fullmatch(value):
                    raise Refused(f"--{name} {value!r}: not a branch name. Allowed: {ALLOWED}")
                argv.append(f"--{name}={value}")
        if args.draft:
            argv.append("--draft")
        return argv, stdin
    if args.json_fields is not None:
        if not JSON_FIELDS.fullmatch(args.json_fields):
            raise Refused(f"--json {args.json_fields!r}: field names and commas only")
        argv.append(f"--json={args.json_fields}")
    if args.comments:
        argv.append("--comments")
    if args.selector is not None:
        if not SELECTOR.fullmatch(args.selector):
            raise Refused(
                f"{args.selector!r}: a pull request of this repository by number or branch, "
                f"not a URL or another repository's. Allowed: {ALLOWED}"
            )
        argv += ["--", args.selector]
    return argv, None


def run(args: argparse.Namespace) -> int:
    """The call, in the runner's clone only (`clonecheck.placement_root`), gh's exit code."""
    try:
        root = clonecheck.placement_root()
    except clonecheck.Refused as exc:
        raise Refused(str(exc)) from None
    if root is None:
        raise Refused("maity gh runs only in a session a runner placed; " + ALLOWED)
    repository, gh = granted(root)
    argv, stdin = command(args, root, repository, gh)
    env = {k: v for k, v in os.environ.items() if k not in DROPPED_ENV}
    done = subprocess.run(argv, input=stdin, cwd=root, env=env, check=False)  # noqa: S603
    return done.returncode
