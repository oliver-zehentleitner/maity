"""`maity-hub serve` and `maity-hub migrate`, and the operator's account commands."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import re
import sys
from types import FrameType
from typing import Any

import uvicorn
from sqlalchemy import exists, insert, inspect, literal, select
from sqlalchemy.exc import SQLAlchemyError

from maity_hub import (
    __version__,
    clock,
    handle_register,
    longpoll,
    moderation,
    namespace,
    paths,
    public_pages,
)
from maity_hub import tables as t
from maity_hub.app import SchemaNotCurrentError, create_app, require_current_schema, serving_engine
from maity_hub.auth import second_factor_reset
from maity_hub.auth.passwords import MIN_LENGTH, hash_password
from maity_hub.config import ConfigError, Settings, redact_database_url
from maity_hub.db import current_revision, head_revision, make_engine, migrate
from maity_hub.errors import ApiError
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
    factor = commands.add_parser("second-factor", help="the second factor of a human account")
    factor_commands = factor.add_subparsers(dest="factor_command", required=True)
    reset = factor_commands.add_parser(
        "reset",
        help="reset a human's second factor at once, the last way in (docs/api.md §2.8.3)",
    )
    reset.add_argument("--handle", required=True)
    account = commands.add_parser("account", help="an account's moderation (docs/api.md §16.8)")
    account_commands = account.add_subparsers(dest="account_command", required=True)
    unsuspend = account_commands.add_parser(
        "unsuspend", help="lift an instance admin's suspension of a human account"
    )
    unsuspend.add_argument("--handle", required=True)
    quick = commands.add_parser(
        "quickstart",
        help="a personal hub on SQLite: set up a new database, the first account, then serve",
    )
    quick.add_argument("--handle", help="the first account's handle (default: your login name)")
    quick.add_argument("--display-name", help="its display name (default: the handle)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.command in ("serve", "quickstart"):
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
    if args.command == "account":
        return _unsuspend(settings, args.handle)
    if args.command == "quickstart":
        return _quickstart(settings, args.handle, args.display_name)
    return _serve(settings)


HANDLE = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")


def _read_password() -> str | None:
    """From the terminal, asked twice; or the first line of standard input. Never argv."""
    if sys.stdin.isatty():
        first = getpass.getpass("password: ")
        if getpass.getpass("again: ") != first:
            return None
        return first
    return sys.stdin.readline().rstrip("\n")


def _owner_create(
    settings: Settings, handle: str, display_name: str, *, first: bool = False
) -> int:
    if not HANDLE.fullmatch(handle):
        return _fail(
            "--handle: lower-case letters, digits and '-', 2 to 63 characters", EXIT_CONFIG
        )
    if handle in paths.RESERVED_FIRST:  # a first segment of the hub (§16.11), the first account too
        return _fail(f"the handle {handle!r} is a reserved first segment", EXIT_CONFIG)
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
            human_id = new_id("human")
            values = {
                "id": human_id,
                "handle": handle,
                "display_name": display_name,
                "password_hash": hash_password(password),
                "created_at": clock.now(),
            }
            if first:
                # quickstart's first account: the check that no human exists and the
                # insert are one statement, so an account another process created while
                # the password was asked for is never joined by a second admin.
                columns = [t.human.c[name] for name in values]
                rows = select(*(literal(values[c.name], type_=c.type) for c in columns)).where(
                    ~exists(select(t.human.c.id))
                )
                if conn.execute(insert(t.human).from_select(columns, rows)).rowcount != 1:
                    return _fail(
                        "an account was created meanwhile; sign in with it, "
                        "or run quickstart again",
                        EXIT_FAILURE,
                    )
                if not handle_register.claim(conn, handle, handle_register.HUMAN, human_id):
                    raise _HandleTaken  # an organisation took it meanwhile: the account rolls back
            else:
                if conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).first():
                    return _fail(f"a human with the handle {handle!r} exists", EXIT_FAILURE)
                if handle_register.taken(conn, handle):
                    return _fail(f"an organisation has the handle {handle!r}", EXIT_FAILURE)
                conn.execute(insert(t.human).values(**values))
                if not handle_register.claim(conn, handle, handle_register.HUMAN, human_id):
                    raise _HandleTaken  # an organisation took it meanwhile: the account rolls back
    except _HandleTaken:
        return _fail(f"the handle {handle!r} was taken meanwhile", EXIT_FAILURE)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    print(f"maity-hub: created {handle} ({human_id})")
    return 0


class _HandleTaken(Exception):
    """The register refused the new account's handle after the checks: roll it back."""


def _second_factor_reset(settings: Settings, handle: str) -> int:
    """The operator's reset (§2.8.3): at once, the enrolment and the recovery codes gone,
    every session of the human ended, the record and the mail as for any reset, `by:
    operator`."""
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    try:
        with engine.begin() as conn:
            try:
                done = second_factor_reset.operator_reset(conn, handle)
            except ApiError:  # no such human
                return _fail(f"no human with the handle {handle!r}", EXIT_FAILURE)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    if not done:
        return _fail(f"{handle} has no second factor enrolled", EXIT_FAILURE)
    print(f"maity-hub: reset the second factor of {handle}; every session of theirs has ended")
    return 0


def _unsuspend(settings: Settings, handle: str) -> int:
    """The operator lifts a suspension (§16.8); nothing comes back by itself: the account
    signs in again, and its agents and runners join and pair again."""
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    try:
        # A process without the app renders the page it brings back (docs: public-pages.md).
        public_pages.configure(settings)
        with engine.begin() as conn:
            human_id = conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).scalar()
            if human_id is None:
                return _fail(f"no human with the handle {handle!r}", EXIT_FAILURE)
            lifted = moderation.unsuspend(conn, human_id)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    if not lifted:
        return _fail(f"{handle} is not suspended", EXIT_FAILURE)
    print(f"maity-hub: lifted the suspension of {handle}; they can sign in again")
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
        with engine.connect() as conn:
            holders = namespace.reserved_holders(conn)
        if holders:  # a release that reserves a held word does not go on (docs/api.md §16.11)
            return _fail(
                "a word that docs/api.md §16.11 reserves is already held, rename it first: "
                + ", ".join(holders),
                EXIT_FAILURE,
            )
        before = current_revision(engine)
        migrate(engine)
        print(f"maity-hub: schema {before or 'empty'} -> {head_revision(engine)}")
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    return 0


def _default_handle() -> str:
    """The login name when it is a valid handle that no route of the hub uses (`admin` is
    one, §16.11), else `owner`."""
    try:
        login = getpass.getuser().lower()
    except (KeyError, OSError):  # no passwd entry, no LOGNAME
        return "owner"
    return login if HANDLE.fullmatch(login) and login not in paths.RESERVED_FIRST else "owner"


def _quickstart(settings: Settings, handle: str | None, display_name: str | None) -> int:
    """`migrate` on a new SQLite database, `owner create` while there is no human, then
    `serve`. New means no tables at all: a file with tables but no schema version, or a
    database behind the current schema, is refused, because migrations never run
    implicitly on a database that already holds something."""
    if not settings.database_url.startswith("sqlite"):
        return _fail(
            "quickstart is the local path on SQLite; for "
            f"{redact_database_url(settings.database_url)} run migrate, owner create and serve",
            EXIT_CONFIG,
        )
    try:
        engine = make_engine(settings.database_url)
        unversioned = current_revision(engine) is None
        tables = inspect(engine).get_table_names()
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    if unversioned and tables:
        engine.dispose()  # not a new file: whatever it holds, only `migrate` touches it
        return _fail(
            f"{redact_database_url(settings.database_url)} holds tables but no Maity schema "
            "version; start in an empty directory, or run `maity-hub migrate` if it is a hub",
            EXIT_FAILURE,
        )
    new = unversioned
    try:
        if new:
            migrate(engine)
            print(f"maity-hub: schema empty -> {head_revision(engine)}")
        else:
            require_current_schema(engine)
        with engine.connect() as conn:
            someone = conn.execute(select(t.human.c.id).limit(1)).first() is not None
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    banner = []
    if someone:
        print("maity-hub: this hub has accounts; sign in with yours")
    else:
        handle = handle or _default_handle()
        created = _owner_create(settings, handle, display_name or handle, first=True)
        if created != 0:
            return created
        banner.append(f"maity-hub: sign in as {handle}")
    return _serve(settings, banner)


def _serve(settings: Settings, banner: list[str] | None = None) -> int:
    try:
        engine = serving_engine(settings)
        require_current_schema(engine)
        app = create_app(settings, engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        proxy_headers=False,
        access_log=False,
        timeout_graceful_shutdown=GRACEFUL_SECONDS,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
    )
    _Server(config, banner=[*(banner or []), _where(settings)]).run()
    return 0


def _where(settings: Settings) -> str:
    """The line printed once the hub listens, last, so it is what the eye lands on."""
    if settings.web_dir is not None and settings.web_dir.is_dir():
        return f"maity-hub: dashboard at {settings.public_url}/"
    return f"maity-hub: API only at {settings.public_url}/api/v1, no dashboard"


# A request still running this long after the stop signal is cut off; the long-polls
# answer at once (`longpoll.begin_shutdown`), so this only bounds a slow request.
GRACEFUL_SECONDS = 10

# How long an idle connection stays open. uvicorn's own 5 s closes it before a proxy's
# pool (Traefik keeps idle backend connections 90 s) has dropped it; the next request on
# it then fails with a 502. Longer than any proxy keeps one.
KEEP_ALIVE_SECONDS = 120


class _Server(uvicorn.Server):
    """On the stop signal, first release every open long-poll, then shut down as
    uvicorn does: a restart takes a second, not the length of the longest wait.

    The signal handler takes no lock: it may have interrupted code that holds the
    long-poll registry's lock. It only hands the release to the event loop, which runs
    it between two callbacks."""

    _loop: asyncio.AbstractEventLoop | None = None

    def __init__(self, config: uvicorn.Config, banner: list[str] | None = None) -> None:
        super().__init__(config)
        self.banner = banner or []

    async def startup(self, sockets: Any = None) -> None:
        self._loop = asyncio.get_running_loop()
        await super().startup(sockets=sockets)
        if self.started:  # after uvicorn's own lines; nothing when the bind failed
            for line in self.banner:
                print(line, flush=True)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(longpoll.begin_shutdown)
        super().handle_exit(sig, frame)


if __name__ == "__main__":
    sys.exit(main())
