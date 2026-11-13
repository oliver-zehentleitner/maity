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
import errno
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from maity import clonecheck, gitfacts, onboarding

# What the runner writes for a clone whose repository's grant has `pull_requests = true`:
# the repository (`host/owner/name`) and the gh it found, one per line. Empty: not granted.
PULL_REQUESTS_PATH = Path(".git", "maity", "pull_requests")
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
# Whether this system can open a name in a directory's descriptor without following a link:
# the body file's walk needs both. Windows has neither, and there maity takes no body file.
WALKS = os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")

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
    """The runner's pull-request record. Under a placement it is read from the `.git` that
    `clonecheck.opened_git` checked, through its descriptor, never by the name `.git` again:
    sandboxed code can rename `.git` and put one of its own there. Without descriptors
    (`dot_git` None: Windows) it is read by name, from a `.git` checked by inode."""
    if dot_git is None:
        where = root / PULL_REQUESTS_PATH
        mode = where.lstat()
        if not stat.S_ISREG(mode.st_mode) or mode.st_size > 4096:
            raise OSError("not a plain file")
        return where.read_bytes()
    folder = os.O_RDONLY | clonecheck.NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(PULL_REQUESTS_PATH.parts[1], folder, dir_fd=dot_git)
    try:
        return clonecheck._read_regular(PULL_REQUESTS_PATH.parts[2], fd, 4096)
    finally:
        os.close(fd)


def granted(root: Path, dot_git: int | None = None) -> tuple[str, str]:
    """The repository and gh the runner recorded for the clone at `root` (`_record`);
    Refused when its grant has no pull requests or the record is not one the runner
    writes."""
    try:
        lines = _record(root, dot_git).decode("utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeDecodeError, clonecheck.Refused):
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


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _in_clone(root: Path, given: str) -> list[str]:
    """The names from the clone's root down to the file `given` names (relative to the
    current directory, as the agent wrote it), worked out on the text alone: no name is
    looked up here, so none can be swapped. Refused when it leads out of the clone."""
    absolute = os.path.normpath(os.path.join(os.getcwd(), given))
    for base in dict.fromkeys((str(root), os.path.realpath(root))):
        relative = os.path.relpath(absolute, base)
        if relative != os.curdir and relative.split(os.sep)[0] != os.pardir:
            return relative.split(os.sep)
    raise Refused(f"--body-file {given}: not a file in this clone ({root})")


def _open_at(directory: int, name: str, flags: int, given: str) -> int:
    """`name` opened in the directory `directory` without following a link."""
    try:
        return os.open(name, flags | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as exc:
        try:
            link = stat.S_ISLNK(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode)
        except OSError:
            link = False
        if link or exc.errno == errno.ELOOP:
            raise Refused(
                f"--body-file {given}: a link; name the file itself ({name} is one)"
            ) from None
        if exc.errno == errno.ENOENT:
            raise Refused(f"--body-file {given}: no such file") from None
        if exc.errno == errno.ENOTDIR:
            raise Refused(f"--body-file {given}: {name} is not a directory") from None
        raise Refused(f"--body-file {given}: cannot be read ({exc.strerror})") from None


def body_file(root: Path, given: str, dot_git: int | None = None) -> bytes:
    """The file's content, read through descriptors only. maity runs outside the sandbox,
    and any name it looked up twice could point elsewhere the second time (a directory
    exchanged with a link by code the sandbox runs). So the clone's root is opened once,
    each directory on the way is opened from the one before without following a link and
    refused when it is the clone's `.git` (device and inode of the `.git` that
    `clonecheck.opened_git` checked, `dot_git`), and the file is opened from
    the last one without following a link and without blocking (a FIFO): a regular file
    with no other hard link, of at most BODY_MAX bytes (cli/context/runner.md 9f43804d)."""
    names = _in_clone(root, given)
    if not WALKS:  # Windows
        raise Refused(
            f"--body-file {given}: this system cannot open a file without following links;"
            " give the text with --body"
        )
    folder = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(root, folder)
    try:
        git: os.stat_result | None
        if dot_git is not None:
            git = os.fstat(dot_git)
        else:
            try:
                git = os.stat(".git", dir_fd=fd, follow_symlinks=False)
            except OSError:
                git = None
        for index, name in enumerate(names):
            last = index == len(names) - 1
            flags = os.O_RDONLY | os.O_NONBLOCK if last else folder
            inner = _open_at(fd, name, flags, given)
            os.close(fd)
            fd = inner
            opened = os.fstat(fd)
            if git is not None and _same(opened, git):
                raise Refused(f"--body-file {given}: a file under the clone's .git is not a body")
        if not stat.S_ISREG(opened.st_mode):
            raise Refused(f"--body-file {given}: not a plain file")
        if opened.st_nlink != 1:
            raise Refused(f"--body-file {given}: the file has other hard links")
        chunks: list[bytes] = []
        size = 0
        while size <= BODY_MAX:
            chunk = os.read(fd, BODY_MAX + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    if size > BODY_MAX:
        raise Refused(f"--body-file {given}: over {BODY_MAX} bytes")
    return b"".join(chunks)


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
    the JSON gh gives is printed as it came. Either way the text is someone's: every field is
    cleaned (`onboarding`), one-line fields kept on their line, so no escape reaches the
    terminal and no title or name starts a line of its own."""
    one = onboarding.inline
    try:
        pr = json.loads(answer)
        author = (pr.get("author") or {}).get("login") or "?"
        state = pr["state"] + (" (draft)" if pr.get("isDraft") else "")
        lines = [
            f"#{one(pr['number'])} {one(pr['title'])}",
            f"{one(state)}  {one(pr['headRefName'])} -> {one(pr['baseRefName'])}  by {one(author)}",
            one(pr["url"]),
            "",
            onboarding.clean((pr.get("body") or "").rstrip()) or "(no description)",
        ]
        for comment in pr.get("comments") or []:
            who = one((comment.get("author") or {}).get("login") or "?")
            when = one(comment.get("createdAt", ""))
            lines += ["", f"--- {who}, {when}", onboarding.clean(comment["body"].rstrip())]
    except (ValueError, KeyError, TypeError, AttributeError):
        return onboarding.clean(answer.decode("utf-8", "replace"))
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
