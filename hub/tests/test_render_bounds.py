"""docs/api.md §16.7: the work of rendering a member's Markdown and of choosing a language from
`Accept-Language` is bounded per input. Each limit at the largest text the hub stores, in time, and
what the renderer shows at the limit."""

from __future__ import annotations

import random
import re
import time

import pytest

from maity_hub import render

# Far above what each case takes (milliseconds) and far below what an unbounded pattern took on
# the same input (seconds to minutes), so a slow machine cannot make it flaky.
BOUND = 1.0
CARD_BODY = 16_384  # the longest card text (models.py)
NOTE = 4_096  # the longest note (board/notes.py)


def timed(source: str) -> tuple[str, float]:
    started = time.perf_counter()
    html = render.markdown(source, ugc=True)
    return html, time.perf_counter() - started


@pytest.mark.parametrize(
    "source",
    [
        ("[a](x" * CARD_BODY)[:CARD_BODY],  # links never closed
        ("[a](x y" * CARD_BODY)[:CARD_BODY],  # ... with a title
        "[a](" + " " * (CARD_BODY - 5) + "x",  # spaces before a target, not the line's end
        "[a](x " + "y" * (CARD_BODY - 6),
        "# a" + " " * (CARD_BODY - 4) + "b",  # a heading with a long run of spaces inside
        "# a" + " #" * ((CARD_BODY - 3) // 2),
        ">" * NOTE,  # a note of quotes
        "\n".join(">" * depth for depth in range(1, 180)),
        "`a" * (CARD_BODY // 2),
        " _a" * (CARD_BODY // 3),
        "**a" * (CARD_BODY // 3),
    ],
    ids=[
        "links",
        "links-titles",
        "link-spaces",
        "link-title-run",
        "heading-spaces",
        "heading-marks",
        "quotes",
        "quote-lines",
        "code",
        "em",
        "strong",
    ],
)
def test_the_largest_stored_text_renders_in_bounded_time(source: str) -> None:
    _, took = timed(source)
    assert took < BOUND, f"{took:.2f}s"


def test_the_spaces_before_a_link_target_are_read_once() -> None:
    # Four times the longest card: the spaces before the target were tried against the title's.
    source = "[a](" + " " * (4 * CARD_BODY) + "x"
    started = time.perf_counter()
    render.inline(source)
    took = time.perf_counter() - started
    assert took < BOUND, f"{took:.2f}s"


# The inline pattern before a link's opening spaces were taken whole: the oracle on short lines.
OLD_INLINE = re.compile(render._INLINE.pattern.replace(r"\([ \t]*+", r"\([ \t]*"))


def test_a_link_reads_as_the_old_pattern_read_it() -> None:
    assert OLD_INLINE.pattern != render._INLINE.pattern
    chance = random.Random(16_7)
    for _ in range(20_000):
        line = "".join(chance.choice('[]() \tax"') for _ in range(chance.randint(0, 14)))
        new = [(m.span(), m.groupdict()) for m in render._INLINE.finditer(line)]
        old = [(m.span(), m.groupdict()) for m in OLD_INLINE.finditer(line)]
        assert new == old, repr(line)


def test_a_link_renders_with_a_title_and_not_past_its_bounds() -> None:
    assert render.inline('[a](https://e.org/x "t")') == (
        '<a href="https://e.org/x" rel="noopener">a</a>'
    )
    # A target of LINK_MAX characters is a link named `a`; past the bounds the address is only
    # a bare link of its own, the brackets text.
    named = 'rel="noopener">a</a>'
    target = "https://e.org/" + "x" * (render.LINK_MAX - len("https://e.org/"))
    assert named in render.inline(f"[a]({target})")
    assert named not in render.inline(f"[a]({target}x)")
    # A title stays on its line and holds no `[`.
    assert named not in render.markdown('[a](https://e.org/x\n"t")')
    assert named not in render.inline('[a](https://e.org/x "[t]")')


def test_quotes_nest_eight_deep_and_deeper_lines_are_a_paragraph_as_written() -> None:
    eight = render.markdown(">" * 8 + " deep")
    assert eight.count("<blockquote>") == 8 and "<p>deep</p>" in eight
    nine = render.markdown(">" * 9 + " deep")
    assert nine.count("<blockquote>") == 8 and "<p>&gt; deep</p>" in nine
    many = render.markdown(">" * NOTE)
    assert many.count("<blockquote>") == render.QUOTE_DEPTH
    assert "&gt;" * (NOTE - render.QUOTE_DEPTH) in many


# The heading pattern before its text was found by string operations: the oracle on short lines.
OLD_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def test_a_heading_reads_as_the_old_pattern_read_it() -> None:
    chance = random.Random(16_7)
    for _ in range(20_000):
        line = "".join(chance.choice("# \t x") for _ in range(chance.randint(0, 12)))
        old = OLD_HEADING.match(line)
        expected = (len(old.group(1)), old.group(2)) if old else None
        assert render._heading(line) == expected, repr(line)


def test_only_the_first_parts_of_accept_language_are_read() -> None:
    offered = ["en", "de", "fr"]
    filler = ",".join(["xx"] * (render.ACCEPT_PARTS - 1))
    assert render.best_language(offered, None, filler + ",de") == "de"  # the 20th part
    assert render.best_language(offered, None, filler + ",xx,de") is None  # the 21st
    long_tag = "de-" + "x" * (render.TAG_MAX - 2)
    assert render.best_language(offered, None, long_tag + ",fr") == "fr"
    assert render.best_language(offered, None, "de-" + "x" * (render.TAG_MAX - 3)) == "de"
    # Only the parts wholly within the first ACCEPT_CHARS characters are read.
    pad = "x" * (render.ACCEPT_CHARS - len("de"))
    assert render.best_language(offered, None, pad + ",de") is None  # cut by the limit
    assert render.best_language(offered, None, pad[1:] + ",de") == "de"  # ends at the limit
    assert render.best_language(offered, None, pad[1:] + ",de,fr") == "de"
    assert render.best_language(offered, None, pad + ",de-AT,fr") is None
    # A q-value past the limit is not converted, nor is a long tail copied or split.
    assert render.best_language(offered, None, "fr;q=0." + "9" * render.ACCEPT_CHARS) is None
    header = "en;q=0." + "1" * (1 << 22)  # a q-value of 4 MiB of digits
    started = time.perf_counter()
    for _ in range(100):
        render.best_language(offered, None, header)
    assert (time.perf_counter() - started) / 100 < 0.005


def test_the_registration_mail_reads_the_same_parts() -> None:
    from maity_hub import registration_mail

    pad = "x" * (render.ACCEPT_CHARS - len("de"))
    assert registration_mail.language_of(pad[1:] + ",de") == "de"
    assert registration_mail.language_of(pad + ",de") == "en"  # cut by the limit
