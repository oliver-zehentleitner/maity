"""A mail's defanged text (§18.5) and the browser named from a `User-Agent` (§2.6.5) are read in
time that grows with the text's length, with the result of the patterns they replace."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from typing import Any

import pytest

from maity_hub.auth import sessions
from maity_hub.notifications import mailer

# Far above what each case takes (milliseconds) and far below what the replaced patterns took on
# the same input (seconds), so a slow machine cannot make it flaky.
BOUND = 1.0
LONG = 64 * 1024

# The patterns the functions replaced, kept here as the oracle of what they find.
OLD_SCHEME = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*):(?=//)")
OLD_SAFARI = re.compile(r"\bVersion/[\d.]+.*\bSafari/")


def timed(read: Callable[[], Any]) -> float:
    started = time.perf_counter()
    read()
    return time.perf_counter() - started


@pytest.mark.parametrize(
    "read",
    [
        lambda: mailer.defang("a." * (LONG // 2)),
        lambda: mailer.defang("a-" * (LONG // 2) + ":/"),
        lambda: sessions.describe("Version/" + "1" * LONG),
        lambda: sessions.describe("Version/1 " * (LONG // 10)),
    ],
    ids=["scheme-dots", "scheme-dashes", "safari-digits", "safari-versions"],
)
def test_a_long_text_is_read_in_bounded_time(read: Callable[[], Any]) -> None:
    took = timed(read)
    assert took < BOUND, f"{took:.2f}s"


def test_defang_and_describe_read_as_before() -> None:
    assert mailer.defang("see https://example.org/x") == "see https[:]//example[.]org/x"
    assert mailer.defang("a+b.c-d://x") == "a+b[.]c-d[:]//x"
    assert mailer.defang("_x://y") == "_x://y"  # no word boundary before the letter
    assert mailer.defang("_.x://y") == "_.x[:]//y"
    assert mailer.defang("1a://x a://y") == "1a://x a[:]//y"
    safari = "Mozilla/5.0 (Macintosh) AppleWebKit/605 (KHTML) Version/17.1 Safari/605.1.15"
    assert sessions.describe(safari) == ("Safari", "macOS")
    assert sessions.describe("Version/17 Mobile\nSafari/605") == (None, None)  # not on one line
    assert sessions.describe("Version/1Safari/2") == (None, None)  # no boundary before Safari


def test_texts_read_as_the_old_patterns_read_them() -> None:
    rng = random.Random(1364)
    # The scheme's characters, a colon and slashes, word characters outside the scheme's class
    # (`_`, `é`, an Arabic digit) and separators; for the browser, its two words and the runs
    # around them, a newline the old `.` did not cross.
    scheme = "a:/.+-_é1 Z\u0661\n"
    agent = ["Version/", "Safari/", "1", ".", "a", " ", "\n", "_", "é", "/"]
    for _ in range(20_000):
        text = "".join(rng.choice(scheme) for _ in range(rng.randint(0, 14)))
        assert mailer._schemes(text) == OLD_SCHEME.sub(r"\1[:]", text), repr(text)
        line = "".join(rng.choice(agent) for _ in range(rng.randint(0, 8)))
        assert bool(sessions._safari(line)) == bool(OLD_SAFARI.search(line)), repr(line)
