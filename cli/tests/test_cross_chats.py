"""Cross-project group chats in the resume text (docs/api.md §5.2, §9.5, §13).

The block follows the project's unread chats and names the GET for the room.
`maity chat` reads a project's conversation and is not how this chat is read.
"""

from __future__ import annotations

from typing import Any

from test_onboarding import packet

from maity import onboarding


def _chat(id_: str, unread: int | None, mentions: int = 0, **more: Any) -> dict[str, Any]:
    return {"id": id_, "kind": "cross", "title": None, "unread": unread,
            "mentions_unread": mentions, **more}  # fmt: skip


def _block(text: str) -> list[str]:
    return text.split("Cross-project chats:\n", 1)[1].split("\n\n", 1)[0].splitlines()


def test_the_resume_lists_each_cross_chat_with_unread_messages() -> None:
    chats = [
        _chat("xch-1", 4, 1, title="Across the projects"),
        _chat("xch-read", 0, 3, title="Quiet"),
        _chat("xch-2", 2),
        _chat("xch-blank", 1, title=""),
    ]
    text = onboarding.render({**packet(), "cross_chats": chats})
    assert _block(text) == [
        "  Across the projects xch-1 (4 unread, 1 mentions): " "GET /me/cross-chats/xch-1/messages",
        "  Cross xch-2 (2 unread, 0 mentions): GET /me/cross-chats/xch-2/messages",
        "  Cross xch-blank (1 unread, 0 mentions): GET /me/cross-chats/xch-blank/messages",
    ]
    assert "maity chat" not in text.split("Cross-project chats:\n", 1)[1].split("\n\n", 1)[0]
    assert "Quiet" not in text


def test_the_block_follows_the_projects_unread_chats() -> None:
    text = onboarding.render(
        {
            **packet(),
            "conversations": [
                {
                    "id": "cnv-1",
                    "kind": "group",
                    "title": "Launch",
                    "unread": 1,
                    "mentions_unread": 0,
                }
            ],
            "cross_chats": [_chat("xch-1", 1, title="Across")],
        }
    )
    unread_at = text.index("Unread chats:")
    cross_at = text.index("Cross-project chats:")
    assert unread_at < cross_at
    assert "maity chat cnv-1" in text
    assert "GET /me/cross-chats/xch-1/messages" in text


def test_past_ten_chats_the_rest_are_counted() -> None:
    chats = [_chat(f"xch-{n}", 1, title=f"Room {n}") for n in range(13)]
    text = onboarding.render({**packet(), "cross_chats": chats})
    block = _block(text)
    assert len(block) == onboarding.UNREAD_CHATS + 1
    assert block[0].startswith("  Room 0 xch-0 ")
    assert block[-1] == "  … 3 more: GET /me/cross-chats"


def test_nothing_unread_prints_no_section() -> None:
    text = onboarding.render({**packet(), "cross_chats": [_chat("xch-1", 0, 4)]})
    assert "Cross-project chats" not in text
    assert "GET /me/cross-chats" not in text


def test_a_packet_without_the_field_prints_no_section() -> None:
    assert "Cross-project chats" not in onboarding.render(packet())


def test_a_bool_unread_is_not_a_count() -> None:
    chat = _chat("xch-1", 0)
    chat["unread"] = True  # a JSON boolean is not a count; bool is an int in Python
    text = onboarding.render({**packet(), "cross_chats": [chat]})
    assert "Cross-project chats" not in text


def test_a_chat_title_is_cleaned() -> None:
    text = onboarding.render({**packet(), "cross_chats": [_chat("xch-1", 1, title="x\x1b[2Jy")]})
    assert "\x1b" not in text
    assert "xch-1 (1 unread" in text
