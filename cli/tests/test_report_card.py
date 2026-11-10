"""`maity report` says what it reports and refuses a pull request that is not the card's (§6.6)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import fake_gh, git

from maity import cli

TASK = "/api/v1/projects/oliver/maity/tasks/tsk-0004"
REPO = "https://github.com/acme/widget"


def _gh(
    bin_dir: Path,
    head: str,
    number: int = 12,
    state: str = "OPEN",
    title: str = "Leases (tsk-0004)",
) -> None:
    row = {"number": number, "headRefOid": head, "state": state, "url": f"{REPO}/pull/{number}",
           "title": title}  # fmt: skip
    fake_gh(bin_dir, json.dumps([row]))


def _card(fake: fakehub.FakeHub, **fields: Any) -> None:
    card = {"id": "tsk-0004", "links": [], "report": None, **fields}
    fake.routes[("GET", TASK)] = lambda seen: (200, card)
    fake.routes[("POST", f"{TASK}/report")] = lambda seen: (
        200,
        {"id": "tsk-0004", "status": "review"},
    )


def _report() -> int:
    return cli.main(["report", "--task", "tsk-0004", "--summary", "Adds leases."])


def _sent(fake: fakehub.FakeHub) -> bool:
    return any(r.path == f"{TASK}/report" for r in fake.signed())


def _head(joined: Path) -> str:
    return git(joined.parent.parent, "rev-parse", "HEAD")


def _link(number: int, repo: str = REPO) -> dict[str, Any]:
    return {
        "id": f"lnk-{number}",
        "kind": "pr",
        "forge_url": f"{repo}/pull/{number}",
        "number": number,
    }


def test_the_report_says_what_it_reports_before_sending(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(joined)
    _gh(bin_dir, head)
    _card(fake)
    assert _report() == cli.EXIT_OK
    err = capsys.readouterr().err
    assert f'maity: reporting work at {head[:12]}, PR #12 "Leases (tsk-0004)" (open)\n' in err
    assert _sent(fake)


def test_a_pull_request_the_card_does_not_link_is_refused(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The case it is for: the card's PR #780 merged, the report sent from #799's branch."""
    _gh(bin_dir, _head(joined), number=799)
    _card(fake, links=[_link(780)])
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "tsk-0004 links pull request #780, this checkout has PR #799" in err
    assert "`git switch <branch>`" in err
    assert not _sent(fake)


@pytest.mark.parametrize(
    "links",
    [
        [_link(780), _link(12)],  # one of the linked pull requests
        [_link(780, "https://github.com/acme/other")],  # another repository of the owner
        [{"id": "lnk-1", "kind": "url", "url": f"{REPO}/pull/780"}],  # a plain URL link
    ],
)
def test_a_linked_or_unrelated_link_lets_the_report_through(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, links: list[dict[str, Any]]
) -> None:
    _gh(bin_dir, _head(joined))
    _card(fake, links=links)
    assert _report() == cli.EXIT_OK
    assert _sent(fake)


def test_a_branch_without_a_pull_request_on_a_linked_card_is_refused(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(bin_dir, "[]")
    _card(fake, links=[_link(780)])
    assert _report() == cli.EXIT_REFUSED
    assert "this checkout has no pull request" in capsys.readouterr().err


def test_a_checkout_whose_pull_request_is_unknown_is_refused_on_a_linked_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without gh the CLI cannot show that the report is the card's pull request."""
    _card(fake, links=[_link(780)])
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "this checkout has an unknown pull request (gh is not installed)" in err
    assert not _sent(fake)


def _before(
    number: int, state: str, observed: str | None = None, repo: str = REPO
) -> dict[str, Any]:
    return {
        "pr": {"number": number, "url": f"{repo}/pull/{number}", "state": state},
        "observed": {"pr_state": observed} if observed else None,
    }


def test_another_pull_request_than_the_open_one_reported_before_is_refused(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh(bin_dir, _head(joined), number=799)
    _card(fake, report=_before(780, "open"))
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "the last report on tsk-0004 names pull request #780, still open" in err
    assert not _sent(fake)


@pytest.mark.parametrize(
    "before",
    [
        _before(780, "open", observed="merged"),  # the probe saw it merged: a follow-up PR is fine
        _before(780, "closed"),
        _before(12, "open"),  # the same pull request again
        _before(780, "open", repo="https://github.com/acme/other"),  # another repository
    ],
)
def test_a_report_after_a_merged_closed_or_the_same_pull_request_goes_through(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, before: dict[str, Any]
) -> None:
    _gh(bin_dir, _head(joined))
    _card(fake, report=before)
    assert _report() == cli.EXIT_OK
    assert _sent(fake)


def _gh_view(bin_dir: Path, head: str, state: str | None) -> None:
    """A gh that lists this checkout's PR #799; `pr view` answers `state`, or fails on None."""
    if sys.platform == "win32":
        pytest.skip("Windows starts only an .exe by a bare name, and this gh is a shell script")
    row = {"number": 799, "headRefOid": head, "state": "OPEN", "url": f"{REPO}/pull/799",
           "title": "Follow-up (tsk-0004)"}  # fmt: skip
    view = f"printf '%s\\n' '{json.dumps({'state': state})}'" if state else "exit 1"
    script = bin_dir / "gh"
    script.write_text(
        f'#!/bin/sh\nif [ "$2" = view ]; then {view}; exit 0; fi\n'
        f"printf '%s\\n' '{json.dumps([row])}'\n"
    )
    script.chmod(0o755)


@pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
def test_a_pull_request_the_hub_still_shows_open_but_the_forge_does_not_is_no_refusal(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, state: str
) -> None:
    _gh_view(bin_dir, _head(joined), state)
    _card(fake, report=_before(780, "open", observed="open"))
    assert _report() == cli.EXIT_OK
    assert _sent(fake)


def test_a_pull_request_the_forge_confirms_open_is_refused(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh_view(bin_dir, _head(joined), "OPEN")
    _card(fake, report=_before(780, "open", observed="open"))
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "#780, still open; this checkout" in err
    assert not _sent(fake)


def test_a_forge_that_can_not_be_asked_keeps_the_refusal_and_says_so(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh_view(bin_dir, _head(joined), None)
    _card(fake, report=_before(780, "open", observed="open"))
    assert _report() == cli.EXIT_REFUSED
    assert "gh could not check it" in capsys.readouterr().err
    assert not _sent(fake)


def test_a_url_naming_another_number_is_not_asked_about_the_reported_one(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh_view(bin_dir, _head(joined), "MERGED")  # what #781 would say, of no use for #780
    before = _before(780, "open", observed="open")
    before["pr"]["url"] = f"{REPO}/pull/781"
    _card(fake, report=before)
    assert _report() == cli.EXIT_REFUSED
    assert "#780, still open (the hub's last observation" in capsys.readouterr().err
    assert not _sent(fake)


def test_no_code_reads_no_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _card(fake, links=[_link(780)])
    assert cli.main(["report", "--task", "tsk-0004", "--summary", "x", "--no-code"]) == 0
    assert not any(r.method == "GET" and r.path == TASK for r in fake.signed())
    assert "reporting" not in capsys.readouterr().err


# Without a working gh (a cloud session: gh missing, or its GraphQL refused), the card's
# linked pull request is read through the hub's probe (§11) and reported only when its head
# is the head git pushed (tsk-grk7tg5temyc).
PROBE = "/api/v1/projects/oliver/maity/probe"


def _probe(fake: fakehub.FakeHub, heads: dict[int, str], state: str = "open") -> list[str]:
    """The probe's answer for each linked pull request; returns the queries it was asked."""
    asked: list[str] = []

    def answer(seen: fakehub.Seen) -> tuple[Any, ...]:
        asked.append(seen.query)
        number = int(dict(p.split("=", 1) for p in seen.query.split("&"))["pr"])
        if number not in heads:
            return 200, {"repository": "acme/widget", "pr": {"number": number, "found": False}}
        pr = {"number": number, "found": True, "url": f"{REPO}/pull/{number}",
              "title": "Leases (tsk-0004)", "state": state, "head_sha": heads[number]}  # fmt: skip
        return 200, {"forge": "github", "repository": "acme/widget", "fresh": True, "pr": pr}

    fake.routes[("GET", PROBE)] = answer
    return asked


def _report_body(fake: fakehub.FakeHub) -> dict[str, Any]:
    return next(r.json() for r in fake.signed() if r.path == f"{TASK}/report")


def test_without_gh_the_linked_pull_request_with_the_pushed_head_is_reported(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(joined)
    asked = _probe(fake, {12: head})
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_OK
    body = _report_body(fake)
    assert body["pr_status"] == "found" and body["pr_unknown_reason"] is None
    assert body["pr"] == {"number": 12, "url": f"{REPO}/pull/12", "head": head, "state": "open"}
    assert [dict(p.split("=", 1) for p in q.split("&")) for q in asked] == [
        {"pr": "12", "max_age": "0"}  # a forced read (the hub's floor may still be 30 s)
    ]
    assert 'PR #12 "Leases (tsk-0004)" (open, read by the hub\'s probe)' in capsys.readouterr().err


def test_without_gh_a_linked_pull_request_with_another_head_is_refused(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _probe(fake, {12: "f" * 40})
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert f"PR #12 (open) has head {'f' * 40}" in err and _head(joined) in err
    assert not _sent(fake)


def test_a_failing_gh_falls_back_to_the_probe_for_a_linked_pull_request(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path
) -> None:
    """gh installed, but its GraphQL refused, as in a Claude Code cloud session."""
    fake_gh(bin_dir, "", exit_code=1, stderr="HTTP 403: GitHub GraphQL is not available")
    head = _head(joined)
    _probe(fake, {780: "e" * 40, 12: head})
    _card(fake, links=[_link(780), _link(12)])
    assert _report() == cli.EXIT_OK
    assert _report_body(fake)["pr"]["number"] == 12


def test_without_a_probe_the_unknown_pull_request_is_still_refused(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", PROBE)] = lambda seen: (
        409,
        {"error": {"code": "probe_not_configured", "message": "no grant", "details": {}}},
    )
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "this checkout has an unknown pull request (gh is not installed)" in err
    assert not _sent(fake)


def test_a_failing_gh_without_a_linked_pull_request_stays_an_error(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """66da7721: a forge tool that fails is never reported as "no pull request"."""
    fake_gh(bin_dir, "", exit_code=1, stderr="HTTP 403: GitHub GraphQL is not available")
    _card(fake)
    assert _report() == cli.EXIT_ERROR
    assert "gh could not list pull requests" in capsys.readouterr().err
    assert not _sent(fake)


# The branch deleted after its merge, gh missing (f720dd3c without gh): the card's linked pull
# request, merged with this very head, stands in for the branch.
def _delete_branch(joined: Path) -> None:
    git(joined.parent.parent, "push", "--quiet", "origin", "--delete", "work")


def test_without_gh_a_deleted_branch_reports_the_merged_head_of_the_linked_pull_request(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(joined)
    _delete_branch(joined)
    _probe(fake, {12: head}, state="merged")
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_OK
    body = _report_body(fake)
    assert body["remote_head"] == head and body["head"] == head
    assert body["pr_status"] == "found" and body["pr"]["state"] == "merged"
    assert (
        'PR #12 "Leases (tsk-0004)" (merged, read by the hub\'s probe)' in capsys.readouterr().err
    )


@pytest.mark.parametrize(
    ("state", "same_head"), [("merged", False), ("open", True), ("closed", True)]
)
def test_without_gh_a_deleted_branch_without_a_matching_merge_is_refused(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    state: str,
    same_head: bool,
) -> None:
    head = _head(joined)
    _delete_branch(joined)
    _probe(fake, {12: head if same_head else "a" * 40}, state=state)
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "is gone on the remote and the hub's probe reads PR #12" in err and head in err
    assert not _sent(fake)


def test_without_gh_a_deleted_branch_on_a_card_without_a_linked_pull_request_is_refused(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _delete_branch(joined)
    asked = _probe(fake, {})
    _card(fake)
    assert _report() == cli.EXIT_REFUSED
    assert "does not exist on" in capsys.readouterr().err
    assert asked == [] and not _sent(fake)


def test_links_past_the_cap_are_named_not_read(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(joined)
    numbers = list(range(1, cli.PROBED_LINKS_MAX + 2))
    asked = _probe(fake, {numbers[0]: head})
    _card(fake, links=[_link(n) for n in numbers])
    assert _report() == cli.EXIT_OK
    assert len(asked) == 1  # the first matched; past the cap nothing would be read
    err = capsys.readouterr().err
    assert f"the card links {len(numbers)} pull requests" in err
    assert f"first {cli.PROBED_LINKS_MAX} only" in err


# The pull request found does not name the card (tsk-41hjdphkcw4e): shown with its title, then
# asked on a terminal, refused without one, or confirmed with --yes.
class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _terminal(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    monkeypatch.setattr("sys.stdin", _Terminal(answer + "\n"))
    monkeypatch.setattr("sys.stderr.isatty", lambda: True, raising=False)


def _report_yes() -> int:
    return cli.main(["report", "--task", "tsk-0004", "--summary", "Adds leases.", "--yes"])


def test_a_pull_request_naming_the_card_in_its_branch_is_sent_without_asking(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clone = joined.parent.parent
    git(clone, "checkout", "--quiet", "-b", "agent-b/tsk-0004-leases")
    git(clone, "push", "--quiet", "-u", "origin", "agent-b/tsk-0004-leases")
    _gh(bin_dir, _head(joined), title="Leases")
    _card(fake)
    assert _report() == cli.EXIT_OK and _sent(fake)
    assert "[y/N]" not in capsys.readouterr().err


def test_a_pull_request_that_does_not_name_the_card_is_refused_without_a_terminal(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh(bin_dir, _head(joined), number=31, title="Unrelated cleanup")
    _card(fake)
    assert _report() == cli.EXIT_REFUSED and not _sent(fake)
    err = capsys.readouterr().err
    assert 'PR #31 "Unrelated cleanup" (open)' in err  # shown before anything is decided
    assert "does not name tsk-0004" in err and "--yes" in err


@pytest.mark.parametrize(("answer", "sent"), [("y", True), ("n", False), ("", False)])
def test_on_a_terminal_a_pull_request_that_does_not_name_the_card_is_asked_about(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], answer: str, sent: bool,
) -> None:  # fmt: skip
    _gh(bin_dir, _head(joined), number=31, title="Unrelated cleanup")
    _card(fake)
    _terminal(monkeypatch, answer)
    assert _report() == (cli.EXIT_OK if sent else cli.EXIT_REFUSED)
    assert _sent(fake) is sent
    assert "Report tsk-0004 with it? [y/N]" in capsys.readouterr().err


def test_yes_confirms_a_pull_request_that_does_not_name_the_card(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path
) -> None:
    _gh(bin_dir, _head(joined), number=31, title="Unrelated cleanup")
    _card(fake)
    assert _report_yes() == cli.EXIT_OK and _sent(fake)


def test_yes_never_overrides_a_card_that_links_another_pull_request(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh(bin_dir, _head(joined), number=799, title="Unrelated cleanup")
    _card(fake, links=[_link(780)])
    assert _report_yes() == cli.EXIT_REFUSED and not _sent(fake)
    assert "tsk-0004 links pull request #780" in capsys.readouterr().err


def test_a_pull_request_the_card_links_is_not_asked_about_whatever_its_title(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path
) -> None:
    _gh(bin_dir, _head(joined), number=12, title="Unrelated cleanup")
    _card(fake, links=[_link(12)])
    assert _report() == cli.EXIT_OK and _sent(fake)


def test_a_branch_without_a_pull_request_is_not_asked_about(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_gh(bin_dir, "[]")
    _card(fake)
    assert _report() == cli.EXIT_OK and _sent(fake)
    err = capsys.readouterr().err
    assert "no pull request" in err and "[y/N]" not in err


def test_the_title_reaches_the_terminal_disarmed(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh(bin_dir, _head(joined), title="Leases tsk-0004 \x1b[2J\x07")
    _card(fake)
    assert _report() == cli.EXIT_OK
    line = next(ln for ln in capsys.readouterr().err.splitlines() if "reporting" in ln)
    assert "Leases tsk-0004" in line and "\x1b" not in line and "\x07" not in line


def test_yes_never_overrides_an_open_pull_request_of_the_last_report(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The second case of 8c58cebb: the last report names another pull request, still open."""
    _gh_view(bin_dir, _head(joined), "OPEN")
    _card(fake, report=_before(780, "open", observed="open"))
    assert _report_yes() == cli.EXIT_REFUSED and not _sent(fake)
    assert "#780, still open; this checkout" in capsys.readouterr().err


def test_a_link_past_the_cap_is_not_probed_even_where_it_would_match(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only the sixth link has the pushed head: it is never asked about, so the report is
    refused as unknown on the linked card, never filed with that pull request."""
    head = _head(joined)
    numbers = list(range(1, cli.PROBED_LINKS_MAX + 2))
    asked = _probe(fake, {numbers[-1]: head})
    _card(fake, links=[_link(n) for n in numbers])
    assert _report() == cli.EXIT_REFUSED
    probed = [dict(p.split("=", 1) for p in q.split("&"))["pr"] for q in asked]
    assert probed == [str(n) for n in numbers[: cli.PROBED_LINKS_MAX]]
    assert str(numbers[-1]) not in probed and not _sent(fake)
    assert "this checkout has an unknown pull request" in capsys.readouterr().err


# --- a branch cut from main tracks main (tsk-8qwmbw5xydpw) -----------------------------------


def _track_main(work: Path, pushed: bool) -> None:
    git(work, "push", "--quiet", "origin", "work:main")
    git(work, "fetch", "--quiet", "origin")
    git(work, "remote", "set-head", "origin", "main")
    (work / "a.txt").write_text("two\n")
    git(work, "commit", "--quiet", "-am", "two")
    if pushed:
        git(work, "push", "--quiet", "origin", "work")
    else:
        git(work, "push", "--quiet", "origin", "--delete", "work")
    git(work, "config", "branch.work.merge", "refs/heads/main")


def test_report_sets_a_branch_tracking_main_to_its_own_and_reports(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    work = joined.parent.parent
    _track_main(work, pushed=True)
    _card(fake)
    assert _report() == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "maity: branch work tracked origin/main, the default branch; set" in err
    assert git(work, "config", "branch.work.merge") == "refs/heads/work"
    body = next(r.json() for r in fake.signed() if r.path == f"{TASK}/report")
    assert body["upstream"] == "origin/work" and body["remote_head"] == _head(joined)


def test_report_refuses_a_branch_tracking_main_before_it_is_pushed(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    work = joined.parent.parent
    _track_main(work, pushed=False)
    _card(fake)
    assert _report() == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "push it with `git push -u origin work`" in err
    assert git(work, "config", "branch.work.merge") == "refs/heads/main"
    assert not fake.signed()
