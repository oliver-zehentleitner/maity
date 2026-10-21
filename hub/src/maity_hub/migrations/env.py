"""Alembic environment. Migrations run only through `maity-hub migrate`."""

from alembic import context
from sqlalchemy import Engine

from maity_hub import tables  # noqa: F401  (registers the tables on the metadata)
from maity_hub.db import metadata

engine: Engine = context.config.attributes["engine"]

with engine.begin() as connection:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        # SQLite cannot ALTER most things; batch mode rebuilds the table instead.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    context.run_migrations()
