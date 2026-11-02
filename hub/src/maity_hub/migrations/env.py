"""Alembic environment. Migrations run only through `maity-hub migrate`."""

from alembic import context
from sqlalchemy import Engine

from maity_hub import tables  # noqa: F401  (registers the tables on the metadata)
from maity_hub.db import metadata

engine: Engine = context.config.attributes["engine"]

with engine.connect() as connection:
    sqlite = connection.dialect.name == "sqlite"
    raw = connection.connection.driver_connection if sqlite else None

    def configure() -> None:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            # SQLite cannot ALTER most things; batch mode rebuilds the table instead.
            render_as_batch=sqlite,
        )

    if raw is not None:
        # Batch mode rebuilds a table by copy, drop and rename; with foreign keys
        # on, dropping a referenced table fails. SQLite ignores this pragma inside
        # a transaction, so it is set on the driver connection before the begin.
        raw.execute("PRAGMA foreign_keys=OFF")
    try:
        if connection.dialect.name in ("mariadb", "mysql"):
            # Every DDL statement commits here, so one transaction around the run would only
            # lose the last `alembic_version` update when a migration refuses, and the revision
            # would name a schema already gone. Outside a transaction, alembic commits per step.
            configure()
            context.run_migrations()
        else:
            with connection.begin():
                configure()
                context.run_migrations()
                if sqlite:
                    broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                    if broken:
                        raise RuntimeError(f"the migration left dangling references: {broken[:5]}")
    finally:
        if raw is not None:
            raw.execute("PRAGMA foreign_keys=ON")  # the pooled connection goes back as it came
