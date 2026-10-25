"""Answers to a round's questions (docs/api.md §20.3, §20.4).

One answer per member and round, named or anonymous, kept to one by a tag: HMAC-SHA256
under the round's random key over the round id and the member id. The tags and the key
die when the window closes. An anonymous answer stores nothing that names its author; its
author finds it again only through the tag, so only while the window is open.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.ids import new_id

TEXT_MAX = 4096  # bytes, per text
TOTAL_MAX = 12288  # bytes, the three together
FIELDS = ("went_well", "went_badly", "would_help")


def refused(reason: str, message: str) -> ApiError:
    """`forbidden` with the reason the jour fixe names (§20.9)."""
    return ApiError(403, "forbidden", message, {"reason": reason})


def tag(key: str, round_id: str, member_id: str) -> str:
    return hmac.new(
        bytes.fromhex(key), f"{round_id}\n{member_id}".encode(), hashlib.sha256
    ).hexdigest()


def _size(text: str | None) -> int:
    return len((text or "").encode())


def check_texts(texts: dict[str, str | None]) -> None:
    if not any((texts.get(f) or "").strip() for f in FIELDS):
        raise invalid({"answer": "empty"}, "answer at least one of the three questions")
    if any(_size(texts.get(f)) > TEXT_MAX for f in FIELDS) or (
        sum(_size(texts.get(f)) for f in FIELDS) > TOTAL_MAX
    ):
        raise invalid({"answer": "too_long"}, "each text at most 4 KiB, together 12 KiB")


def is_participant(round_row: Any, mine: Any) -> bool:
    """Invited, and still an active member of the project (§20.3)."""
    invited = {i["member_id"] for i in round_row.invited}
    return mine.principal_id in invited and mine.row.active is True


def window_open(round_row: Any) -> bool:
    close_at: Any = round_row.answers_close_at
    return bool(round_row.status == "answering" and clock.now() < close_at)


def submit(
    conn: Connection, round_row: Any, mine: Any, texts: dict[str, str | None], anonymous: bool
) -> dict[str, Any]:
    """Store one answer; `jour_fixe_answered` for a second, `jour_fixe_state` after the
    window, `forbidden` for anyone not a current participant."""
    if not is_participant(round_row, mine):
        raise refused("not_participant", "only the round's participants answer")
    if not window_open(round_row):
        raise ApiError(
            409, "jour_fixe_state", "the answer window is closed", {"status": round_row.status}
        )
    check_texts(texts)
    mark = tag(round_row.tag_key, round_row.id, mine.principal_id)
    try:
        with conn.begin_nested():
            conn.execute(insert(t.jour_fixe_tag).values(round_id=round_row.id, tag=mark))
    except IntegrityError:
        raise ApiError(409, "jour_fixe_answered", "you answered this round already") from None
    answer_id = new_id("jour_fixe_answer")
    conn.execute(
        insert(t.jour_fixe_answer).values(
            id=answer_id,
            round_id=round_row.id,
            anonymous=anonymous,
            author=None if anonymous else mine.id,
            # The tag finds an anonymous answer for its author while the window is open.
            tag=mark if anonymous else None,
            withdrawn=False,
            shuffle=secrets.token_hex(32),
            **{f: texts.get(f) for f in FIELDS},
        )
    )
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(answers_received=t.jour_fixe_round.c.answers_received + 1)
    )
    shown: dict[str, Any] = {"round_id": round_row.id, "anonymous": anonymous}
    if not anonymous:
        shown["id"] = answer_id
    return shown


def _view(row: Any, authors: dict[int, str], reader: Any = None) -> dict[str, Any]:
    shown: dict[str, Any] = {"id": row.id, "anonymous": row.anonymous}
    if not row.anonymous:
        shown["author"] = authors.get(row.author)
        shown["withdrawn"] = row.withdrawn
    if row.redaction is not None:
        from maity_hub.jourfixe.views import project_redaction

        shown.update({f: None for f in FIELDS}, redaction=project_redaction(row.redaction, reader))
    else:
        shown.update({f: getattr(row, f) for f in FIELDS}, redaction=None)
    return shown


def readers_see_all(round_row: Any, mine: Any) -> bool:
    """The moderator and humans with `owner` or `admin` read every answer (§20.3)."""
    if mine.principal_id == round_row.moderator["member_id"]:
        return True
    return mine.kind == "human" and mine.role in ("owner", "admin")


def listed(conn: Connection, round_row: Any, mine: Any, only_mine: bool) -> list[dict[str, Any]]:
    """The answers the caller reads, in the shuffled order; `not_found` to anyone else."""
    rows = conn.execute(
        select(t.jour_fixe_answer)
        .where(t.jour_fixe_answer.c.round_id == round_row.id)
        .order_by(t.jour_fixe_answer.c.shuffle)
    ).all()
    from maity_hub.views import principal_ids

    authors = principal_ids(conn, (r.author for r in rows if r.author is not None))
    if only_mine:
        return [_view(r, authors, mine) for r in rows if _is_own(round_row, r, mine)]
    if not readers_see_all(round_row, mine):
        raise not_found()
    return [_view(r, authors, mine) for r in rows]


def _is_own(round_row: Any, row: Any, mine: Any) -> bool:
    if not row.anonymous:
        return bool(row.author == mine.id)
    if not window_open(round_row) or round_row.tag_key is None or row.tag is None:
        # Past the deadline it is no one's, even before the sweep drops the key (§20.4).
        return False
    return hmac.compare_digest(row.tag, tag(round_row.tag_key, round_row.id, mine.principal_id))


def withdraw(conn: Connection, round_row: Any, mine: Any) -> dict[str, Any]:
    """While the window is open: an anonymous answer is deleted outright, found by its tag;
    a named one keeps a record with its author. The tag stays, so no second answer."""
    if not window_open(round_row):
        raise ApiError(
            409, "jour_fixe_state", "the answer window is closed", {"status": round_row.status}
        )
    rows = conn.execute(
        select(t.jour_fixe_answer).where(
            t.jour_fixe_answer.c.round_id == round_row.id,
            t.jour_fixe_answer.c.withdrawn.is_(False),
        )
    ).all()
    own = next((r for r in rows if _is_own(round_row, r, mine)), None)
    if own is None:
        raise not_found()
    if own.anonymous:
        conn.execute(delete(t.jour_fixe_answer).where(t.jour_fixe_answer.c.id == own.id))
    else:
        conn.execute(
            update(t.jour_fixe_answer)
            .where(t.jour_fixe_answer.c.id == own.id)
            .values(withdrawn=True, **{f: None for f in FIELDS})
        )
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.id == round_row.id)
        .values(answers_received=t.jour_fixe_round.c.answers_received - 1)
    )
    return {"round_id": round_row.id, "withdrawn": True}
