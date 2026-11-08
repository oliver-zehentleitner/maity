"""One shared watcher for a pull request's CI result on an exact head.

    python3 tools/ci_watch.py add <queue> <pr> <full head sha> <author handle#instance>
    python3 tools/ci_watch.py remove <queue> <pr>
    python3 tools/ci_watch.py run <queue> [--inbox <member id>] [--once] [--interval 120]
                                          [--repo owner/name]

The queue file holds one line per watched head: `<pr> <full head sha> <author>`, where the
author is the Maity address the result goes to (`handle#instance` or `agt-…#instance`). The
author adds the line after a push; a newer head for the same pull request replaces it. The line
holds nothing else: no path, no state directory, no credentials.

`run` goes through the queue every `--interval` seconds (one pass with `--once`). For each line
it takes the newest run of the `ci` workflow (`.github/workflows/ci.yml`) for exactly that head,
started by that pull request's branch (`pull_request` event), and waits until the run is
completed. It then reports the `ci-ok` job's conclusion, and the jobs that failed, to the author
and removes the line. A head that moved, a closed or merged pull request, and a conflict with
main (no run starts then) are reported and removed too.

Intake through Maity, for authors who cannot reach the file (a cloud session): with `--inbox
<member id>`, `run` first reads the project's messages to that member and takes each one whose
whole text is `ciwatch <pr> <full head sha>`:

    maity say --type notice <watcher address> 'ciwatch <pr> <full head sha>'

The author is the message's sender as the hub records it (`from#from_instance`), never an
address in the text. The pull request must be open with that SHA as its head; then the line is
added (a newer head replaces an older one, as with `add`). The number has at most nine digits.
Any other message is left alone and gets no answer, and the watcher's own messages are never
read as intake, so it never answers itself.

Each request is decided once and answered (added, or why not), with `(request <seq>)` at the end.
The decision, the answer and the last message read are saved in `<queue>.intake` before the
answer is said. An answer whose `maity say` failed is said again only after a later pass read
the messages to the end without finding it there (a `say` whose response got lost did post
it), and given up after five failures, logged; then the request gets no answer. A request
whose GitHub check fails five passes in a row is answered so and passed over. One way to two
answers stays: if the hub changed the posted body and the response was lost, the read-back
misses it and the answer is said again. A pass reads at most five pages and answers at most 50
requests; the next pass goes on from there. A first start begins after the newest message,
following empty pages (across passes, from a saved continuation), and never takes older ones.
An unreadable state file is logged every pass and the queue pass still runs. Reading
messages moves no read mark of the identity (`maity messages` acknowledges nothing), so a
`maity wait` of the same identity still gets every message. But every read is a hub call, and
every hub call is presence (docs/api.md §2.4): each pass marks the instance of the
`MAITY_STATE_DIR` online and renews the leases of the claims it holds. Until the watcher has an
identity of its own, that instance's claims do not run out while the watcher runs, even if its
session is stuck; run it under an instance that holds no claims where that matters. A message
whose sender is no member id gets no answer (logged).

What the intake does not check: that the sender wrote the pull request. Anyone who can message
the watcher can have any open head watched, and the result goes to them.

Who reports: `run` posts with `maity say` under the Maity identity of the `MAITY_STATE_DIR` it is
started with, and refuses to start without one, so the sender is never a guess. On the shared
machine that is the identity of whoever runs the merge queue.

What it never does: it only reads. Every GitHub call is a GET through `gh api`; it never
cancels, re-runs or merges anything. It does not use `gh pr checks` (exit code 8 while a check
fails or is pending, and an older cancelled run listed next to the newer one), nor the commit's
check runs (after a fast-forward an old green `ci-ok` of a push run hangs on the same SHA). A
failing `gh` or `maity` call is taken as passing trouble: the line stays and is tried again.

Standard library only; `gh` must be logged in.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

REPO = "oliver-zehentleitner/maity"
WORKFLOW = ".github/workflows/ci.yml"
SUMMARY_JOB = "ci-ok"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PR = re.compile(r"^[1-9][0-9]*$")
# A Maity address: a handle or member id, `#`, an instance. No `/`, so never a path.
_AUTHOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*#[A-Za-z0-9]+$")
_MEMBER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# The pull request number is bounded, so a message can never make `int()` fail.
_INTAKE = re.compile(r"^ciwatch ([1-9][0-9]{0,8}) ([0-9a-f]{40})$")
# Per pass: at most this many answers and this many pages of messages; the rest waits for the
# next pass, which goes on where this one stopped.
INTAKE_PER_PASS = 50
PAGES_PER_PASS = 5
# A request whose GitHub check fails this many passes in a row is answered and passed over;
# an answer whose `maity say` fails this many times is given up (and logged).
TRIES = 5
_FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


class Refused(Exception):
    """A queue line or command the tool will not take, said so the author can fix it."""


class Transient(Exception):
    """A `gh` or `maity` call that failed; the line is tried again on the next pass."""


class NotFound(Exception):
    """GitHub answered 404: the pull request does not exist."""


@dataclass(frozen=True)
class Entry:
    pr: int
    sha: str
    author: str

    def line(self) -> str:
        return f"{self.pr} {self.sha} {self.author}"


def parse_entry(pr: str, sha: str, author: str) -> Entry:
    if not _PR.match(pr):
        raise Refused(f"pull request {pr!r}: not a number")
    if not _SHA.match(sha):
        raise Refused("head: give the full 40-character SHA in lower case")
    if not _AUTHOR.match(author):
        raise Refused("author: give a Maity address, handle#instance")
    return Entry(int(pr), sha, author)


def parse_line(line: str) -> Entry | None:
    """An entry, or None for a blank or `#` line; a malformed line raises Refused."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split()
    if len(parts) != 3:
        raise Refused("a line is `<pr> <full head sha> <author handle#instance>`")
    return parse_entry(*parts)


@contextlib.contextmanager
def locked(queue: Path) -> Iterator[None]:
    """Holds the queue's lock file, so `add`, `remove` and `run` never write over each other."""
    with open(f"{queue}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(queue: Path) -> list[str]:
    try:
        return queue.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _write(queue: Path, lines: list[str]) -> None:
    tmp = queue.with_name(queue.name + ".tmp")
    tmp.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    os.replace(tmp, queue)


def _same_pr(line: str, pr: int) -> bool:
    parts = line.split()
    return bool(parts) and parts[0] == str(pr)


def add(queue: Path, entry: Entry) -> None:
    """Adds the entry; a line of the same pull request (an older head) is replaced."""
    with locked(queue):
        lines = [line for line in _read(queue) if not _same_pr(line, entry.pr)]
        _write(queue, [*lines, entry.line()])


def remove(queue: Path, pr: int) -> bool:
    with locked(queue):
        lines = _read(queue)
        kept = [line for line in lines if not _same_pr(line, pr)]
        _write(queue, kept)
    return len(kept) != len(lines)


def _drop(queue: Path, entry: Entry) -> None:
    """Removes exactly this line; a line added meanwhile (a newer head) stays."""
    with locked(queue):
        _write(queue, [line for line in _read(queue) if line.split() != entry.line().split()])


Gh = Callable[[str], object]
Say = Callable[[str, str], None]


def check(entry: Entry, gh: Gh, repo: str = REPO) -> str | None:
    """The report for this entry, or None while there is nothing to report yet."""
    pr = gh(f"repos/{repo}/pulls/{entry.pr}")
    assert isinstance(pr, dict)
    where = f"#{entry.pr} on {entry.sha}"
    if pr.get("merged"):
        return f"CI watch: {where}: the pull request is merged; no longer watched."
    if pr.get("state") != "open":
        return f"CI watch: {where}: the pull request is closed; no longer watched."
    head = pr["head"]
    if head["sha"] != entry.sha:
        return (
            f"CI watch: {where}: the head moved to {head['sha']}; not watched. "
            "Add the new head to watch it."
        )
    runs = gh(f"repos/{repo}/actions/runs?head_sha={entry.sha}&event=pull_request&per_page=100")
    assert isinstance(runs, dict)
    ours = [
        run
        for run in runs.get("workflow_runs", [])
        if run.get("path") == WORKFLOW and run.get("head_branch") == head["ref"]
    ]
    if not ours:
        # A pull request that conflicts with main gets no run at all.
        if pr.get("mergeable_state") == "dirty":
            return f"CI watch: {where}: conflicts with main, so no CI run starts; not watched."
        return None
    run = max(ours, key=lambda r: (r["created_at"], r["id"]))
    if run.get("status") != "completed":
        return None
    jobs = gh(
        f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
    )
    assert isinstance(jobs, dict)
    by_name = {job["name"]: job for job in jobs.get("jobs", [])}
    failed = sorted(
        name
        for name, job in by_name.items()
        if name != SUMMARY_JOB and job.get("conclusion") in _FAILED
    )
    summary = by_name.get(SUMMARY_JOB, {}).get("conclusion")
    url = run.get("html_url", "")
    if summary == "success":
        return f"CI watch: {where}: ci-ok green. {url}"
    said = f"ci-ok {summary}" if summary else "no ci-ok result"
    jobs_said = f"; failed: {', '.join(failed)}" if failed else ""
    return f"CI watch: {where}: RED, {said} (run {run.get('conclusion')}){jobs_said}. {url}"


def run_pass(queue: Path, gh: Gh, say: Say, repo: str = REPO, log: TextIO = sys.stderr) -> int:
    """One pass over the queue; returns how many lines were reported and removed."""
    with locked(queue):
        lines = _read(queue)
    done = 0
    for line in lines:
        try:
            entry = parse_line(line)
        except Refused as refused:
            print(f"ci_watch: skipped a line: {refused}", file=log)
            continue
        if entry is None:
            continue
        try:
            try:
                report = check(entry, gh, repo)
            except NotFound:
                report = f"CI watch: #{entry.pr} on {entry.sha}: no such pull request; not watched."
            if report is None:
                continue
            say(entry.author, report)
        except Transient as trouble:
            print(f"ci_watch: #{entry.pr}: {trouble}; tried again next pass", file=log)
            continue
        _drop(queue, entry)
        print(report, file=log)
        done += 1
    return done


def _member(address: object) -> str:
    return str(address or "").split("#", 1)[0]


def _clean(text: str) -> str:
    """Another program's output for one log line: control characters shown as `?`."""
    return "".join(c if c.isprintable() else "?" for c in text.strip()[:200])


def admit(pr: int, sha: str, gh: Gh, repo: str = REPO) -> str | None:
    """Why the head may not be watched, or None when it may."""
    try:
        data = gh(f"repos/{repo}/pulls/{pr}")
    except NotFound:
        return "no such pull request"
    assert isinstance(data, dict)
    if data.get("merged"):
        return "the pull request is merged"
    if data.get("state") != "open":
        return "the pull request is closed"
    head = data["head"]["sha"]
    if head != sha:
        return f"its head is {head}"
    return None


Page = tuple[list[dict[str, object]], str | None]
# (after, cursor) -> (items, next cursor): after a seq, oldest first; None for newest first.
Messages = Callable[[int | None, str | None], Page]


def _intake_file(queue: Path) -> Path:
    return queue.with_name(queue.name + ".intake")


def _load(queue: Path) -> dict[str, Any] | None:
    """The saved intake state; None before the first start. While the first start is still
    looking for the newest message, `after` is None and `starting` holds its continuation."""
    try:
        state = json.loads(_intake_file(queue).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except OSError as bad:
        raise Transient(f"{_intake_file(queue)}: cannot be read ({bad.strerror})") from bad
    except ValueError as bad:
        raise Transient(f"{_intake_file(queue)}: not JSON; fix or remove it") from bad
    if not isinstance(state, dict):
        raise Transient(f"{_intake_file(queue)}: not an object; fix or remove it")
    starting = state.get("after") is None and isinstance(state.get("starting"), str)
    if not starting and not isinstance(state.get("after"), int):
        raise Transient(f"{_intake_file(queue)}: no `after`; fix or remove it")
    state.setdefault("pass", 0)
    state.setdefault("resume", None)
    state.setdefault("tries", {})
    state.setdefault("outbox", [])
    return state


def _save(queue: Path, state: dict[str, Any]) -> None:
    path = _intake_file(queue)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _seq(item: dict[str, object]) -> int:
    seq = item.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise Transient("maity messages: a message without a seq")
    return seq


def _newest(messages: Messages, cursor: str | None) -> int | str:
    """The newest message's seq (0 for none), following continuations past empty pages from
    `cursor`; or, when the read budget runs out first, the continuation to go on from."""
    for _ in range(PAGES_PER_PASS):
        items, following = messages(None, cursor)
        if items:
            return max(_seq(item) for item in items)
        if not following:
            return 0
        cursor = following
    assert cursor is not None
    return cursor


def _send(
    queue: Path, state: dict[str, Any], answer: dict[str, Any], say: Say, log: TextIO
) -> None:
    """Says an answer from the outbox; it leaves the outbox once said or given up."""
    try:
        say(answer["to"], answer["text"])
    except Transient as trouble:
        answer["failed"] = state["pass"]
        answer["tries"] = answer.get("tries", 0) + 1
        if answer["tries"] >= TRIES:
            state["outbox"].remove(answer)
            print(f"ci_watch: intake: gave up answering {answer['to']}: {trouble}", file=log)
        else:
            print(f"ci_watch: intake: {trouble}; answer tried again", file=log)
    else:
        state["outbox"].remove(answer)
    _save(queue, state)


def _decide(
    item: dict[str, object],
    match: re.Match[str],
    seq: int,
    state: dict[str, Any],
    queue: Path,
    gh: Gh,
    repo: str,
) -> tuple[str, str, Entry | None] | None:
    """(to, answer, entry to add) for one request, or None when the sender is no member id to
    answer; a GitHub failure raises Transient until it has failed TRIES passes in a row, then
    the request is answered and passed over."""
    sender = str(item.get("from") or "")
    if not _MEMBER.match(sender):
        return None
    instance = item.get("from_instance")
    author = f"{sender}#{instance}"
    pr, sha = int(match[1]), match[2]
    tag = f" (request {seq})"
    if not instance:
        return sender, f"ciwatch: #{pr} not added: the message has no sender instance.{tag}", None
    if not _AUTHOR.match(author):
        return sender, f"ciwatch: #{pr} not added: the sender instance is not valid.{tag}", None
    try:
        why = admit(pr, sha, gh, repo)
    except Transient:
        tries = state["tries"][str(seq)] = state["tries"].get(str(seq), 0) + 1
        if tries < TRIES:
            _save(queue, state)
            raise
        why = f"GitHub did not answer {tries} times; send it again"
    if why is None:
        text = f"ciwatch: #{pr} {sha} added; the result comes when CI is done.{tag}"
        return author, text, Entry(pr, sha, author)
    return author, f"ciwatch: #{pr} {sha} not added: {why}.{tag}", None


def intake_pass(
    queue: Path,
    inbox: str,
    messages: Messages,
    gh: Gh,
    say: Say,
    repo: str = REPO,
    log: TextIO = sys.stderr,
) -> int:
    """Takes `ciwatch <pr> <sha>` messages to `inbox` into the queue; returns how many.

    Each request is decided once: the queue line, the answer (in the outbox) and the seq read
    are saved before the answer is said, so a failed or lost `say` never decides it again. An
    answer whose `say` failed is said again only after a later pass has read the messages to
    the end without finding it, since a `say` whose response was lost did post it."""
    state = _load(queue)
    if state is None or state["after"] is None:
        found = _newest(messages, state["starting"] if state else None)
        if isinstance(found, str):
            # Only empty pages so far: the next pass goes on from here, never from the top.
            _save(queue, {"after": None, "starting": found})
            print("ci_watch: intake still looking for the newest message", file=log)
            return 0
        _save(queue, {"after": found, "pass": 0, "resume": None, "tries": {}, "outbox": []})
        print(f"ci_watch: intake starts after message {found}", file=log)
        return 0
    state["pass"] += 1
    for answer in state["outbox"]:
        if answer.get("failed") is None:  # decided by an earlier pass that stopped before say
            answer["failed"] = state["pass"] - 1
    _save(queue, state)
    if state["resume"]:
        start, cursor = state["resume"]
    else:
        start, cursor = state["after"], None
    taken = answered = 0
    stopped = at_end = False
    for _ in range(PAGES_PER_PASS):
        items, following = messages(start, cursor)
        for item in items:
            seq = _seq(item)
            if seq <= state["after"]:
                continue
            body = str(item.get("body") or "").strip()
            sender = str(item.get("from") or "")
            if sender == inbox:
                # Our own message: an answer whose `say` failed may have been posted after all.
                for answer in state["outbox"]:
                    if answer["text"] == body and _member(item.get("to")) == _member(answer["to"]):
                        state["outbox"].remove(answer)
                        break
            elif _member(item.get("to")) == inbox and (match := _INTAKE.match(body)):
                if answered >= INTAKE_PER_PASS:
                    stopped = True
                    break
                decided = _decide(item, match, seq, state, queue, gh, repo)
                if decided is None:
                    print(f"ci_watch: intake: message {seq} has no sender to answer", file=log)
                    state["after"] = seq
                    _save(queue, state)
                    continue
                to, text, entry = decided
                if entry is not None:
                    add(queue, entry)
                    print(f"ci_watch: added #{entry.pr} {entry.sha} for {entry.author}", file=log)
                    taken += 1
                answer = {"seq": seq, "to": to, "text": text, "failed": None}
                state["outbox"].append(answer)
                state["tries"].pop(str(seq), None)
                state["after"] = seq
                _save(queue, state)
                _send(queue, state, answer, say, log)
                answered += 1
                continue
            state["after"] = seq
            _save(queue, state)
        if stopped or not following:
            at_end = not stopped
            break
        cursor = following
    state["resume"] = None if stopped or at_end else [start, cursor]
    _save(queue, state)
    if at_end:
        for answer in [a for a in state["outbox"] if a["failed"] < state["pass"]]:
            if answered >= INTAKE_PER_PASS:
                break
            _send(queue, state, answer, say, log)
            answered += 1
    return taken


def maity_messages(after: int | None, cursor: str | None) -> Page:
    """One page of `maity messages --json`: after a seq, oldest first; or newest first."""
    argv = ["maity", "messages", "--json"]
    argv += ["--limit", "1"] if after is None else ["--after", str(after), "--limit", "200"]
    if cursor:
        argv += ["--cursor", cursor]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Transient(f"maity messages: {_clean(done.stderr)}")
    try:
        data = json.loads(done.stdout)
    except ValueError as bad:
        raise Transient("maity messages: not JSON") from bad
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise Transient("maity messages: no items")
    following = data.get("next_cursor")
    return data["items"], str(following) if following else None


def gh_get(path: str) -> object:
    """`gh api <path>`: a GET, never anything that writes."""
    done = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        if "HTTP 404" in done.stderr:
            raise NotFound(path)
        raise Transient(f"gh api {path.split('?')[0]}: {_clean(done.stderr)}")
    try:
        return json.loads(done.stdout)
    except ValueError as bad:
        raise Transient(f"gh api {path.split('?')[0]}: not JSON") from bad


def maity_say(author: str, text: str) -> None:
    done = subprocess.run(
        ["maity", "say", "--type", "notice", author, "-"],
        input=text,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise Transient(f"maity say: {_clean(done.stderr)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_add = sub.add_parser("add", help="watch a pull request's head")
    p_add.add_argument("queue", type=Path)
    p_add.add_argument("pr")
    p_add.add_argument("sha")
    p_add.add_argument("author")
    p_remove = sub.add_parser("remove", help="stop watching a pull request")
    p_remove.add_argument("queue", type=Path)
    p_remove.add_argument("pr")
    p_run = sub.add_parser("run", help="watch the queue and report results")
    p_run.add_argument("queue", type=Path)
    p_run.add_argument("--once", action="store_true", help="one pass, then exit")
    p_run.add_argument("--interval", type=int, default=120, help="seconds between passes")
    p_run.add_argument("--repo", default=REPO)
    p_run.add_argument(
        "--inbox", help="member id whose `ciwatch <pr> <sha>` messages are taken into the queue"
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            add(args.queue, parse_entry(args.pr, args.sha, args.author))
            return 0
        if args.command == "remove":
            if not _PR.match(args.pr):
                raise Refused(f"pull request {args.pr!r}: not a number")
            if not remove(args.queue, int(args.pr)):
                print(f"ci_watch: #{args.pr} is not in the queue", file=sys.stderr)
            return 0
        if not os.environ.get("MAITY_STATE_DIR"):
            raise Refused("run: set MAITY_STATE_DIR to the identity the reports go out under")
        if args.inbox is not None and not _MEMBER.match(args.inbox):
            raise Refused("--inbox: give a member id, without `#instance`")
        while True:
            if args.inbox:
                try:
                    intake_pass(
                        args.queue, args.inbox, maity_messages, gh_get, maity_say, args.repo
                    )
                except (Transient, OSError) as trouble:
                    # Never stops the queue pass below: results still go out.
                    print(f"ci_watch: intake: {trouble}; tried again next pass", file=sys.stderr)
            run_pass(args.queue, gh_get, maity_say, args.repo)
            if args.once:
                return 0
            time.sleep(args.interval)
    except Refused as refused:
        print(f"ci_watch: {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
