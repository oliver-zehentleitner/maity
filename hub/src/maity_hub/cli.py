"""`maity-hub serve` and `maity-hub migrate`."""

from __future__ import annotations

import argparse
import getpass
import logging
import re
import sys

import uvicorn
from sqlalchemy import insert, select
from sqlalchemy.exc import SQLAlchemyError

from maity_hub import __version__, clock
from maity_hub import tables as t
from maity_hub.app import SchemaNotCurrentError, create_app, require_current_schema
from maity_hub.auth.passwords import MIN_LENGTH, hash_password
from maity_hub.config import ConfigError, Settings, redact_database_url
from maity_hub.db import current_revision, head_revision, make_engine, migrate
from maity_hub.ids import new_id

EXIT_FAILURE = 1
EXIT_CONFIG = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maity-hub", description="The Maity hub server.")
    parser.add_argument("--version", action="version", version=f"maity-hub {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="serve the API and the dashboard")
    commands.add_parser("migrate", help="bring the database schema to the current version")
    owner = commands.add_parser("owner", help="manage human accounts")
    owner_commands = owner.add_subparsers(dest="owner_command", required=True)
    create = owner_commands.add_parser(
        "create",
        help="create a human account; the password is read from the terminal or standard input",
    )
    create.add_argument("--handle", required=True)
    create.add_argument("--display-name", required=True)
    factor = commands.add_parser("second-factor", help="manage a human's second factor")
    factor_commands = factor.add_subparsers(dest="factor_command", required=True)
    reset = factor_commands.add_parser(
        "reset",
        help="reset a human's second factor at once and end their sessions (docs/api.md §2.8.3)",
    )
    reset.add_argument("--handle", required=True)
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
    if args.command == "owner":
        return _owner_create(settings, args.handle, args.display_name)
    if args.command == "second-factor":
        return _second_factor_reset(settings, args.handle)
    return _serve(settings)


def _second_factor_reset(settings: Settings, handle: str) -> int:
    """The operator's last way in (§2.8.3): no mail, no instance key needed."""
    from maity_hub.auth import second_factor_reset

    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    try:
        with engine.begin() as conn:
            human_id = second_factor_reset.operator_reset(conn, handle)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    if human_id is None:
        return _fail(f"no human with the handle {handle!r}", EXIT_FAILURE)
    print(f"maity-hub: reset the second factor of {handle} ({human_id}); their sessions ended")
    return 0


HANDLE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")


def _read_password() -> str | None:
    """From the terminal, asked twice; or the first line of standard input. Never argv."""
    if sys.stdin.isatty():
        first = getpass.getpass("password: ")
        if getpass.getpass("again: ") != first:
            return None
        return first
    return sys.stdin.readline().rstrip("\n")


def _owner_create(settings: Settings, handle: str, display_name: str) -> int:
    if not HANDLE.fullmatch(handle):
        return _fail(
            "--handle: lower-case letters, digits and '-', 2 to 63 characters", EXIT_CONFIG
        )
    if not display_name.strip() or len(display_name) > 200:
        return _fail("--display-name: 1 to 200 characters", EXIT_CONFIG)
    password = _read_password()
    if not password:
        return _fail("no password given, or the two entries differ", EXIT_CONFIG)
    if len(password) < MIN_LENGTH:
        return _fail(f"a password has at least {MIN_LENGTH} characters", EXIT_CONFIG)
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    try:
        with engine.begin() as conn:
            if conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).first():
                return _fail(f"a human with the handle {handle!r} exists", EXIT_FAILURE)
            human_id = new_id("human")
            conn.execute(
                insert(t.human).values(
                    id=human_id,
                    handle=handle,
                    display_name=display_name,
                    password_hash=hash_password(password),
                    created_at=clock.now(),
                )
            )
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    print(f"maity-hub: created {handle} ({human_id})")
    return 0


def _fail(message: str, code: int) -> int:
    print(f"maity-hub: {message}", file=sys.stderr)
    return code


def _database_error(settings: Settings, error: Exception) -> int:
    # The driver's own message, first line only: SQLAlchemy appends the SQL and
    # its parameters. The URL is printed only in its redacted form.
    original = getattr(error, "orig", None) or error
    reason = (str(original).strip().splitlines() or [type(original).__name__])[0]
    return _fail(f"database {redact_database_url(settings.database_url)}: {reason}", EXIT_FAILURE)


def _migrate(settings: Settings) -> int:
    try:
        engine = make_engine(settings.database_url)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
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
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
        app = create_app(settings, engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    uvicorn.run(app, host=settings.host, port=settings.port, proxy_headers=False, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
