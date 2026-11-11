"""`maity gh`: a placed agent's pull requests on its own clone's repository, nothing else.

The forge login on a runner's machine is the operator's and reaches every repository its
account may. No glob rule on a command line pins gh to one (`gh pr create -dR other/repo`,
a pull request's URL, `-F` with the login file), so no placed session runs gh at all. This
command runs outside the harness's sandbox like every `maity` call, takes only the shapes
below, and starts gh with the repository the runner recorded for the clone, never one the
command line or the environment names, in an empty directory of its own with the branch
and the body given by maity (cli/context/runner.md).
"""

from __future__ import annotations

import argparse
import errno
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from maity import clonecheck, gitfacts, proc

# What the runner writes for a clone whose repository's grant has `pull_requests = true`:
# the repository (`host/owner/name`) and the gh it found, one per line. Empty: not granted.
PULL_REQUESTS_PATH = Path(".git", "maity", "pull_requests")
BODY_MAX = 65536  # bytes; the forge's own limit for a pull request's body
JSON_FIELDS = re.compile(r"[A-Za-z]+(,[A-Za-z]+)*")
# A pull request named by its number or its head branch; never a URL or `owner:branch`.
SELECTOR = re.compile(r"[0-9]+|[A-Za-z0-9._][A-Za-z0-9._/-]{0,254}")
REPOSITORY = re.compile(r"[a-z0-9.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
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


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _where(root: Path, real: Path) -> str:
    """`inside`, `git` (under the clone's .git) or `outside`: the parents of `real` compared
    with the clone and its .git by device and inode, not by name, so a case-insensitive
    volume's `.GIT` is the same directory as `.git`."""
    clone = os.stat(root)
    try:
        git = os.stat(root / ".git")
    except OSError:
        git = None
    for parent in real.parents:
        try:
            here = os.stat(parent)
        except OSError:
            return "outside"
        if git is not None and _same(here, git):
            return "git"
        if _same(here, clone):
            return "inside"
    return "outside"


def body_file(root: Path, given: str) -> bytes:
    """The file's content, read here through one descriptor. maity runs outside the sandbox,
    so a path checked and then opened again by name could be swapped in between (a link or
    a directory, by code the sandbox runs). The file is opened first, without following a
    final link and without blocking (a FIFO), and then checked as opened: a regular file
    with no other hard link, of at most BODY_MAX bytes, whose path, resolved after the open,
    is that same file (device and inode), inside the clone and not under its `.git`."""
    path = Path(given)
    if not path.is_absolute():
        path = Path.cwd() / path
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP or path.is_symlink():
            raise Refused(f"--body-file {given}: a link; name the file itself") from None
        if exc.errno == errno.ENOENT:
            raise Refused(f"--body-file {given}: no such file") from None
        raise Refused(f"--body-file {given}: cannot be read ({exc.strerror})") from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise Refused(f"--body-file {given}: not a plain file")
        if opened.st_nlink != 1:
            raise Refused(f"--body-file {given}: the file has other hard links")
        try:
            real = path.resolve(strict=True)
            named = os.stat(real)
        except (OSError, RuntimeError):
            raise Refused(f"--body-file {given}: changed while it was read") from None
        if not _same(named, opened):
            raise Refused(f"--body-file {given}: changed while it was read")
        place = _where(root, real)
        if place == "git":
            raise Refused(f"--body-file {given}: a file under the clone's .git is not a body")
        if place != "inside":
            raise Refused(f"--body-file {given}: not a file in this clone ({root})")
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
    except proc.ToolError as exc:
        raise Refused(str(exc)) from None
    if branch is None:
        raise Refused("the clone is on no branch (a detached HEAD); check out your branch first")
    return branch


def command(
    args: argparse.Namespace, root: Path, repository: str, gh: str
) -> tuple[list[str], bytes | None]:
    """gh's argument list, built here option by option (`--name=value`, so no value is read
    as an option), with the recorded repository, and what goes to its standard input. The
    head branch and the pull request to view are always named: gh reads nothing from git."""
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
    selector = args.selector if args.selector is not None else current_branch(root)
    if not SELECTOR.fullmatch(selector):
        raise Refused(
            f"{selector!r}: a pull request of this repository by number or branch, "
            f"not a URL or another repository's. Allowed: {ALLOWED}"
        )
    argv += ["--", selector]
    return argv, None


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
    repository, gh = granted(root)
    argv, stdin = command(args, root, repository, gh)
    with tempfile.TemporaryDirectory(prefix="maity-gh-") as empty:
        done = subprocess.run(  # noqa: S603 - the recorded gh, arguments built above
            argv, input=stdin, cwd=empty, env=gh_env(os.environ, gh), check=False
        )
    return done.returncode
