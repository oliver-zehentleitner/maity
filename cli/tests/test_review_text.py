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

# A Keep-the-Why id in the full form. The fabricated id and the prefix share its first
# eight hex digits; only the full id is written into the committed file.
KTW_ID = "c0ffee00-1234-4abc-8def-0123456789ab"
KTW_FAKE = "c0ffee00-0000-4000-8000-000000000000"
KTW_PREFIX = "c0ffee00-1234"


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
        ("`test_invented_name` covers it", "`test_invented_name`: not a test at the head"),
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
        "1.5",
        "--",
    ],
)
def test_spans_that_name_nothing_checkable_are_skipped(clone: Path, span: str) -> None:
    assert bad(clone, f"see `{span}` here") == []


def test_a_hash_range_in_a_span_is_checked_as_objects(clone: Path) -> None:
    head = _commit(FILES)
    # The shortest prefix from 8 characters on that §8.4 counts as a hash: a fixed head[:8]
    # is all digits in about 2 % of commits, is then no hash, and the span is checked as a name.
    short = next(head[:n] for n in range(8, 41) if textcheck.is_object_hash(head[:n]))
    assert textcheck.check(clone, head, f"`{short}..{short}`").bad == []
    found = textcheck.check(clone, head, f"`{short}..ab12cd34`").bad
    assert len(found) == 1 and "ab12cd34: no such object" in found[0], found


def test_a_range_with_a_side_that_is_no_hash_is_checked_as_a_name(clone: Path) -> None:
    head = _commit(FILES)
    found = textcheck.check(clone, head, "`12345678..ab12cd34`").bad
    assert len(found) == 2, found
    assert "`12345678..ab12cd34`: not found as text" in found[0]
    assert "ab12cd34: no such object" in found[1]


def test_trees_and_blobs_are_objects_and_uuid_groups_are_no_hash(clone: Path) -> None:
    head = _commit(FILES)
    tree = _git("rev-parse", "HEAD^{tree}")[:10]
    blob = _git("rev-parse", "HEAD:web/i18n/nl.json")[:10]
    # The UUID's groups are not object hashes. The id itself is not at the head, so it is
    # named, and nothing else is.
    body = f"tree {tree}, blob {blob}, KTW 66b1e1f9-4641-4a55-be2d-d60963606cb3"
    assert textcheck.check(clone, head, body).bad == [
        "body: 66b1e1f9-4641-4a55-be2d-d60963606cb3: no such id at the head"
    ]


def test_a_numeric_ratio_is_not_a_file_and_line(clone: Path) -> None:
    assert bad(clone, "The contrast is 5.60:1, above 4.5:1 and 3:1.") == []


def test_a_keep_the_why_id_is_the_full_uuid_at_the_head(clone: Path) -> None:
    head = _commit({**FILES, "context/sample.md": f"**Id:** {KTW_ID}\n"})
    assert textcheck.check(clone, head, f"See `{KTW_ID}`.").bad == []
    fake = textcheck.check(clone, head, f"See `{KTW_FAKE}`.").bad
    assert fake == [f"body: {KTW_FAKE}: no such id at the head"], fake
    short = textcheck.check(clone, head, f"See `{KTW_PREFIX}`.").bad
    assert short == [f"body: {KTW_PREFIX}: not a full id"], short


def test_a_cited_test_name_is_a_test_at_the_head(clone: Path) -> None:
    head = _commit(
        {
            **FILES,
            "pkg/tests/test_widget.py": (
                "def test_real_widget():\n    return 1\n# see test_real_widget_note\n"
            ),
        }
    )
    assert textcheck.check(clone, head, "`test_real_widget` covers it.").bad == []
    prefix = textcheck.check(clone, head, "`test_real` covers it.").bad
    assert prefix == ["body: `test_real`: not a test at the head"], prefix
    noted = textcheck.check(clone, head, "`test_real_widget_note` covers it.").bad
    assert noted == ["body: `test_real_widget_note`: not a test at the head"], noted
    missing = textcheck.check(clone, head, "`test_no_such_widget` covers it.").bad
    assert missing == ["body: `test_no_such_widget`: not a test at the head"], missing


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
    assert "`test_invented`: not a test at the head" in err
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


# Form 4: a quotation from a file. FILES has no prose, so these tests add a page.
PAGE = {
    "docs/how/connected.md": (
        "# How agents are connected\n\n"
        "An agent that asks a question goes back to the card it asked about,\n"
        "and the card is marked blocked, so everyone can see why it is not moving.\n"
        "The `.flag` box stays until the answer.\n"
        'Its label reads "waiting for an answer" until then.\n'
    ),
    "web/js/wake.js": (
        "// The wait returns at once with every new event\n"
        "// addressed to this agent, then the harness wakes it.\n"
        'const LABEL = "a \\"quoted\\" word in the label";\n'
    ),
}


def quoted(clone: Path, body: str) -> list[str]:
    head = _commit({**FILES, **PAGE})
    return textcheck.check(clone, head, body).bad


@pytest.mark.parametrize(
    "body",
    [
        'docs/how/connected.md:3 says "the agent closes the card when it is done".',
        "docs/how/connected.md:3: “the agent closes the card when it is done”",
        "„the agent closes the card when it is done“ (docs/how/connected.md:3) is wrong.",
        '"the agent closes the card when it is done" (`docs/how/connected.md:3`)',
    ],
)
def test_a_quote_next_to_a_file_and_line_must_stand_in_that_file(clone: Path, body: str) -> None:
    found = quoted(clone, body)
    assert len(found) == 1, found
    assert '"the agent closes the card when it is done": not in docs/how/connected.md' in found[0]


def test_a_quote_in_a_section_about_one_file_must_stand_in_that_file(clone: Path) -> None:
    body = (
        "## `docs/how/connected.md`\n\n"
        "P2: “nobody can see why the card stopped moving” reads oddly.\n\n"
        "### Wording\n\n"
        'Also "an agent waits for the owner here".\n\n'
        "## Summary\n\n"
        '"a sentence that is in no file" is prose here, not a quote.\n'
    )
    found = quoted(clone, body)
    assert len(found) == 2, found
    assert "nobody can see why the card stopped moving" in found[0]
    assert "an agent waits for the owner here" in found[1]


def test_a_quote_that_stands_passes_across_wrapped_lines_cuts_and_code_marks(
    clone: Path,
) -> None:
    body = (
        "docs/how/connected.md:3-4: “goes back to the card it asked about, and the card is "
        'marked blocked”, and "so everyone can see … it is not moving." '
        "(docs/how/connected.md:4); “The .flag box stays until the answer” "
        "(docs/how/connected.md:5)."
    )
    assert quoted(clone, body) == []


def test_a_section_quote_may_stand_on_the_default_branch_but_a_line_quote_may_not(
    clone: Path,
) -> None:
    main = _commit({**FILES, **PAGE})
    _git("update-ref", "refs/remotes/origin/HEAD", main)
    head = _commit({"docs/how/connected.md": "# How agents are connected\n\nRewritten.\n"})
    removed = "goes back to the card it asked about"
    section = f'## docs/how/connected.md\n\nThe change drops "{removed}".\n'
    assert textcheck.check(clone, head, section).bad == []
    found = textcheck.check(clone, head, f'docs/how/connected.md:3 says "{removed}"').bad
    assert len(found) == 1, found
    assert "not in docs/how/connected.md at the head, verbatim" in found[0]


@pytest.mark.parametrize(
    "body",
    [
        'docs/how/connected.md:3 calls it "blocked" and "merge-ready" and "in review" here.',
        'docs/how/connected.md:3 the `"a quote in a code span is a name"` form 2 checks.',
        'A sentence with no file: "nothing in the head says this at all".',
        'docs/how/connected.md:3 an odd quote " stays text.',
        '- "a claim the review checked here": docs/how/connected.md:3 is its evidence.',
        'docs/how/connected.md:3 holds. Proposal: "an agent goes back to its card".',
        '"a mutation the reviewer applied here" (after docs/how/connected.md:3) survives.',
        "## docs/how/connected.md and web/i18n/nl.json\n\n"
        '"a quote in a section about two files".',
    ],
)
def test_short_terms_and_quotes_not_tied_to_a_file_pass(clone: Path, body: str) -> None:
    assert [line for line in quoted(clone, body) if "not in docs/how" in line] == []


def test_say_refuses_a_quote_that_is_not_at_the_head(
    joined: Path,
    fake: fakehub.FakeHub,
    events: None,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    head = _commit({**FILES, **PAGE})
    before = len(fake.signed())
    text = 'docs/how/connected.md:3 says "the agent closes the card when it is done".'
    assert _send(tmp_path, head, text) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert '"the agent closes the card when it is done": not in docs/how/connected.md' in err
    assert "a proposed wording, an output, a mutation or a removed text" in err
    assert [r for r in fake.signed()[before:] if r.path.endswith("/events")] == []


def test_a_quote_of_a_wrapped_comment_or_with_an_escaped_quote_stands(clone: Path) -> None:
    body = (
        'web/js/wake.js:1 says "every new event addressed to this agent, then the harness".\n\n'
        'web/js/wake.js:3 holds "a \\"quoted\\" word in the label".\n\n'
        'docs/how/connected.md:6 says "Its label reads \\"waiting for an answer\\" until".\n\n'
        'docs/how/connected.md:3 has no "agent \\"waits\\" for the owner here".\n'
    )
    found = quoted(clone, body)
    assert len(found) == 1 and 'agent \\"waits\\" for the owner here' in found[0], found


def test_a_heading_with_two_files_ends_the_section_of_one_above(clone: Path) -> None:
    body = (
        "## docs/how/connected.md\n\n"
        "### docs/how/connected.md and web/js/wake.js\n\n"
        '"every new event addressed to this agent" is from the script.\n'
    )
    assert quoted(clone, body) == []


def test_a_table_cell_ties_no_quote_in_the_next_cell(clone: Path) -> None:
    body = (
        "| Where | Proposal |\n|---|---|\n"
        '| docs/how/connected.md:3 | "an agent goes back to its own card" |\n'
    )
    assert quoted(clone, body) == []


def test_an_escaped_backslash_before_a_quote_closes_it() -> None:
    # Two backslashes before a quote are a backslash, then the closing quote; one masks it.
    files = ["docs/how/connected.md"]
    closed = 'docs/how/connected.md:3 says "a path ends in C:\\\\" and "the next quote here".'
    assert [q.text for q in textcheck.quotations(closed, files)] == ["a path ends in C:\\\\"]
    masked = 'docs/how/connected.md:3 says "a \\"masked\\" word stays inside".'
    assert [q.text for q in textcheck.quotations(masked, files)] == [
        'a \\"masked\\" word stays inside'
    ]
    # Three backslashes mask the quote mark; blanking them keeps the quote's end in place.
    three = 'docs/how/connected.md:3 says "a word \\\\\\" with three, then closed here".'
    assert [q.text for q in textcheck.quotations(three, files)] == [
        'a word \\\\\\" with three, then closed here'
    ]


def test_places_of_two_files_next_to_a_quote_tie_it_to_none() -> None:
    files = ["docs/how/connected.md", "web/js/wake.js"]
    both_after = (
        'It reads "four entirely fabricated words" (docs/how/connected.md:3 and web/js/wake.js:1).'
    )
    assert textcheck.quotations(both_after, files) == []
    around = 'docs/how/connected.md:3 says "four entirely fabricated words" (web/js/wake.js:1).'
    assert textcheck.quotations(around, files) == []
    one = 'docs/how/connected.md:3 says "four entirely fabricated words" (docs/how/connected.md:4).'
    assert [q.files for q in textcheck.quotations(one, files)] == [["docs/how/connected.md"]]


def test_a_place_in_brackets_on_the_next_line_ties_the_quote() -> None:
    files = ["docs/how/connected.md"]
    wrapped = 'The page reads "four entirely fabricated words"\n(docs/how/connected.md:3).'
    assert [q.files for q in textcheck.quotations(wrapped, files)] == [["docs/how/connected.md"]]


def test_the_brackets_of_one_quote_are_no_place_before_the_next() -> None:
    files = ["docs/how/connected.md", "web/js/wake.js"]
    two = (
        'It reads "four entirely fabricated words" (docs/how/connected.md:3) and'
        ' "four more fabricated words here" (web/js/wake.js:1).'
    )
    assert [q.files for q in textcheck.quotations(two, files)] == [
        ["docs/how/connected.md"],
        ["web/js/wake.js"],
    ]
