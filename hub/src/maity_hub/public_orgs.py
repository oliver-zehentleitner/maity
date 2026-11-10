"""An organisation's public page (docs/api.md §16.9): its name, its handle and its projects that
have a page. Who belongs to it is not public, so its members are never read here."""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from html import escape
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, moderation, namespace, public_pages, public_projects, render
from maity_hub import tables as t
from maity_hub.config import Settings

KIND = "organisation"


def served(conn: Connection, org: Any) -> bool:
    return bool(
        org.public_page == "on"
        and org.deleted_at is None
        and moderation.hold(conn, "org", org.id) is None
    )


def render_org(conn: Connection, hub: Settings, org_id: str) -> list[public_pages.Page]:
    org = conn.execute(select(t.org).where(t.org.c.id == org_id)).first()
    if org is None or not served(conn, org):
        return []
    projects = sorted(
        (namespace.full_name(conn, project), project.name)
        for project in conn.execute(
            select(t.project).where(
                t.project.c.owner_org_id == org.id, t.project.c.public_page == "on"
            )
        )
        if public_projects.served(conn, project)
    )
    items = "".join(
        f'<li><a href="/{escape(full, quote=True)}">{escape(name)}</a></li>'
        for full, name in projects
    )
    content = f'<p class="eyebrow">{escape(org.handle)}</p><h1>{escape(org.display_name)}</h1>' + (
        f"<h2>Projects</h2><ul>{items}</ul>" if items else ""
    )
    path = f"/{org.handle}"
    digest = hashlib.sha256("\x00".join((path, org.display_name, content)).encode())
    return [
        public_pages.Page(
            path=path,
            body=render.page_document(
                lang="en",
                title=f"{org.display_name} ({org.handle})",
                canonical=f"{hub.public_url.rstrip('/')}{path}",
                content=content,
            ),
            inputs=digest.hexdigest(),
            lastmod=clock.now(),
            view="organisation_page",
            data={
                "name": org.display_name,
                "handle": org.handle,
                "projects": [{"name": name, "full_name": full} for full, name in projects],
            },
        )
    ]


def targets(conn: Connection, among: Collection[str] | None = None) -> list[str]:
    return list(
        conn.execute(
            select(t.org.c.id)
            .where(t.org.c.public_page == "on", *public_pages.only(t.org.c.id, among))
            .order_by(t.org.c.id)
        ).scalars()
    )


public_pages.register(public_pages.Kind(KIND, render_org, targets))
