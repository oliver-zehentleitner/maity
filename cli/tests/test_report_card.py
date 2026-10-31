"""`maity report` says what it reports and refuses a pull request that is not the card's (§6.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest
from conftest import fake_gh, git

from maity import cli

TASK = "/api/v1/projects/oliver/maity/tasks/tsk-0004"
REPO = "https://github.com/acme/widget"


def _gh(bin_dir: Path, head: str, number: int = 12, state: str = "OPEN") -> None:
    row = {"number": number, "headRefOid": head, "state": state, "url": f"{REPO}/pull/{number}"}
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
    assert f"maity: reporting work at {head[:12]}, PR #12 (open)\n" in err
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


def _before(number: int, state: str, observed: str | None = None) -> dict[str, Any]:
    return {
        "pr": {"number": number, "url": f"{REPO}/pull/{number}", "state": state},
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
    ],
)
def test_a_report_after_a_merged_closed_or_the_same_pull_request_goes_through(
    joined: Path, fake: fakehub.FakeHub, bin_dir: Path, before: dict[str, Any]
) -> None:
    _gh(bin_dir, _head(joined))
    _card(fake, report=before)
    assert _report() == cli.EXIT_OK
    assert _sent(fake)


def test_no_code_reads_no_card(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _card(fake, links=[_link(780)])
    assert cli.main(["report", "--task", "tsk-0004", "--summary", "x", "--no-code"]) == 0
    assert not any(r.method == "GET" and r.path == TASK for r in fake.signed())
    assert "reporting" not in capsys.readouterr().err
