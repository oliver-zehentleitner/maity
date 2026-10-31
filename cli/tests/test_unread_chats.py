"""Unread chats in the resume text and on a `maity wait` timeout (docs/api.md §5.2, §13)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, onboarding

CHATS = "/api/v1/projects/oliver/maity/conversations"


def _chat(id_: str, unread: int | None, mentions: int = 0, **more: Any) -> dict[str, Any]:
    return {"id": id_, "kind": "group", "title": None, "unread": unread,
            "mentions_unread": mentions, **more}  # fmt: skip


def test_the_resume_lists_each_chat_with_unread_messages() -> None:
    conversations = [
        _chat("cnv-1", 4, 1, title="Launch"),
        _chat("agt-b", 0, kind="direct"),  # read
        _chat("cnv-2", None),  # an owner reading along has no unread count
        _chat("cnv-3", 2),
    ]
    text = onboarding.render({**packet(), "conversations": conversations})
    block = text.split("Unread chats:\n", 1)[1].split("\n\n", 1)[0]
    assert block.splitlines() == [
        "  Launch cnv-1 (4 unread, 1 mentions): maity chat cnv-1",
        "  group cnv-3 (2 unread, 0 mentions): maity chat cnv-3",
    ]


def test_past_ten_chats_the_rest_are_counted() -> None:
    conversations = [_chat(f"cnv-{n}", 1) for n in range(13)]
    text = onboarding.render({**packet(), "conversations": conversations})
    block = text.split("Unread chats:\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert len(block) == onboarding.UNREAD_CHATS + 1
    assert block[-1] == "  … 3 more: maity chats"


def test_nothing_unread_prints_no_section() -> None:
    text = onboarding.render({**packet(), "conversations": [_chat("cnv-1", 0)]})
    assert "Unread chats" not in text


def test_a_chat_title_is_cleaned() -> None:
    text = onboarding.render({**packet(), "conversations": [_chat("cnv-1", 1, title="x\x1b[2Jy")]})
    assert "\x1b" not in text and "cnv-1 (1 unread" in text


def test_wait_names_unread_chats_on_a_timeout(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    items = [_chat("cnv-1", 4, 1), _chat("cnv-2", 2), _chat("agt-b", 0, kind="direct")]
    fake.routes[("GET", CHATS)] = lambda seen: (200, {"items": items, "next_cursor": None})
    assert cli.main(["wait", "--timeout", "4"]) == cli.EXIT_TIMEOUT
    err = capsys.readouterr().err
    assert "maity: unread chats: 6 in 2 chats (1 mentions): maity chats\n" in err


def test_wait_says_nothing_without_unread_chats(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", CHATS)] = lambda seen: (200, {"items": [_chat("cnv-1", 0)]})
    assert cli.main(["wait", "--timeout", "4"]) == cli.EXIT_TIMEOUT
    assert "unread chats" not in capsys.readouterr().err


def test_the_note_stays_within_the_timeout_when_the_hub_stops_answering(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    release = threading.Event()

    def hang(seen: fakehub.Seen) -> tuple[int, Any]:
        release.wait(30)
        return 200, {"items": [_chat("cnv-1", 1)]}

    fake.routes[("GET", CHATS)] = hang
    started = time.monotonic()
    try:
        assert cli.main(["wait", "--timeout", "4"]) == cli.EXIT_TIMEOUT
    finally:
        release.set()
    assert time.monotonic() - started < 5
    assert "unread chats" not in capsys.readouterr().err
