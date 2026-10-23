"""The ticker's endpoints (docs/api.md §17.6, §17.8, §17.9): the manual post, the
listing, and one's own follow and mute."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, insert, select, update

from maity_hub import clock, events, idempotency, ticker
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.models import Strict
from maity_hub.ratelimit import Limiter
from maity_hub.routes.events import PAGE_MAX, load_event
from maity_hub.views import event_views

router = APIRouter()

# §17.6: at most 20 manual posts per membership per hour, of them 5 to everyone.
POSTS = Limiter(20, 3600)
POSTS_TO_ALL = Limiter(5, 3600)
URL_MAX = 2048
TOKENS_MAX = 20
AREAS_MAX = 20
ENVIRONMENT_MAX = 64
TOKEN = re.compile(r"^(member|role|area):\S{1,255}$")


def _https(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= URL_MAX
        and re.fullmatch(r"https://[^\s]+", value, re.IGNORECASE) is not None
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and 1 <= len(list(value)) <= ticker.TEXT_MAX


class PostIn(Strict):
    """Every field top-level and typed loosely: the checks below give §17.6's reasons."""

    type: Any = None
    text: Any = None
    url: Any = None
    to: Any = None
    release_task_id: Any = None
    areas: Any = None
    deploy: Any = None


PER_TYPE = {"release_task_id": "release", "areas": "note", "deploy": "deploy"}


def _check(conn: Connection, mine: Membership, body: PostIn) -> Any:
    """§17.6's field rules, all at once; returns the release card for a release."""
    given = body.model_fields_set
    errors: dict[str, str] = {}
    kind = body.type
    if kind is None:
        errors["type"] = "required"
    elif kind in ("merge", "decision"):
        errors["type"] = "not_for_type"
    elif kind not in ("note", "deploy", "release"):
        errors["type"] = "invalid"
    if body.text is None:
        errors["text"] = "required"
    elif not _text(body.text):
        errors["text"] = "invalid"
    if body.url is not None and not _https(body.url):
        errors["url"] = "invalid"
    to = body.to if "to" in given else "computed"
    if not (
        to in ("computed", "all")
        or (
            isinstance(to, list)
            and 1 <= len(to) <= TOKENS_MAX
            and all(isinstance(x, str) and TOKEN.match(x) for x in to)
        )
    ):
        errors["to"] = "invalid"
    for name, only in PER_TYPE.items():
        if name in given and kind in ticker.TYPES and kind != only:
            errors[name] = "not_for_type"
    card = None
    if kind == "note":
        areas = body.areas
        if areas is None:
            if to == "computed":
                errors["areas"] = "required"
        elif not (
            isinstance(areas, list)
            and 1 <= len(areas) <= AREAS_MAX
            and all(isinstance(a, str) and 1 <= len(a) <= 255 for a in areas)
        ):
            errors["areas"] = "invalid"
    if kind == "release":
        if not isinstance(body.release_task_id, str):
            errors["release_task_id"] = "required"
        else:
            card = conn.execute(
                select(t.card).where(
                    t.card.c.id == body.release_task_id, t.card.c.project_id == mine.project.id
                )
            ).first()
            if card is None or card.kind != "release" or card.status != "done":
                errors["release_task_id"] = "not_done"
    if kind == "deploy":
        deploy = body.deploy
        if not isinstance(deploy, dict):
            errors["deploy"] = "required"
        else:
            unknown = set(deploy) - {"environment", "sha", "version", "log_url"}
            environment = deploy.get("environment")
            if unknown:
                errors["deploy"] = "invalid"
            elif not isinstance(environment, str) or not 1 <= len(environment) <= ENVIRONMENT_MAX:
                errors["deploy.environment"] = "required" if environment is None else "invalid"
            elif not (deploy.get("sha") or deploy.get("version")):
                errors["deploy"] = "required"
            elif any(
                deploy.get(k) is not None
                and not (isinstance(deploy[k], str) and 1 <= len(deploy[k]) <= 64)
                for k in ("sha", "version")
            ):
                errors["deploy"] = "invalid"
            elif deploy.get("log_url") is not None and not _https(deploy["log_url"]):
                errors["deploy.log_url"] = "invalid"
    if errors:
        raise invalid(errors)
    if isinstance(to, list):
        for token in to:
            if token.startswith("member:") and not ticker.resolve(
                ticker.members(conn, mine.project.id), token
            ):
                raise invalid({"to": "invalid"}, f"{token} names no active member")
    return card


def _charge(conn: Connection, mine: Membership, to_all: bool) -> None:
    key = str(mine.id)
    wait = POSTS.hit(key)
    if wait:
        raise rate_limited(wait)
    events.on_rollback(conn, lambda: POSTS.give_back(key, 1))
    if to_all:
        wait = POSTS_TO_ALL.hit(key)
        if wait:
            raise rate_limited(wait)
        events.on_rollback(conn, lambda: POSTS_TO_ALL.give_back(key, 1))


@router.post("/projects/{slug}/ticker")
def post_item(slug: str, body: PostIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("ticker:post")
        card = _check(conn, mine, body)
        to = body.to if "to" in body.model_fields_set else "computed"
        kind = body.type
        people = ticker.members(conn, mine.project.id)
        audience = ticker.Audience()
        facts: dict[str, Any] = {}
        key: str | None = None
        if kind == "note":
            facts["areas"] = list(body.areas or [])
        if kind == "release":
            version = card.release_version or ""
            key = f"release:{version}"
            facts["release"] = {"task_id": card.id, "version": version}
            facts["tasks"] = [card.id]
        if kind == "deploy":
            d = body.deploy
            key = f"deploy:{d['environment']}:{d.get('sha') or d.get('version')}"
            facts["deploy"] = {
                "environment": d["environment"],
                "sha": d.get("sha"),
                "version": d.get("version"),
                "log_url": d.get("log_url"),
            }
        if to == "all":
            for m in people:
                audience.add(m.principal, "posted_to_all")
        elif isinstance(to, list):
            for token in to:
                for m in ticker.resolve(people, token):
                    audience.add(m.principal, "addressed")
        elif kind == "note":
            for area in facts["areas"]:
                owner = ticker.area_owner(people, area)
                if owner:
                    audience.add(owner[0].principal, f"area_owner:{owner[1]}")
        elif kind == "release":
            for m in people:
                audience.add(m.principal, "all_members")
        else:  # a deploy to whom it concerns: every member (§17.6)
            for m in people:
                audience.add(m.principal, "addressed")
        ticker.apply_subscriptions(conn, people, audience, kind, False, facts.get("areas", []))
        if key is not None:
            found = ticker.existing(conn, mine.project.id, key)
            if found is not None:
                raise ApiError(
                    409, "ticker_duplicate", "an item with this key exists", {"seq": found}
                )
        _charge(conn, mine, to == "all")
        seq = ticker.write(
            conn,
            mine.project.id,
            kind=kind,
            text=body.text,
            url=body.url,
            audience=audience,
            origin="manual",
            actor=caller.actor(mine.id),
            actor_principal=mine.principal_id,
            subject=("task", card.id) if card is not None else None,
            dedupe_key=key,
            facts=facts,
        )
        if seq is None:  # taken between the check and the write: the first item stands
            raise ApiError(
                409,
                "ticker_duplicate",
                "an item with this key exists",
                {"seq": ticker.existing(conn, mine.project.id, key or "")},
            )
        view = load_event(conn, str(seq), mine)
        return idempotency.Outcome(201, "event", str(seq), view)

    return idempotency.run(engine_of(request), request, caller, action)


# --- the listing (§17.9) ---------------------------------------------------------------


def _since(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    if not re.search(r"(Z|[+-]\d{2}:\d{2})$", raw):
        raise invalid({"since": "invalid"}, "since needs an offset")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise invalid({"since": "invalid"}) from None


def _cursor(seq: int, filters: str) -> str:
    raw = json.dumps([seq, filters])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _uncursor(text: str, filters: str) -> int:
    try:
        seq, made_for = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
    if made_for != filters or not isinstance(seq, int):
        raise invalid({"cursor": "invalid"}, "a cursor is valid for one filter set")
    return seq


def compact(view: dict[str, Any], principal: str) -> dict[str, Any]:
    """An item in the listing's form (§17.9), the caller's own `why` and `muted`."""
    p = view["payload"] or {}
    mine = ticker.reason_of(p, principal)
    return {
        "id": f"tck-{view['seq']}",
        "seq": view["seq"],
        "at": view["at"],
        "type": p.get("type"),
        "text": p.get("text"),
        "url": p.get("url"),
        "actor": view["actor"],
        "subject": view["subject"],
        "areas": p.get("areas", []),
        "contract": p.get("contract"),
        "tasks": p.get("tasks", []),
        "for_me": mine is not None,
        "why": mine["why"] if mine else [],
        "muted": bool(mine and mine.get("muted")),
        "detail": p.get("detail"),
        "redacted": view["redacted"],
    }


def _keep(
    item: dict[str, Any],
    payload: dict[str, Any],
    types: list[str] | None,
    area: str | None,
    for_me: bool,
    since: datetime | None,
    at: datetime,
) -> bool:
    if types is not None:
        kind = item["type"]
        if not (kind in types or ("contract" in types and kind == "merge" and item["contract"])):
            return False
    if area is not None:
        places = list(item["areas"]) + list(payload.get("paths", []))
        if not any(ticker.contains(area, p) for p in places):
            return False
    if for_me and not item["for_me"]:
        return False
    return since is None or at >= since


def listing(
    conn: Connection,
    mine: Membership,
    *,
    types: list[str] | None = None,
    area: str | None = None,
    for_me: bool = False,
    since: datetime | None = None,
    before: int | None = None,
    after: int | None = None,
    limit: int = 50,
) -> tuple[list[dict[str, Any]], bool]:
    """The readable items matching the filters: newest first below `before`, or oldest
    first above `after`. Returns (items, more)."""
    found: list[dict[str, Any]] = []
    edge = before if after is None else after
    while True:
        query = select(t.event).where(
            t.event.c.project_id == mine.project.id, t.event.c.kind == "ticker"
        )
        if after is not None:
            query = query.where(t.event.c.seq > edge).order_by(t.event.c.seq)
        else:
            if edge is not None:
                query = query.where(t.event.c.seq < edge)
            query = query.order_by(t.event.c.seq.desc())
        batch = conn.execute(query.limit(200)).all()
        hidden = events.hidden_redactions(conn, batch, mine.row)
        readable = [r for r in batch if events.readable_by(r, mine.row, mine.principal_id, hidden)]
        for row, view in zip(readable, event_views(conn, readable, mine), strict=True):
            item = compact(view, mine.principal_id)
            if _keep(item, row.payload or {}, types, area, for_me, since, row.at):
                if len(found) == limit:
                    return found, True
                found.append(item)
        if len(batch) < 200:
            return found, False
        edge = batch[-1].seq


@router.get("/projects/{slug}/ticker")
def get_listing(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    q = request.query_params
    errors: dict[str, str] = {}
    raw_type = q.get("type")
    types = raw_type.split(",") if raw_type else None
    if types is not None and any(x not in ticker.FILTER_TYPES for x in types):
        errors["type"] = "invalid"
    who = q.get("for", "all")
    if who not in ("me", "all"):
        errors["for"] = "invalid"
    raw_limit = q.get("limit", "50")
    if not raw_limit.isdigit() or not 1 <= int(raw_limit) <= PAGE_MAX:
        errors["limit"] = "out_of_range"
    raw_after = q.get("after")
    if raw_after is not None and (not raw_after.isdigit() or q.get("cursor") is not None):
        errors["after"] = "invalid"
    if errors:
        raise invalid(errors)
    since = _since(q.get("since"))
    area = q.get("area")
    filters = json.dumps([q.get("type"), area, who, q.get("since")])
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        before = _uncursor(q["cursor"], filters) if q.get("cursor") else None
        items, more = listing(
            conn,
            mine,
            types=types,
            area=area,
            for_me=who == "me",
            since=since,
            before=before,
            after=int(raw_after) if raw_after is not None else None,
            limit=int(raw_limit),
        )
    next_cursor = _cursor(items[-1]["seq"], filters) if more and raw_after is None else None
    return JSONResponse({"items": items, "next_cursor": next_cursor})


PACKET_ITEMS = 20
PACKET_SCAN = 10_000


def packet(conn: Connection, mine: Membership, cursor: int) -> dict[str, Any]:
    """The resume packet's `ticker` (§17.9): the items after the cursor, at most 20, those
    for the member first, then the newest; counts of all of them."""
    items, more = listing(conn, mine, after=cursor, limit=PACKET_SCAN)
    mine_first = [i for i in reversed(items) if i["for_me"]] + [
        i for i in reversed(items) if not i["for_me"]
    ]
    for_me = sum(1 for i in items if i["for_me"])
    return {
        "items": mine_first[:PACKET_ITEMS],
        "for_me": for_me,
        "others": len(items) - for_me,
        "truncated": more or len(items) > PACKET_ITEMS,
    }


# --- follow and mute (§17.8) -------------------------------------------------------------


def _subscription_view(sub: dict[str, Any]) -> dict[str, Any]:
    return {
        "follow": {"areas": list(sub["follow"]["areas"]), "types": list(sub["follow"]["types"])},
        "mute": {"areas": list(sub["mute"]["areas"]), "types": list(sub["mute"]["types"])},
        "updated_at": clock.rfc3339(sub["updated_at"]) if sub["updated_at"] else None,
    }


@router.get("/projects/{slug}/ticker/subscription")
def get_subscription(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        return JSONResponse(_subscription_view(ticker.subscription_of(conn, mine.id)))


class ListsIn(Strict):
    areas: list[str] | None = None
    types: list[str] | None = None


class SideIn(Strict):
    follow: ListsIn | None = None
    mute: ListsIn | None = None


class SubscriptionPatch(Strict):
    add: SideIn | None = None
    remove: SideIn | None = None


AREA = re.compile(r"^(/|[^/\s][^\s]{0,254})$")


@router.patch("/projects/{slug}/ticker/subscription")
def patch_subscription(
    slug: str, body: SubscriptionPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        current = ticker.subscription_of(conn, mine.id)
        errors: dict[str, str] = {}
        changed = False
        result: dict[str, dict[str, list[str]]] = {}
        for side in ("follow", "mute"):
            result[side] = {}
            for kind in ("areas", "types"):
                add = (
                    list(getattr(getattr(body.add, side, None) or ListsIn(), kind) or [])
                    if body.add
                    else []
                )
                remove = (
                    list(getattr(getattr(body.remove, side, None) or ListsIn(), kind) or [])
                    if body.remove
                    else []
                )
                name = f"{side}.{kind}"
                if set(add) & set(remove):
                    errors[name] = "invalid"
                if kind == "types" and any(v not in ticker.FILTER_TYPES for v in add + remove):
                    errors[name] = "invalid"
                if kind == "areas" and any(not AREA.match(v) for v in add + remove):
                    errors[name] = "invalid"
                before = list(current[side][kind])
                after = [v for v in before if v not in remove] + [
                    v for v in dict.fromkeys(add) if v not in before
                ]
                if kind == "areas" and len(after) > 20:
                    errors[name] = "too_many"
                changed = changed or after != before
                result[side][kind] = after
        if errors:
            raise invalid(errors)
        if not changed:
            view = _subscription_view(current)
            return idempotency.Outcome(200, "ticker_subscription", str(mine.id), view)
        now = clock.now()
        values = {"follow": result["follow"], "mute": result["mute"], "updated_at": now}
        exists = conn.execute(
            select(t.ticker_subscription.c.membership_id).where(
                t.ticker_subscription.c.membership_id == mine.id
            )
        ).first()
        if exists:
            conn.execute(
                update(t.ticker_subscription)
                .where(t.ticker_subscription.c.membership_id == mine.id)
                .values(**values)
            )
        else:
            conn.execute(insert(t.ticker_subscription).values(membership_id=mine.id, **values))
        view = _subscription_view({**values})
        # Nobody's audience; the member itself and the human owners and admins read it (§17.12).
        events.emit(
            conn,
            mine.project.id,
            "ticker_subscription_changed",
            [],
            {"member_id": mine.principal_id, **view},
            actor=caller.actor(mine.id),
            subject=("member", mine.principal_id),
        )
        return idempotency.Outcome(200, "ticker_subscription", str(mine.id), view)

    return idempotency.run(engine_of(request), request, caller, action)
