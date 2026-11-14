"""`maity-hub serve` refuses a PostgreSQL role that can change the schema (a superuser, the
owner of the schema or of one of its tables, also as a member of the owner, or a role that may
create in the schema), unless MAITY_DB_ALLOW_PRIVILEGED is set; a role that only reads and
writes rows serves (hub/context/deploy-access.md, docs/install/README.md "Database roles").

The roles are made per test with unique names and dropped again; each test connects as the
suite's role and switches with `SET ROLE` on every connection, so no password is needed. The
suite's role on PostgreSQL is a superuser (CI's and hub/scripts/with_postgres.sh's)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from maity_hub import cli
from maity_hub.app import privileged_role, require_unprivileged_role
from maity_hub.cli import EXIT_CONFIG, main
from maity_hub.config import ConfigError, Settings
from maity_hub.db import make_engine


def _postgres_only(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("roles and owners are checked on PostgreSQL only")


def test_other_databases_are_not_checked(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        pytest.skip("SQLite and MariaDB only")
    assert privileged_role(engine) is None


@pytest.fixture
def scratch(engine: Engine, database_url: str) -> Iterator[Any]:
    """A schema of its own and a way to make roles and engines that act as one of them in it."""
    _postgres_only(engine)
    tag = uuid.uuid4().hex[:10]
    schema = f"t_role_{tag}"
    roles: list[str] = []
    engines: list[Engine] = []

    class Scratch:
        name = schema

        def role(self, suffix: str, *grants: str) -> str:
            role = f"t_role_{tag}_{suffix}"
            with engine.begin() as conn:
                conn.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER"))
                for grant in grants:
                    conn.execute(text(grant.format(role=role, schema=schema)))
            roles.append(role)
            return role

        def run(self, *statements: str) -> None:
            with engine.begin() as conn:
                for statement in statements:
                    conn.execute(text(statement.format(schema=schema)))

        def as_role(self, role: str, search_path: str | None = None) -> Engine:
            acting = make_engine(database_url)

            @event.listens_for(acting, "connect")
            def _act(dbapi_connection: Any, _record: Any) -> None:
                with dbapi_connection.cursor() as cursor:
                    cursor.execute(f"SET ROLE {role}")
                    cursor.execute(f"SET search_path TO {search_path or schema}")
                dbapi_connection.commit()

            engines.append(acting)
            return acting

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"CREATE TABLE {schema}.rows (id integer PRIMARY KEY)"))
    try:
        yield Scratch()
    finally:
        for acting in engines:
            acting.dispose()
        with engine.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            for role in reversed(roles):
                conn.execute(text(f"DROP OWNED BY {role}"))
                conn.execute(text(f"DROP ROLE {role}"))


USE = "GRANT USAGE ON SCHEMA {schema} TO {role}"
ROWS = "GRANT SELECT, INSERT, UPDATE, DELETE ON {schema}.rows TO {role}"


def test_a_role_that_only_reads_and_writes_rows_serves(scratch: Any) -> None:
    app = scratch.role("app", USE, ROWS)
    acting = scratch.as_role(app)
    with acting.begin() as conn:  # it can do what the hub does
        conn.execute(text("INSERT INTO rows (id) VALUES (1)"))
    assert privileged_role(acting) is None
    require_unprivileged_role(acting, _settings())


def test_the_superuser_is_refused(engine: Engine, scratch: Any) -> None:
    with engine.connect() as conn:
        user = conn.execute(text("SELECT current_user")).scalar_one()
        assert conn.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        ).scalar_one()
    assert privileged_role(engine) == f"the database role {user!r} is a superuser"


def test_the_owner_of_the_schema_is_refused(scratch: Any) -> None:
    owner = scratch.role("owner", USE)
    scratch.run(f"ALTER SCHEMA {{schema}} OWNER TO {owner}")
    assert privileged_role(scratch.as_role(owner)) == (
        f"the database role {owner!r} owns the hub's schema"
    )


def test_the_owner_of_a_table_is_refused(scratch: Any) -> None:
    owner = scratch.role("tables", USE)
    scratch.run(f"ALTER TABLE {{schema}}.rows OWNER TO {owner}")
    assert privileged_role(scratch.as_role(owner)) == (
        f"the database role {owner!r} owns tables of the hub's schema"
    )


def test_a_member_of_the_owner_is_refused(scratch: Any) -> None:
    owner = scratch.role("owner", USE)
    scratch.run(f"ALTER SCHEMA {{schema}} OWNER TO {owner}")
    member = scratch.role("member", "GRANT " + owner + " TO {role}")
    assert privileged_role(scratch.as_role(member)) == (
        f"the database role {member!r} owns the hub's schema"
    )


def test_a_member_that_does_not_inherit_but_may_switch_is_refused(scratch: Any) -> None:
    """Without INHERIT the member has none of the owner's rights as itself, but SET ROLE gives
    it all of them."""
    owner = scratch.role("owner", USE)
    scratch.run(f"ALTER SCHEMA {{schema}} OWNER TO {owner}")
    member = scratch.role(
        "member", USE, ROWS, "GRANT " + owner + " TO {role} WITH INHERIT FALSE, SET TRUE"
    )
    acting = scratch.as_role(member)
    with acting.connect() as conn:
        assert not conn.execute(
            text("SELECT pg_has_role(current_user, :owner, 'USAGE')"), {"owner": owner}
        ).scalar_one()
    assert privileged_role(acting) == f"the database role {member!r} owns the hub's schema"


def test_a_role_that_may_create_in_the_schema_is_refused(scratch: Any) -> None:
    creator = scratch.role("creator", USE, ROWS, "GRANT CREATE ON SCHEMA {schema} TO {role}")
    assert privileged_role(scratch.as_role(creator)) == (
        f"the database role {creator!r} may create objects in the hub's schema"
    )


def test_the_superuser_is_refused_without_a_current_schema(engine: Engine, scratch: Any) -> None:
    with engine.connect() as conn:
        user = conn.execute(text("SELECT current_user")).scalar_one()
    acting = scratch.as_role(user, search_path="''")
    with acting.connect() as conn:
        assert conn.execute(text("SELECT current_schema()")).scalar_one() is None
    assert privileged_role(acting) == f"the database role {user!r} is a superuser"


def test_a_row_role_without_a_current_schema_serves(scratch: Any) -> None:
    app = scratch.role("app", USE, ROWS)
    assert privileged_role(scratch.as_role(app, search_path="''")) is None


def _settings(**env: str) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "postgresql+psycopg://u:p@localhost/h",
            "MAITY_PUBLIC_URL": "https://hub.example",
            **env,
        }
    )


def test_the_refusal_names_the_way_out(scratch: Any) -> None:
    owner = scratch.role("owner", USE)
    scratch.run(f"ALTER SCHEMA {{schema}} OWNER TO {owner}")
    with pytest.raises(ConfigError) as refused:
        require_unprivileged_role(scratch.as_role(owner), _settings())
    assert "owns the hub's schema" in str(refused.value)
    assert "MAITY_DB_ALLOW_PRIVILEGED=1" in str(refused.value)
    assert '"Database roles"' in str(refused.value)


def test_the_opt_out_serves_with_a_warning(scratch: Any, caplog: pytest.LogCaptureFixture) -> None:
    owner = scratch.role("owner", USE)
    scratch.run(f"ALTER SCHEMA {{schema}} OWNER TO {owner}")
    settings = _settings(MAITY_DB_ALLOW_PRIVILEGED="1")
    assert settings.db_allow_privileged
    with caplog.at_level(logging.WARNING, logger="maity_hub.app"):
        require_unprivileged_role(scratch.as_role(owner), settings)
    assert any("MAITY_DB_ALLOW_PRIVILEGED is set" in r.getMessage() for r in caplog.records)


def test_the_flag_takes_only_a_flag() -> None:
    assert not _settings().db_allow_privileged
    with pytest.raises(ConfigError):
        _settings(MAITY_DB_ALLOW_PRIVILEGED="maybe")


# --- the serving command -------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    started: list[Any] = []
    monkeypatch.setattr(cli._Server, "run", lambda self, sockets=None: started.append(self))
    return started


def test_serve_refuses_the_superuser(
    migrated: Engine,
    database_url: str,
    served: list[Any],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _postgres_only(migrated)
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    monkeypatch.delenv("MAITY_DB_ALLOW_PRIVILEGED", raising=False)
    assert main(["serve"]) == EXIT_CONFIG
    assert "is a superuser" in capsys.readouterr().err
    assert not served


def test_serve_with_the_opt_out_starts(
    migrated: Engine,
    database_url: str,
    served: list[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _postgres_only(migrated)
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    monkeypatch.setenv("MAITY_DB_ALLOW_PRIVILEGED", "1")
    assert main(["serve"]) == 0
    assert len(served) == 1


def test_migrate_does_not_ask(
    migrated: Engine, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migrations run as the schema's owner, without the opt-out."""
    _postgres_only(migrated)
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    monkeypatch.delenv("MAITY_DB_ALLOW_PRIVILEGED", raising=False)
    assert main(["migrate"]) == 0


def test_the_settings_carry_the_flag_unchanged_into_a_worker() -> None:
    from maity_hub import serving

    settings = _settings(MAITY_DB_ALLOW_PRIVILEGED="1")
    assert serving.per_worker(replace(settings, workers=2)).db_allow_privileged
