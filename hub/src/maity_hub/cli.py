"""`maity-hub serve` and `maity-hub migrate`."""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from maity_hub import __version__
from maity_hub.app import SchemaNotCurrentError, create_app, require_current_schema
from maity_hub.config import ConfigError, Settings
from maity_hub.db import current_revision, head_revision, make_engine, migrate


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
        print(f"maity-hub: {error}", file=sys.stderr)
        return 2

    if args.command == "migrate":
        return _migrate(settings)
    return _serve(settings)


def _migrate(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        before = current_revision(engine)
        migrate(engine)
        print(f"maity-hub: schema {before or 'empty'} -> {head_revision(engine)}")
    finally:
        engine.dispose()
    return 0


def _serve(settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    try:
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        print(f"maity-hub: {error}", file=sys.stderr)
        return 1
    app = create_app(settings, engine)
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
