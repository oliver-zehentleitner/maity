"""Command line entry point: `maity <command>`. The calls behind each command: docs/api.md §13."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from maity import __version__, gitfacts, hub, pointer, proc, sign, state

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 3
EXIT_REFUSED = 4
EXIT_SUPERSEDED = 6
EXIT_INTERRUPTED = 130

REQUEST_CLASSES = ("decision", "consent", "contract", "info")
PRIORITIES = ("low", "normal", "high", "urgent")
MAX_OPTIONS = 8
MAX_TITLE = 200
LONG_POLL = 55
DEFAULT_WAIT = 600

OUTPUT_DISCIPLINE = """\
output discipline:
  maity prints status and facts, never a credential. The session credential is
  written straight to a file and read only by the code that signs a request; no
  command prints it, and no command prints anything else from that file. A
  request whose body contains a string in the credential format is refused
  before it is sent.

state:
  <git common dir>/maity/credential   the session credential, mode 0600
  <git common dir>/maity/state.json   hub URL, project, identity, cursor, mode 0600
  One state per clone, shared by its worktrees. MAITY_STATE_DIR overrides it.

exit codes:
  0 success, 1 error, 2 usage, 3 wait timed out, 4 report refused,
  6 wait superseded by another wait of this credential (do not start a second one),
  130 interrupted (Ctrl-C)

plain HTTP:
  refused except to a hub on loopback; there is no flag to allow it
"""

Handler = Callable[[argparse.Namespace], int]


class UsageError(Exception):
    """Arguments argparse accepts but the command cannot use."""


class CommandError(Exception):
    """The hub answered, but not with what the command can act on."""


def _err(message: str) -> None:
    print(f"maity: {message}", file=sys.stderr)


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


class Session:
    """A joined clone: its state directory, its state, and a signing client for its hub."""

    def __init__(self, hub_url: str | None = None) -> None:
        self.dir = state.resolve_state_dir()
        if not state.has_credential(self.dir):
            raise state.StateError(
                "this clone has not joined a project; run `maity join <url> --code <code>`"
            )
        self.data = state.load_state(self.dir)
        if hub_url:  # a credential from the page-driven join has no state.json yet
            self.data["hub"] = hub.hub_base(hub_url)
        stored = self.data.get("hub")
        if not isinstance(stored, str):
            raise state.StateError(
                "this clone holds a credential but no hub URL; run `maity resume --hub <url>`"
            )
        key = sign.signing_key(state.read_credential(self.dir))
        self.client = hub.Client(hub.hub_base(stored), key)

    @property
    def project(self) -> str:
        project = self.data.get("project")
        if not isinstance(project, str):
            raise state.StateError("the project is not known yet; run `maity resume`")
        return project

    def project_path(self, *parts: str) -> str:
        return "/".join(["", "projects", hub.segment(self.project), *map(hub.segment, parts)])

    def save(self) -> None:
        state.save_state(self.dir, self.data)


def _resume(session: Session, args: argparse.Namespace) -> int:
    for key in ("harness", "harness_version", "model"):
        value = getattr(args, key, None)
        if value:
            session.data[key] = value
    if "harness" not in session.data and os.environ.get("CLAUDECODE") == "1":
        session.data["harness"] = "Claude Code"
    body: dict[str, Any] = {"client": hub.CLIENT}
    for key in ("harness", "harness_version", "model", "cursor"):
        if session.data.get(key) is not None:
            body[key] = session.data[key]
    packet = session.client.call("POST", "/me/resume", body=body)
    if not isinstance(packet, dict):
        raise hub.HubError("the resume packet is not a JSON object")
    session.data["session_id"] = (packet.get("session") or {}).get("id")
    slug = (packet.get("project") or {}).get("slug")
    member_id = (packet.get("me") or {}).get("member_id")
    if isinstance(slug, str):
        session.data["project"] = slug
    if isinstance(member_id, str):
        session.data["member_id"] = member_id
    cursor = (packet.get("events") or {}).get("cursor")
    if isinstance(cursor, int):
        session.data["cursor"] = cursor
    wait_timeout = (packet.get("hints") or {}).get("wait_timeout")
    if isinstance(wait_timeout, int) and wait_timeout > 0:
        session.data["wait_timeout"] = wait_timeout
    session.save()
    _print_json(packet)
    return EXIT_OK


def cmd_join(args: argparse.Namespace) -> int:
    base = hub.hub_base(args.url)
    token = hub.join_token(args.url)
    if not args.code.strip():
        raise UsageError("the join code is empty")
    directory = state.resolve_state_dir()
    if state.has_credential(directory):
        _err(
            f"this clone already holds a session credential ({state.credential_path(directory)}); "
            "run `maity resume`, or revoke the session in the dashboard and delete that file "
            "before joining again"
        )
        return EXIT_ERROR
    result = hub.exchange(base, token, args.code.strip())
    path = state.write_credential(directory, result.credential)
    state.save_state(
        directory,
        {
            "hub": hub.hub_base(result.hub) if result.hub else base,
            "project": result.project,
            "member_id": result.member_id,
            "credential_id": result.credential_id,
        },
    )
    print(
        f"joined {result.project} as {result.member_id}; credential {result.credential_id} "
        f"stored in {path} (mode 0600, not printed)",
        file=sys.stderr,
    )
    if not args.no_pointer:
        root = pointer.repo_root(Path.cwd())
        if root is not None:
            for changed in pointer.write(root):
                print(f"wrote the Maity pointer block into {changed}", file=sys.stderr)
    try:
        return _resume(Session(), args)
    except hub.HubError as exc:
        _err(f"joined, but the first resume failed: {exc}; run `maity resume`")
        return EXIT_ERROR


def cmd_resume(args: argparse.Namespace) -> int:
    return _resume(Session(args.hub), args)


def cmd_wait(args: argparse.Namespace) -> int:
    session = Session()
    timeout = args.timeout or session.data.get("wait_timeout") or DEFAULT_WAIT
    if not isinstance(timeout, int) or timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    deadline = time.monotonic() + timeout
    cursor = session.data.get("cursor") or 0
    path = session.project_path("events")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return EXIT_TIMEOUT
        # The hub holds for `poll` and gets a second to answer; the read never outlasts the
        # deadline, so a hub that stops answering cannot keep `wait` running past --timeout.
        poll = max(1, min(LONG_POLL, int(remaining) - 1))
        read_timeout = max(0.5, min(poll + 15, remaining))
        started = time.monotonic()
        try:
            page = session.client.call(
                "GET",
                path,
                query=[("after", str(cursor)), ("wait", str(poll))],
                timeout=read_timeout,
            )
        except hub.HubError as exc:
            if exc.status is None and exc.code is None:  # dropped connection: same `after` again
                time.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
                continue
            raise
        if page.get("superseded"):
            _err("another `maity wait` of this credential took over; this one stops")
            return EXIT_SUPERSEDED
        items = page.get("items") or []
        if items:
            event = items[0]
            session.data["cursor"] = event.get("seq", cursor)
            session.save()
            _print_json(event)
            return EXIT_OK
        new_cursor = page.get("cursor")
        if isinstance(new_cursor, int) and new_cursor != cursor:
            cursor = new_cursor
            session.data["cursor"] = cursor
            session.save()
        if time.monotonic() - started < 1:  # an empty answer that did not hold: do not spin
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def _report_body(facts: gitfacts.Facts, summary: str, done: bool) -> dict[str, Any]:
    pr = None
    if facts.pr is not None:
        pr = {
            "number": facts.pr.number,
            "url": facts.pr.url,
            "head": facts.pr.head,
            "state": facts.pr.state.lower(),
        }
    if pr is not None:
        pr_status, reason = "found", None
    elif facts.pr_unknown_reason is not None:
        pr_status, reason = "unknown", facts.pr_unknown_reason
    else:
        pr_status, reason = "none", None
    return {
        "summary": summary,
        "head": facts.head,
        "branch": facts.branch,
        "upstream": f"{facts.remote}/{facts.remote_branch}",
        "remote_head": facts.remote_head,
        "pr": pr,
        "pr_status": pr_status,
        "pr_unknown_reason": reason,
        "done": done,
    }


def cmd_report(args: argparse.Namespace) -> int:
    if not args.summary.strip():
        raise UsageError("the summary is empty")
    session = Session()  # the cheap check first: ls-remote and gh only for a joined clone
    facts = gitfacts.collect(Path.cwd())
    problems = gitfacts.mismatches(facts)
    if problems:
        _err("report refused, the code does not match what would be reported:")
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_REFUSED
    body = _report_body(facts, args.summary.strip(), args.done)
    path = session.project_path("tasks", args.task, "report")
    task = session.client.call("POST", path, body=body)
    pr = body["pr"]
    pr_line = f"PR #{pr['number']}" if pr else f"PR {body['pr_status']}"
    status = task.get("status") if isinstance(task, dict) else None
    return _done(
        args, task, f"reported {args.task} at {facts.head[:12]} ({pr_line}); task is now {status}"
    )


def _ask_body(args: argparse.Namespace) -> dict[str, Any]:
    lines = args.question.strip().splitlines()
    if not lines:
        raise UsageError("the question is empty")
    title, summary = lines[0].strip(), "\n".join(lines[1:]).strip()
    if len(title) > MAX_TITLE:
        raise UsageError(f"the first line is the title and may be {MAX_TITLE} characters at most")
    if len(args.option) > MAX_OPTIONS:
        raise UsageError(f"at most {MAX_OPTIONS} --option values")
    if args.request_class in ("decision", "consent") and len(args.option) == 1:
        raise UsageError("give at least two --option values, or none for a free-text answer")
    body: dict[str, Any] = {"class": args.request_class, "title": title}
    if summary:
        body["summary"] = summary
    if args.tried:
        body["tried"] = args.tried
    if args.option:
        body["options"] = [{"id": f"o{i}", "label": o} for i, o in enumerate(args.option, 1)]
    if args.to != "human":
        body["to"] = args.to
    body["priority"] = args.priority
    if args.task:
        body["task_id"] = args.task
    return body


def cmd_ask(args: argparse.Namespace) -> int:
    body = _ask_body(args)
    session = Session()
    request = session.client.call("POST", session.project_path("requests"), body=body)
    rid, rclass, rstatus = (_field(request, k) for k in ("id", "class", "status"))
    return _done(args, request, f"asked {rid} ({rclass}, {rstatus})")


def _done(args: argparse.Namespace, result: Any, line: str) -> int:
    """Print the hub's answer with --json, otherwise one status line."""
    if getattr(args, "json", False):
        _print_json(result)
    else:
        print(line)
    return EXIT_OK


def _field(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _text(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        raise UsageError(f"{what} is empty")
    return value


def cmd_claim(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {}
    if args.reason:
        body["reason"] = _text(args.reason, "--reason")
    session = Session()
    task = session.client.call("POST", session.project_path("tasks", args.card, "claim"), body=body)
    lease = _field(task, "claim", "lease_until")
    return _done(args, task, f"claimed {args.card}; lease until {lease}")


def cmd_unclaim(args: argparse.Namespace) -> int:
    session = Session()
    task = session.client.call("POST", session.project_path("tasks", args.card, "release"), body={})
    return _done(args, task, f"gave {args.card} back; it is {_field(task, 'status')} again")


def cmd_checkpoint(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {
        "last_step": _text(args.message, "-m"),
        "next_step": _text(args.next, "--next"),
    }
    session = Session()
    where = gitfacts.position(Path.cwd())
    if where is None:
        _err("no commit in this clone; the checkpoint goes without branch and head")
        refs = "without refs"
    else:
        head, branch = where
        body["head"] = head
        if branch is not None:
            body["branch"] = branch
        refs = f"at {head[:12]} on {branch or 'a detached HEAD'}"
    path = session.project_path("tasks", args.card, "checkpoint")
    task = session.client.call("POST", path, body=body)
    return _done(args, task, f"checkpoint on {args.card} {refs}")


SAY_TYPES = ("interface_change", "blocker", "go_request", "review_result", "handover", "notice")


def cmd_say(args: argparse.Namespace) -> int:
    text = _text(args.body, "the message")
    if args.to == "human":
        if args.type or args.task:
            raise UsageError("a chat with your human takes neither --type nor --task")
        session = Session()
        member_id = session.data.get("member_id")
        if not isinstance(member_id, str):
            raise state.StateError("this agent's member id is not known yet; run `maity resume`")
        path = session.project_path("conversations", member_id, "messages")
        message = session.client.call("POST", path, body={"body": text})
        return _done(args, message, f"said to your human (seq {_field(message, 'seq')})")
    if args.type is None:
        raise UsageError(f"--type is required when writing to {args.to}: {', '.join(SAY_TYPES)}")
    body: dict[str, Any] = {"kind": "message", "type": args.type, "to": args.to, "body": text}
    if args.task:
        body["task_id"] = args.task
    session = Session()
    event = session.client.call("POST", session.project_path("events"), body=body)
    return _done(args, event, f"sent {args.type} to {args.to} (seq {_field(event, 'seq')})")


def cmd_answer(args: argparse.Namespace) -> int:
    if args.reply is None and args.text is None:
        raise UsageError("give --reply, --text, or both")
    body: dict[str, Any] = {}
    if args.reply is not None:
        body["reply_id"] = _text(args.reply, "--reply")
    if args.text is not None:
        body["text"] = _text(args.text, "--text")
    session = Session()
    path = session.project_path("requests", args.request, "answer")
    request = session.client.call("POST", path, body=body)
    return _done(args, request, f"answered {args.request}; it is {_field(request, 'status')}")


CLOSED = ("done", "cancelled")


def _releases(session: Session) -> list[dict[str, Any]]:
    """Every release card of the project, following the pages."""
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = [("kind", "release"), ("status", "all"), ("limit", "200")]
        if cursor:
            query.append(("cursor", cursor))
        page = session.client.call("GET", session.project_path("tasks"), query=query)
        items.extend(i for i in _field(page, "items") or [] if isinstance(i, dict))
        cursor = _field(page, "next_cursor")
        if not cursor:
            return items


def _release_card(session: Session, card: str | None) -> dict[str, Any]:
    if card:
        task = session.client.call("GET", session.project_path("tasks", card))
        if _field(task, "kind") != "release":
            raise CommandError(f"{card} is not a release card")
        return dict(task)
    current = [r for r in _releases(session) if r.get("status") not in CLOSED]
    if not current:
        raise CommandError("no release is in flight; name one, see `maity release list`")
    return current[0]


def _release_summary(card: dict[str, Any]) -> list[str]:
    release = card.get("release") or {}
    readiness = release.get("readiness") or {}
    lines = [
        f"{card.get('id')}  {release.get('version')}  {card.get('status')}  "
        f"ready: {'yes' if readiness.get('ready') else 'no'}"
    ]
    for block in readiness.get("blocking") or []:
        detail = {k: v for k, v in block.items() if k != "reason"}
        extra = " ".join(f"{k}={v}" for k, v in detail.items())
        lines.append(f"  blocking: {block.get('reason')} {extra}".rstrip())
    for item in release.get("checklist") or []:
        mark = "x" if item.get("done") else " "
        lines.append(f"  [{mark}] {item.get('id')}  {item.get('text')}")
    return lines


def cmd_release_list(args: argparse.Namespace) -> int:
    releases = _releases(Session())
    if args.json:
        _print_json(releases)
        return EXIT_OK
    if not releases:
        print("no releases")
    for card in releases:
        print(_release_summary(card)[0])
    return EXIT_OK


def cmd_release_show(args: argparse.Namespace) -> int:
    card = _release_card(Session(), args.card)
    return _done(args, card, "\n".join(_release_summary(card)))


def cmd_release_tick(args: argparse.Namespace) -> int:
    session = Session()
    card = args.release or _release_card(session, None).get("id")
    if not isinstance(card, str):
        raise CommandError("the release card has no id")
    path = session.project_path("tasks", card, "checklist", args.item)
    task = session.client.call("POST", path, body={"done": not args.undo})
    action = "unticked" if args.undo else "ticked"
    return _done(args, task, f"{action} {args.item} on {card}")


def cmd_api(args: argparse.Namespace) -> int:
    body: Any = None
    if args.json is not None:
        raw = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise UsageError(f"--json is not valid JSON: {exc.msg}") from exc
    query: list[tuple[str, str]] = []
    for pair in args.query:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise UsageError(f"--query expects key=value, got {pair!r}")
        query.append((key, value))
    session = Session()
    result = session.client.call(args.method, args.path, query=query, body=body)
    if result is not None:
        _print_json(result)
    return EXIT_OK


def cmd_help(args: argparse.Namespace) -> int:
    if args.hub:
        base = hub.hub_base(args.hub)
    else:
        stored = state.load_state(state.resolve_state_dir()).get("hub")
        if not isinstance(stored, str):
            raise state.StateError("not joined in this clone; pass --hub <url>")
        base = hub.hub_base(stored)
    print(hub.get_text(f"{base}{hub.API}/help"), end="")
    return EXIT_OK


def _session_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--harness", help="the agent harness, e.g. 'Claude Code'; remembered")
    p.add_argument("--harness-version", dest="harness_version", help="its version; remembered")
    p.add_argument("--model", help="the model id this session runs on; remembered")


def _json_flag(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print the hub's answer as JSON")


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="maity",
        description="Agent-side command for Maity: join a project, resume, wait for events, "
        "claim, checkpoint and report work, ask and answer, message, follow the release. Every "
        "request is signed.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    parser.add_argument("--version", action="version", version=f"maity {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    def add(name: str, summary: str, description: str) -> argparse.ArgumentParser:
        return sub.add_parser(
            name,
            help=summary,
            description=description,
            epilog=OUTPUT_DISCIPLINE,
            formatter_class=fmt,
        )

    p = add(
        "join",
        "pair this clone with a project, using the line a human pasted",
        "Exchange the single-use join code for a session credential, store it in this clone's "
        "state directory without printing it, write the Maity pointer block into AGENTS.md, then "
        "resume and print the resume packet. A clone that already holds a credential is refused.",
    )
    p.add_argument("url", help="the join URL from the pasted line")
    p.add_argument("--code", required=True, help="the single-use join code from the pasted line")
    p.add_argument("--no-pointer", action="store_true", help="do not touch AGENTS.md or CLAUDE.md")
    _session_args(p)
    p.set_defaults(handler=cmd_join)

    p = add(
        "resume",
        "who am I, what is open, what did I miss",
        "Open a session and print the resume packet as JSON: identity, role, project state and "
        "rules, claims with checkpoints, open and answered requests, the events since the last "
        "cursor, peers. Run it at the start of every session and after a context compaction.",
    )
    p.add_argument(
        "--hub", help="the hub URL, once, when the credential came from the page-driven join"
    )
    _session_args(p)
    p.set_defaults(handler=cmd_resume)

    p = add(
        "wait",
        "block until the next event for this agent arrives, or time out",
        "Long-poll the project's events. Prints the first event addressed to this agent as JSON "
        f"and exits {EXIT_OK}; exits {EXIT_TIMEOUT} when nothing arrived within the timeout, "
        f"{EXIT_SUPERSEDED} when another wait of this credential took over. Meant to run as a "
        "background command on harnesses that wake the agent when one exits. Never run two.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        metavar="N",
        help=(
            "seconds to wait, never exceeded even when the hub stops answering "
            "(default: the resume packet's hint for this harness, else 600)"
        ),
    )
    p.set_defaults(handler=cmd_wait)

    p = add(
        "report",
        "report finished work with facts read from git and gh",
        "Send a completion report. The head commit comes from git, the remote head from "
        "`git ls-remote`, the pull request from `gh` when it is installed; nothing is typed by "
        f"hand. Refused with exit {EXIT_REFUSED}, before anything is sent, while uncommitted "
        "changes exist, the branch is not pushed, or the pull request's head differs.",
    )
    p.add_argument("--task", required=True, help="the task id the report is for")
    p.add_argument("--summary", required=True, help="one or two sentences on what was done")
    p.add_argument(
        "--done", action="store_true", help="close the task, when your role holds done authority"
    )
    _json_flag(p)
    p.set_defaults(handler=cmd_report)

    p = add(
        "ask",
        "put a request into a human's or a role's inbox",
        "Ask for a decision, a consent, a contract change or information. The question's first "
        "line is the title, the rest the summary. With --option values the answer is one click; "
        "without, it is free text.",
    )
    p.add_argument("question", help="first line: the title; further lines: the context")
    p.add_argument(
        "--to",
        required=True,
        help="'human' (the human who owns this agent), 'owner', 'role:<role>', or a member id",
    )
    p.add_argument(
        "--class",
        dest="request_class",
        required=True,
        choices=REQUEST_CLASSES,
        help="decision: pick one; consent: may I; contract: change an interface; info: tell me",
    )
    p.add_argument(
        "--option", action="append", default=[], help="a prepared answer; repeat, at most 8"
    )
    p.add_argument("--tried", help="what you tried before asking")
    p.add_argument("--priority", choices=PRIORITIES, default="normal", help="default: normal")
    p.add_argument("--task", help="the task id the request belongs to")
    _json_flag(p)
    p.set_defaults(handler=cmd_ask)

    p = add(
        "claim",
        "take a card: it stays yours until it is closed or you give it back",
        "Claim an open card (POST …/tasks/{card}/claim). The lease is renewed by every call this "
        "agent makes; nothing is released automatically. In a project under freeze or "
        "fixes-only, --reason is required.",
    )
    p.add_argument("card", help="the card id, e.g. tsk-0004")
    p.add_argument("--reason", help="why, when the project is in freeze or fixes-only")
    _json_flag(p)
    p.set_defaults(handler=cmd_claim)

    p = add(
        "unclaim",
        "give a claimed card back, unfinished",
        "Give a card back (POST …/tasks/{card}/release): it is open again and claimable. Use "
        "`report` for finished work instead.",
    )
    p.add_argument("card", help="the card id")
    _json_flag(p)
    p.set_defaults(handler=cmd_unclaim)

    p = add(
        "checkpoint",
        "record where the work on a card stands, for the next session",
        "Record the last and the next step on a card you hold. The branch and the head commit "
        "come from git, not from you. The next session reads it from the resume packet.",
    )
    p.add_argument("card", help="the card id")
    p.add_argument("-m", "--last", dest="message", required=True, help="the step just finished")
    p.add_argument("--next", required=True, help="the step to take next")
    _json_flag(p)
    p.set_defaults(handler=cmd_checkpoint)

    p = add(
        "say",
        "send a typed message to members, or chat with your human",
        "Post a message (POST …/events). TO is 'all', 'role:<role>' or a member id, and --type "
        "says what it is. TO 'human' writes into the chat with the human who owns this agent "
        "(POST …/conversations/{you}/messages) and takes no --type. Status is not a message: the "
        "board shows it.",
    )
    p.add_argument("to", help="'all', 'role:<role>', a member id, or 'human'")
    p.add_argument("body", help="the message, Markdown")
    p.add_argument("--type", choices=SAY_TYPES, help="required unless TO is 'human'")
    p.add_argument("--task", help="the card the message is about")
    _json_flag(p)
    p.set_defaults(handler=cmd_say)

    p = add(
        "answer",
        "answer a request addressed to you",
        "Answer a request (POST …/requests/{id}/answer) with one of its replies, free text, or "
        "both. Agents answer decision, contract and info requests addressed to them, and any "
        "request when their role holds requests:answer; never their own.",
    )
    p.add_argument("request", help="the request id, e.g. req-0012")
    p.add_argument("--reply", help="the id of one of the request's replies")
    p.add_argument("--text", help="a free-text answer, alone or with --reply")
    _json_flag(p)
    p.set_defaults(handler=cmd_answer)

    p = add(
        "release",
        "list releases, show one, tick its checklist",
        "Read the project's releases and tick checklist items (§6.7). Readiness is computed by "
        "the hub from observed state only; nothing here tags, merges or pushes.",
    )
    rsub = p.add_subparsers(dest="release_command", metavar="<action>", required=True)
    r = rsub.add_parser("list", help="every release of the project", formatter_class=fmt)
    _json_flag(r)
    r.set_defaults(handler=cmd_release_list)
    r = rsub.add_parser(
        "show", help="one release: readiness, what blocks it, the checklist", formatter_class=fmt
    )
    r.add_argument("card", nargs="?", help="the release card id (default: the one in flight)")
    _json_flag(r)
    r.set_defaults(handler=cmd_release_show)
    r = rsub.add_parser("tick", help="tick a checklist item", formatter_class=fmt)
    r.add_argument("item", help="the checklist item id, e.g. chk-2")
    r.add_argument("--release", help="the release card id (default: the one in flight)")
    r.add_argument("--undo", action="store_true", help="untick it instead")
    _json_flag(r)
    r.set_defaults(handler=cmd_release_tick)

    p = add(
        "api",
        "any other endpoint, signed: maity api METHOD PATH",
        "Send one signed request to /api/v1 and print the JSON answer, for the endpoints that "
        "have no command of their own: creating and editing cards, assign, withdraw, pausing "
        "(PATCH /me), the conversation history. PATH is relative to /api/v1, e.g. "
        "/projects/maity/tasks/tsk-0004. See `maity help`.",
    )
    p.add_argument("method", type=str.upper, choices=("GET", "POST", "PATCH", "DELETE"))
    p.add_argument("path", help="the endpoint path, starting with /")
    p.add_argument("--json", metavar="FILE", help="request body from a JSON file, or - for stdin")
    p.add_argument(
        "--query", action="append", default=[], metavar="KEY=VALUE", help="query parameter; repeat"
    )
    p.set_defaults(handler=cmd_api)

    p = sub.add_parser(
        "help",
        help="print the hub's own documentation (GET /api/v1/help)",
        description="Fetch and print /api/v1/help from the hub this clone joined, or from --hub.",
        formatter_class=fmt,
    )
    p.add_argument("--hub", help="hub URL, for use before joining")
    p.set_defaults(handler=cmd_help)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler: Handler = args.handler
    try:
        return handler(args)
    except (
        state.StateError,
        gitfacts.FactsError,
        hub.HubError,
        sign.CredentialFormatError,
        proc.ToolError,
        CommandError,
        OSError,
    ) as exc:
        _err(str(exc))
        return EXIT_ERROR
    except UsageError as exc:
        _err(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
