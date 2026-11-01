from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

import pytest
from sqlalchemy import Engine, Insert

from maity_hub.db import (
    create_revision,
    current_revision,
    downgrade,
    head_revision,
    migrate,
    revision_id,
)


@pytest.mark.wheel
def test_migrate_reaches_head_and_is_idempotent(engine: Engine) -> None:
    assert current_revision(engine) is None
    migrate(engine)
    assert current_revision(engine) == head_revision(engine)
    migrate(engine)
    assert current_revision(engine) == head_revision(engine)


@pytest.mark.wheel
def test_every_migration_downgrades(engine: Engine) -> None:
    migrate(engine)
    downgrade(engine)
    assert current_revision(engine) is None


def test_sqlite_keeps_foreign_keys_on_after_a_migration(engine: Engine) -> None:
    """Migrations switch SQLite's foreign keys off to rebuild tables; the pooled
    connection must come back with them on, or the hub would stop enforcing them."""
    if engine.dialect.name != "sqlite":
        return
    migrate(engine)
    downgrade(engine, "0002")  # a downgrade rebuilds referenced tables
    migrate(engine)
    for _ in range(3):  # whichever pooled connection comes next
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_sqlite_keeps_the_event_seq_autoincrement_through_every_migration(engine: Engine) -> None:
    """A migration that rebuilds `event` on SQLite must keep AUTOINCREMENT, or a seq
    freed by a delete could be handed out again (0002, docs/api.md §8)."""
    if engine.dialect.name != "sqlite":
        return

    def ddl() -> str:
        with engine.connect() as conn:
            sql: str = conn.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'event'"
            ).scalar_one()
        return sql

    migrate(engine)
    assert "AUTOINCREMENT" in ddl()
    downgrade(engine, "0002")
    assert "AUTOINCREMENT" in ddl()


def test_create_revision_names_the_migration_by_time_and_slug(
    engine: Engine, tmp_path: Path
) -> None:
    """A new revision's id cannot collide with a parallel branch's: the UTC second and the
    slug, cut to the 32 characters of `alembic_version`; `tools/rechain.py` chains it."""
    from datetime import UTC, datetime

    migrations = tmp_path / "migrations"
    shutil.copytree(Path(str(files("maity_hub") / "migrations")), migrations)
    head = head_revision(engine)
    assert head is not None
    now = datetime(2026, 10, 30, 10, 25, 12, tzinfo=UTC)
    created = create_revision(engine, "Add the tasks!", migrations, now=now)
    assert created.name == "20261030102512_add_the_tasks.py"
    assert 'revision: str = "20261030102512_add_the_tasks"' in created.read_text()
    assert f'down_revision: str | None = "{head}"' in created.read_text()
    assert revision_id("x" * 80, now) == "20261030102512_" + "x" * 17
    assert len(revision_id("x" * 80, now)) == 32


def test_every_revision_id_fits_the_version_column() -> None:
    """`alembic_version.version_num` is 32 characters on PostgreSQL, which SQLite and MariaDB do
    not enforce: a longer id passes everywhere but there, and fails every test's setup."""
    import re

    pattern = re.compile(r'^(?:revision|down_revision)(?:: str(?: \| None)?)? = "([^"]+)"$', re.M)
    too_long = [
        (path.name, found)
        for path in Path(str(files("maity_hub") / "migrations" / "versions")).glob("*.py")
        for found in pattern.findall(path.read_text())
        if len(found) > 32
    ]
    assert not too_long, f"revision ids over 32 characters: {too_long}"


def test_the_profile_delete_downgrade_restores_one_handle_per_owner(engine: Engine) -> None:
    """0032 down: deleted profiles whose handle a live one took get their id appended, so
    the old `(owner_id, handle)` key holds again and is enforced."""
    from datetime import UTC, datetime

    import pytest
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from maity_hub import tables as t

    migrate(engine)
    now = datetime(2026, 10, 23, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(t.human).values(
                id="hum-o", handle="o", display_name="O", password_hash="x", created_at=now
            )
        )
        for n, deleted in (("1", now), ("2", now), ("3", None)):
            conn.execute(
                insert(t.agent_profile).values(
                    id=f"agt-{n}", owner_id="hum-o", handle="same", display_name="Same",
                    created_at=now, deleted_at=deleted, live=None if deleted else True,
                )
            )  # fmt: skip
    downgrade(engine, "0020")
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("SELECT id, handle FROM agent_profile ORDER BY id").all()
    assert [tuple(r) for r in rows] == [
        ("agt-1", "same~agt-1"),
        ("agt-2", "same~agt-2"),
        ("agt-3", "same"),
    ]
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO agent_profile (id, owner_id, handle, display_name, created_at) "
            "VALUES ('agt-4', 'hum-o', 'same', 'Same', '2026-10-23 00:00:00')"
        )


def _before(engine: Engine, revision: str) -> str:
    """The revision `revision` builds on, read from the chain: it is re-chained whenever
    a migration lands before it."""
    from alembic.script import ScriptDirectory

    from maity_hub.db import alembic_config

    down = ScriptDirectory.from_config(alembic_config(engine)).get_revision(revision).down_revision
    assert isinstance(down, str)
    return down


def _before_namespace(engine: Engine) -> str:
    """The revision 0060 builds on. Read from the chain, not written down: 0060 is
    re-chained whenever a migration lands before it."""
    from alembic.script import ScriptDirectory

    from maity_hub.db import alembic_config

    down = ScriptDirectory.from_config(alembic_config(engine)).get_revision("0060").down_revision
    assert isinstance(down, str)
    return down


def _namespace_rows(engine: Engine) -> dict[str, str]:
    """Humans a, b and c, and a project `shop` whose first owner (a) left: just before the
    namespace, without its owner column; returns the ids. Only 0060 is undone, so a run
    that stops in 0060 ends on the same revision on every database (MySQL and MariaDB
    commit each revision's DDL as it goes, SQLite and PostgreSQL roll back the run)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    ids = {h: factory.human(engine, h) for h in ("a", "b", "c")}
    ids["shop"] = factory.project(engine, "shop", owner_id=ids["a"])
    start = datetime(2026, 10, 1, tzinfo=UTC)
    with engine.begin() as conn:
        for n, (who, active) in enumerate((("a", None), ("b", True), ("c", True))):
            conn.execute(
                insert_membership(ids["shop"], ids[who], start + timedelta(days=n), active)
            )
    downgrade(engine, _before_namespace(engine))
    with engine.begin() as conn:  # a limit as the old schema stored it: slugs
        conn.execute(update(t.human).where(t.human.c.id == ids["b"]).values(
            limit_show_reason_in=["shop", "gone"]))  # fmt: skip
    return ids


def insert_membership(project_id: str, human_id: str, joined: object, active: object) -> Insert:
    from sqlalchemy import insert

    from maity_hub import tables as t

    return insert(t.membership).values(
        project_id=project_id, human_id=human_id, trust="owner", role="coder",
        role_base="coder", areas=["/"], capabilities=[], joined_at=joined, active=active,
    )  # fmt: skip


def test_the_namespace_owner_is_the_oldest_active_owner(engine: Engine) -> None:
    """0060: the creator left, so the next oldest active owner holds the namespace; a
    limit's `show_reason_in` names full names."""
    from sqlalchemy import select

    from maity_hub import tables as t

    ids = _namespace_rows(engine)
    migrate(engine)
    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.id == ids["shop"])).one()
        shown = conn.execute(
            select(t.human.c.limit_show_reason_in).where(t.human.c.id == ids["b"])
        ).scalar()
    assert project.owner_id == ids["b"]
    assert shown == ["b/shop"]


def test_the_namespace_migration_stops_on_a_project_without_an_active_human_owner(
    engine: Engine,
) -> None:
    import pytest
    from sqlalchemy import update

    from maity_hub import tables as t

    _namespace_rows(engine)
    with engine.begin() as conn:
        conn.execute(update(t.membership).values(active=None))
    with pytest.raises(Exception, match="no human with an active owner membership in: shop"):
        migrate(engine)
    # 0060 checks before it changes anything, so a stop leaves no half schema.
    assert current_revision(engine) == _before_namespace(engine)


def test_trust_and_role_maps_every_stored_role_and_token_both_ways(engine: Engine) -> None:
    """0067 (§2.3, #419): memberships, invitations, joins and the stored tokens, written
    in the new model, go down to the single role and come back."""
    from datetime import timedelta

    from sqlalchemy import insert, select

    from maity_hub import clock
    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    now = clock.now()
    project = factory.project(
        engine, "split", settings={"onboarding": {"check_in_with": "trust:admin"}}
    )
    owner = factory.human(engine, "boss")
    owner_row = factory.membership(engine, project, "owner", human_id=owner)
    # An owner whose role is not coder stays an owner on the way down.
    designer = factory.membership(
        engine, project, "designer", trust="owner", human_id=factory.human(engine, "maker")
    )
    seats = {
        "admin": ("admin", "coder"),
        "proxy": ("admin", "proxy"),
        "reviewer": ("member", "reviewer"),
        "coder": ("member", "coder"),
        "tester": ("member", "tester"),
        "guest": ("guest", "reviewer"),
    }
    agents = {
        name: factory.agent(engine, project, owner, role, trust=trust)
        for name, (trust, role) in seats.items()
    }
    with engine.begin() as conn:
        conn.execute(
            t.project.update()
            .where(t.project.c.id == project)
            .values(contract_arbiter="trust:admin", coordinator="trust:admin")
        )
        conn.execute(
            t.membership.update()
            .where(t.membership.c.id == agents["coder"].membership_id)
            .values(
                availability_policy={
                    "on_unavailable": "substitute",
                    "substitutes": ["trust:admin", "role:reviewer", "role:coder"],
                    "grace_minutes": 15,
                }
            )
        )
        conn.execute(
            insert(t.event).values(
                project_id=project, kind="message", at=now, payload={}, redacted=False,
                audience=["trust:owner", "trust:admin", "role:coder", "role:reviewer", "all"],
            )
        )  # fmt: skip
        conn.execute(
            insert(t.request).values(
                id="req-split", project_id=project, title="Which?", options=[],
                priority="normal", to_kind="role", to_role="trust:admin",
                asked_by=agents["coder"].membership_id, while_open="wait", status="open",
                created_at=now, forwarding=[{"to": "trust:admin"}],
                proposal={"kind": "member_change", "action": "patch",
                          "values": {"trust": "guest", "role": "coder",
                                     "availability_policy": {"substitutes": ["trust:admin"]}}},
                **{"class": "decision"},
            )
        )  # fmt: skip
        for n, values in enumerate(({"role": "tester"}, {"trust": "member"})):
            conn.execute(
                insert(t.request).values(
                    id=f"req-half-{n}", project_id=project, title="Change", options=[],
                    priority="normal", to_kind="owner", asked_by=agents["admin"].membership_id,
                    while_open="wait", status="open", created_at=now, **{"class": "consent"},
                    proposal={"kind": "member_change", "action": "patch",
                              "membership_id": agents["reviewer"].membership_id,
                              "values": values},
                )
            )  # fmt: skip
        conn.execute(
            insert(t.invitation).values(
                id="inv-split", project_id=project, trust="admin", role="coder",
                token_hash="a" * 64, created_by=owner, created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )  # fmt: skip
    card = factory.card(engine, project, owner_row, contract={"arbiter": "trust:admin"})

    downgrade(engine, _before(engine, "0067"))
    with engine.connect() as conn:
        old: dict[int, str] = {
            r[0]: r[1] for r in conn.exec_driver_sql("SELECT id, role FROM membership")
        }
        assert old[owner_row] == old[designer] == "owner"
        proposal = conn.execute(
            select(t.request.c.proposal).where(t.request.c.id == "req-split")
        ).scalar()
        assert proposal is not None
        assert proposal["values"]["availability_policy"] == {"substitutes": ["role:" + "admin"]}
        # Fail closed: an open member_change consent is withdrawn, never applied in the
        # single role with a trust × role value.
        statuses = dict(
            conn.execute(
                select(t.request.c.id, t.request.c.status).where(
                    t.request.c.id.in_(["req-split", "req-half-0", "req-half-1"])
                )
            ).all()
        )
        assert set(statuses.values()) == {"withdrawn"}
        # Fail closed: the guest is removed and its credential revoked, never a member.
        guest = conn.execute(
            select(t.membership.c.active).where(t.membership.c.id == agents["guest"].membership_id)
        ).scalar()
        assert guest is None
        revoked = conn.execute(
            select(t.credential.c.revoked_at).where(
                t.credential.c.membership_id == agents["guest"].membership_id
            )
        ).scalar()
        assert revoked is not None
        expected = {
            "admin": "admin", "proxy": "proxy", "reviewer": "reviewer", "coder": "member",
            "tester": "member", "guest": "member",
        }  # fmt: skip
        for name, role in expected.items():
            assert old[agents[name].membership_id] == role
        assert conn.exec_driver_sql("SELECT role FROM invitation").scalar() == "admin"
        row = conn.execute(select(t.project.c.contract_arbiter, t.project.c.coordinator)).one()
        assert tuple(row) == ("role:" + "admin", "role:" + "admin")  # the old tokens
        audience = conn.execute(select(t.event.c.audience).where(t.event.c.kind == "message"))
        assert audience.scalar() == [
            "role:" + "owner",
            "role:" + "admin",
            "role:" + "member",
            "role:reviewer",
            "all",
        ]
        request = conn.exec_driver_sql(
            "SELECT to_role FROM request WHERE id = 'req-split'"
        ).scalar()
        assert request == "admin"

    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(select(t.membership.c.id, t.membership.c.trust, t.membership.c.role))
        back = {r.id: (r.trust, r.role) for r in rows}
        assert back[owner_row] == back[designer] == ("owner", "coder")
        proposal = conn.execute(
            select(t.request.c.proposal).where(t.request.c.id == "req-split")
        ).scalar()
        # Withdrawn on the way down, the consent keeps its values as they were.
        assert proposal is not None and proposal["values"] == {
            "trust": "guest",
            "role": "coder",
            "availability_policy": {"substitutes": ["trust:admin"]},
        }
        for name in ("admin", "proxy", "reviewer", "coder"):
            assert back[agents[name].membership_id] == seats[name]
        # What the single role could not hold comes back as a member coder.
        assert back[agents["tester"].membership_id] == ("member", "coder")
        assert back[agents["guest"].membership_id] == ("member", "coder")
        row = conn.execute(select(t.project)).one()
        assert (row.contract_arbiter, row.coordinator) == ("trust:admin", "trust:admin")
        assert row.settings["onboarding"]["check_in_with"] == "trust:admin"
        cover = conn.execute(
            select(t.membership.c.availability_policy).where(
                t.membership.c.id == agents["coder"].membership_id
            )
        ).scalar()
        assert cover is not None and cover["substitutes"] == [
            "trust:admin",
            "role:reviewer",
            "role:coder",
        ]
        audience = conn.execute(select(t.event.c.audience).where(t.event.c.kind == "message"))
        assert audience.scalar() == [
            "trust:owner",
            "trust:admin",
            "role:coder",
            "role:reviewer",
            "all",
        ]
        request = conn.execute(
            select(t.request.c.to_role, t.request.c.forwarding).where(t.request.c.id == "req-split")
        ).one()
        assert (request.to_role, request.forwarding) == ("trust:admin", [{"to": "trust:admin"}])
        invitation = conn.execute(select(t.invitation.c.trust, t.invitation.c.role)).one()
        assert tuple(invitation) == ("admin", "coder")
        contract = conn.execute(select(t.card.c.contract).where(t.card.c.id == card)).scalar()
        assert contract == {"arbiter": "trust:admin"}


def test_a_placement_profile_splits_its_role() -> None:
    """0067 on a placement's `new_profile`, a JSON column the hub reads at the pickup."""
    import importlib.util

    path = files("maity_hub") / "migrations" / "versions" / "0067_trust_and_role.py"
    spec = importlib.util.spec_from_file_location("m0067", str(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    up = module._profile_up({"display_name": "X", "role": "admin", "areas": []})
    assert up == {"display_name": "X", "trust": "admin", "role": "coder", "areas": []}
    assert module._profile_down(up) == {"display_name": "X", "role": "admin", "areas": []}
    assert module._profile_up(None) is None


def test_settings_stored_for_removed_notification_kinds_are_deleted(engine: Engine) -> None:
    """0084 (§18.4): the kinds removed on 2026-10-26 leave `browser.kinds`,
    `browser.content` and `email.kinds`; the four that exist, and a row with nothing to
    delete, stay as they were."""
    from sqlalchemy import insert, select

    from maity_hub import clock
    from maity_hub import tables as t
    from tests import factory

    migrate(engine, _before(engine, "0084"))
    old = {
        "browser": {
            "enabled": True,
            "kinds": {"card": True, "chat": False},
            "content": {"chat": True, "agent": True},
        },
        "email": {
            "kinds": {"ticker": {"mode": "off"}, "inbox": {"mode": "daily"}},
            "language": "de",
        },
    }
    clean = {"email": {"kinds": {"security": {"mode": "off"}}}}
    owners = {"old": factory.human(engine, "old"), "clean": factory.human(engine, "clean")}
    with engine.begin() as conn:
        for name, stored in (("old", old), ("clean", clean)):
            conn.execute(
                insert(t.notification_settings).values(
                    human_id=owners[name],
                    preferences=stored,
                    address_status="none",
                    epoch=0,
                    hard_failures=0,
                    updated_at=clock.now(),
                )
            )
    migrate(engine)
    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                select(t.notification_settings.c.human_id, t.notification_settings.c.preferences)
            ).all()
        )
    assert rows[owners["old"]] == {
        "browser": {"enabled": True, "kinds": {"chat": False}, "content": {"chat": True}},
        "email": {"kinds": {"inbox": {"mode": "daily"}}, "language": "de"},
    }
    assert rows[owners["clean"]] == clean


def test_the_old_landing_body_is_carried_into_the_first_section_page(engine: Engine) -> None:
    """0090 (§16.7): the title, call to action and Markdown of the one-body landing become
    the `en` page, a `hero` and a `text` section; a landing that held nothing stays off,
    and going back restores the old columns from that page."""
    import sqlalchemy as sa

    migrate(engine, _before(engine, "0090"))
    old = sa.table(
        "instance_landing",
        sa.column("id", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("title", sa.String),
        sa.column("markdown", sa.Text),
        sa.column("cta", sa.JSON),
        sa.column("updated_at", sa.DateTime),
        sa.column("updated_by", sa.String),
    )
    from maity_hub import clock

    cta = {"label": "Sign in", "href": "/login"}
    with engine.begin() as conn:
        conn.execute(
            sa.insert(old).values(
                id="landing",
                enabled=True,
                title="Bring your agent",
                markdown="# Hi",
                cta=cta,
                updated_at=clock.now(),
                updated_by=None,
            )
        )
    migrate(engine)
    new = sa.table(
        "instance_landing",
        sa.column("enabled", sa.Boolean),
        sa.column("default_language", sa.String),
        sa.column("pages", sa.JSON),
        sa.column("footer", sa.JSON),
    )
    with engine.connect() as conn:
        row = conn.execute(sa.select(new)).one()
    assert (row.enabled, row.default_language, row.footer) == (True, "en", None)
    assert row.pages == {
        "en": {
            "title": "Bring your agent",
            "description": "",
            "sections": [
                {
                    "type": "hero",
                    "enabled": True,
                    "title": "Bring your agent",
                    "cta_primary": cta,
                },
                {"type": "text", "enabled": True, "markdown": "# Hi"},
            ],
        }
    }
    downgrade(engine, _before(engine, "0090"))
    with engine.connect() as conn:
        back = conn.execute(sa.select(old.c.enabled, old.c.title, old.c.markdown, old.c.cta)).one()
    assert tuple(back) == (True, "Bring your agent", "# Hi", cta)


def test_a_landing_that_held_nothing_stays_off_and_empty(engine: Engine) -> None:
    import sqlalchemy as sa

    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(sa.text("select count(*) from instance_landing")).scalar() == 0
        assert conn.execute(sa.text("select count(*) from legal_page")).scalar() == 0


@pytest.mark.parametrize(
    ("title", "markdown", "cta", "kinds", "page_title"),
    [
        ("Hello", "Body", None, ["text"], "Hello"),  # a title alone is the page's title
        (None, "Body", {"label": "Go", "href": "/login"}, ["text"], "Maity"),  # no title: no hero
        ("Hello", None, {"label": "Go", "href": "/login"}, ["hero"], "Hello"),
        ("Hello", "Body", {"label": "Go", "href": "/login"}, ["hero", "text"], "Hello"),
        (None, "Body", None, ["text"], "Maity"),
    ],
)
def test_a_carried_landing_passes_the_checks_of_the_setting(
    engine: Engine,
    title: str | None,
    markdown: str | None,
    cta: dict[str, str] | None,
    kinds: list[str],
    page_title: str,
) -> None:
    """0090 must never make a hero the setting itself would refuse: a hero needs a title and
    a call to action, and the old schema allowed either to be null (§16.7)."""
    import sqlalchemy as sa

    from maity_hub import clock, landing

    migrate(engine, _before(engine, "0090"))
    old = sa.table(
        "instance_landing",
        sa.column("id", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("title", sa.String),
        sa.column("markdown", sa.Text),
        sa.column("cta", sa.JSON),
        sa.column("updated_at", sa.DateTime),
        sa.column("updated_by", sa.String),
    )
    with engine.begin() as conn:
        conn.execute(
            sa.insert(old).values(
                id="landing",
                enabled=True,
                title=title,
                markdown=markdown,
                cta=cta,
                updated_at=clock.now(),
                updated_by=None,
            )
        )
    migrate(engine)
    new = sa.table(
        "instance_landing", sa.column("pages", sa.JSON), sa.column("enabled", sa.Boolean)
    )
    with engine.connect() as conn:
        row = conn.execute(sa.select(new)).one()
    page = row.pages["en"]
    assert page["title"] == page_title and [s["type"] for s in page["sections"]] == kinds
    current = {
        "enabled": False,
        "default_language": "en",
        "pages": {},
        "footer": {"operator": None, "social": []},
        "variants": {},
        "campaigns": [],
    }
    checked = landing.check({"enabled": True, "pages": row.pages}, current)
    assert checked["pages"] == row.pages  # the editor can write it back unchanged


def test_the_states_before_2026_10_27_are_mapped_once(engine: Engine) -> None:
    """0094 (§6.1): `freeze` and `fixes-only` become `review`, `accepted` becomes `archived`,
    `build` and `archived` stay; downgrading maps `review` back to `freeze`."""
    from sqlalchemy import select

    from maity_hub import tables as t
    from tests import factory

    migrate(engine, _before(engine, "0094"))
    old = ("build", "freeze", "fixes-only", "accepted", "archived")
    ids = {state: factory.project(engine, f"p-{state}", state=state) for state in old}

    def states() -> dict[str, str]:
        with engine.connect() as conn:
            return dict(conn.execute(select(t.project.c.id, t.project.c.state)).all())

    migrate(engine)
    assert states() == {
        ids["build"]: "build",
        ids["freeze"]: "review",
        ids["fixes-only"]: "review",
        ids["accepted"]: "archived",
        ids["archived"]: "archived",
    }
    downgrade(engine, _before(engine, "0094"))
    assert states()[ids["freeze"]] == "freeze" and states()[ids["accepted"]] == "archived"


def test_the_org_alias_downgrade_drops_what_the_old_check_cannot_hold(engine: Engine) -> None:
    from datetime import UTC, datetime

    from sqlalchemy import insert, text

    from maity_hub import tables as t

    migrate(engine)
    now = datetime(2026, 11, 1, tzinfo=UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(t.human).values(
                id="hum-o", handle="o", display_name="O", password_hash="x", created_at=now
            )
        )
        conn.execute(
            insert(t.org).values(id="org-o", handle="new", display_name="O", created_at=now)
        )
        for values in ({"org_id": "org-o", "handle": "old"}, {"human_id": "hum-o", "handle": "p"}):
            conn.execute(insert(t.handle_alias).values(**values, scope="human", created_at=now))
    downgrade(engine, _before(engine, "20261101050000_org_alias"))
    with engine.connect() as conn:
        left = conn.execute(text("SELECT handle FROM handle_alias")).scalars().all()
    assert left == ["p"]


def test_a_project_with_a_found_release_tag_is_released_by_0097(engine: Engine) -> None:
    """0097 (§6.1): `released_at` from the earliest found tag of a release; a missing tag,
    a tag of no release and a project without either stay `null`."""
    from datetime import UTC, datetime

    from sqlalchemy import insert, select

    from maity_hub import tables as t
    from tests import factory

    migrate(engine, _before(engine, "0097"))
    ids = {name: factory.project(engine, name) for name in ("two", "missing", "other", "none")}
    early, late = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC)
    tags = [
        ("two", "0.1.0", "v0.1.0", True, late),
        ("two", "0.2.0", "v0.2.0", True, early),
        ("missing", "0.1.0", "v0.1.0", False, early),
        ("other", "0.1.0", "v9.0.0", True, early),
    ]
    maker = factory.human(engine, "maker")
    members = {name: factory.membership(engine, ids[name], human_id=maker) for name in ids}
    for name, version, _ref, _found, _at in tags:
        factory.card(
            engine, ids[name], members[name], kind="release", title=version,
            release_version=version,
        )  # fmt: skip
    with engine.begin() as conn:
        for name, _version, ref, found, at in tags:
            conn.execute(
                insert(t.forge_observation).values(
                    project_id=ids[name], kind="tag", ref=ref, observed_at=at,
                    data={"name": ref, "sha": None, "found": found},
                )
            )  # fmt: skip
    migrate(engine)
    with engine.connect() as conn:
        released = dict(conn.execute(select(t.project.c.id, t.project.c.released_at)).all())
    assert released[ids["two"]] == early
    assert released[ids["missing"]] is None and released[ids["other"]] is None
    assert released[ids["none"]] is None


def test_cards_are_written_in_the_one_shape_the_code_reads(engine: Engine) -> None:
    """0101: a reported card without `reported_instances` gets the instance of its report,
    a contract without a place gets the default place; nothing else is touched."""
    from sqlalchemy import select, update

    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    human_id = factory.human(engine, "a")
    project_id = factory.project(engine, "shop", owner_id=human_id)
    membership_id = factory.membership(engine, project_id, "owner", human_id=human_id)
    report = {"reported_by": "agt-x", "reported_instance": "ab12"}
    old_report = factory.card(engine, project_id, membership_id, report=report)
    new_report = factory.card(
        engine,
        project_id,
        membership_id,
        report=report,
        reported_instances=[{"member_id": "agt-y", "instance": "cd34"}],
    )
    unreported = factory.card(engine, project_id, membership_id)
    bare = {"arbiter": "trust:admin", "state": "proposed", "watchers": []}
    old_contract = factory.card(engine, project_id, membership_id, kind="contract", contract=bare)
    placed = {**bare, "path": "docs/other.md", "section": "2.1"}
    new_contract = factory.card(engine, project_id, membership_id, kind="contract", contract=placed)
    downgrade(engine, "0100")
    with engine.begin() as conn:
        conn.execute(
            update(t.card).where(t.card.c.id == old_report).values(reported_instances=None)
        )
    migrate(engine)
    with engine.connect() as conn:
        found = {
            r.id: r for r in conn.execute(select(t.card).where(t.card.c.project_id == project_id))
        }
    assert found[old_report].reported_instances == [{"member_id": "agt-x", "instance": "ab12"}]
    assert found[new_report].reported_instances == [{"member_id": "agt-y", "instance": "cd34"}]
    assert found[unreported].reported_instances is None
    assert found[old_contract].contract == {**bare, "path": "docs/api.md", "section": None}
    assert found[new_contract].contract == placed


def test_an_older_setup_gets_the_ci_and_dashboard_options_as_not_chosen(engine: Engine) -> None:
    """0107: a project's `setup` from before `keep_the_why_ci`, `keep_the_why_dashboard`
    and `dashboard_path` gets them as `false`, `false` and `null` (nothing was chosen);
    a project without `setup` keeps `null`; the downgrade takes the three keys away."""
    from sqlalchemy import select, update

    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    old = {"keep_the_why_init": True, "keep_the_why_badge": False, "maity_badge": True}
    with_cards = factory.project(engine, "cards")
    without = factory.project(engine, "plain")
    none = factory.project(engine, "none")
    downgrade(engine, "0102")
    with engine.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == with_cards)
            .values(setup={**old, "cards": ["tsk-1"]})
        )
        conn.execute(
            update(t.project).where(t.project.c.id == without).values(setup={**old, "cards": None})
        )
        conn.execute(update(t.project).where(t.project.c.id == none).values(setup=None))
    migrate(engine)
    added = {"keep_the_why_ci": False, "keep_the_why_dashboard": False, "dashboard_path": None}
    with engine.connect() as conn:
        found = dict(conn.execute(select(t.project.c.id, t.project.c.setup)).all())
    assert found[with_cards] == {**old, **added, "cards": ["tsk-1"]}
    assert found[without] == {**old, **added, "cards": None}
    assert found[none] is None
    downgrade(engine, "0102")
    with engine.connect() as conn:
        found = dict(conn.execute(select(t.project.c.id, t.project.c.setup)).all())
    assert found[with_cards] == {**old, "cards": ["tsk-1"]}
    assert found[none] is None


def test_project_roles_give_every_membership_its_base_and_go_back_to_it(engine: Engine) -> None:
    """0112: every membership so far holds a built-in role and gets it as `role_base`; the
    downgrade turns a project role into its base wherever it is named."""
    from sqlalchemy import select, update

    from maity_hub import tables as t
    from tests import factory

    migrate(engine)
    human = factory.human(engine, "a")
    project_id = factory.project(engine, "shop", owner_id=human)
    downgrade(engine, _before(engine, "0112"))
    reviewer = factory.membership(
        engine, project_id, role="reviewer", human_id=factory.human(engine, "b")
    )
    migrate(engine)
    with engine.connect() as conn:
        bases = dict(conn.execute(select(t.membership.c.id, t.membership.c.role_base)).all())
    assert bases[reviewer] == "reviewer"
    assert set(bases.values()) <= {"coder", "reviewer"}
    with engine.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(
                roles=[
                    {
                        "name": "legal",
                        "base": "reviewer",
                        "description": "",
                        "guide": "",
                        "guide_by": None,
                    }
                ]
            )
        )
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == reviewer)
            .values(role="legal", role_base="reviewer")
        )
    downgrade(engine, _before(engine, "0112"))
    with engine.connect() as conn:
        role = conn.execute(
            select(t.membership.c.role).where(t.membership.c.id == reviewer)
        ).scalar_one()
    assert role == "reviewer"


def test_a_human_with_the_meat_proxy_switch_on_gets_both_parts_by_0103(engine: Engine) -> None:
    """0103 (§5.2): `meat_proxy` true becomes both parts true, false both false; downgrading
    makes the switch the or of the parts."""
    from sqlalchemy import text

    from tests import factory

    migrate(engine, _before(engine, "0103"))
    on, off = factory.human(engine, "on"), factory.human(engine, "off")
    with engine.begin() as conn:
        conn.execute(text("UPDATE human SET meat_proxy = :v WHERE id = :id"), {"v": True, "id": on})

    def parts() -> dict[str, tuple[bool, bool]]:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, meat_proxy_lead, meat_proxy_hands FROM human")
            ).all()
        return {r[0]: (bool(r[1]), bool(r[2])) for r in rows}

    migrate(engine)
    assert parts()[on] == (True, True) and parts()[off] == (False, False)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE human SET meat_proxy_hands = :v WHERE id = :id"), {"v": False, "id": on}
        )
    downgrade(engine, _before(engine, "0103"))
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, meat_proxy FROM human")).all()
    switch = {r[0]: bool(r[1]) for r in rows}
    assert switch[on] is True and switch[off] is False


def test_the_single_schedule_becomes_one_series_with_its_rounds_and_grants(
    engine: Engine,
) -> None:
    """20261031190604 (§20.1, "From the single schedule"): a project with `policy.jour_fixe` gets
    one series, `circle: all`, topic "How we work", its schedule, its rounds and `created_by`
    the human of the last change; the admin agents get the right, at once when their owner set
    the policy, else pending; a project with rounds but no policy gets a disabled series; one
    `jour_fixe_series_changed` and one rules bump each. The downgrade puts the schedule back."""
    from datetime import UTC, datetime

    import sqlalchemy as sa
    from sqlalchemy import text

    from maity_hub import tables as t
    from maity_hub.types import JSON_VALUE
    from tests import factory

    revision = "20261031190604_jour_fixe_series"
    migrate(engine, _before(engine, revision))
    scheduled = factory.project(engine, "scheduled")
    by_hand = factory.project(engine, "byhand")
    with engine.connect() as conn:
        setter = conn.execute(text("SELECT id FROM human WHERE handle = 'maintainer'")).scalar_one()
    other = factory.human(engine, "otter")
    factory.membership(engine, scheduled, "owner", human_id=setter)
    factory.membership(engine, scheduled, "owner", human_id=other)
    own = factory.agent(engine, scheduled, setter, "admin", trust="admin", with_session=False)
    foreign = factory.agent(engine, scheduled, other, "admin", trust="admin", with_session=False)
    policy = {
        "enabled": True,
        "recurrence": {"freq": "daily"},
        "time": "10:00",
        "timezone": "UTC",
        "moderator": "admin_agent",
        "answer_window_minutes": 90,
        "step_window_minutes": 120,
        "report_window_hours": 12,
    }
    now = datetime.now(UTC)
    project = sa.table("project", sa.column("id"), sa.column("jour_fixe", JSON_VALUE))
    with engine.begin() as conn:
        conn.execute(project.update().where(project.c.id == scheduled).values(jour_fixe=policy))
        conn.execute(
            t.event.insert().values(
                project_id=scheduled,
                kind="policy_changed",
                at=now,
                actor_human_id=setter,
                audience=["all"],
                payload={"old": {"jour_fixe": None}, "new": {"jour_fixe": policy}},
                redacted=False,
            )
        )
        for n, project_id in enumerate((scheduled, by_hand)):
            conn.execute(
                t.jour_fixe_round.insert().values(
                    id=f"jfx-old{n}",
                    project_id=project_id,
                    status="reported",
                    trigger="manual",
                    mode="message",
                    scheduled_for=now,
                    steps=[],
                    invited=[],
                    absent=[],
                    answers_received=0,
                    posts=[],
                    created_at=now,
                )
            )
    migrate(engine)
    with engine.connect() as conn:
        series = {r.project_id: r for r in conn.execute(sa.select(t.jour_fixe_series)).all()}
        assert series[scheduled].topic == "How we work" and series[scheduled].circle == "all"
        assert series[scheduled].enabled is True and series[scheduled].created_by == setter
        assert series[scheduled].config["answer_window_minutes"] == 90
        assert series[by_hand].enabled is False and series[by_hand].created_by is None
        rounds_of = dict(
            conn.execute(sa.select(t.jour_fixe_round.c.id, t.jour_fixe_round.c.series_id)).all()
        )
        assert rounds_of == {"jfx-old0": series[scheduled].id, "jfx-old1": series[by_hand].id}
        grants = {
            r.membership_id: r.state
            for r in conn.execute(
                sa.select(t.jour_fixe_moderator).where(
                    t.jour_fixe_moderator.c.series_id == series[scheduled].id
                )
            )
        }
        assert grants == {own.membership_id: "active", foreign.membership_id: "pending"}
        changed = conn.execute(
            sa.select(t.event.c.project_id, t.event.c.payload).where(
                t.event.c.kind == "jour_fixe_series_changed"
            )
        ).all()
        assert {r.project_id for r in changed} == {scheduled, by_hand}
        assert all(r.payload["change"] == "created" and r.payload["by"] is None for r in changed)
    downgrade(engine, _before(engine, revision))
    with engine.connect() as conn:
        restored = conn.execute(
            sa.select(project.c.jour_fixe).where(project.c.id == scheduled)
        ).scalar_one()
    assert restored["time"] == "10:00" and restored["moderator"] == "admin_agent"


def test_an_account_with_a_verified_or_disabled_address_counts_as_having_had_one(
    engine: Engine,
) -> None:
    """20261031191500 (§2.8.8): the flag "ever verified" is set for `verified` and `disabled`
    addresses at the upgrade, so no such account falls under "never had one"."""
    from sqlalchemy import select

    from maity_hub import clock
    from maity_hub import tables as t
    from tests import factory

    migrate(engine, _before(engine, "20261031191500_mail_factor"))
    humans = {
        status: factory.human(engine, f"h-{status}")
        for status in ("none", "pending", "verified", "disabled")
    }
    with engine.begin() as conn:
        for status, human_id in humans.items():
            conn.execute(
                t.notification_settings.insert().values(
                    human_id=human_id,
                    preferences={},
                    address_status=status,
                    epoch=0,
                    hard_failures=0,
                    updated_at=clock.now(),
                )
            )
    migrate(engine)
    with engine.connect() as conn:
        flags = {
            row.address_status: row.address_ever_verified
            for row in conn.execute(
                select(
                    t.notification_settings.c.address_status,
                    t.notification_settings.c.address_ever_verified,
                )
            )
        }
    assert flags == {"none": False, "pending": False, "verified": True, "disabled": True}
