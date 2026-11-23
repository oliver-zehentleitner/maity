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
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from maity import clonecheck, gitfacts, inclone, onboarding

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
    "maity gh pr create --title <title> (--body <text> | --body-file <file in this clone or"
    " the scratch>) [--base <branch>] [--head <branch>] [--draft]; "
    "maity gh pr view [<number> | <branch>] [--json <fields>] [--comments]; for a placed lead"
    " (a manager, with lead = true in the grant): "
    "maity gh pr merge <number> --match-head-commit <sha> --subject <text> (--body <text> |"
    " --body-file <file>); "
    "maity gh pr edit [<number> | <branch>] [--title <text>] (--body <text> | --body-file"
    " <file>); "
    "maity gh pr ready [<number> | <branch>]; "
    "maity gh run list --commit <sha>; "
    "maity gh run view <run id> [--job <job id>] [--log-failed]"
)

# The lead commands (tsk-pvnj16k8d6m0): what a placed lead needs daily and no placed session
# can do with gh itself. Each needs the runner's LEAD record beside PULL_REQUESTS and the
# member's role `manager`, read from the hub at each call (cli/context/runner.md).
LEAD = "gh_lead"
LEAD_COMMANDS = frozenset({("pr", "merge"), ("pr", "edit"), ("pr", "ready"),
                           ("run", "list"), ("run", "view")})  # fmt: skip
LEAD_ROLE = "manager"
# The LEAD record's bytes as the runner's text write leaves them on this system.
LEAD_RECORD = ("lead" + os.linesep).encode("ascii")
SHA = re.compile(r"[0-9a-f]{40}")  # a full commit id: a merge names exactly the head it read
NUMBER = re.compile(r"[1-9][0-9]{0,9}")  # a pull request of this repository
# A CI run or job of this repository: ids are already 11 and 12 digits, and grow; 19 digits
# hold any positive 64-bit id.
RUN_ID = re.compile(r"[1-9][0-9]{0,18}")
# What `run list` asks gh for: one run per line of the head's workflows, the ids `run view` takes.
RUN_FIELDS = (
    "databaseId", "workflowName", "name", "event", "status", "conclusion", "headSha",
    "createdAt",
)  # fmt: skip
# What `run view` without `--log-failed` asks gh for: the run's jobs by name, so a required
# check (`ci-ok`) is read as a job of the head's own run (context/process.md, the CI watcher).
RUN_VIEW_FIELDS = ("databaseId", "name", "status", "conclusion", "headSha", "event", "jobs")
LOG_TAIL = 400  # lines of `run view --log-failed` maity prints, the last ones
# Whole lines a lead's merge or edit body loses: the attribution trailers and the generated-with
# footer a harness appends. Only a line that is wholly one of these; text inside a line stays.
FOOTER = (
    re.compile(r"\s*co-authored-by:.*", re.IGNORECASE),
    re.compile(r"\s*(?:\U0001f916\s*)?generated (?:with|by) \[[^\]]*\]\([^)]*\)\s*", re.IGNORECASE),
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
    body.add_argument(
        "--body-file", help="a file in this clone or the scratch, read by maity, not by gh"
    )
    create.add_argument("--base", help="the branch to merge into (the default branch if left out)")
    create.add_argument("--head", help="the branch with the changes (the current one if left out)")
    create.add_argument("--draft", action="store_true", help="open it as a draft")
    view = pr_sub.add_parser("view", help="read a pull request", allow_abbrev=False)
    view.add_argument("selector", nargs="?", help="its number or head branch (the current one)")
    view.add_argument("--json", dest="json_fields", help="comma-separated fields, as gh's --json")
    view.add_argument("--comments", action="store_true", help="with its comments")
    lead = " (a placed lead: a manager, with lead = true in the grant)"
    merge = pr_sub.add_parser("merge", help="squash-merge a pull request" + lead,
                              allow_abbrev=False)  # fmt: skip
    merge.add_argument("selector", metavar="number", help="the pull request's number")
    merge.add_argument(
        "--match-head-commit",
        dest="head_commit",
        required=True,
        help="the full sha of the head you read; gh refuses if it moved",
    )
    merge.add_argument("--subject", required=True, help="the squash commit's subject, one line")
    _body_options(merge)
    edit = pr_sub.add_parser("edit", help="set a pull request's body" + lead, allow_abbrev=False)
    edit.add_argument("selector", nargs="?", help="its number or head branch (the current one)")
    edit.add_argument("--title", help="a new title")
    _body_options(edit)
    ready = pr_sub.add_parser("ready", help="mark a draft ready for review" + lead,
                              allow_abbrev=False)  # fmt: skip
    ready.add_argument("selector", nargs="?", help="its number or head branch (the current one)")
    run = gh_sub.add_parser("run", help="CI runs" + lead, allow_abbrev=False)
    run_sub = run.add_subparsers(dest="gh_command", required=True)
    runs = run_sub.add_parser("list", help="the runs of a commit" + lead, allow_abbrev=False)
    runs.add_argument("--commit", required=True, help="the commit's full sha")
    shown = run_sub.add_parser("view", help="a run's jobs, or its failed lines" + lead,
                               allow_abbrev=False)  # fmt: skip
    shown.add_argument("selector", metavar="run_id", help="the run's id (digits)")
    shown.add_argument(
        "--job",
        help="one job, by its id (digits); gh then reads the run the job belongs to and does "
        "not use the run id given",
    )
    shown.add_argument("--log-failed", action="store_true",
                       help=f"the failed steps' log, its last {LOG_TAIL} lines")  # fmt: skip
    return gh


def _body_options(command: argparse.ArgumentParser) -> None:
    """`--body` or `--body-file`, one of them required, as `pr create` takes them."""
    body = command.add_mutually_exclusive_group(required=True)
    body.add_argument("--body", help="the body as text")
    body.add_argument(
        "--body-file", help="a file in this clone or the scratch, read by maity, not by gh"
    )


def is_lead(args: argparse.Namespace) -> bool:
    """Whether the call is one of the lead commands (LEAD_COMMANDS)."""
    return (args.gh_group, args.gh_command) in LEAD_COMMANDS


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


def lead_granted(root: Path, dot_git: int | None = None) -> None:
    """Refused unless the runner wrote its LEAD record for this clone (`lead = true` beside
    `pull_requests = true`): `lead` and a newline, in the runner's directory for the agent.
    Never one in the clone (Codex's IN_CLONE), which the session could write itself, and only
    from this placement's own directory in the runner's layout, `…/agents/<placement id>/git`
    (review A1721 of #2054): GIT_PRIVATE_ENV is taken as the runner set it, so a value naming
    another placement's directory is refused here."""
    where = clonecheck.runner_dir(root)
    if where is None:
        raise Refused("the lead commands need the runner's own record, which this placement lacks")
    placement = clonecheck.placement_id()
    if (placement is None or where.name != "git" or where.parent.name != placement
            or where.parent.parent.name != "agents"):  # fmt: skip
        raise Refused(
            f"{clonecheck.GIT_PRIVATE_ENV} is not this placement's directory of the runner's"
            " (agents/<placement id>/git)"
        )
    owned_layout(where)
    try:
        content = clonecheck.runner_record(root, dot_git, LEAD, 64)
    except FileNotFoundError:
        content = b""
    except (OSError, clonecheck.Refused):
        raise Refused(f"the runner's record {LEAD} is not readable") from None
    if content == b"":
        raise Refused(
            "this clone's repository grants no lead commands: the runner's operator sets "
            "lead = true (with pull_requests = true) in its repositories table"
        )
    # Exactly what the runner writes (`adapters.lead_record` through `state.write_file`, a text
    # file, so its line end is this system's: `\r\n` on Windows, lotse#ajwe's run of #2054).
    if content != LEAD_RECORD:
        raise Refused(f"the runner's record {LEAD} is not one it writes")


def owned_layout(where: Path) -> None:
    """Refused unless `…/agents/<placement>/git` is reached with no link anywhere on the way
    (its resolved path is the path as given) and `agents/`, `<placement>/` and `git/` are each
    a real directory of this user's that group and others cannot write (the security leg's P3
    on #2054, tightened by the lead). In every layout the runner makes all three as the
    agents' user, the uid this session runs as: under `single` and on an ssh host that user
    is the runner's own, under `agent_user` it is the agent user, in whose own `~/.maity-runner`
    they lie (`config.agent_files`, `supervisor` and `adapters.launch` through `as_user`); the
    runner keeps `agents/` 0700 (`AsUser.tighten`). A placed maity has nothing else that names
    where the runner keeps them; this narrows, but does not close, the case of an agent that
    controls its own environment (agy, opencode)."""
    if os.path.realpath(where) != str(where):
        raise Refused(f"{clonecheck.GIT_PRIVATE_ENV} is reached through a link ({where})")
    if os.name == "nt":  # the lead commands refuse on Windows later (no descriptor read)
        return
    for step in (where.parent.parent, where.parent, where):
        try:
            info = os.lstat(step)
        except OSError:
            raise Refused(f"the runner's directory {step} cannot be read") from None
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise Refused(f"the runner's directory {step} is not a directory of this user's")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise Refused(f"the runner's directory {step} is writable by group or others")


def strip_footer(text: str) -> tuple[str, int]:
    """`text` without the whole lines FOOTER names, and how many it dropped. Text inside a
    line is never rewritten; the remaining lines keep their order and line ends."""
    kept: list[str] = []
    dropped = 0
    for line in text.splitlines(keepends=True):
        if any(pattern.fullmatch(line.rstrip("\r\n")) for pattern in FOOTER):
            dropped += 1
        else:
            kept.append(line)
    return "".join(kept), dropped


def body_file(root: Path, given: str, opened: clonecheck.Opened | None = None) -> bytes:
    """The file's content, read through descriptors only (`inclone.read`): maity runs
    outside the sandbox, and any name it looked up twice could point elsewhere the second
    time. A regular file in the clone whose root and `.git` `clonecheck.opened_clone`
    checked (`opened`), outside that `.git`, or in the placement's scratch (783e476c), with
    no other hard link, of at most BODY_MAX bytes (cli/context/runner.md 9f43804d)."""
    scratch = inclone.recorded_scratch(root, opened.git if opened else None)
    try:  # a path out of the clone and its scratch says so everywhere, with both named
        inclone.located(root, given, "--body-file", scratch)
    except inclone.Refused as exc:
        raise Refused(str(exc)) from None
    if not WALKS:  # Windows
        raise Refused(
            f"--body-file {given}: this system cannot open a file without following links;"
            " give the text with --body"
        )
    try:
        return inclone.read(root, given, "--body-file", BODY_MAX, opened, scratch)
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
    args: argparse.Namespace,
    root: Path,
    repository: str,
    gh: str,
    opened: clonecheck.Opened | None = None,
) -> tuple[list[str], bytes | None, str | None]:
    """gh's argument list, built here option by option (`--name=value`, so no value is read
    as an option), with the recorded repository, what goes to its standard input, and for an
    edit the number of the pull request it changes (None otherwise). The head branch and the
    pull request to view are always named: gh reads nothing from git."""
    argv = [gh, args.gh_group, args.gh_command, f"--repo={repository}"]
    if args.gh_group == "run":
        return _run_command(args, argv), None, None
    if args.gh_command == "merge":
        if not NUMBER.fullmatch(args.selector):
            raise Refused(f"{args.selector!r}: a merge names the pull request by its number")
        if not SHA.fullmatch(args.head_commit):
            raise Refused(f"--match-head-commit {args.head_commit!r}: the head's full sha")
        if not args.subject.strip() or not args.subject.isprintable():
            raise Refused("--subject: one line of text")
        argv += ["--squash", f"--match-head-commit={args.head_commit}",
                 f"--subject={args.subject}", "--body-file=-", "--", args.selector]  # fmt: skip
        return argv, _lead_body(args, root, opened).encode("utf-8"), None
    if args.gh_command == "edit":
        return _edit_command(args, root, repository, gh, opened)
    if args.gh_command == "ready":
        return [*argv, "--", _selector(args, root)], None, None
    if args.gh_command == "create":
        argv.append(f"--title={args.title}")
        stdin = _body(args, root, opened)
        argv.append("--body-file=-")  # gh reads the body from maity, never a path
        head = args.head if args.head is not None else current_branch(root)
        for name, value in (("base", args.base), ("head", head)):
            if value is not None:
                if not SELECTOR.fullmatch(value):
                    raise Refused(f"--{name} {value!r}: not a branch name. Allowed: {ALLOWED}")
                argv.append(f"--{name}={value}")
        if args.draft:
            argv.append("--draft")
        return argv, stdin, None
    if args.json_fields is not None:
        if not JSON_FIELDS.fullmatch(args.json_fields):
            raise Refused(f"--json {args.json_fields!r}: field names and commas only")
        argv.append(f"--json={args.json_fields}")
        if args.comments:
            argv.append("--comments")
    else:  # never gh's text view (VIEW_FIELDS): the fields maity prints as text
        fields = [*VIEW_FIELDS, *(["comments"] if args.comments else [])]
        argv.append(f"--json={','.join(fields)}")
    argv += ["--", _selector(args, root)]
    return argv, None, None


def _edit_command(
    args: argparse.Namespace,
    root: Path,
    repository: str,
    gh: str,
    opened: clonecheck.Opened | None,
) -> tuple[list[str], bytes, str]:
    """`pr edit` as one REST call through gh (tsk-bmknv06ps0c6): `PATCH
    repos/<owner>/<name>/pulls/<number>` with a JSON object on stdin that holds the body and,
    when given, the title, and nothing else. Not `gh pr edit`: older gh versions ask the forge
    for `projectCards` (Projects classic) there, which the forge refuses, so the edit failed and
    set nothing. The host, owner and name come only from the pinned repository; a branch is
    turned into its pull request's number first (`pr_number`), and only the number is used;
    it is returned with the call, for the line `run` prints."""
    fields: dict[str, str] = {}
    if args.title is not None:
        if not args.title.strip() or not args.title.isprintable():
            raise Refused("--title: one line of text")
        fields["title"] = args.title
    fields["body"] = _lead_body(args, root, opened)
    selector = _selector(args, root)
    number = selector if NUMBER.fullmatch(selector) else pr_number(gh, repository, selector)
    host, owner, name = repository.split("/")
    argv = [gh, "api", f"--hostname={host}", "--method=PATCH",
            f"repos/{owner}/{name}/pulls/{number}", "--input=-"]  # fmt: skip
    return argv, json.dumps(fields).encode("utf-8"), number


def _gh_json(gh: str, argv: list[str], cwd: str) -> Any:
    """gh's answer to `argv`, run in `cwd` with `gh_env`, as JSON; None when gh failed or
    answered no JSON."""
    done = subprocess.run(  # noqa: S603 - the recorded gh, arguments built by the caller
        argv, cwd=cwd, env=gh_env(os.environ, gh), check=False, capture_output=True
    )
    try:
        return json.loads(done.stdout) if done.returncode == 0 else None
    except ValueError:
        return None


def pr_number(gh: str, repository: str, branch: str) -> str:
    """The number of the pull request of this repository whose head is `branch`, read with
    `gh pr view --repo=<pinned> --json=number`, the read `view` already makes. Refused unless
    gh answers with a whole number a pull request can have."""
    argv = [gh, "pr", "view", f"--repo={repository}", "--json=number", "--", branch]
    with tempfile.TemporaryDirectory(prefix="maity-gh-") as empty:
        answer = _gh_json(gh, argv, empty)
    number = answer.get("number") if isinstance(answer, dict) else None
    if type(number) is not int or not NUMBER.fullmatch(str(number)):
        raise Refused(
            f"no pull request of this repository has the head {branch!r} (or gh could not say)"
        )
    return str(number)


def _edited(answer: bytes, number: str) -> str:
    """One line for a PATCH gh reported as done: the pull request's number and address,
    each inline-cleaned (`onboarding.inline`: a line break in a field shows as `\\n`), so the
    line stays one. gh prints the whole pull request; the lead needs only which one changed.
    An answer of another shape is never echoed (it could hold the body and the title): a
    fixed line says the edit was sent and may have taken effect (review A1841 of #2081)."""
    try:
        pr = json.loads(answer)
    except ValueError:
        pr = None
    # Success only for the pull request the PATCH named (review A1851 of #2081): an answer
    # naming another number, zero or a negative one gets the fixed line for the requested one.
    if not isinstance(pr, dict) or type(pr.get("number")) is not int or str(pr["number"]) != number:
        return (
            f"sent the edit of pull request #{number}; gh's answer was not the pull request, "
            "so it may have taken effect: read it with maity gh pr view\n"
        )
    url = pr.get("html_url")
    where = f" {onboarding.inline(url)}" if isinstance(url, str) else ""
    return f"edited pull request #{pr['number']}{where}\n"


def _selector(args: argparse.Namespace, root: Path) -> str:
    """The pull request a `view`, `edit` or `ready` names: a number or a branch of this
    repository (the current branch when left out), never a URL or another repository's."""
    selector = args.selector if args.selector is not None else current_branch(root)
    if not SELECTOR.fullmatch(selector):
        raise Refused(
            f"{selector!r}: a pull request of this repository by number or branch, "
            f"not a URL or another repository's. Allowed: {ALLOWED}"
        )
    return selector


def _body(args: argparse.Namespace, root: Path, opened: clonecheck.Opened | None) -> bytes:
    """`--body` or `--body-file` (read by maity, `body_file`), at most BODY_MAX bytes."""
    if args.body_file is not None:
        return body_file(root, args.body_file, opened)
    body: bytes = str(args.body).encode("utf-8")
    if len(body) > BODY_MAX:
        raise Refused(f"--body: over {BODY_MAX} bytes")
    return body


def _lead_body(args: argparse.Namespace, root: Path, opened: clonecheck.Opened | None) -> str:
    """A merge's or an edit's body (`_body`) as text, without its footer lines
    (`strip_footer`); how many went is said on stderr, so the lead sees it."""
    try:
        text = _body(args, root, opened).decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("the body is not UTF-8 text") from None
    kept, dropped = strip_footer(text)
    if dropped:
        sys.stderr.write(f"maity: left out {dropped} footer line(s) of the body\n")
    return kept


def _run_command(args: argparse.Namespace, argv: list[str]) -> list[str]:
    """`run list --commit <sha>` and `run view <id> [--job <id>] [--log-failed]`, read only."""
    if args.gh_command == "list":
        if not SHA.fullmatch(args.commit):
            raise Refused(f"--commit {args.commit!r}: the commit's full sha")
        return [*argv, f"--commit={args.commit}", f"--json={','.join(RUN_FIELDS)}",
                "--limit=50"]  # fmt: skip
    if not RUN_ID.fullmatch(args.selector):
        raise Refused(f"{args.selector!r}: a run of this repository by its id (digits)")
    if args.job is not None:
        if not RUN_ID.fullmatch(args.job):
            raise Refused(f"--job {args.job!r}: a job by its id (digits)")
        argv.append(f"--job={args.job}")
    if args.log_failed:
        argv.append("--log-failed")
    else:
        argv.append(f"--json={','.join(RUN_VIEW_FIELDS)}")
    return [*argv, "--", args.selector]


def as_text(args: argparse.Namespace) -> bool:
    """Whether maity prints gh's answer as text: a `pr view` without `--json`."""
    return bool(args.gh_group == "pr" and args.gh_command == "view" and args.json_fields is None)


def as_log(args: argparse.Namespace) -> bool:
    """Whether gh's answer is a job log that maity cleans and cuts (`_tail`)."""
    return bool(args.gh_group == "run" and args.gh_command == "view" and args.log_failed)


def _tail(answer: bytes) -> str:
    """A `run view --log-failed` answer cut to its last LOG_TAIL lines, with a line that says
    so, and only those cleaned (`onboarding`: the log is the repository's code's output), so a
    log of megabytes is not scanned whole (review A1719 of #2054)."""
    lines = answer.decode("utf-8", "replace").replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    cut = len(lines) > LOG_TAIL
    head = f"maity: cut to the last {LOG_TAIL} of {len(lines)} lines\n" if cut else ""
    return head + "".join(onboarding.clean(line) + "\n" for line in lines[-LOG_TAIL:])


# Reads the caller's role base from the hub for the clone at a root, its `.git` as checked.
RoleOf = Callable[[Path, "clonecheck.Opened | None"], "str | None"]


def check_role(role_of: RoleOf | None, root: Path, opened: clonecheck.Opened | None = None) -> None:
    """Refused unless the hub names this member's role, by its base, `manager` now: a project
    role built on manager counts, one built on any other role does not (context/trust.md: a
    project role grants no more than its base). `role_of` reads the base with the session's
    credential at each call, that session read through `opened`, the clone's checked `.git`;
    None, or a read that fails, refuses (fail closed)."""
    if role_of is None:
        raise Refused("the lead commands need this member's role from the hub")
    role = role_of(root, opened)
    if role != LEAD_ROLE:
        raise Refused(
            f"the lead commands are for a member whose role is {LEAD_ROLE} or built on it; "
            f"the hub names this one's base {role or 'no role'}"
        )


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


def run(args: argparse.Namespace, role_of: RoleOf | None = None) -> int:
    """The call, under the runner's placement only (`clonecheck.placement_root`): gh's exit
    code. gh runs in an empty directory of its own, never in the clone, whose .git the
    session can shape: the repository, the branch and the body all come from maity. A lead
    command also needs the LEAD record and the role `manager` from the hub (`role_of`), both
    checked before its body is read or gh starts."""
    try:
        root = clonecheck.placement_root()
    except clonecheck.Refused as exc:
        raise Refused(str(exc)) from None
    if root is None:
        raise Refused("maity gh runs only in a session a runner placed; " + ALLOWED)
    try:
        with clonecheck.opened_clone(root) as opened:
            dot_git = None if opened is None else opened.git
            repository, gh = granted(root, dot_git)
            if is_lead(args):
                lead_granted(root, dot_git)
                check_role(role_of, root, opened)
            argv, stdin, edited = command(args, root, repository, gh, opened)
    except clonecheck.Refused as exc:
        raise Refused(str(exc)) from None
    text, log = as_text(args), as_log(args)
    with tempfile.TemporaryDirectory(prefix="maity-gh-") as empty:
        if args.gh_group == "pr" and args.gh_command == "merge":
            direct_merge_only(gh, repository, args.selector, args.head_commit, empty)
        done = subprocess.run(  # noqa: S603 - the recorded gh, arguments built above
            argv,
            input=stdin,
            cwd=empty,
            env=gh_env(os.environ, gh),
            check=False,
            capture_output=True,
        )
    # Every answer of gh is printed cleaned (review A1721 of #2054): a confirmation can echo a
    # title or a branch someone else wrote, on either stream.
    if edited is not None and done.returncode == 0:  # one line, also when gh printed nothing
        sys.stdout.write(_edited(done.stdout, edited))
        sys.stdout.flush()
    elif done.stdout:
        out = _readable(done.stdout) if text else _tail(done.stdout) if log else _clean(done.stdout)
        sys.stdout.write(out)
        sys.stdout.flush()
    if done.stderr:
        sys.stderr.write(_clean(done.stderr))
        sys.stderr.flush()
    return done.returncode


# What the merge reads first (the lead's ruling on review A1804 of #2054): GitHub's own
# merge-queue state for the pull request, through one fixed GraphQL query. It answers for a
# queue whatever configured it, a ruleset or a classic branch protection rule, and for every
# reader; the owner, the name and the number go as variables, never into the query's text.
MERGE_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) {"
    " repository(owner: $owner, name: $name) {"
    " pullRequest(number: $number) {"
    " baseRefName headRefOid isMergeQueueEnabled isInMergeQueue } } }"
)
QUEUE_FIELDS = ("isMergeQueueEnabled", "isInMergeQueue")


def direct_merge_only(gh: str, repository: str, number: str, head: str, cwd: str) -> None:
    """Refused unless the pull request merges directly, as a squash of `head` (review A1804
    of #2054). On a base branch with a merge queue `gh pr merge` hands the method and the
    moment to the queue, so `--squash` and `--match-head-commit` would be flags, not the
    outcome. So maity asks GitHub first (`gh api graphql`, MERGE_QUERY, the pinned host,
    owner and name, the checked number as an integer) and goes on only when both
    `isMergeQueueEnabled` and `isInMergeQueue` are literally false and `headRefOid` is
    `head`. A failed read, no JSON, an `errors` member, a missing pull request or a field
    that is missing or of another type refuses (fail closed)."""
    host, owner, name = repository.split("/")
    argv = [gh, "api", "graphql", f"--hostname={host}", "-f", f"query={MERGE_QUERY}",
            "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={number}"]  # fmt: skip
    answer = _gh_json(gh, argv, cwd)
    pr: Any = None
    if isinstance(answer, dict) and "errors" not in answer:
        data = answer.get("data")
        repo = data.get("repository") if isinstance(data, dict) else None
        pr = repo.get("pullRequest") if isinstance(repo, dict) else None
    if not isinstance(pr, dict) or any(pr.get(f) is not False for f in QUEUE_FIELDS):
        raise Refused(
            f"pull request {number} does not merge directly (a merge queue, or GitHub could "
            "not say): maity gh merges only by a direct squash of the head named"
        )
    if pr.get("headRefOid") != head:
        raise Refused(
            f"pull request {number}'s head is not {head} (it moved, or GitHub could not say): "
            "read it again before merging"
        )


def _clean(answer: bytes) -> str:
    """gh's output as text with every character a terminal acts on shown as an escape
    (`onboarding.clean`); line feeds and tabs stay."""
    return onboarding.clean(answer.decode("utf-8", "replace"))
