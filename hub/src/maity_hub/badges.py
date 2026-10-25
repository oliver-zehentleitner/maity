"""Counts-only public project badge (docs/api.md §6.20)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from html import escape

from sqlalchemy import Connection, func, select

from maity_hub import tables as t
from maity_hub.badge_template import TEMPLATE
from maity_hub.views import member_views

# Verdana 11 px advances in hundredths, from web/brand/BADGE.md.
ADVANCES = {
    **{str(n): 700 for n in range(10)},
    " ": 387,
    "·": 472,
    **dict(
        zip(
            "abcdefghijklmnopqrstuvwxyz",
            (
                666,
                686,
                572,
                686,
                656,
                387,
                686,
                696,
                301,
                378,
                651,
                301,
                1068,
                696,
                668,
                686,
                686,
                468,
                572,
                434,
                696,
                651,
                902,
                651,
                651,
                577,
            ),
            strict=True,
        )
    ),
}


def render(value: str, color: str) -> bytes:
    text = (Decimal(sum(ADVANCES.get(c, 660) for c in value)) / 100).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    fields = {
        "VALUE": escape(value, quote=True),
        "TITLE": escape("maity: " + value, quote=True),
        "COLOR": color,
        "TEXT_W": f"{text:.1f}",
        "RIGHT_W": f"{text + 12:.1f}",
        "WIDTH": f"{text + Decimal('72.9'):.1f}",
    }
    document = TEMPLATE
    for key, replacement in fields.items():
        document = document.replace("{" + key + "}", replacement)
    return document.encode("utf-8")


def members(conn: Connection, project_id: str) -> tuple[str, str]:
    humans, agents = conn.execute(
        select(func.count(t.membership.c.human_id), func.count(t.membership.c.agent_id)).where(
            t.membership.c.project_id == project_id, t.membership.c.active.is_(True)
        )
    ).one()
    value = (
        f"{humans} human{'s' if humans != 1 else ''} · {agents} agent{'s' if agents != 1 else ''}"
    )
    return value, "#1a66d9"


def agents_online(conn: Connection, project_id: str) -> tuple[str, str]:
    rows = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.is_not(None),
        )
    ).all()
    # Use the same member view as §6.2, including pauses and instance aggregation;
    # this endpoint never derives an alternative presence rule from timestamps.
    count = sum(view["presence"] == "online" for view in member_views(conn, rows))
    return f"{count} agent{'s' if count != 1 else ''} online", "#1a7f37" if count else "#5e6670"
