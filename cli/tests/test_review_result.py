"""`maity say --type review_result --review-file` (docs/api.md §8.4 "A review result cites
what it judged", §13)."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import fakehub
import pytest

from maity import cli, state

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


def _review_at(tmp_path: Path, *cites: dict[str, object]) -> str:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    review = {"subject": "#1", "head": head, "verdict": "approve", "cites": list(cites)}
    (tmp_path / "review.json").write_text(json.dumps(review))
    return str(tmp_path / "review.json")


def _commit(name: str, text: str | None) -> None:
    if text is None:
        Path(name).unlink()
    else:
        Path(name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", name],
        check=True,
    )


def test_cites_that_stand_at_the_head_are_sent(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    _commit("b.txt", "first line\n  second ünï line\n")
    path = _review_at(
        tmp_path,
        {"path": "b.txt", "line": 2, "quote": "second ünï"},
        {"path": "b.txt", "quote": "first line"},
    )
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_OK
    assert fake.signed()[-1].json()["review"]["cites"][0]["quote"] == "second ünï"


@pytest.mark.parametrize(
    ("cite", "named"),
    [
        ({"path": "b.txt", "line": 1, "quote": "second"}, "it stands on line 2"),
        ({"path": "b.txt", "line": 99, "quote": "second"}, "it stands on line 2"),
        ({"path": "b.txt", "line": 1, "quote": "invented"}, "not in the file"),
        ({"path": "none.txt", "line": 1, "quote": "second"}, "not at this commit"),
        ({"path": "b.txt", "quote": "invented"}, "neither in the file nor removed"),
    ],
)
def test_a_cite_that_does_not_stand_refuses_the_send(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    cite: dict[str, object],
    named: str,
) -> None:
    _commit("b.txt", "first\nsecond\n")
    good = {"path": "b.txt", "line": 1, "quote": "first"}
    path = _review_at(tmp_path, good, cite)
    before = len(fake.signed())
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "not sent: 1 cite(s)" in err
    assert "review.cites.1 " in err
    assert named in err
    assert [r for r in fake.signed()[before:] if r.path.endswith("/events")] == []


@pytest.mark.parametrize("deleted", [False, True])
def test_a_cite_without_a_line_may_quote_what_was_removed(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path, deleted: bool
) -> None:
    _commit("b.txt", "old text\nkept\n")
    _commit("b.txt", None if deleted else "kept\n")
    path = _review_at(tmp_path, {"path": "b.txt", "quote": "old text"})
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_OK


def test_a_removed_quote_with_a_line_is_refused(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    _commit("b.txt", "old text\nkept\n")
    _commit("b.txt", "kept\n")
    path = _review_at(tmp_path, {"path": "b.txt", "line": 1, "quote": "old text"})
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_ERROR


def test_a_commit_not_in_the_clone_is_said_and_sent(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "review.json").write_text(json.dumps(REVIEW))
    assert cli.main(_say("Approve.", "--review-file", str(tmp_path / "review.json"))) == cli.EXIT_OK
    assert f"cites not checked: commit {REVIEW['head']} is not in this clone" in (
        capsys.readouterr().err
    )
    assert fake.signed()[-1].json()["review"] == REVIEW


def test_no_clone_is_said_and_sent(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "review.json").write_text(json.dumps(REVIEW))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    state_dir = state.resolve_state_dir()
    monkeypatch.setenv("MAITY_STATE_DIR", str(state_dir))
    monkeypatch.chdir(elsewhere)
    assert cli.main(_say("Approve.", "--review-file", str(tmp_path / "review.json"))) == cli.EXIT_OK
    assert "cites not checked: this directory is not a clone" in capsys.readouterr().err


def test_a_malformed_review_is_left_to_the_hub(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    (tmp_path / "review.json").write_text(json.dumps({"head": "short", "cites": "x"}))
    assert cli.main(_say("Approve.", "--review-file", str(tmp_path / "review.json"))) == cli.EXIT_OK
    assert fake.signed()[-1].json()["review"] == {"head": "short", "cites": "x"}


def test_a_removed_quote_is_found_from_a_subdirectory(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commit("b.txt", "old text\nkept\n")
    _commit("b.txt", "kept\n")
    path = _review_at(tmp_path, {"path": "b.txt", "quote": "old text"})
    state_dir = state.resolve_state_dir()
    monkeypatch.setenv("MAITY_STATE_DIR", str(state_dir))
    Path("sub").mkdir()
    monkeypatch.chdir("sub")
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_OK


@pytest.mark.parametrize("line", [1, None])
def test_a_quote_with_a_line_break_is_left_to_the_hub(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path, line: int | None
) -> None:
    _commit("b.txt", "first\nsecond\n")
    path = _review_at(tmp_path, {"path": "b.txt", "line": line, "quote": "first\nsecond"})
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_OK
    assert fake.signed()[-1].json()["review"]["cites"][0]["quote"] == "first\nsecond"
