from __future__ import annotations

import shutil
from importlib.resources import files
from pathlib import Path

import pytest
from sqlalchemy import Engine, Insert

from maity_hub.db import create_revision, current_revision, downgrade, head_revision, migrate


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


def test_create_revision_numbers_the_next_migration(engine: Engine, tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(str(files("maity_hub") / "migrations")), migrations)
    head = head_revision(engine)
    assert head is not None
    # The highest number plus one, not the head's: numbers are reserved ahead, so a
    # revision chained later may carry a lower number than one merged before it.
    numbers = [int(p.name[:4]) for p in (migrations / "versions").glob("[0-9]*.py")]
    following = f"{max(numbers) + 1:04d}"
    created = create_revision(engine, "add the task table", migrations)
    assert created.name == f"{following}_add_the_task_table.py"
    assert f'revision: str = "{following}"' in created.read_text()
    assert f'down_revision: str | None = "{head}"' in created.read_text()


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
        project_id=project_id, human_id=human_id, trust="owner", role="coder", areas=["/"],
        capabilities=[], joined_at=joined, active=active,
    )  # fmt: skip


def test_the_namespace_owner_is_the_oldest_active_owner(engine: Engine) -> None:
    """0060: the creator left, so the next oldest active owner holds the namespace; the
    slug is kept as `legacy_slug`; a limit's `show_reason_in` names full names."""
    from sqlalchemy import select

    from maity_hub import tables as t

    ids = _namespace_rows(engine)
    migrate(engine)
    with engine.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.id == ids["shop"])).one()
        shown = conn.execute(
            select(t.human.c.limit_show_reason_in).where(t.human.c.id == ids["b"])
        ).scalar()
    assert (project.owner_id, project.legacy_slug) == (ids["b"], "shop")
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
    seats = {
        "admin": ("admin", "coder"),
        "proxy": ("admin", "proxy"),
        "reviewer": ("member", "reviewer"),
        "coder": ("member", "coder"),
        "tester": ("member", "tester"),
        "guest": ("guest", "designer"),
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
                **{"class": "decision"},
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
        assert old[owner_row] == "owner"
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
        request = conn.exec_driver_sql("SELECT to_role FROM request").scalar()
        assert request == "admin"

    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(select(t.membership.c.id, t.membership.c.trust, t.membership.c.role))
        back = {r.id: (r.trust, r.role) for r in rows}
        assert back[owner_row] == ("owner", "coder")
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
        request = conn.execute(select(t.request.c.to_role, t.request.c.forwarding)).one()
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
