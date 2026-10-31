"""What the hub counts about landing variants and campaign links (docs/api.md §16.7.2).

Daily sums per UTC day, variant (`default` is the main page) and campaign (`""` in the table
for none): `views`, `registrations`, `activations`. Nothing is kept about a visit; a row is never
linked to an account, a source address or a session. The one thing kept with an account is the
`campaign_origin`, until its first agent exchange or 30 days, to count that activation, and in the
person's own export while it exists. Everything here happens only while `variants` or `campaigns`
is non-empty (`landing.configured`); the sums stay for 400 days.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, landing
from maity_hub import tables as t

ORIGIN_DAYS = 30  # an origin stays with the account at most this long
KEEP_DAYS = 400  # the daily sums are deleted after this
MAX_DAYS = 400
DEFAULT_DAYS = 30
NONE = ""  # a campaign in `campaign_count` for "none": the key is part of the primary key

# The hub's own list of crawlers and link-preview fetchers (§16.7.2), part of its code: a request
# whose `User-Agent` names one of these is no visit. A crawler that pretends to be a browser is
# counted, and the answer says the views are approximate.
CRAWLERS = re.compile(
    r"bot\b|bot/|crawl|spider|slurp|preview|fetch|scan|monitor|probe|"
    r"facebookexternalhit|facebot|embedly|quora link|outbrain|pinterest|vkshare|w3c_validator|"
    r"whatsapp|telegram|discord|slack|skype|linkedin|twitter|mastodon|bluesky|cardyb|"
    r"semrush|ahrefs|mj12|dotbot|petalbot|yandex|baidu|duckduck|bingpreview|"
    r"headlesschrome|python-requests|curl/|wget/|go-http-client|java/|okhttp|axios|node-fetch",
    re.IGNORECASE,
)


def is_view(method: str, headers: Any, *, as_public: bool = False) -> bool:
    """Whether a request for the landing page or a variant counts as a view: a browser's
    top-level navigation (`Sec-Fetch-Mode: navigate` and `Sec-Fetch-Dest: document`), a `GET`
    (no `HEAD`), no crawler, not `?as=public`."""
    if method != "GET" or as_public:
        return False
    if headers.get("sec-fetch-mode") != "navigate" or headers.get("sec-fetch-dest") != "document":
        return False
    return CRAWLERS.search(headers.get("user-agent") or "") is None


def _today() -> date:
    return clock.now().date()


def count(
    conn: Connection,
    variant: str,
    campaign: str | None,
    *,
    views: int = 0,
    registrations: int = 0,
    activations: int = 0,
    day: date | None = None,
) -> None:
    """Add to the sums of the day: an increment in the database, not a read and a write, so
    that two visitors at once are both counted; the first of the day inserts the row."""
    key = (
        t.campaign_count.c.day == (day or _today()),
        t.campaign_count.c.variant == variant,
        t.campaign_count.c.campaign == (campaign or NONE),
    )
    sums = {
        "views": t.campaign_count.c.views + views,
        "registrations": t.campaign_count.c.registrations + registrations,
        "activations": t.campaign_count.c.activations + activations,
    }
    if conn.execute(update(t.campaign_count).where(*key).values(**sums)).rowcount:
        return
    row = {
        "day": day or _today(),
        "variant": variant,
        "campaign": campaign or NONE,
        "views": views,
        "registrations": registrations,
        "activations": activations,
    }
    try:
        with conn.begin_nested():
            conn.execute(insert(t.campaign_count).values(**row))
    except IntegrityError:  # another request made the row meanwhile
        conn.execute(update(t.campaign_count).where(*key).values(**sums))


def view(conn: Connection, variant: str, campaign: str | None) -> None:
    count(conn, variant, campaign, views=1)


def keep(setting: dict[str, Any], given: dict[str, Any] | None) -> dict[str, Any] | None:
    """The origin a registration may keep: the variant only when it is `default` or exists, the
    campaign only when the admin created it; a part that is not either is dropped silently, and
    nothing is kept while neither variants nor campaigns are set or when both parts are
    dropped (§16.7.2, "Only while configured")."""
    if not given or not landing.configured(setting):
        return None
    variant = given.get("variant")
    campaign = given.get("campaign")
    variant_ok = variant == landing.DEFAULT_VARIANT or variant in setting["variants"]
    campaign_ok = campaign in {one["code"] for one in setting["campaigns"]}
    if not variant_ok and not campaign_ok:
        return None
    return {
        "variant": variant if variant_ok else landing.DEFAULT_VARIANT,
        "campaign": campaign if campaign_ok else None,
    }


def registered(conn: Connection, human_id: str, origin: dict[str, Any] | None) -> None:
    """The account made from a registration that carried an origin: count the registration on
    the day of completion under the origin it was made with (even when that campaign or variant
    was removed since) and keep the origin with the account. Nothing while neither variants nor
    campaigns are set any more."""
    if not origin or not landing.configured(landing.stored(conn)):
        return
    now = clock.now()
    conn.execute(
        insert(t.campaign_origin).values(
            human_id=human_id,
            variant=origin["variant"],
            campaign=origin.get("campaign"),
            registered_at=now,
        )
    )
    count(conn, origin["variant"], origin.get("campaign"), registrations=1, day=now.date())


def activated(conn: Connection, human_id: str | None) -> None:
    """An agent of the account completed an exchange (§3.3): the first one, within 30 days of the
    registration, counts once as an activation and ends the origin."""
    if human_id is None:
        return
    row = conn.execute(
        select(t.campaign_origin).where(t.campaign_origin.c.human_id == human_id)
    ).first()
    if row is None:
        return
    conn.execute(delete(t.campaign_origin).where(t.campaign_origin.c.human_id == human_id))
    now = clock.now()
    if row.registered_at + timedelta(days=ORIGIN_DAYS) > now:
        count(conn, row.variant, row.campaign, activations=1, day=now.date())


def purge(conn: Connection) -> None:
    """Delete the origins older than 30 days and the sums older than 400 days."""
    now = clock.now()
    conn.execute(
        delete(t.campaign_origin).where(
            t.campaign_origin.c.registered_at <= now - timedelta(days=ORIGIN_DAYS)
        )
    )
    conn.execute(
        delete(t.campaign_count).where(
            t.campaign_count.c.day < now.date() - timedelta(days=KEEP_DAYS)
        )
    )


def statistics(conn: Connection, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    """`GET /admin/statistics/campaigns` (§16.7.2): the rows of the window with at least one
    non-zero sum, newest day first, and the variants and campaigns they name."""
    now = clock.now()
    since = now.date() - timedelta(days=days - 1)
    setting = landing.stored(conn)
    rows = [
        {
            "date": row.day.isoformat() if isinstance(row.day, date) else str(row.day)[:10],
            "variant": row.variant,
            "campaign": row.campaign or None,
            "views": row.views,
            "registrations": row.registrations,
            "activations": row.activations,
        }
        for row in conn.execute(
            select(t.campaign_count)
            .where(t.campaign_count.c.day >= since)
            .order_by(
                t.campaign_count.c.day.desc(),
                t.campaign_count.c.variant,
                t.campaign_count.c.campaign,
            )
        )
        if row.views or row.registrations or row.activations
    ]
    configured = {one["code"]: one["label"] for one in setting["campaigns"]}
    seen = {r["campaign"] for r in rows if r["campaign"]}
    campaigns = [
        {"code": code, "label": label, "removed": False} for code, label in configured.items()
    ] + [{"code": code, "label": None, "removed": True} for code in sorted(seen - set(configured))]
    variants = [landing.DEFAULT_VARIANT, *setting["variants"]]
    variants += sorted({r["variant"] for r in rows} - set(variants))
    return {
        "as_of": clock.rfc3339(now),
        "window_days": days,
        "views_approximate": True,
        "variants": variants,
        "campaigns": campaigns,
        "rows": rows,
    }


def as_csv(found: dict[str, Any]) -> str:
    """The rows as `text/csv`: `date,variant,campaign,views,registrations,activations`, a header
    line, `campaign` empty for none."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["date", "variant", "campaign", "views", "registrations", "activations"])
    for r in found["rows"]:
        writer.writerow(
            [
                r["date"],
                r["variant"],
                r["campaign"] or "",
                r["views"],
                r["registrations"],
                r["activations"],
            ]
        )
    return out.getvalue()
