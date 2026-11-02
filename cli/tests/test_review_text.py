"""A review's text names only what stands at its head (docs/api.md §8.4, "A review's text
names only what stands at its head", §13): `maity say --type review_result` checks the
message before it sends it."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import fakehub
import pytest

from maity import cli, textcheck

P = "/api/v1/projects/oliver/maity"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(files: dict[str, str]) -> str:
    for name, text in files.items():
        Path(name).parent.mkdir(parents=True, exist_ok=True)
        Path(name).write_text(text, encoding="utf-8")
    _git("add", "-A")
    _git("commit", "-q", "--allow-empty", "-m", "files")
    return _git("rev-parse", "HEAD")


FILES = {
    "hub/src/maity_hub/rules.py": "def review_line():\n    return KEEP\n\n\nKEEP = 1\n",
    "web/i18n/ja.json": '{\n  "data.delete.hint": "x"\n}\n',
    "web/i18n/nl.json": "{}\n",
    "hub/tests/test_public_pages.py": "def test_a_page_is_public():\n    get('/api/v1/events')\n",
}


def bad(clone: Path, body: str) -> list[str]:
    head = _commit(FILES)
    return textcheck.check(clone, head, body).bad


def test_names_that_stand_at_the_head_pass(clone: Path) -> None:
    body = (
        "`review_line` in hub/src/maity_hub/rules.py:1-2 returns `KEEP`; "
        "`data.delete.hint` in `web/i18n/ja.json`, `hub/tests/test_public_*`, "
        '`"data.delete.hint"`, `rules.py`, `hub/src/` and the route `/api/v1/events`.'
    )
    assert bad(clone, body) == []


@pytest.mark.parametrize(
    ("body", "named"),
    [
        ("`test_invented_name` covers it", "`test_invented_name`: not found"),
        ("see `hub/src/maity_hub/nope.py`", "`hub/src/maity_hub/nope.py`: no such file"),
        ("`hub/nothing_*` matches", "`hub/nothing_*`: no such file"),
        ("hub/src/maity_hub/rules.py:9 says", "rules.py:9: the file has 5 lines"),
        ("hub/src/maity_hub/rules.py:1-6 says", "rules.py:1-6: the file has 5 lines"),
        ("rules.py:2 says", "did you mean hub/src/maity_hub/rules.py?"),
        ("ja.json:1 says", "ja.json:1: not a full path"),
        ("commit 1234abcd is it", "1234abcd: no such object"),
        ("`_Facts.key` exists", "`_Facts.key`: not found"),
    ],
)
def test_a_name_that_is_not_there_is_named(clone: Path, body: str, named: str) -> None:
    found = bad(clone, body)
    assert len(found) == 1, found
    assert named in found[0]


def test_each_part_of_a_dotted_name_may_stand_alone(clone: Path) -> None:
    assert bad(clone, "`review_line.KEEP` and `KEEP.review_line`") == []
    assert len(bad(clone, "`rules.review_line`")) == 1  # a path's word is no text


@pytest.mark.parametrize(
    "span",
    [
        "git diff a b",  # whitespace: a command
        "墨消し",  # outside ASCII
        "{runner}",
        "lotse#f63b",
        "@owner/handle",
        "<path>",
        "agt-1wjr47d6vkyx",
        "66b1e1f9-4641-4a55-be2d-d60963606cb3",
        "1.5",
        "--",
    ],
)
def test_spans_that_name_nothing_checkable_are_skipped(clone: Path, span: str) -> None:
    assert bad(clone, f"see `{span}` here") == []


def test_a_hash_range_in_a_span_is_checked_as_objects(clone: Path) -> None:
    head = _commit(FILES)
    short = head[:8]
    assert textcheck.check(clone, head, f"`{short}..{short}`").bad == []
    found = textcheck.check(clone, head, f"`{short}..ab12cd34`").bad
    assert len(found) == 1 and "ab12cd34: no such object" in found[0]


def test_trees_and_blobs_are_objects_and_uuid_groups_are_no_hash(clone: Path) -> None:
    head = _commit(FILES)
    tree = _git("rev-parse", "HEAD^{tree}")[:10]
    blob = _git("rev-parse", "HEAD:web/i18n/nl.json")[:10]
    body = f"tree {tree}, blob {blob}, KTW 66b1e1f9-4641-4a55-be2d-d60963606cb3"
    assert textcheck.check(clone, head, body).bad == []


def test_a_hex_word_needs_a_digit_to_be_a_hash(clone: Path) -> None:
    assert bad(clone, "the page was defaced, then acceded") == []


def test_the_ran_section_and_fenced_blocks_are_not_checked(clone: Path) -> None:
    body = (
        "Approve.\n\n"
        "```\ninvented_in_a_block deadbeef12\n```\n"
        "## ran\n"
        "`pytest tests/test_invented.py` and `test_invented`, commit 1234abcd\n"
        "### deeper, still under Ran\n"
        "`still_invented`\n"
        "## Notes\n"
        "`after_ran_invented`\n"
    )
    found = bad(clone, body)
    assert len(found) == 1 and "`after_ran_invented`" in found[0]


@pytest.mark.parametrize("heading", ["## Ran (head)", "Ran\n---"])
def test_only_an_atx_heading_ran_starts_the_section(clone: Path, heading: str) -> None:
    found = bad(clone, f"{heading}\n`test_invented`\n")
    assert len(found) == 1


def test_backticks_pair_as_commonmark_pairs_them(clone: Path) -> None:
    # The double-backtick span holds a single one; the stray backtick at the end opens nothing.
    body = "``a ` b`` then `review_line` and a stray ` here"
    assert bad(clone, body) == []
    assert textcheck.code_spans("``x`` `y` ` z") == ["y"]


def test_a_name_on_the_default_branch_passes_but_a_line_does_not(clone: Path) -> None:
    main = _commit({**FILES, "hub/src/maity_hub/old.py": "def removed_helper():\n    pass\n"})
    _git("update-ref", "refs/remotes/origin/HEAD", main)
    _git("rm", "-q", "hub/src/maity_hub/old.py")
    _git("commit", "-qm", "remove")
    head = _git("rev-parse", "HEAD")
    body = "`removed_helper` in `hub/src/maity_hub/old.py`, hub/src/maity_hub/old.py:1"
    found = textcheck.check(clone, head, body).bad
    assert len(found) == 1 and "old.py:1: not a full path" in found[0]


@pytest.fixture
def events(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})


def _send(tmp_path: Path, head: str, message: str) -> int:
    review = {
        "subject": "#1",
        "head": head,
        "verdict": "approve",
        "cites": [{"path": "web/i18n/nl.json", "line": 1, "quote": "{}"}],
    }
    (tmp_path / "review.json").write_text(json.dumps(review))
    (tmp_path / "m.md").write_text(message)
    argv = ["say", "agt-a", "--type", "review_result", "--body-file", str(tmp_path / "m.md")]
    return cli.main([*argv, "--review-file", str(tmp_path / "review.json")])


def test_say_refuses_a_text_that_names_what_is_not_there(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    head = _commit(FILES)
    before = len(fake.signed())
    assert _send(tmp_path, head, "`test_invented` covers it.") == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "not sent: 1 name(s) in the text are not there" in err
    assert "`test_invented`: not found as text or as a file name" in err
    assert [r for r in fake.signed()[before:] if r.path.endswith("/events")] == []


def test_say_sends_a_text_whose_names_stand(
    joined: Path, fake: fakehub.FakeHub, events: None, tmp_path: Path
) -> None:
    head = _commit(FILES)
    assert _send(tmp_path, head, "`review_line` holds.\n\n## Ran\n`make invented`\n") == 0
    assert fake.signed()[-1].json()["body"].startswith("`review_line` holds.")


def test_without_the_commit_neither_is_checked_and_it_is_sent(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = "7039a4b6fd8b988d71a63338711da188fcd95fba"
    assert _send(tmp_path, missing, "`test_invented` covers it.") == cli.EXIT_OK
    assert "cites and text not checked: commit" in capsys.readouterr().err
