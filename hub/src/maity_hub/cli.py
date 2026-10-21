"""`maity-hub serve` and `maity-hub migrate`."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from maity_hub import __version__
from maity_hub.app import SchemaNotCurrentError, create_app, require_current_schema
from maity_hub.config import ConfigError, Settings, redact_database_url
from maity_hub.db import current_revision, head_revision, make_engine, migrate

EXIT_FAILURE = 1
EXIT_CONFIG = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maity-hub", description="The Maity hub server.")
    parser.add_argument("--version", action="version", version=f"maity-hub {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="serve the API and the dashboard")
    commands.add_parser("migrate", help="bring the database schema to the current version")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        # Alembic logs its context on every revision lookup, i.e. on every health call.
        logging.getLogger("alembic").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)

    if args.command == "migrate":
        return _migrate(settings)
    return _serve(settings)


def _fail(message: str, code: int) -> int:
    print(f"maity-hub: {message}", file=sys.stderr)
    return code


def _database_error(settings: Settings, error: SQLAlchemyError) -> int:
    # The driver's own message, first line only (SQLAlchemy appends the SQL and
    # its parameters), with the password scrubbed should a driver ever quote it.
    original = getattr(error, "orig", None) or error
    reason = (str(original).strip().splitlines() or [type(original).__name__])[0]
    password = make_url(settings.database_url).password
    if password:
        reason = reason.replace(password, "***")
    return _fail(f"database {redact_database_url(settings.database_url)}: {reason}", EXIT_FAILURE)


def _migrate(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        before = current_revision(engine)
        migrate(engine)
        print(f"maity-hub: schema {before or 'empty'} -> {head_revision(engine)}")
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    return 0


def _serve(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        require_current_schema(engine)
        app = create_app(settings, engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
