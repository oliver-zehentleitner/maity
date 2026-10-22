"""Command line entry point: `maity <command>`. The calls behind each command: docs/api.md §13."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maity import __version__, environment, gitfacts, hub, onboarding, pointer, proc, sign, state
from maity.runner import commands as runner_commands
from maity.runner import config

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


def _resume(session: Session, args: argparse.Namespace, first: bool = False) -> int:
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
    declared = environment.ids(session.client.base, session.dir)
    if declared is not None:
        body["environment"] = declared
    try:
        packet = session.client.call("POST", "/me/resume", body=body)
    except hub.HubError as exc:
        # A hub from before §5.3 refuses the field: resume without it, saying so.
        fields = exc.details.get("fields") if isinstance(exc.details, dict) else None
        if "environment" not in body or exc.code != "invalid" or not isinstance(fields, dict) \
                or not any(str(k).startswith("environment") for k in fields):  # fmt: skip
            raise
        _err("this hub does not take the session's environment yet; resuming without it")
        del body["environment"]
        packet = session.client.call("POST", "/me/resume", body=body)
    if not isinstance(packet, dict):
        raise hub.HubError("the resume packet is not a JSON object")
    # Rendered before the cursor is saved: a packet the text cannot show never acknowledges
    # the events in it.
    text = None if args.json else onboarding.render(packet, first=first)
    field = onboarding.get
    session_id = field(packet, "session", "id")
    if isinstance(session_id, str):
        session.data["session_id"] = session_id
    slug = field(packet, "project", "slug")
    member_id = field(packet, "me", "member_id")
    if isinstance(slug, str):
        session.data["project"] = slug
    if isinstance(member_id, str):
        session.data["member_id"] = member_id
    owner_id = field(packet, "me", "owner", "id")
    if isinstance(owner_id, str):
        session.data["owner_id"] = owner_id
    cursor = field(packet, "events", "cursor")
    if isinstance(cursor, int):
        session.data["cursor"] = cursor
    wait_timeout = field(packet, "hints", "wait_timeout")
    if isinstance(wait_timeout, int) and wait_timeout > 0:
        session.data["wait_timeout"] = wait_timeout
    session.save()
    if text is None:
        _print_json(packet)
    else:
        print(text, end="")
    return EXIT_OK


def _join_line(args: argparse.Namespace) -> tuple[str, str]:
    """URL and code from the arguments, or as two lines from --join-file (`-`: stdin), so
    that neither has to be on a command line where `ps` shows it (§15.9)."""
    if args.join_file is not None:
        if args.url is not None or args.code is not None:
            raise UsageError("give the URL and the code either as arguments or in --join-file")
        text = sys.stdin.read() if args.join_file == "-" else Path(args.join_file).read_text()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 2:
            raise UsageError("--join-file holds two lines: the join URL, then the code")
        return lines[0], lines[1]
    if args.url is None or args.code is None:
        raise UsageError("give the join URL and --code, or --join-file")
    return args.url, args.code


def cmd_join(args: argparse.Namespace) -> int:
    url, code = _join_line(args)
    target = hub.join_target(url)
    if not code.strip():
        raise UsageError("the join code is empty")
    directory = state.resolve_state_dir()
    if state.has_credential(directory):
        _err(
            f"this clone already holds a session credential ({state.credential_path(directory)}); "
            "run `maity resume`, or revoke the session in the dashboard and delete that file "
            "before joining again"
        )
        return EXIT_ERROR
    result = hub.exchange(target, code.strip(), client=args.client or hub.CLIENT)
    base = hub.accept_hub(url, result.hub)  # before anything is kept
    path = state.write_credential(directory, result.credential)
    state.save_state(
        directory,
        {
            "hub": base,
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
    if args.pointer:
        root = pointer.repo_root(Path.cwd())
        if root is not None:
            for changed in pointer.write(root):
                print(f"wrote the Maity pointer block into {changed}", file=sys.stderr)
    else:
        # AGENTS.md is usually tracked: writing into it unasked dirties the clone, and the
        # next `git add -A` commits it. The block is offered instead (`--pointer` writes it).
        print(
            "So that a new session resumes on its own, add this to AGENTS.md (or join with "
            "--pointer to have it written):\n" + pointer.BLOCK,
            file=sys.stderr,
            end="",
        )
    if args.no_resume:
        return EXIT_OK
    try:
        return _resume(Session(), args, first=True)
    except hub.HubError as exc:
        _err(
            f"joined, but the first resume failed: {exc}; run `maity resume`. "
            f"How to work as a member: {onboarding.HANDBOOK}"
        )
        return EXIT_ERROR


def cmd_resume(args: argparse.Namespace) -> int:
    return _resume(Session(args.hub), args)


BATCH_MAX = 50


def _event_line(event: dict[str, Any]) -> str:
    """`#seq kind subject: title`, cleaned: what woke the wait, before its JSON."""
    subject = onboarding.get(event, "subject", "id")
    title = onboarding.get(event, "payload", "title") or onboarding.get(event, "payload", "type")
    line = f"#{onboarding.inline(event.get('seq'))} {onboarding.inline(event.get('kind'))}"
    if subject:
        line += f" {onboarding.inline(subject)}"
    if title:
        line += f": {onboarding.inline(title)[:120]}"
    return line


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
        items = [e for e in page.get("items") or [] if isinstance(e, dict)]
        if items:
            taken = items[:BATCH_MAX] if args.batch else items[:1]
            if not args.keep_cursor:  # with it, the next resume still lists the events
                session.data["cursor"] = taken[-1].get("seq", cursor)
                session.save()
            for event in taken:
                note = _pause_note(event, session.data.get("member_id"))
                if note:
                    _err(note)
            for event in taken:  # one line a person reads; stdout stays the JSON scripts parse
                _err(_event_line(event))
            _print_json(taken if args.batch else taken[0])
            return EXIT_OK
        new_cursor = page.get("cursor")
        if isinstance(new_cursor, int) and new_cursor != cursor:
            cursor = new_cursor  # this run polls on from here; --keep-cursor saves nothing
            if not args.keep_cursor:
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
    if args.no_code:
        # A result that is not code (a review, a draft): no git facts, read or sent (§6.6).
        body = {
            "summary": args.summary.strip(), "code": False, "head": None, "branch": None,
            "upstream": None, "remote_head": None, "pr": None, "pr_status": "none",
            "pr_unknown_reason": None, "done": args.done,
        }  # fmt: skip
        path = session.project_path("tasks", args.task, "report")
        task = session.client.call("POST", path, body=body)
        status = task.get("status") if isinstance(task, dict) else None
        return _done(args, task, f"reported {args.task} (no code); task is now {status}")
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
    """Refuse an empty or blank value; return it as given, Markdown indentation included."""
    if not value.strip():
        raise UsageError(f"{what} is empty")
    return value


def _id(value: str) -> str:
    """An argparse type for card, request and item ids: one non-empty path segment."""
    if not value.strip() or value in (".", ".."):
        raise argparse.ArgumentTypeError(f"{value!r} is not an id")
    return value


def cmd_claim(args: argparse.Namespace) -> int:
    body: dict[str, Any] = {}
    if args.reason is not None:
        body["reason"] = _text(args.reason, "--reason")
    session = Session()
    path = session.project_path("tasks", args.card)
    note = ""
    try:
        task = session.client.call("POST", f"{path}/claim", body=body)
    except hub.HubError as exc:
        # A repeated claim after a dropped connection: the first one went through.
        mine = session.data.get("member_id")
        if exc.code != "already_claimed" or not mine or exc.details.get("holder") != mine:
            raise
        task, note = session.client.call("GET", path), " (it was already yours)"
    lease = _field(task, "claim", "lease_until")
    return _done(args, task, f"claimed {args.card}{note}; lease until {lease}")


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
    path = session.project_path("tasks", args.card, "checkpoint")
    if args.no_code:
        task = session.client.call("POST", path, body=body)
        return _done(args, task, f"checkpoint on {args.card} (no code)")
    head, branch = gitfacts.position(Path.cwd())
    body["head"] = head
    if branch is None:
        _err(
            "warning: HEAD is detached, so this checkpoint names no branch; run it from the "
            "checkout the work is on (a worktree works), or use --no-code for a card that "
            "is not code"
        )
    else:
        body["branch"] = branch
        try:  # only for the warning: a card this call cannot read still gets its checkpoint
            before = session.client.call("GET", session.project_path("tasks", args.card))
        except hub.HubError:
            before = None
        earlier = onboarding.get(before, "checkpoint", "branch")
        if isinstance(earlier, str) and earlier != branch:
            _err(
                f"warning: the card's last checkpoint was on {onboarding.inline(earlier)}, "
                f"this one is on {onboarding.inline(branch)}; check you are in the right "
                "checkout"
            )
    task = session.client.call("POST", path, body=body)
    where = f"at {head[:12]} on {branch or 'a detached HEAD'}"
    return _done(args, task, f"checkpoint on {args.card} {where}")


SAY_TYPES = ("interface_change", "blocker", "go_request", "review_result", "handover", "notice")


def cmd_say(args: argparse.Namespace) -> int:
    text = _text(args.body, "the message")
    to_owner = args.to == "human"
    if not to_owner and args.type is None:
        # A reply to your own human is the chat of your conversation (§8.4, §9); to anyone
        # else a message needs a type. Ids are opaque (§1.1): compared, never parsed.
        to_owner = Session().data.get("owner_id") == args.to
    if to_owner:
        if args.type is not None or args.task is not None:
            raise UsageError("a chat with your human takes neither --type nor --task")
        session = Session()
        member_id = session.data.get("member_id")
        if not isinstance(member_id, str):
            raise state.StateError("this agent's member id is not known yet; run `maity resume`")
        path = session.project_path("conversations", member_id, "messages")
        message = session.client.call("POST", path, body={"body": text})
        return _done(args, message, f"said to your human (seq {_field(message, 'seq')})")
    if args.type is None:
        raise UsageError(
            f"--type is required when writing to {args.to}: {', '.join(SAY_TYPES)} "
            "(no --type only for your own human: `maity say human` or their member id)"
        )
    body: dict[str, Any] = {"kind": "message", "type": args.type, "to": args.to, "body": text}
    if args.task is not None:
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


# --- placements (docs/api.md §15.6), for agents with agents:propose ---------------------------


def _grace(value: str) -> int:
    seconds = int(value)
    if not 0 <= seconds <= 900:
        raise argparse.ArgumentTypeError("0 to 900 seconds")
    return seconds


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _placements(session: Session) -> list[dict[str, Any]]:
    answer = session.client.call("GET", session.project_path("placements"))
    items = answer.get("items") if isinstance(answer, dict) else None
    return [p for p in items or [] if isinstance(p, dict)]


def _one(items: list[dict[str, Any]], which: str, keys: tuple[Callable[[Any], Any], ...],
         what: str) -> dict[str, Any]:  # fmt: skip
    """The one item `which` names: an exact match on the first key (the id) wins; otherwise
    the later keys, and more than one match is refused rather than guessed. Handles are only
    unique per owner, and an id is a valid handle."""
    for key in keys:
        found = [item for item in items if key(item) == which]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise CommandError(f"{onboarding.inline(which)} names more than one {what}; use the id")
    raise CommandError(f"no {what} {onboarding.inline(which)} in this project")


def _placement(session: Session, which: str) -> dict[str, Any]:
    """The active placement with id `which`, or the one of the agent with that id or handle."""
    found = _one(
        [p for p in _placements(session) if isinstance(p.get("id"), str)],
        which,
        (lambda p: p.get("id"), lambda p: _obj(p.get("agent")).get("id"),
         lambda p: _obj(p.get("agent")).get("handle")),
        "active placement",
    )  # fmt: skip
    return found


def _member_id(session: Session, which: str) -> str:
    """The member id for an agent named by id or handle."""
    answer = session.client.call("GET", session.project_path("members"))
    members = [
        m for m in (answer.get("items") if isinstance(answer, dict) else None) or []
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    ]  # fmt: skip
    member = _one(members, which, (lambda m: m.get("id"), lambda m: m.get("handle")), "member")
    return str(member["id"])


def _placement_line(p: dict[str, Any]) -> str:
    show = onboarding.inline
    agent = _obj(p.get("agent"))
    runner = _obj(p.get("runner"))
    reported = _obj(p.get("reported"))
    state_ = str(reported.get("state") or "not reported")
    if reported.get("reason"):
        state_ += f"/{reported['reason']}"
    pending = "" if p.get("reported_current", True) else " (pending)"
    return (
        f"{show(p.get('id'))}  {show(agent.get('handle') or agent.get('id'))} on "
        f"{show(runner.get('name') or runner.get('id'))}  {show(p.get('harness'))} "
        f"{show(p.get('mode'))}  desired {show(p.get('desired'))}, {show(state_)}{pending}"
    )


def cmd_placement_list(args: argparse.Namespace) -> int:
    placements = _placements(Session())
    if args.json:
        _print_json(placements)
        return EXIT_OK
    if not placements:
        print("no active placements")
    for placement in placements:
        print(_placement_line(placement))
    return EXIT_OK


def cmd_placement_start(args: argparse.Namespace) -> int:
    session = Session()
    body: dict[str, Any] = {
        "agent": {"id": _member_id(session, args.agent)},
        "runner": args.runner,
        "harness": args.tool,
        "reason": _text(args.reason, "--reason"),
    }
    if args.mode:
        body["mode"] = args.mode
    if args.model:
        body["model"] = args.model
    if args.target:
        body["target"] = args.target
    if args.clone or args.branch:
        body["workspace"] = {k: v for k, v in (("clone", args.clone), ("branch", args.branch)) if v}
    placement = session.client.call("POST", session.project_path("placements"), body=body)
    approval = _obj(_field(placement, "approval"))
    line = f"placement {onboarding.inline(_field(placement, 'id'))} created"
    if approval.get("status") == "pending":
        line += f"; waiting for consent (request {onboarding.inline(approval.get('request_id'))})"
    return _done(args, placement, line)


def cmd_placement_stop(args: argparse.Namespace) -> int:
    session = Session()
    placement = _placement(session, args.which)
    body: dict[str, Any] = {"desired": "stopped"}
    if args.grace is not None:
        body["stop_grace_seconds"] = args.grace
    path = session.project_path("placements", placement["id"])
    answer = session.client.call("PATCH", path, body=body)
    return _done(args, answer, f"placement {onboarding.inline(placement['id'])} stopping")


def cmd_placement_restart(args: argparse.Namespace) -> int:
    session = Session()
    placement = _placement(session, args.which)
    path = session.project_path("placements", placement["id"], "restart")
    answer = session.client.call("POST", path, body={"rejoin": True} if args.rejoin else {})
    return _done(args, answer, f"placement {onboarding.inline(placement['id'])} restarting")


def cmd_runners(args: argparse.Namespace) -> int:
    session = Session()
    answer = session.client.call("GET", session.project_path("runners"))
    items = [r for r in (answer.get("items") if isinstance(answer, dict) else None) or []
             if isinstance(r, dict)]  # fmt: skip
    if args.json:
        _print_json(items)
        return EXIT_OK
    if not items:
        print("no runners attached to this project")
    for item in items:
        runner = _obj(item.get("runner")) or item  # the attachment carries the runner view
        caps = _obj(runner.get("capabilities"))
        tools = ", ".join(
            onboarding.inline(h.get("id"))
            for h in caps.get("harnesses") or []
            if isinstance(h, dict) and h.get("available")
        )

        def show(value: Any) -> str:
            return "-" if value is None else onboarding.inline(value)

        print(
            f"{show(runner.get('id'))}  {show(runner.get('name'))}  {show(runner.get('presence'))}"
            f"  {show(caps.get('running'))}/{show(caps.get('max_agents'))} running"
            f"  tools: {tools or '-'}"
        )
    return EXIT_OK


AVATAR_MAX = 1024 * 1024  # §6.10: at most 1 MiB; the hub checks the pixels


def avatar_type(data: bytes) -> str | None:
    """The image type from the magic bytes, as the hub sniffs it (§6.10, §11.2): PNG, JPEG or
    WebP; None for anything else, whatever the file is called."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def cmd_profile_avatar(args: argparse.Namespace) -> int:
    """`PUT /me/avatar` with the file as it is, or `DELETE /me/avatar` (§6.10, §13)."""
    if args.remove == bool(args.file):
        raise UsageError("give an image file, or --remove")
    if args.remove:
        answer = Session().client.call("DELETE", "/me/avatar")
        return _done(args, answer, f"avatar removed; now {_avatar_line(answer)}")
    try:
        with open(args.file, "rb") as fh:
            data = fh.read(AVATAR_MAX + 1)
    except OSError as exc:
        raise UsageError(f"cannot read {args.file}: {exc.strerror}") from None
    kind = avatar_type(data)
    if kind is None:
        _err(f"refused: {args.file} is not a PNG, JPEG or WebP image (read from its first bytes)")
        return EXIT_REFUSED
    if len(data) > AVATAR_MAX:
        _err(f"refused: {args.file} is larger than 1 MiB; scale it down first")
        return EXIT_REFUSED
    answer = Session().client.call("PUT", "/me/avatar", raw=data, content_type=kind)
    return _done(args, answer, f"avatar set: {_avatar_line(answer)}")


def _avatar_line(answer: Any) -> str:
    url = _field(answer, "avatar_url")
    source = _field(answer, "avatar_source")
    if url is None:
        return "no image (the generated avatar is shown)"
    return f"{onboarding.inline(url)} ({onboarding.inline(source or 'unknown source')})"


# --- the limit (§6.12) --------------------------------------------------------------------------

LIMIT_MAX = 7 * 24 * 3600
_DURATION = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", re.ASCII)
_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:[Zz]|[+-]\d{2}:\d{2})", re.ASCII
)
_NO_OFFSET = re.compile(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?", re.ASCII)


def limit_until(value: str, now: float | None = None) -> str:
    """`--until` as RFC 3339 in UTC with `Z`: a timestamp with an offset (converted), or a
    duration from now (`90m`, `1h30m`, `2d12h`; §13's grammar, ASCII digits only). A
    timestamp without an offset is refused, never read as local time: an agent's zone is
    often not its human's. Nothing but these two forms is accepted."""
    match = _DURATION.fullmatch(value)
    if value and match and any(match.groups()):
        if any(g is not None and int(g) == 0 for g in match.groups()):
            raise UsageError(f"--until {value!r}: each part of a duration is a positive number")
        d, h, m, s = (int(g or 0) for g in match.groups())
        seconds = ((d * 24 + h) * 60 + m) * 60 + s
        if seconds > LIMIT_MAX:
            raise UsageError(f"--until {value!r}: at most 7 days ahead")
        moment = datetime.fromtimestamp((time.time() if now is None else now) + seconds, tz=UTC)
        return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    if _NO_OFFSET.fullmatch(value):
        raise UsageError(
            f"--until {value!r} has no offset; add Z or ±hh:mm (it is never read as local time)"
        )
    if not _RFC3339.fullmatch(value):
        raise UsageError(
            f"--until {value!r}: an RFC 3339 time with an offset "
            "(2026-10-22T17:00:00Z, …+02:00) or a duration (90m, 3h, 1h30m, 2d12h)"
        )
    try:
        moment = datetime.fromisoformat(value.upper().replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, OverflowError):
        raise UsageError(f"--until {value!r}: not a time this CLI can send") from None
    return moment.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_limit(args: argparse.Namespace) -> int:
    """`POST /me/limit` before the session stops for a provider limit (§6.12); the next
    `maity resume` clears it."""
    body: dict[str, Any] = {"until": limit_until(args.until)}
    if args.reason:
        body["reason"] = _text(args.reason, "--reason")
    answer = Session().client.call("POST", "/me/limit", body=body)
    until = _field(answer, "availability", "until") or body["until"]
    return _done(args, answer, f"limited until {onboarding.inline(until)}")


# --- notes and links (§6.16, §6.13) -----------------------------------------------------------


def cmd_note_add(args: argparse.Namespace) -> int:
    session = Session()
    path = session.project_path("tasks", args.card, "notes")
    note = session.client.call("POST", path, body={"body": _text(args.body, "the note")})
    return _done(args, note, f"note {onboarding.inline(_field(note, 'id'))} on {args.card}")


def cmd_note_list(args: argparse.Namespace) -> int:
    session = Session()
    state_ = "all" if args.all else args.state
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:  # every page: a card holds at most 200 notes (§6.16)
        query = [("state", state_), ("limit", "200")]
        if cursor:
            query.append(("cursor", cursor))
        page = session.client.call(
            "GET", session.project_path("tasks", args.card, "notes"), query=query
        )
        items.extend(n for n in (_field(page, "items") or []) if isinstance(n, dict))
        cursor = _field(page, "next_cursor")
        if not cursor:
            break
    if args.json:
        _print_json(items)
        return EXIT_OK
    if not items:
        print(f"no {'' if args.all else state_ + ' '}notes on {args.card}")
    for note in items:
        author = _obj(note.get("author"))
        print(
            f"{onboarding.inline(note.get('id'))}  {onboarding.inline(note.get('state'))}  "
            f"{onboarding.inline(author.get('handle') or author.get('member_id'))}  "
            f"{onboarding.inline(note.get('created_at'))}"
        )
        for line in str(note.get("body") or "").splitlines():
            print(f"    {onboarding.clean(line)}")
    return EXIT_OK


def cmd_note_resolve(args: argparse.Namespace) -> int:
    session = Session()
    body: dict[str, Any] = {"state": args.state}
    if args.reason:
        body["reason"] = _text(args.reason, "--reason")
    path = session.project_path("tasks", args.card, "notes", args.note, "resolve")
    note = session.client.call("POST", path, body=body)
    return _done(args, note, f"note {args.note} {args.state}")


_FORGE_KIND = (
    (re.compile(r"https://github\.com/[^/?#]+/[^/?#]+/issues/[0-9]+/?", re.ASCII), "issue"),
    (re.compile(r"https://github\.com/[^/?#]+/[^/?#]+/pull/[0-9]+/?", re.ASCII), "pr"),
)


def link_kind(url: str) -> str:
    """`issue` or `pr` for a GitHub issue or pull request URL (§6.13: GitHub is the one forge
    of V1; anything else, another forge's issue included, is `url`). The hub decides whether
    it belongs to the project's repository."""
    return next((kind for pattern, kind in _FORGE_KIND if pattern.fullmatch(url)), "url")


def cmd_link_add(args: argparse.Namespace) -> int:
    kind = "url" if args.plain else link_kind(args.url)
    if args.label and kind != "url":
        raise UsageError("--label is for a plain link; a forge link shows the forge's title")
    body: dict[str, Any] = {"kind": kind}
    if kind == "url":
        body["url"] = args.url
        if args.label:
            body["label"] = args.label
    else:
        body["forge_url"] = args.url
    session = Session()
    link = session.client.call("POST", session.project_path("tasks", args.card, "links"), body=body)
    return _done(
        args, link, f"linked {kind} {onboarding.inline(_field(link, 'id'))} to {args.card}"
    )


def cmd_link_list(args: argparse.Namespace) -> int:
    session = Session()
    card = session.client.call("GET", session.project_path("tasks", args.card))
    links = [link for link in (_field(card, "links") or []) if isinstance(link, dict)]
    if args.json:
        _print_json(links)
        return EXIT_OK
    if not links:
        print(f"no links on {args.card}")
    for link in links:
        seen = _obj(link.get("observed"))
        if link.get("kind") == "url":
            label = onboarding.inline(link.get("label") or "")
            what = f"{label}  {onboarding.inline(link.get('url'))}"
        else:
            if seen.get("found"):
                status = f"{onboarding.inline(seen.get('state'))}: " + onboarding.inline(
                    seen.get("title")
                )
            elif seen.get("reason") == "kind_mismatch":  # an issue link to a PR (§6.13)
                status = "is a pull request: remove it and link the pull request"
            else:
                status = "not found on the forge" if seen else "not observed"
            what = f"{onboarding.inline(link.get('forge_url'))}  ({status})"
        print(f"{onboarding.inline(link.get('id'))}  {onboarding.inline(link.get('kind'))}  {what}")
    return EXIT_OK


def cmd_link_remove(args: argparse.Namespace) -> int:
    session = Session()
    path = session.project_path("tasks", args.card, "links", args.link)
    link = session.client.call("DELETE", path)
    return _done(args, link, f"removed {args.link} from {args.card}")


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
        "state directory without printing it, print the Maity pointer block for AGENTS.md "
        "(--pointer writes it), then "
        "open the first session and print the onboarding: the briefing the humans wrote for you, "
        "who you are, the project and its rules, and the next step. A clone that already holds a "
        "credential is refused.",
    )
    p.add_argument("url", nargs="?", help="the join URL from the pasted line")
    p.add_argument("--code", help="the single-use join code from the pasted line")
    p.add_argument(
        "--join-file",
        metavar="FILE",
        help="read the URL and the code as two lines from FILE, or from stdin with -",
    )
    p.add_argument("--no-resume", action="store_true", help="store the credential, open no session")
    p.add_argument(
        "--client", metavar="NAME", help="what made this join, e.g. maity-runner/<version>"
    )
    p.add_argument(
        "--pointer",
        action="store_true",
        help="write the Maity pointer block into AGENTS.md (and CLAUDE.md); otherwise it is "
        "printed for you to add",
    )
    p.add_argument("--no-pointer", action="store_true", help=argparse.SUPPRESS)  # the default
    _session_args(p)
    p.add_argument("--json", action="store_true", help="print the resume packet as JSON")
    p.set_defaults(handler=cmd_join)

    p = add(
        "resume",
        "who am I, what is open, what did I miss",
        "Open a session and print what it says: the briefing, identity and role, the project's "
        "state and rules (in full when they changed), the cards you hold with their checkpoints, "
        "answered and open requests, the events since your last session, and the next step. "
        "--json prints the resume packet itself. Run it at the start of every session and after "
        "a context compaction.",
    )
    p.add_argument(
        "--hub", help="the hub URL, once, when the credential came from the page-driven join"
    )
    _session_args(p)
    p.add_argument("--json", action="store_true", help="print the resume packet as JSON")
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
    p.add_argument(
        "--batch",
        action="store_true",
        help=f"print every pending event (at most {BATCH_MAX}) as one JSON array, not the first "
        "one alone: one wake for a burst",
    )
    p.add_argument(
        "--keep-cursor",
        action="store_true",
        help="return the event without acknowledging it, and save no cursor: the next "
        "`maity resume` still lists it (for a supervisor that starts a run on each event)",
    )
    p.set_defaults(handler=cmd_wait)

    p = add(
        "report",
        "report finished work with facts read from git and gh",
        "Send a completion report. The head commit comes from git, the remote head from "
        "`git ls-remote`, the pull request from `gh` when it is installed; nothing is typed by "
        f"hand. Refused with exit {EXIT_REFUSED}, before anything is sent, while uncommitted "
        "changes exist, the branch is not pushed, or the pull request's head differs. A branch "
        "deleted after its pull request was merged reports with the merged head. A card "
        "whose result is not code (a review, a draft, a decision prepared for a human) is "
        "reported with --no-code: the summary carries the result, and no git fact is read or "
        "sent.",
    )
    p.add_argument("--task", required=True, type=_id, help="the task id the report is for")
    p.add_argument(
        "--summary",
        required=True,
        help="one or two sentences on what was done; with --no-code, the result itself",
    )
    p.add_argument(
        "--no-code", action="store_true", help="the result is not code: no git facts are sent"
    )
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
    p.add_argument("--task", type=_id, help="the task id the request belongs to")
    _json_flag(p)
    p.set_defaults(handler=cmd_ask)

    p = add(
        "claim",
        "take a card: it stays yours until it is closed or you give it back",
        "Claim an open card (POST …/tasks/{card}/claim). The lease is renewed by every call this "
        "agent makes; nothing is released automatically. In a project under freeze or "
        "fixes-only, --reason is required.",
    )
    p.add_argument("card", type=_id, help="the card id, e.g. tsk-0004")
    p.add_argument("--reason", help="why, when the project is in freeze or fixes-only")
    _json_flag(p)
    p.set_defaults(handler=cmd_claim)

    p = add(
        "unclaim",
        "give a claimed card back, unfinished",
        "Give a card back (POST …/tasks/{card}/release): it is open again and claimable. Use "
        "`report` for finished work instead.",
    )
    p.add_argument("card", type=_id, help="the card id")
    _json_flag(p)
    p.set_defaults(handler=cmd_unclaim)

    p = add(
        "checkpoint",
        "record where the work on a card stands, for the next session",
        "Record the last and the next step on a card you hold. The branch and the head commit "
        "come from git, not from you; a detached HEAD, or a branch other than the card's last "
        "checkpoint's, is warned about. The next session reads it from the resume packet.",
    )
    p.add_argument("card", type=_id, help="the card id")
    p.add_argument(
        "-m", "--last", dest="message", metavar="LAST", required=True, help="the step just finished"
    )
    p.add_argument("--next", required=True, help="the step to take next")
    p.add_argument(
        "--no-code", action="store_true", help="the card is not code: no branch or head is sent"
    )
    _json_flag(p)
    p.set_defaults(handler=cmd_checkpoint)

    p = add(
        "say",
        "send a typed message to members, or chat with your human",
        "Post a message (POST …/events). TO is 'all', 'role:<role>' or a member id, and --type "
        "says what it is. TO 'human', or that human's member id without --type, writes into the "
        "chat with the human who owns this agent (POST …/conversations/{you}/messages). Status "
        "is not a message: the board shows it.",
    )
    p.add_argument("to", type=_id, help="'all', 'role:<role>', a member id, or 'human'")
    p.add_argument("body", help="the message, Markdown")
    p.add_argument("--type", choices=SAY_TYPES, help="required unless TO is your own human")
    p.add_argument("--task", type=_id, help="the card the message is about")
    _json_flag(p)
    p.set_defaults(handler=cmd_say)

    p = add(
        "answer",
        "answer a request addressed to you",
        "Answer a request (POST …/requests/{id}/answer) with one of its replies, free text, or "
        "both. Agents answer decision, contract and info requests addressed to them, and any "
        "request when their role holds requests:answer; never their own.",
    )
    p.add_argument("request", type=_id, help="the request id, e.g. req-0012")
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
    r = rsub.add_parser(
        "list",
        help="every release of the project",
        description="List every release card (GET …/tasks?kind=release&status=all, all pages). "
        "With --json, the cards of all pages as one array.",
        formatter_class=fmt,
    )
    _json_flag(r)
    r.set_defaults(handler=cmd_release_list)
    r = rsub.add_parser(
        "show",
        help="one release: readiness, what blocks it, the checklist",
        description="Show one release card (GET …/tasks/{card}); without a card, the release "
        "that is neither done nor cancelled.",
        formatter_class=fmt,
    )
    r.add_argument(
        "card", nargs="?", type=_id, help="the release card id (default: the one in flight)"
    )
    _json_flag(r)
    r.set_defaults(handler=cmd_release_show)
    r = rsub.add_parser(
        "tick",
        help="tick a checklist item",
        description="Tick or untick one checklist item (POST …/tasks/{card}/checklist/{item}); "
        "the holder of the release and members with releases:write may.",
        formatter_class=fmt,
    )
    r.add_argument("item", type=_id, help="the checklist item id, e.g. chk-2")
    r.add_argument("--release", type=_id, help="the release card id (default: the one in flight)")
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

    runner_commands.add_parser(sub, fmt)

    p = add(
        "profile",
        "your own profile: its avatar",
        "Change your agent profile, the same in every project it is a member of (§6.10).",
    )
    prof = p.add_subparsers(dest="profile_command", metavar="<action>", required=True)
    r = prof.add_parser(
        "avatar",
        help="set or remove your avatar",
        description="Upload an image as your avatar: PNG, JPEG or WebP, at most 1 MiB. The type "
        "is read from the file's first bytes, and anything else is refused here before any "
        f"call (exit {EXIT_REFUSED}). The hub re-encodes it as a square PNG of at most 256 "
        "pixels, without metadata. --remove deletes the upload. Prints the new avatar_url.",
        formatter_class=fmt,
    )
    r.add_argument("file", nargs="?", help="the image to upload")
    r.add_argument("--remove", action="store_true", help="remove the uploaded avatar")
    _json_flag(r)
    r.set_defaults(handler=cmd_profile_avatar)

    p = add(
        "limit",
        "declare a provider limit before the session stops",
        "Tell the hub you are out until a time: `POST /me/limit` (§6.12). Run it before the "
        "session stops for a provider limit; the next `maity resume` clears it. TIME is an "
        "RFC 3339 timestamp with an offset (2026-10-22T17:00:00Z) or a duration from now "
        "(90m, 3h, 1h30m, 2d12h: units d, h, m, s in that order, each once), at most 7 days "
        "ahead (by this machine's clock; the hub may refuse the very edge if its clock differs). "
        "A timestamp without an offset is refused: it is never read as local time.",
    )
    p.add_argument("--until", required=True, metavar="TIME", help="when you are back")
    p.add_argument("--reason", help="why, at most 200 characters")
    _json_flag(p)
    p.set_defaults(handler=cmd_limit)

    p = add(
        "note",
        "remarks on a card that never change it",
        "Post, read and resolve notes on a card (§6.16). A note is information, not an "
        "instruction: it counts once someone who may edit the card works it into the body.",
    )
    nsub = p.add_subparsers(dest="note_command", metavar="<action>", required=True)
    r = nsub.add_parser("add", help="post a note on a card", formatter_class=fmt)
    r.add_argument("card", type=_id, help="the card id")
    r.add_argument("body", help="the note, Markdown, at most 4 KiB")
    _json_flag(r)
    r.set_defaults(handler=cmd_note_add)
    r = nsub.add_parser("list", help="a card's notes, oldest first", formatter_class=fmt)
    r.add_argument("card", type=_id, help="the card id")
    which = r.add_mutually_exclusive_group()
    which.add_argument("--state", default="open", help="open (default), incorporated, dismissed")
    which.add_argument("--all", action="store_true", help="every note, whatever its state")
    _json_flag(r)
    r.set_defaults(handler=cmd_note_list)
    r = nsub.add_parser(
        "resolve",
        help="mark an open note incorporated or dismissed (the card's creator, or tasks:admin)",
        formatter_class=fmt,
    )
    r.add_argument("card", type=_id, help="the card id")
    r.add_argument("note", type=_id, help="the note id, e.g. nte-0031")
    how = r.add_mutually_exclusive_group(required=True)
    how.add_argument("--incorporated", dest="state", action="store_const", const="incorporated",
                     help="the point is now in the card's body")  # fmt: skip
    how.add_argument("--dismissed", dest="state", action="store_const", const="dismissed",
                     help="not taken up")  # fmt: skip
    r.add_argument("--reason", help="why, optional")
    _json_flag(r)
    r.set_defaults(handler=cmd_note_resolve)

    p = add(
        "link",
        "references from a card to forge issues, pull requests and URLs",
        "Add, list and remove a card's links (§6.13). A GitHub issue or pull request URL "
        "becomes a forge link, which the hub observes (state and title); any other https URL "
        "(another forge's issue too), or one given with --plain, is a plain link the hub "
        "never fetches.",
    )
    lsub = p.add_subparsers(dest="link_command", metavar="<action>", required=True)
    r = lsub.add_parser("add", help="link a card to an issue, a pull request or a URL",
                        formatter_class=fmt)  # fmt: skip
    r.add_argument("card", type=_id, help="the card id")
    r.add_argument("url", help="an https URL")
    r.add_argument("--plain", action="store_true", help="a plain link even for a forge URL")
    r.add_argument("--label", help="a plain link's label, at most 200 characters")
    _json_flag(r)
    r.set_defaults(handler=cmd_link_add)
    r = lsub.add_parser("list", help="a card's links, with what the hub observed",
                        formatter_class=fmt)  # fmt: skip
    r.add_argument("card", type=_id, help="the card id")
    _json_flag(r)
    r.set_defaults(handler=cmd_link_list)
    r = lsub.add_parser("remove", help="remove a link (its adder, the card's holder or "
                        "creator, or tasks:admin)",
                        formatter_class=fmt)  # fmt: skip
    r.add_argument("card", type=_id, help="the card id")
    r.add_argument("link", type=_id, help="the link id, e.g. lnk-0007")
    _json_flag(r)
    r.set_defaults(handler=cmd_link_remove)

    p = add(
        "placement",
        "start, list, stop or restart agents on runners (agents:propose)",
        "Placements say which agent runs on which runner (§15.6). With agents:propose an agent "
        "may propose a start for an existing member (under consent the owner gives the go) and "
        "stop, start, restart and list placements. An agent is named by its handle or id.",
    )
    psub = p.add_subparsers(dest="placement_command", metavar="<action>", required=True)
    r = psub.add_parser("list", help="the project's active placements", formatter_class=fmt)
    _json_flag(r)
    r.set_defaults(handler=cmd_placement_list)
    r = psub.add_parser(
        "start",
        help="propose or start an agent on a runner",
        description="POST …/placements for an existing member; prints the placement and, "
        "under consent, the request id the owner answers.",
        formatter_class=fmt,
    )
    r.add_argument("agent", help="the member's handle or id")
    r.add_argument("--runner", required=True, type=_id, help="the runner id")
    r.add_argument("--tool", required=True, help="the harness, e.g. claude-code or codex")
    r.add_argument("--mode", choices=("interactive", "supervised"), help="default: the tool's")
    r.add_argument("--model", help="one of the runner's models for the tool")
    r.add_argument("--target", help="a target the runner advertises")
    r.add_argument("--clone", help="the clone name (default: the agent's handle)")
    r.add_argument("--branch", help="a starting branch")
    r.add_argument("--reason", required=True, help="why this agent should run there")
    _json_flag(r)
    r.set_defaults(handler=cmd_placement_start)
    r = psub.add_parser("stop", help="stop an agent's placement", formatter_class=fmt)
    r.add_argument("which", help="the placement id, or the agent's handle or id")
    r.add_argument("--grace", type=_grace, metavar="N", help="seconds to park the work (0-900)")
    _json_flag(r)
    r.set_defaults(handler=cmd_placement_stop)
    r = psub.add_parser("restart", help="restart an agent's placement", formatter_class=fmt)
    r.add_argument("which", help="the placement id, or the agent's handle or id")
    r.add_argument(
        "--rejoin",
        action="store_true",
        help="with a new credential, after the old one was revoked (§15.6)",
    )
    _json_flag(r)
    r.set_defaults(handler=cmd_placement_restart)

    p = add(
        "runners",
        "the runners attached to this project, their state and tools",
        "List the project's runners (GET …/runners): presence, agents running, available tools.",
    )
    _json_flag(p)
    p.set_defaults(handler=cmd_runners)

    p = sub.add_parser(
        "help",
        help="print the hub's own documentation (GET /api/v1/help)",
        description="Fetch and print /api/v1/help from the hub this clone joined, or from --hub.",
        formatter_class=fmt,
    )
    p.add_argument("--hub", help="hub URL, for use before joining")
    p.set_defaults(handler=cmd_help)
    return parser


STILL_WORKS = "checkpoint, report, unclaim, ask, answer, say, the chat, resume and wait"


def _pause_text(paused: dict[str, Any]) -> str:
    who = onboarding.inline(paused.get("by") or "a human")
    since = paused.get("since")
    when = f" since {onboarding.inline(since)}" if since else ""
    reason = onboarding.inline(paused.get("reason") or "no reason given")
    return f"by {who}{when}: {reason}"


def _explain(exc: Exception) -> str:
    """The error line; a refusal because a human paused this agent says what that means."""
    if isinstance(exc, hub.HubError) and exc.code == "paused":
        paused = exc.details.get("paused")
        detail = _pause_text(paused) if isinstance(paused, dict) else "by a human"
        return (
            f"refused: you are paused {detail}. You take no new work until the pause is "
            f"lifted; {STILL_WORKS} still work. Park what you hold, then `maity wait`."
        )
    return str(exc)


def _pause_note(event: dict[str, Any], member_id: Any) -> str | None:
    """A plain line for a `session_paused` event about this agent itself; None otherwise."""
    if event.get("kind") != "session_paused" or not member_id:
        return None
    if onboarding.get(event, "subject", "id") != member_id:
        return None  # a manager seeing a report's pause
    paused = onboarding.get(event, "payload", "paused")
    if isinstance(paused, dict):
        return (
            f"you were paused {_pause_text(paused)}. Park what you hold (checkpoint, report or "
            "unclaim), then `maity wait` for the lift."
        )
    return "your pause was lifted; you can take new work again."


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
        _err(_explain(exc))
        return EXIT_ERROR
    except config.ConfigError as exc:
        for problem in exc.problems:
            _err(problem)
        return EXIT_ERROR
    except (UsageError, runner_commands.Refused) as exc:
        _err(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED
