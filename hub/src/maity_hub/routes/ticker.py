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
from sqlalchemy import Connection, select

from maity_hub import clock, events, idempotency, ticker
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.models import Strict
from maity_hub.namespace import ProjectRoute
from maity_hub.ratelimit import Limiter
from maity_hub.views import event_views

router = APIRouter(route_class=ProjectRoute)

PAGE_MAX = 200

# §17.6: at most 20 manual posts per membership per hour, of them 5 to everyone.
POSTS = Limiter(20, 3600, name="routes.ticker.POSTS")
POSTS_TO_ALL = Limiter(5, 3600, name="routes.ticker.POSTS_TO_ALL")
URL_MAX = 2048
TOKENS_MAX = 20
AREAS_MAX = 20
ENVIRONMENT_MAX = ticker.ENVIRONMENT_MAX
TOKEN = re.compile(r"^(member|role|trust|area):\S{1,255}$")


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
    elif kind in ("merge", "decision", "rename"):
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
    wait, mark = POSTS.place(key)
    if wait:
        raise rate_limited(wait)
    events.on_rollback(conn, lambda: POSTS.release(key, mark))
    if to_all:
        wait, to_all_mark = POSTS_TO_ALL.place(key)
        if wait:
            raise rate_limited(wait)
        events.on_rollback(conn, lambda: POSTS_TO_ALL.release(key, to_all_mark))


@router.post("/projects/{owner}/{slug}/ticker")
def post_item(slug: str, body: PostIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("ticker:post")
        card = _check(conn, mine, body)
        to = body.to if "to" in body.model_fields_set else "computed"
        kind = body.type
        people = ticker.members(conn, mine.project.id)
        facts: dict[str, Any] = {}
        key: str | None = None
        if kind == "note":
            facts["areas"] = list(body.areas or [])
        if kind == "release":
            version = (card.release_data or {}).get("version") or card.release_version or ""
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
        audience = ticker.manual_audience(conn, people, kind, to, facts.get("areas", []))
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
        row = conn.execute(select(t.event).where(t.event.c.seq == seq)).one()
        view = event_views(conn, [row], mine)[0]
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


def _cursor(seq: int, filters: str, ascending: bool) -> str:
    raw = json.dumps([seq, filters, "asc" if ascending else "desc"])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _uncursor(text: str, filters: str) -> tuple[int, bool]:
    """(seq, ascending): a cursor goes on in the order its page was in, for one filter set."""
    try:
        seq, made_for, order = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
    if made_for != filters or not isinstance(seq, int) or order not in ("asc", "desc"):
        raise invalid({"cursor": "invalid"}, "a cursor is valid for one filter set")
    return seq, order == "asc"


@router.get("/projects/{owner}/{slug}/ticker")
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
    before: int | None = None
    after = int(raw_after) if raw_after is not None else None
    if q.get("cursor"):
        seq, ascending = _uncursor(q["cursor"], filters)
        if ascending:
            after = seq
        else:
            before = seq
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        items, more = ticker.listing(
            conn,
            mine,
            types=types,
            area=area,
            for_me=who == "me",
            since=since,
            before=before,
            after=after,
            limit=int(raw_limit),
        )
    # null only on the last page (§1.4), in either order.
    next_cursor = _cursor(items[-1]["seq"], filters, after is not None) if more else None
    return JSONResponse({"items": items, "next_cursor": next_cursor})


def _subscription_view(sub: dict[str, Any]) -> dict[str, Any]:
    return {
        "follow": {"areas": list(sub["follow"]["areas"]), "types": list(sub["follow"]["types"])},
        "mute": {"areas": list(sub["mute"]["areas"]), "types": list(sub["mute"]["types"])},
        "updated_at": clock.rfc3339(sub["updated_at"]) if sub["updated_at"] else None,
    }


def _load_subscription(conn: Connection, membership_id: str, _request: Request) -> dict[str, Any]:
    """A replay answers the subscription as it is now (§1.5)."""
    return _subscription_view(ticker.subscription_of(conn, int(membership_id)))


idempotency.LOADERS["ticker_subscription"] = _load_subscription


@router.get("/projects/{owner}/{slug}/ticker/subscription")
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


@router.patch("/projects/{owner}/{slug}/ticker/subscription")
def patch_subscription(
    slug: str, body: SubscriptionPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        # Read under the project lock: nothing is lost when one member changes it twice at once.
        current = ticker.lock_subscription(conn, mine.project.id, mine.id)
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
        ticker.store_subscription(conn, mine.id, values)
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
