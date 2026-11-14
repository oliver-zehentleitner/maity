"""`maity-hub serve` and `maity-hub migrate`, the operator's account commands, the copy of the
attachments into a bucket, and the load test's seed."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path
from types import FrameType
from typing import Any

import uvicorn
from sqlalchemy import exists, insert, inspect, literal, select
from sqlalchemy.exc import SQLAlchemyError
from uvicorn.config import STARTUP_FAILURE
from uvicorn.supervisors import multiprocess

from maity_hub import (
    __version__,
    attachment_store,
    attachments,
    clock,
    handle_register,
    handles,
    loadtest,
    longpoll,
    moderation,
    namespace,
    paths,
    public_pages,
    serving,
)
from maity_hub import tables as t
from maity_hub.app import (
    SchemaNotCurrentError,
    check_startup,
    check_web_dir,
    create_app,
    require_current_schema,
    require_unprivileged_role,
    serving_engine,
    start_once,
    warn_on_connection_budget,
)
from maity_hub.auth import second_factor_reset
from maity_hub.auth.passwords import MIN_LENGTH, hash_password
from maity_hub.config import ConfigError, Settings, redact_database_url
from maity_hub.db import current_revision, head_revision, make_engine, migrate
from maity_hub.errors import ApiError
from maity_hub.ids import new_id
from maity_hub.mail import address as addresses
from maity_hub.notifications import preferences

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
    create.add_argument(
        "--email",
        required=True,
        help="the account's address, stored as verified: the password signs in with it",
    )
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
    load = commands.add_parser("loadtest", help="the load test's accounts (loadtest/README.md)")
    load_commands = load.add_subparsers(dest="load_command", required=True)
    seed = load_commands.add_parser(
        "seed", help="seed lt-<n> accounts into this hub's database and write their keys to a file"
    )
    seed.add_argument("--humans", type=int, required=True)
    seed.add_argument("--out", required=True, help="a new file; it holds secrets")
    purge = load_commands.add_parser(
        "purge", help="delete every row of the lt-<n> accounts; without --apply only count"
    )
    purge.add_argument("--apply", action="store_true")
    files = commands.add_parser("attachments", help="the attachment store (docs/api.md §8.7)")
    files_commands = files.add_subparsers(dest="attachments_command", required=True)
    copy = files_commands.add_parser(
        "copy-to-s3",
        help="copy the files under MAITY_ATTACHMENT_DIR into the bucket of the s3 store",
    )
    copy.add_argument(
        "--apply",
        action="store_true",
        help="copy, and remove from the bucket what was deleted since an earlier run; without it "
        "only count",
    )
    quick = commands.add_parser(
        "quickstart",
        help="a personal hub on SQLite: set up a new database, the first account, then serve",
    )
    quick.add_argument("--handle", help="the first account's handle (default: your login name)")
    quick.add_argument("--display-name", help="its display name (default: the handle)")
    quick.add_argument(
        "--email", help="its address, the one you sign in with (asked for when not given)"
    )
    args = parser.parse_args(argv)

    if args.command in ("serve", "quickstart"):
        serving.configure_logging()
    else:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)

    if args.command == "migrate":
        return _migrate(settings)
    if args.command == "owner":
        return _owner_create(settings, args.handle, args.display_name, args.email)
    if args.command == "second-factor":
        return _second_factor_reset(settings, args.handle)
    if args.command == "account":
        return _unsuspend(settings, args.handle)
    if args.command == "quickstart":
        return _quickstart(settings, args.handle, args.display_name, args.email)
    if args.command == "attachments":
        return _copy_to_s3(settings, apply=args.apply)
    if args.command == "loadtest" and args.load_command == "purge":
        return _loadtest_purge(settings, apply=args.apply)
    if args.command == "loadtest":
        return _loadtest_seed(settings, args.humans, Path(args.out))
    return _serve(settings)


def _copy_to_s3(settings: Settings, *, apply: bool) -> int:
    """From the volume to the bucket, before the hub runs on `s3` alone; idempotent, so it runs
    once while the hub still serves from the volume and once more after it stopped."""
    if settings.attachment_dir is None:
        return _fail("MAITY_ATTACHMENT_DIR is not set: the files to copy are there", EXIT_CONFIG)
    if settings.attachment_s3 is None:
        return _fail(
            "MAITY_ATTACHMENT_STORE is not s3: set it and MAITY_ATTACHMENT_S3_BUCKET", EXIT_CONFIG
        )
    source = attachment_store.LocalStore(settings.attachment_dir)
    target = attachment_store.S3Store(settings.attachment_s3)
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
        done = attachment_store.copy_local_to_s3(
            source,
            target,
            apply=apply,
            live=lambda project: _live_attachments(engine, project),
            still=lambda key: _still_live(engine, key),
        )
        # The bucket's objects whose attachment was deleted since an earlier run (the hub
        # still on the volume deletes only there), as the hub's sweep under `s3` removes them;
        # without `--apply` only counted.
        cleaned = _clean_bucket(engine, target, apply=apply)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    verb, removed = ("copied", "removed from") if apply else ("to copy", "to remove from")
    print(
        f"{verb}: {done['copied']}, already there: {done['present']}, "
        f"different in the bucket: {done['differs']}, "
        f"deleted, not copied: {done['skipped_deleted']}, "
        f"deleted, {removed} the bucket: {cleaned['tombstoned'] + cleaned['orphans']}, "
        f"failed: {done['failed'] + cleaned['failed']}"
    )
    return EXIT_FAILURE if done["failed"] or cleaned["failed"] or done["differs"] else 0


def _clean_bucket(engine: Any, target: attachment_store.S3Store, *, apply: bool) -> dict[str, int]:
    """The sweep's removals against the bucket, without expiring rows: a tombstone's object,
    and an object no row names once it is older than `BLOB_GRACE` (an upload in flight under
    `s3` is younger). Without `apply` only counted. A failure of the store or the database is
    logged and counted; the copy itself stands, and its counts are printed."""
    try:
        done = attachments.sweep(engine, target, expiring=False, apply=apply)
    except (attachment_store.StoreError, SQLAlchemyError) as error:
        # The driver's first line only, as in `_database_error`: no SQL, no parameters.
        original = getattr(error, "orig", None) or error
        reason = (str(original).strip().splitlines() or [type(original).__name__])[0]
        logging.getLogger(__name__).error("cleaning the bucket: %s", reason)
        return {"tombstoned": 0, "orphans": 0, "failed": 1}
    return {"tombstoned": done["tombstoned"], "orphans": done["orphans"], "failed": 0}


def _live_attachments(engine: Any, project: str) -> set[str] | None:
    """The attachments of a project that have a row and are not deleted, for the copy; None
    for a folder no project has."""
    with engine.connect() as conn:
        if conn.execute(select(t.project.c.id).where(t.project.c.id == project)).first() is None:
            return None
        rows = conn.execute(
            select(t.attachment.c.id).where(
                t.attachment.c.project_id == project, t.attachment.c.deleted_at.is_(None)
            )
        )
        return {str(row.id) for row in rows}


def _still_live(engine: Any, key: str) -> bool:
    """Whether the attachment of a blob key still has a row that is not deleted."""
    project, _, attachment_id = key.partition("/")
    with engine.connect() as conn:
        found = conn.execute(
            select(t.attachment.c.id).where(
                t.attachment.c.id == attachment_id,
                t.attachment.c.project_id == project,
                t.attachment.c.deleted_at.is_(None),
            )
        ).first()
    return found is not None


def _loadtest_refusal(settings: Settings) -> str | None:
    if not os.environ.get("MAITY_PUBLIC_URL"):  # the operator's name for the hub, never derived
        return "MAITY_PUBLIC_URL is not set"
    return loadtest.refusal(
        settings.public_url,
        os.environ.get("LOADTEST_CONFIRMED_TEST_SYSTEM"),
        os.environ.get("LOADTEST_CONFIRMED_PRODUCTION"),
    )


def _loadtest_purge(settings: Settings, *, apply: bool) -> int:
    why = _loadtest_refusal(settings)
    if why is not None:
        return _fail(f"refused: {why}", EXIT_CONFIG)
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
        counted = loadtest.purge(engine, change=apply)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except loadtest.Refused as error:
        return _fail(f"refused: {error}", EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    for name, count in counted.items():
        print(f"{name}: {count}")
    print(
        ("deleted" if apply else "would delete") + f" the rows of {counted.get('human', 0)} humans"
    )
    return 0


def _loadtest_seed(settings: Settings, humans: int, out: Path) -> int:
    why = _loadtest_refusal(settings)
    if why is not None:
        return _fail(f"refused: {why}", EXIT_CONFIG)
    if humans < 0:
        return _fail("--humans: 0 or more", EXIT_CONFIG)
    if out.exists():  # before the database is asked anything; again when it is created
        return _fail(f"refused: {out} exists", EXIT_CONFIG)
    try:
        engine = make_engine(settings.database_url)
        require_current_schema(engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    try:
        made = loadtest.seed(engine, humans, out)
    except FileExistsError:
        return _fail(f"refused: {out} exists", EXIT_CONFIG)
    print(f"seeded {made} humans into {out}")
    return 0


def _read_password() -> str | None:
    """From the terminal, asked twice; or the first line of standard input. Never argv."""
    if sys.stdin.isatty():
        first = getpass.getpass("password: ")
        if getpass.getpass("again: ") != first:
            return None
        return first
    return sys.stdin.readline().rstrip("\n")


def _owner_create(
    settings: Settings, handle: str, display_name: str, email: str, *, first: bool = False
) -> int:
    """The account with its address as verified (docs/api.md §2.1): the password signs in
    by it, with no mail sent, on an instance that has none set up yet."""
    if not handles.FORMAT.fullmatch(handle):  # the hub's one rule, 2 to 31 (§6.24)
        return _fail(
            "--handle: lower-case letters, digits and '-', 2 to 31 characters", EXIT_CONFIG
        )
    if paths.handle_reserved(handle):  # a first segment of the hub (§16.11), the first account too
        return _fail(f"the handle {handle!r} is reserved", EXIT_CONFIG)
    if not display_name.strip() or len(display_name) > 200:
        return _fail("--display-name: 1 to 200 characters", EXIT_CONFIG)
    email = email.strip()
    if not addresses.valid(email):
        return _fail("--email: one address, local-part@domain (docs/api.md §18.4)", EXIT_CONFIG)
    normalized = addresses.normalized(email)
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
        addresses.prepare(engine, settings.secret_key)  # before the lock's transaction
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
                handles.lock(conn, handles.HUMANS, handle)
                if handles.holder(conn, handles.HUMANS, handle) is not None:
                    return _fail(
                        f"a human kept the handle {handle!r} as an alias",
                        EXIT_FAILURE,
                    )
                conn.execute(insert(t.human).values(**values))
                if not handle_register.claim(conn, handle, handle_register.HUMAN, human_id):
                    raise _HandleTaken  # an organisation took it meanwhile: the account rolls back
            if not preferences.claim_verified(
                conn, normalized, human_id, secret_key=settings.secret_key
            ):
                raise _AddressTaken  # another account's address: the account rolls back
    except _HandleTaken:
        return _fail(f"the handle {handle!r} was taken meanwhile", EXIT_FAILURE)
    except _AddressTaken:
        return _fail(f"another account has the address {normalized}", EXIT_FAILURE)
    except SQLAlchemyError as error:
        return _database_error(settings, error)
    finally:
        engine.dispose()
    print(f"maity-hub: created {handle} ({human_id}), signing in as {normalized}")
    return 0


class _HandleTaken(Exception):
    """The register refused the new account's handle after the checks: roll it back."""


class _AddressTaken(Exception):
    """Another account holds the address as its verified one: roll the new account back."""


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
            human_id = handles.human_id_of(conn, handle)  # the handle or an alias (§6.24)
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
        try:
            migrate(engine)
        except SQLAlchemyError:
            # Where the run left the schema, after the last attempt (db.migrate): on PostgreSQL
            # the chain is one transaction and this is `before`; MariaDB commits per step.
            try:
                now = current_revision(engine) or "empty"
            except SQLAlchemyError:
                now = "unknown"
            print(
                f"maity-hub: schema stays at {now}, head {head_revision(engine)} not reached",
                file=sys.stderr,
            )
            raise
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
    return (
        login if handles.FORMAT.fullmatch(login) and not paths.handle_reserved(login) else "owner"
    )


def _read_email() -> str | None:
    """From the terminal; standard input stays the password's (`_read_password`)."""
    if not sys.stdin.isatty():
        return None
    return input("email address (you sign in with it): ").strip() or None


def _quickstart(
    settings: Settings, handle: str | None, display_name: str | None, email: str | None
) -> int:
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
        email = email or _read_email()
        if email is None:
            return _fail(
                "--email: the first account's address, the one it signs in with", EXIT_CONFIG
            )
        created = _owner_create(settings, handle, display_name or handle, email, first=True)
        if created != 0:
            return created
        banner.append(f"maity-hub: sign in as {addresses.normalized(email.strip())}")
    return _serve(settings, banner)


def _serve(settings: Settings, banner: list[str] | None = None) -> int:
    refused = serving.refusal(settings)
    if refused is not None:
        return _fail(refused, EXIT_CONFIG)
    if settings.workers > 1:
        return _serve_workers(settings, banner)
    try:
        engine = serving_engine(settings)
        require_current_schema(engine)
        require_unprivileged_role(engine, settings)
        warn_on_connection_budget(engine, settings)
        app = create_app(settings, engine)
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    _Server(_config(settings, app), banner=[*(banner or []), _where(settings)]).run()
    return 0


def _config(settings: Settings, app: Any, workers: int = 1) -> uvicorn.Config:
    return uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        proxy_headers=False,
        access_log=False,
        timeout_graceful_shutdown=GRACEFUL_SECONDS,
        timeout_keep_alive=KEEP_ALIVE_SECONDS,
        factory=workers > 1,
        workers=workers,
    )


def _serve_workers(settings: Settings, banner: list[str] | None) -> int:
    """`MAITY_WORKERS` processes on one socket under uvicorn's supervisor, which starts a worker
    again when one dies and passes the stop signal on; each worker releases its long-polls on it,
    as one process does (`_Server`). The parent checks the database and the schema once, so a hub
    that cannot start says so once, not once per worker, and holds no connection itself."""
    try:
        check_web_dir(settings)
        engine = serving_engine(serving.per_worker(settings))
        try:
            check_startup(engine, settings)
            require_unprivileged_role(engine, settings)
            warn_on_connection_budget(engine, settings)
            start_once(engine, settings)
        finally:
            engine.dispose()
    except SchemaNotCurrentError as error:
        return _fail(str(error), EXIT_FAILURE)
    except ConfigError as error:
        return _fail(str(error), EXIT_CONFIG)
    except (SQLAlchemyError, ImportError) as error:
        return _database_error(settings, error)
    config = _config(settings, "maity_hub.serving:app", settings.workers)
    socket = config.bind_socket()
    # Printed once, by the parent: each worker would print it again.
    for line in [*(banner or []), _where(settings), f"maity-hub: {settings.workers} workers"]:
        print(line, flush=True)
    # Every worker uvicorn starts, also one started again, is a `_WorkerProcess`.
    multiprocess.Process = _WorkerProcess  # type: ignore[misc]
    supervisor = multiprocess.Multiprocess(config, sockets=[socket])
    supervisor.run()
    # uvicorn stops every worker when one fails before it serves; the hub then fails too.
    failed = any(p.process.exitcode == STARTUP_FAILURE for p in supervisor.processes)
    return EXIT_FAILURE if failed else 0


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


class _WorkerProcess(multiprocess.Process):
    """One of the `MAITY_WORKERS` processes: uvicorn's worker, serving with `_Server`, so that
    the stop signal releases its long-polls first, as a hub of one process does."""

    @property
    def server(self) -> uvicorn.Server:
        if self._server is None:
            self._server = _Server(config=self.config)
        return self._server


if __name__ == "__main__":
    sys.exit(main())
