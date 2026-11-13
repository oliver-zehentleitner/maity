"""`maity gh`: a placed agent's pull requests on its own clone's repository, nothing else.

The forge login on a runner's machine is the operator's and reaches every repository its
account may. No glob rule on a command line pins gh to one (`gh pr create -dR other/repo`,
a pull request's URL, `-F` with the login file), so under the harness's sandbox no placed
session runs gh at all. This
command runs outside the harness's sandbox like every `maity` call, takes only the shapes
below, and starts gh with the repository the runner recorded for the clone, never one the
command line or the environment names, in an empty directory of its own with the branch
and the body given by maity (cli/context/runner.md).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from maity import clonecheck, gitfacts, inclone

# What the runner writes for a clone whose repository's grant has `pull_requests = true`:
# the repository (`host/owner/name`) and the gh it found, one per line. Empty: not granted.
# A record of the runner's, in its directory for the agent (`clonecheck.runner_record`); only
# for Codex, which is never granted pull requests, at PULL_REQUESTS_PATH in the clone.
PULL_REQUESTS = "pull_requests"
PULL_REQUESTS_PATH = Path(".git", "maity", PULL_REQUESTS)
BODY_MAX = 65536  # bytes; the forge's own limit for a pull request's body
JSON_FIELDS = re.compile(r"[A-Za-z]+(,[A-Za-z]+)*")
# A pull request named by its number or its head branch; never a URL or `owner:branch`.
SELECTOR = re.compile(r"[0-9]+|[A-Za-z0-9._][A-Za-z0-9._/-]{0,254}")
REPOSITORY = re.compile(r"[a-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
# What `pr view` without `--json` asks gh for. gh's own text view is never used: its query
# depends on gh's version, and older ones (2.46, a distribution's package) ask for a field
# the forge refuses today (`projectCards`), so every plain `gh pr view` fails there. These
# fields exist in every gh that has `--json`; maity prints them as text (`_readable`).
VIEW_FIELDS = (
    "number", "title", "state", "isDraft", "url", "headRefName", "baseRefName", "author",
    "body",
)  # fmt: skip
# What gh gets from maity's environment, nothing else: no variable that names another
# repository, host, configuration or login (GH_REPO, GH_HOST, GH_CONFIG_DIR, XDG_CONFIG_HOME,
# GH_TOKEN, GITHUB_TOKEN, the enterprise tokens) and none that starts a program (GH_PAGER,
# PAGER, GH_BROWSER, GH_EDITOR, GH_FORCE_TTY). gh then reads the login of the agents' user
# under HOME. The proxy and certificate settings stay: a network may need them, and they
# come from the session the runner started, which a command cannot change (an assignment in
# front of `maity` matches no allow rule).
ENV_PASSED = (
    "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy",
)  # fmt: skip
ENV_SET = {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "NO_COLOR": "1"}
# Whether the body file's walk (inclone) runs here; on Windows maity takes no body file.
WALKS = inclone.WALKS

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


def _record(root: Path, dot_git: int | None) -> bytes:
    """The runner's pull-request record (`clonecheck.runner_record`): in the runner's
    directory for the agent, never a file in the clone, which the agent can write."""
    return clonecheck.runner_record(root, dot_git, PULL_REQUESTS, 4096)


def granted(root: Path, dot_git: int | None = None) -> tuple[str, str]:
    """The repository and gh the runner recorded for the clone at `root` (`_record`);
    Refused when its grant has no pull requests or the record is not one the runner
    writes."""
    try:
        lines = _record(root, dot_git).decode("utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeDecodeError, clonecheck.Refused):
        raise Refused(f"the runner's record {PULL_REQUESTS} is not readable") from None
    if not lines:
        raise Refused(
            "this clone's repository grants no pull requests: the runner's operator sets "
            "pull_requests = true in its repositories table"
        )
    if len(lines) != 2 or not REPOSITORY.fullmatch(lines[0]):
        raise Refused(f"the runner's record {PULL_REQUESTS} is not one it writes")
    program = lines[1]
    if not (os.path.isabs(program) and os.path.isfile(program) and os.access(program, os.X_OK)):
        raise Refused(f"the gh the runner recorded ({program}) is not a program here")
    return lines[0], program


def body_file(root: Path, given: str, dot_git: int | None = None) -> bytes:
    """The file's content, read through descriptors only (`inclone.read`): maity runs
    outside the sandbox, and any name it looked up twice could point elsewhere the second
    time. A regular file in the clone, outside its `.git` (the one `clonecheck.opened_git`
    checked, `dot_git`), with no other hard link, of at most BODY_MAX bytes
    (cli/context/runner.md 9f43804d)."""
    if not WALKS:  # Windows
        raise Refused(
            f"--body-file {given}: this system cannot open a file without following links;"
            " give the text with --body"
        )
    try:
        return inclone.read(root, given, "--body-file", BODY_MAX, dot_git)
    except inclone.Refused as exc:
        raise Refused(str(exc)) from None


def current_branch(root: Path) -> str:
    """The branch the clone is on, read with maity's own pinned git (never gh's): gh runs
    outside the clone, so it is given the branch instead of reading it there."""
    try:
        branch = gitfacts._branch(root)
    except gitfacts.FactsError as exc:
        raise Refused(str(exc)) from None
    if branch is None:
        raise Refused("the clone is on no branch (a detached HEAD); check out your branch first")
    return branch


def command(
    args: argparse.Namespace, root: Path, repository: str, gh: str, dot_git: int | None = None
) -> tuple[list[str], bytes | None]:
    """gh's argument list, built here option by option (`--name=value`, so no value is read
    as an option), with the recorded repository, and what goes to its standard input. The
    head branch and the pull request to view are always named: gh reads nothing from git."""
    argv = [gh, "pr", args.gh_command, f"--repo={repository}"]
    if args.gh_command == "create":
        argv.append(f"--title={args.title}")
        if args.body_file is not None:
            stdin = body_file(root, args.body_file, dot_git)
        else:
            stdin = args.body.encode("utf-8")
            if len(stdin) > BODY_MAX:
                raise Refused(f"--body: over {BODY_MAX} bytes")
        argv.append("--body-file=-")  # gh reads the body from maity, never a path
        head = args.head if args.head is not None else current_branch(root)
        for name, value in (("base", args.base), ("head", head)):
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
    else:  # never gh's text view (VIEW_FIELDS): the fields maity prints as text
        fields = [*VIEW_FIELDS, *(["comments"] if args.comments else [])]
        argv.append(f"--json={','.join(fields)}")
    selector = args.selector if args.selector is not None else current_branch(root)
    if not SELECTOR.fullmatch(selector):
        raise Refused(
            f"{selector!r}: a pull request of this repository by number or branch, "
            f"not a URL or another repository's. Allowed: {ALLOWED}"
        )
    argv += ["--", selector]
    return argv, None


def as_text(args: argparse.Namespace) -> bool:
    """Whether maity prints gh's answer as text: a `pr view` without `--json`."""
    return bool(args.gh_command == "view" and args.json_fields is None)


def _readable(answer: bytes) -> str:
    """A `pr view` answer (VIEW_FIELDS, comments with `--comments`) as text; what is not
    the JSON gh gives is printed as it came."""
    try:
        pr = json.loads(answer)
        author = (pr.get("author") or {}).get("login") or "?"
        state = pr["state"] + (" (draft)" if pr.get("isDraft") else "")
        lines = [
            f"#{pr['number']} {pr['title']}",
            f"{state}  {pr['headRefName']} -> {pr['baseRefName']}  by {author}",
            pr["url"],
            "",
            (pr.get("body") or "").rstrip() or "(no description)",
        ]
        for comment in pr.get("comments") or []:
            who = (comment.get("author") or {}).get("login") or "?"
            lines += ["", f"--- {who}, {comment.get('createdAt', '')}", comment["body"].rstrip()]
    except (ValueError, KeyError, TypeError, AttributeError):
        return answer.decode("utf-8", "replace")
    return "\n".join(lines) + "\n"


def gh_env(environ: Mapping[str, str], gh: str) -> dict[str, str]:
    """gh's environment: ENV_PASSED from maity's, ENV_SET, and a PATH of gh's own directory
    and the system's, so a program gh starts by name is not one placed on the session's
    PATH; on Windows also what a program needs to start there."""
    env = {name: environ[name] for name in ENV_PASSED if name in environ}
    env.update(clonecheck.kept_env(environ))
    env.update(clonecheck.git_path_env(gh))
    env.update(ENV_SET)
    return env


def run(args: argparse.Namespace) -> int:
    """The call, under the runner's placement only (`clonecheck.placement_root`): gh's exit
    code. gh runs in an empty directory of its own, never in the clone, whose .git the
    session can shape: the repository, the branch and the body all come from maity."""
    try:
        root = clonecheck.placement_root()
    except clonecheck.Refused as exc:
        raise Refused(str(exc)) from None
    if root is None:
        raise Refused("maity gh runs only in a session a runner placed; " + ALLOWED)
    try:
        with clonecheck.opened_git(root) as dot_git:
            repository, gh = granted(root, dot_git)
            argv, stdin = command(args, root, repository, gh, dot_git)
    except clonecheck.Refused as exc:
        raise Refused(str(exc)) from None
    text = as_text(args)
    with tempfile.TemporaryDirectory(prefix="maity-gh-") as empty:
        done = subprocess.run(  # noqa: S603 - the recorded gh, arguments built above
            argv,
            input=stdin,
            cwd=empty,
            env=gh_env(os.environ, gh),
            check=False,
            stdout=subprocess.PIPE if text else None,
        )
    if text and done.stdout:
        sys.stdout.write(_readable(done.stdout))
        sys.stdout.flush()
    return done.returncode
