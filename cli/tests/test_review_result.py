"""`maity say --type review_result --review-file` (docs/api.md §8.4 "A review result cites
what it judged", §13)."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import fakehub
import pytest
from conftest import posix

from maity import citecheck, cli, clonecheck, proc, state

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


def _say(*extra: str, to: str = "agt-a") -> list[str]:
    return ["say", to, "--type", "review_result", *extra]


def test_the_review_is_sent_as_given_from_a_file(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    (tmp_path / "review.json").write_text(json.dumps(REVIEW))
    argv = _say("Approve, see the cites.", "--review-file", str(tmp_path / "review.json"))
    assert cli.main(argv) == cli.EXIT_OK
    sent = fake.signed()[-1].json()
    assert sent["review"] == REVIEW
    assert (sent["type"], sent["body"]) == ("review_result", "Approve, see the cites.")


def test_a_review_file_may_start_with_a_byte_order_mark(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    """Notepad and `Out-File -Encoding utf8BOM` start the file with one, which `json.loads`
    refuses; only the leading mark goes, one inside a quote is the reviewer's text."""
    review = {**REVIEW, "cites": [{"path": "docs/api.md", "line": 1, "quote": "a\ufeffb"}]}
    path = tmp_path / "review.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(review, ensure_ascii=False).encode())
    assert cli.main(_say("Approve.", "--review-file", str(path))) == cli.EXIT_OK
    assert fake.signed()[-1].json()["review"]["cites"][0]["quote"] == "a\ufeffb"


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
    assert f"cites and text not checked: commit {REVIEW['head']} is not in this clone" in (
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
    assert "cites and text not checked: this directory is not a clone" in capsys.readouterr().err


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


def test_a_shallow_clone_does_not_refuse_a_removed_quote_it_cannot_see(
    joined: Path, tmp_path: Path
) -> None:
    _commit("b.txt", "old text\nkept\n")
    _commit("b.txt", "kept\n")
    _commit("b.txt", "kept\nmore\n")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", Path.cwd().as_uri(), str(clone)],
        check=True,
        capture_output=True,
    )
    review = {"head": head, "cites": [{"path": "b.txt", "quote": "old text"}]}
    result = citecheck.check(clone, review)
    assert result.bad == []
    assert result.unchecked == (
        "review.cites.0 b.txt: a shallow clone can't show what was removed; "
        "`git fetch --unshallow` can"
    )
    invented = {"head": head, "cites": [{"path": "b.txt", "line": 1, "quote": "invented"}]}
    assert citecheck.check(clone, invented).bad  # a named line is still read from the file


def test_a_quote_with_umlauts_stands_under_a_c_locale(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "b.txt").write_text("zweite ünï Zeile\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.org"]
    subprocess.run(["git", "-C", str(tmp_path), *identity, "commit", "-qm", "c"], check=True)
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        encoding="ascii",
    ).stdout.strip()
    script = (
        "import sys; from pathlib import Path; from maity import citecheck;"
        f"review = {{'head': {head!r}, 'cites': "
        "[{'path': 'b.txt', 'line': 1, 'quote': '\\u00fcn\\u00ef'}]};"
        "result = citecheck.check(Path.cwd(), review);"
        "sys.exit(1 if result.bad or result.unchecked else 0)"
    )
    env = {
        **os.environ,
        "LC_ALL": "C",
        "PYTHONUTF8": "0",
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONPATH": str(Path(citecheck.__file__).parent.parent),
    }
    done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, check=False)
    assert done.returncode == 0


REPO = Path(citecheck.__file__).resolve().parents[3]


@pytest.mark.parametrize("to", ["agt-a", "some-agent", "agt-a#x1"])  # member id, handle, instance
@pytest.mark.parametrize(
    ("quote", "named"),
    [
        ("x" * 300, None),
        ("ä" * 300, None),  # characters, not bytes: 600 bytes in UTF-8
        ("日" * 300, None),
        ("x" * 301, "the quote has 301 characters, the hub takes at most 300"),
        ("日" * 301, "the quote has 301 characters, the hub takes at most 300"),
    ],
)
def test_a_quote_longer_than_the_hub_takes_refuses_the_send(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    quote: str,
    named: str | None,
    to: str,
) -> None:
    _commit("b.txt", f"first\n{quote}\n")
    path = _review_at(
        tmp_path,
        {"path": "b.txt", "line": 1, "quote": "first"},
        {"path": "b.txt", "line": 2, "quote": quote},
    )
    before = len(fake.signed())
    if named is None:  # sent; to the member id, which the test hub knows
        assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_OK
        assert fake.signed()[-1].json()["review"]["cites"][1]["quote"] == quote
        return
    assert cli.main(_say("Approve.", "--review-file", path, to=to)) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "not sent: 1 cite(s)" in err
    assert f"review.cites.1 b.txt:2: {named}" in err
    assert fake.signed()[before:] == []  # not even the recipient's lookup


def test_a_long_quote_is_refused_without_a_clone(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    review = {**REVIEW, "cites": [{"path": "a.txt", "quote": "x" * 301}]}
    (tmp_path / "review.json").write_text(json.dumps(review))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("MAITY_STATE_DIR", str(state.resolve_state_dir()))
    monkeypatch.chdir(elsewhere)
    before = len(fake.signed())
    assert (
        cli.main(_say("Approve.", "--review-file", str(tmp_path / "review.json"))) == cli.EXIT_ERROR
    )
    assert "review.cites.0 a.txt: the quote has 301 characters" in capsys.readouterr().err
    assert fake.signed()[before:] == []  # not even the recipient's lookup


def test_the_quote_limit_is_the_hubs() -> None:
    hub = (REPO / "hub" / "src" / "maity_hub" / "reviews.py").read_text(encoding="utf-8")
    found = re.findall(r"^QUOTE_MAX = (\d+)$", hub, re.MULTILINE)
    assert found == [str(citecheck.QUOTE_MAX)]


def test_the_quote_limit_is_the_contracts() -> None:
    api = (REPO / "docs" / "api.md").read_text(encoding="utf-8")
    found = re.findall(r"`path` and `quote` 1–(\d+) characters", api)
    assert found == [str(citecheck.QUOTE_MAX)]


def test_a_long_quote_is_named_when_the_commit_is_missing(joined: Path) -> None:
    _commit("b.txt", "first\n")
    review = {**REVIEW, "cites": [{"path": "b.txt", "quote": "x" * 301}]}  # REVIEW's head: absent
    result = citecheck.check(Path.cwd(), review)
    assert result.bad == [
        "review.cites.0 b.txt: the quote has 301 characters, the hub takes at most 300"
    ]
    assert result.unchecked is not None and "is not in this clone" in result.unchecked


def test_a_long_quote_is_named_when_git_fails(
    joined: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit("b.txt", "first\n")
    path = _review_at(tmp_path, {"path": "b.txt", "line": 1, "quote": "x" * 301})
    review = json.loads(Path(path).read_text())
    calls = []

    def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        if len(calls) > 1:  # the clone is found, then git stops answering
            raise proc.ToolError("git did not answer")
        return real(argv, cwd)

    real = proc.run
    monkeypatch.setattr(proc, "run", run)
    result = citecheck.check(Path.cwd(), review)
    assert result.bad == [
        "review.cites.0 b.txt:1: the quote has 301 characters, the hub takes at most 300"
    ]
    assert result.unchecked == "git did not answer"


def test_a_cite_with_two_problems_counts_once(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _commit("b.txt", "first\n" + "x" * 301 + "\n")
    path = _review_at(tmp_path, {"path": "b.txt", "line": 1, "quote": "x" * 301})  # line 2, really
    assert cli.main(_say("Approve.", "--review-file", path)) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "not sent: 1 cite(s)" in err
    assert err.count("review.cites.0 b.txt:1: ") == 2  # too long, and on line 2


@posix  # under a placement a named file is read only where descriptors walk (not Windows)
@pytest.mark.parametrize(
    ("cite", "sent"),
    [
        ({"path": "b.txt", "line": 2, "quote": "second"}, True),
        ({"path": "b.txt", "line": 1, "quote": "second"}, False),
    ],
)
def test_under_a_placement_the_cites_are_checked_in_the_clone_from_its_folder(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cite: dict[str, object],
    sent: bool,
) -> None:
    """agy works in the workspace folder that holds the clone as `repo` (§15.5): the cites
    stand or fall in the runner's clone, not in the folder, which is no clone."""
    _commit("b.txt", "first\nsecond\n")
    clone = Path.cwd()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    # A runner's clone is plain (clonecheck): the fixture's redirect to its local remote goes;
    # the cite check needs no remote.
    subprocess.run(["git", "config", "--remove-section", "url." + str(clone.parent / "remote.git")],
                   check=True)  # fmt: skip
    # Under a placement maity reads a named file only inside the clone (inclone).
    (clone / "review.json").write_text(
        json.dumps({"subject": "#1", "head": head, "verdict": "approve", "cites": [cite]})
    )
    monkeypatch.setenv("MAITY_STATE_DIR", str(state.resolve_state_dir()))
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = clone.parent / "agent-git"
    private.mkdir()
    git = shutil.which("git")
    assert git is not None
    (private / "git").write_text(git)  # the git the runner recorded for the clone
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    monkeypatch.chdir(clone.parent)
    review = os.path.join(clone.name, "review.json")
    result = cli.main(_say("Approve.", "--review-file", review))
    err = capsys.readouterr().err
    assert "not checked" not in err
    if sent:
        assert result == cli.EXIT_OK, err
    else:
        assert result == cli.EXIT_ERROR
        assert "it stands on line 2" in err


def test_under_a_placement_whose_clone_cannot_be_named_nothing_is_sent(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`MAITY_PLACEMENT` without `GIT_COMMON_DIR`: the cites are not checked from the current
    directory instead (cli/context/runner.md b4a8030d); the review is refused, unsent."""
    monkeypatch.setenv("MAITY_STATE_DIR", str(state.resolve_state_dir()))
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    monkeypatch.delenv("GIT_COMMON_DIR", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REVIEW)))
    before = len(fake.seen)
    result = cli.main(_say("Approve.", "--review-file", "-"))
    err = capsys.readouterr().err
    assert result == cli.EXIT_ERROR, err
    assert "without GIT_COMMON_DIR" in err and "not checked" not in err
    assert not [s for s in fake.seen[before:] if s.method == "POST"]


@posix  # under a placement a named file is read only where descriptors walk (not Windows)
def test_under_a_placement_a_clone_its_git_refuses_sends_nothing(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runner's clone, but one maity's git does not run in (clonecheck): not "no clone
    here", so the review is not sent unchecked (cli/context/commands.md 7f3c1e52)."""
    _commit("b.txt", "first\nsecond\n")
    clone = Path.cwd()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "config", "--remove-section", "url." + str(clone.parent / "remote.git")],
                   check=True)  # fmt: skip
    # A key that runs code: maity's git refuses the clone (clonecheck.UNSUPPORTED_KEYS).
    subprocess.run(["git", "config", "core.fsmonitor", "true"], check=True)
    cite = {"path": "b.txt", "line": 2, "quote": "second"}
    (clone / "review.json").write_text(
        json.dumps({"subject": "#1", "head": head, "verdict": "approve", "cites": [cite]})
    )
    monkeypatch.setenv("MAITY_STATE_DIR", str(state.resolve_state_dir()))
    monkeypatch.setenv(clonecheck.PLACEMENT_ENV, "plc-0003")
    monkeypatch.setenv("GIT_COMMON_DIR", str(clone / ".git"))
    monkeypatch.setenv(clonecheck.GIT_INODE_ENV, str(os.lstat(clone / ".git").st_ino))
    private = clone.parent / "agent-git"
    private.mkdir()
    git = shutil.which("git")
    assert git is not None
    (private / "git").write_text(git)
    monkeypatch.setenv(clonecheck.GIT_PRIVATE_ENV, str(private))
    before = len(fake.seen)
    result = cli.main(_say("Approve.", "--review-file", "review.json"))
    err = capsys.readouterr().err
    assert result == cli.EXIT_ERROR, err
    assert "not sent: the review's cites cannot be checked: maity runs no git here" in err
    assert not [s for s in fake.seen[before:] if s.method == "POST"]
