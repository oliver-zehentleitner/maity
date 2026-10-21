"""Command line entry point: `maity <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from maity import __version__, gitfacts, hub, state

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_TIMEOUT = 3
EXIT_REFUSED = 4
EXIT_NOT_IMPLEMENTED = 5

REQUEST_CLASSES = ("decision", "consent", "contract", "info")
PRIORITIES = ("low", "normal", "high")

OUTPUT_DISCIPLINE = """\
output discipline:
  maity prints status and facts, never a credential. The session credential is
  written straight to a file and read only by the code that sends a request; no
  command prints it, and no command prints anything else from that file.

state:
  <git common dir>/maity/credential   the session credential, mode 0600
  <git common dir>/maity/state.json   hub URL, project, identity, mode 0600
  One state per clone, shared by its worktrees. MAITY_STATE_DIR overrides it.

exit codes:
  0 success, 1 error, 2 usage, 3 wait timed out, 4 report refused,
  5 not implemented yet (the hub API contract is pending)
"""

Handler = Callable[[argparse.Namespace], int]


class UsageError(Exception):
    """Arguments argparse accepts but the command cannot use."""


def _err(message: str) -> None:
    print(f"maity: {message}", file=sys.stderr)


def _pending(what: str) -> int:
    _err(f"not implemented yet, the hub API contract is pending: {what}")
    return EXIT_NOT_IMPLEMENTED


def _state_dir() -> Path:
    return state.resolve_state_dir()


def _joined_state() -> tuple[Path, dict[str, object]]:
    directory = _state_dir()
    if not state.has_credential(directory):
        raise state.StateError(
            "this clone has not joined a project; run `maity join <url> --code <code>`"
        )
    return directory, state.load_state(directory)


def cmd_join(args: argparse.Namespace) -> int:
    base = hub.hub_base(args.url)
    if not args.code.strip():
        raise hub.HubError("the join code is empty")
    directory = _state_dir()
    if state.has_credential(directory):
        _err(
            f"this clone already holds a session credential ({state.credential_path(directory)}); "
            "run `maity resume`, or revoke the session in the dashboard and delete that file "
            "before joining again"
        )
        return EXIT_ERROR
    return _pending(
        f"exchange the join code with {base}, write the session credential to "
        f"{state.credential_path(directory)} (mode 0600, never printed) and the hub, project "
        f"and identity to {directory / state.STATE_FILE}, then print the resume packet"
    )


def cmd_resume(args: argparse.Namespace) -> int:
    directory, data = _joined_state()
    target = data.get("hub", "the hub")
    return _pending(
        f"fetch the resume packet from {target}: who this agent is, its role, open tasks, "
        "unanswered requests and the events since the last cursor"
    )


def cmd_wait(args: argparse.Namespace) -> int:
    if args.timeout <= 0:
        raise UsageError("--timeout must be a positive number of seconds")
    _joined_state()
    return _pending(
        f"long-poll the events endpoint for up to {args.timeout}s, print the first event as "
        f"JSON and exit {EXIT_OK}, or exit {EXIT_TIMEOUT} when nothing arrived"
    )


def cmd_report(args: argparse.Namespace) -> int:
    facts = gitfacts.collect(Path.cwd())
    problems = gitfacts.mismatches(facts)
    if problems:
        _err("report refused, the code does not match what would be reported:")
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"head      {facts.head}")
    print(f"branch    {facts.branch} = {facts.remote}/{facts.remote_branch}")
    if facts.pr is not None:
        print(f"pr        #{facts.pr.number} {facts.pr.state.lower()} {facts.pr.url}")
    elif facts.gh_available:
        print("pr        none for this branch")
    else:
        print("pr        unknown (gh is not installed)")
    _joined_state()
    return _pending(f"send the completion report for task {args.task} with these facts")


def cmd_ask(args: argparse.Namespace) -> int:
    if not args.question.strip():
        raise UsageError("the question is empty")
    if args.request_class in ("decision", "consent") and len(args.option) == 1:
        raise UsageError("give at least two --option values, or none for a free-text answer")
    _joined_state()
    request = {
        "to": args.to,
        "class": args.request_class,
        "question": args.question,
        "options": args.option,
        "priority": args.priority,
        "task": args.task,
    }
    print(json.dumps(request, indent=2))
    return _pending("send this request to the hub and print its id")


def cmd_help(args: argparse.Namespace) -> int:
    if args.hub:
        base = hub.hub_base(args.hub)
    else:
        data = state.load_state(_state_dir())
        stored = data.get("hub")
        if not isinstance(stored, str):
            raise state.StateError("not joined in this clone; pass --hub <url>")
        base = hub.hub_base(stored)
    print(hub.get_text(f"{base}/help"), end="")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="maity",
        description="Agent-side command for Maity: join a project, resume, wait for events, "
        "report finished work, ask a human.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    parser.add_argument("--version", action="version", version=f"maity {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p = sub.add_parser(
        "join",
        help="pair this clone with a project, using the line a human pasted",
        description="Exchange the single-use join code for a session credential. The "
        "credential is written to this clone's state directory and never printed. Run it "
        "once per clone; a clone that already holds a credential is refused.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    p.add_argument("url", help="the join URL from the pasted line")
    p.add_argument("--code", required=True, help="the single-use join code from the pasted line")
    p.set_defaults(handler=cmd_join)

    p = sub.add_parser(
        "resume",
        help="who am I, what is open, what did I miss",
        description="Fetch the resume packet for this clone's agent identity: role, project "
        "rules, open tasks, unanswered requests and the events since the last cursor. Run it "
        "at the start of every session.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    p.set_defaults(handler=cmd_resume)

    p = sub.add_parser(
        "wait",
        help="block until the next event arrives, or time out",
        description="Long-poll the project's events. Prints the first event as JSON and exits "
        f"{EXIT_OK}; exits {EXIT_TIMEOUT} when nothing arrived within the timeout. Meant to run "
        "as a background command on harnesses that wake the agent when one exits.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    p.add_argument(
        "--timeout", type=int, default=600, metavar="N", help="seconds to wait (default: 600)"
    )
    p.set_defaults(handler=cmd_wait)

    p = sub.add_parser(
        "report",
        help="report finished work with facts read from git and gh",
        description="Send a completion report. The head commit comes from git, the remote "
        "head from `git ls-remote`, the pull request from `gh` when it is installed; nothing "
        f"is typed by hand. Refused with exit {EXIT_REFUSED} while uncommitted changes exist, "
        "the branch is not pushed, or the pull request's head differs from the local one.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    p.add_argument("--task", required=True, help="the task id the report is for")
    p.add_argument("--summary", default="", help="one or two sentences on what was done")
    p.set_defaults(handler=cmd_report)

    p = sub.add_parser(
        "ask",
        help="put a request into a human's or a role's inbox",
        description="Ask a human or a role for a decision, a consent, a contract change or "
        "information. With --option values the answer is one click; without, it is free text.",
        epilog=OUTPUT_DISCIPLINE,
        formatter_class=fmt,
    )
    p.add_argument("question", help="the request, self-contained: what, why, what you tried")
    p.add_argument(
        "--to", required=True, help="'human', a role such as 'role:reviewer', or a member"
    )
    p.add_argument(
        "--class",
        dest="request_class",
        required=True,
        choices=REQUEST_CLASSES,
        help="decision: pick one; consent: may I; contract: change an interface; info: tell me",
    )
    p.add_argument(
        "--option", action="append", default=[], help="a prepared answer; repeat for each one"
    )
    p.add_argument("--priority", choices=PRIORITIES, default="normal", help="default: normal")
    p.add_argument("--task", help="the task id the request belongs to")
    p.set_defaults(handler=cmd_ask)

    p = sub.add_parser(
        "help",
        help="print the hub's own documentation (GET /help)",
        description="Fetch and print /help from the hub this clone joined, or from --hub.",
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
    except (state.StateError, gitfacts.FactsError, hub.HubError) as exc:
        _err(str(exc))
        return EXIT_ERROR
    except UsageError as exc:
        _err(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130
