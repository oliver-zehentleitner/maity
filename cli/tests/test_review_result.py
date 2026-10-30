"""`maity say --type review_result --review-file` (docs/api.md §8.4 "A review result cites
what it judged", §13)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import fakehub
import pytest

from maity import cli

P = "/api/v1/projects/oliver/maity"
REVIEW = {
    "subject": "#743",
    "head": "7039a4b6fd8b988d71a63338711da188fcd95fba",
    "verdict": "approve",
    "cites": [{"path": "docs/api.md", "line": 11929, "quote": 'a "quote" with `ticks` and $(x)'}],
}


@pytest.fixture
def events(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})


def _say(*extra: str) -> list[str]:
    return ["say", "agt-a", "--type", "review_result", *extra]


def test_the_review_is_sent_as_given_from_a_file(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    (tmp_path / "review.json").write_text(json.dumps(REVIEW))
    argv = _say("Approve, see the cites.", "--review-file", str(tmp_path / "review.json"))
    assert cli.main(argv) == cli.EXIT_OK
    sent = fake.signed()[-1].json()
    assert sent["review"] == REVIEW
    assert (sent["type"], sent["body"]) == ("review_result", "Approve, see the cites.")


def test_the_review_from_stdin_with_the_message_from_a_file(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "m.md").write_text("Approve.")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REVIEW)))
    argv = _say("--body-file", str(tmp_path / "m.md"), "--review-file", "-")
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json()["review"] == REVIEW


def test_message_and_review_both_from_stdin_is_a_usage_error(
    joined: Path,
    fake: fakehub.FakeHub,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("Approve."))
    assert cli.main(_say("-", "--review-file", "-")) == cli.EXIT_USAGE
    assert "cannot both come from stdin" in capsys.readouterr().err
    assert not fake.signed()


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (_say("Approve."), "needs --review-file"),
        (
            ["say", "agt-a", "--type", "notice", "Hi", "--review-file", "r.json"],
            "review_result only",
        ),
        (["say", "--chat", "cnv-1", "Hi", "--review-file", "r.json"], "review_result only"),
    ],
)
def test_the_review_file_goes_with_review_result_and_only_there(
    joined: Path,
    fake: fakehub.FakeHub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    says: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "r.json").write_text(json.dumps(REVIEW))
    assert cli.main(argv) == cli.EXIT_USAGE
    assert says in capsys.readouterr().err
    assert not fake.signed()


def test_a_review_file_that_is_not_json_sends_nothing(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "r.json").write_text("{not json")
    assert cli.main(_say("Approve.", "--review-file", str(tmp_path / "r.json"))) == cli.EXIT_USAGE
    assert "--review-file: not JSON" in capsys.readouterr().err
    assert not fake.signed()


def test_the_hubs_indexed_paths_are_shown(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fields = {"review.cites.2.line": "format", "review.cites": "too_many"}
    fake.routes[("POST", f"{P}/events")] = lambda s: (
        400,
        {"error": {"code": "invalid", "message": "bad review", "details": {"fields": fields}}},
    )
    (tmp_path / "r.json").write_text(json.dumps(REVIEW))
    assert cli.main(_say("Approve.", "--review-file", str(tmp_path / "r.json"))) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "review.cites.2.line: format" in err and "review.cites: too_many" in err
