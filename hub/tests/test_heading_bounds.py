"""The contract's ATX headings (§6.8) and the `.keep-the-why` list lines (§11.3) are read in time
that grows with the line's length: each case at the largest input the hub reads, and the same
result as the patterns the string steps replaced."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from typing import Any

import pytest

from maity_hub import contract_text, ktw

# Far above what each case takes (milliseconds) and far below what the replaced patterns took on
# the same input (seconds to hours), so a slow machine cannot make it flaky.
BOUND = 1.0
FILE = contract_text.FILE_CAP
CONFIG = ktw.CONFIG_CAP

# The patterns the string steps replaced, kept here as the oracle of what a line means.
OLD_ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
OLD_SETTING = re.compile(r"^\s*-\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")
OLD_CHILD = re.compile(r"^\s*-\s*([^:]+?)\s*:\s*(\S+)(?:\s+—\s+.*)?\s*$")


def block(name: str, body: str) -> str:
    return f"<!-- keep-the-why:{name} -->\n{body}\n<!-- /keep-the-why:{name} -->\n"


def timed(read: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = read()
    return result, time.perf_counter() - started


@pytest.mark.parametrize(
    "read",
    [
        lambda: contract_text.toc("## 1 a" + " " * (FILE - 8) + "x"),
        lambda: contract_text.toc("## 1 a" + " " * (FILE - 9) + "x#"),
        lambda: ktw.config(block("config", "- a: b" + " " * CONFIG + "x")),
        lambda: ktw.children(block("children", "- " + " " * CONFIG)),
        lambda: ktw.children(block("children", "- a" + " " * CONFIG + "x")),
    ],
    ids=[
        "heading-spaces",
        "heading-closing",
        "setting-spaces",
        "child-spaces",
        "child-name-spaces",
    ],
)
def test_the_largest_line_is_read_in_bounded_time(read: Callable[[], Any]) -> None:
    _, took = timed(read)
    assert took < BOUND, f"{took:.2f}s"


def test_a_section_under_a_long_heading_is_found_in_bounded_time() -> None:
    heading = "## 1 a" + " " * (FILE - 9) + "x #"
    section, took = timed(lambda: contract_text.find_section(heading + "\ntext\n", "1"))
    assert took < BOUND, f"{took:.2f}s"
    assert section.heading == heading


def test_headings_read_as_before() -> None:
    assert contract_text._atx("## 8. Events ##") == (2, "8. Events")
    assert contract_text._atx("   # a") == (1, "a")
    assert contract_text._atx("    # a") is None  # four spaces: code, not a heading
    assert contract_text._atx("####### a") is None
    assert contract_text._atx("#a") is None
    assert contract_text._atx("#") == (1, "")
    assert contract_text._atx("# a#") == (1, "a#")  # no space before the `#`: part of the title
    assert contract_text._atx("# ##") == (1, "##")


def test_list_lines_read_as_before() -> None:
    assert ktw._setting("  - context-schema : `0.2.0` ") == ("context-schema", "`0.2.0`")
    assert ktw._setting("- a b: c") is None
    assert ktw._child("- hub: hub/ — the hub") == ("hub", "hub/")
    assert ktw._child("- hub: hub/ more") is None
    assert ktw._child("- a b : c") == ("a b", "c")
    assert ktw._child("-  : c") == (" ", "c")  # a name of spaces only is its last one


def old(pattern: re.Pattern[str], line: str) -> tuple[str, str] | None:
    found = pattern.match(line)
    return (found.group(1), found.group(2)) if found else None


def old_atx(line: str) -> tuple[int, str] | None:
    found = OLD_ATX.match(line)
    if not found:
        return None
    return len(found.group(1)), re.sub(r"[ \t]+#+$", "", found.group(2) or "").strip()


def test_lines_read_as_the_old_patterns_read_them() -> None:
    rng = random.Random(1334)
    # Spaces, tabs and the marks, with whitespace the patterns' `\s` holds and `[ \t]` does not,
    # a separator `str.splitlines` would cut at, and a zero-width space that is no whitespace.
    heading = " \t#a 　\x0b\x1c​"
    item = " \t-:a_— 　\x0b\x1c\x85 ​Z9"
    for _ in range(20_000):
        line = "".join(rng.choice(heading) for _ in range(rng.randint(0, 12)))
        assert contract_text._atx(line) == old_atx(line), repr(line)
        line = rng.choice(["", "-", "  -", " - a"]) + "".join(
            rng.choice(item) for _ in range(rng.randint(0, 12))
        )
        assert ktw._setting(line) == old(OLD_SETTING, line), repr(line)
        assert ktw._child(line) == old(OLD_CHILD, line), repr(line)
