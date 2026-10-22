"""Alembic environment. Migrations run only through `maity-hub migrate`."""

from alembic import context
from sqlalchemy import Engine

from maity_hub import tables  # noqa: F401  (registers the tables on the metadata)
from maity_hub.db import metadata

engine: Engine = context.config.attributes["engine"]

with engine.connect() as connection:
    sqlite = connection.dialect.name == "sqlite"
    raw = connection.connection.driver_connection if sqlite else None
    if raw is not None:
        # Batch mode rebuilds a table by copy, drop and rename; with foreign keys
        # on, dropping a referenced table fails. SQLite ignores this pragma inside
        # a transaction, so it is set on the driver connection before the begin.
        raw.execute("PRAGMA foreign_keys=OFF")
    try:
        with connection.begin():
            context.configure(
                connection=connection,
                target_metadata=metadata,
                # SQLite cannot ALTER most things; batch mode rebuilds the table instead.
                render_as_batch=sqlite,
            )
            context.run_migrations()
            if sqlite:
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"the migration left dangling references: {broken[:5]}")
    finally:
        if raw is not None:
            raw.execute("PRAGMA foreign_keys=ON")  # the pooled connection goes back as it came
