"""docs/api.md §2.9: every table that names a human is handled by the account deletion and
by the export, or left out on purpose with a reason. A new table that names a human fails
here until someone decides which (forge links and sign-in links were missed once, #586).

A table names a human through a foreign key to `human`, a column called `human_id`, or a
column `NAMES_A_HUMAN` marks: one without a foreign key that holds a human's id (often a
`hum-…`/`agt-…` principal id) or an address. Every column whose name looks like a person's
and has no foreign key is decided there, so a new one fails until it is."""

from __future__ import annotations

import ast
import inspect
import re
from types import ModuleType
from typing import Any

from sqlalchemy import Table

from maity_hub import account_deletion, avatars, export
from maity_hub import tables as t  # noqa: F401  (registers every table on the metadata)
from maity_hub.auth import second_factor
from maity_hub.db import metadata
from maity_hub.notifications import preferences as notification_preferences
from maity_hub.routes import agents, members, runners

# The account row itself stays with its id, so that every stored id keeps resolving (§2.9).
ACCOUNT = "human"

# A column name that looks like a person's.
LOOKS_LIKE_A_PERSON = re.compile(r"human|_by$|^owner_id$|^caller$|^address")
# Whether each such column without a foreign key names a human (True), or is something
# else that only looks like one (False): a reason, a time, a mode, a session's id.
NAMES_A_HUMAN: dict[tuple[str, str], bool] = {
    ("account_deletion", "withdrawn_by"): False,  # why: `replaced`, `password_change`, …
    ("account_record", "read_by"): True,
    ("account_registration", "address"): True,
    ("account_registration", "address_normalized"): True,
    ("account_registration", "decided_by"): True,
    ("account_registration", "human_id"): True,  # no foreign key on purpose (tables.py)
    ("address_lock", "address"): True,
    ("attachment", "deleted_by"): True,
    ("avatar_image", "owner_id"): True,
    ("conversation_participant", "added_by"): True,
    ("conversation_participant", "removed_by"): True,
    ("credential", "ktw_acknowledge_by"): False,  # a deadline
    ("credential", "paused_by"): True,
    ("credential", "revoke_due_by"): True,
    ("credential", "revoked_by"): True,
    ("email_sign_in", "address_epoch"): False,  # a counter
    ("event", "actor_human_id"): True,
    ("human_session", "approved_by"): False,  # the approving session's public id
    ("human_session", "ended_by"): False,  # why: `logout`, `revoked`, …
    ("idempotency_key", "caller"): True,
    ("instance_landing", "updated_by"): True,
    ("invitation", "address"): True,
    ("invitation", "address_normalized"): True,
    ("membership", "briefing_by"): True,
    ("membership", "paused_by"): True,
    ("membership", "team_updated_by"): True,
    ("notification_settings", "address"): True,
    ("notification_settings", "address_change"): True,
    ("notification_settings", "address_normalized"): True,
    ("notification_settings", "address_status"): False,  # `verified`, `pending`, …
    ("pending_registration", "address"): True,
    ("pending_registration", "address_normalized"): True,
    ("placement", "updated_by"): True,
    ("preferences", "confirmed_by"): True,
    ("preferences", "proposed_by"): True,
    ("preferences_version", "confirmed_by"): True,
    ("preferences_version", "proposed_by"): True,
    ("project", "spawn_consent_by"): False,  # a mode: `human`, `role`
    ("registration_block", "address_normalized"): True,
    ("registration_lock", "address_normalized"): True,
    ("request", "filed_by"): False,  # who filed: `agent`, `hub`, …
    ("request", "humans_only"): False,
    ("runner_attachment", "detached_by"): True,
    ("runner_credential", "revoked_by"): True,
}

# Tables the deletion hands to the module that removes such a row anywhere (§2.9: "as a
# removal does", "as §6.3 deletes a profile", "as DELETE /runners/{id} removes it").
DELETION_THROUGH: dict[str, ModuleType] = {
    "agent_profile": agents,  # delete_profile
    "membership": members,  # apply_remove
    "runner": runners,  # remove
}

# Tables the deletion leaves as they are: their column points at the account row, which
# stays, and every view shows it as `Deleted account` (§2.9).
_RECORD = "the projects' or the instance's record, kept without the person (§2.9)"
_OPEN = "open: the row keeps the address after the deletion; raised with the coordinator"
DELETION_KEEPS = {
    "address_lock": _OPEN,
    "attachment": f"who deleted an attachment: {_RECORD}",
    "conversation_participant": f"who added or removed a participant: {_RECORD}",
    "credential": f"who paused or revoked an agent's credential: {_RECORD}",
    "event": "the log stays as written; a deleted person is shaped at read time (§2.9)",
    "idempotency_key": "a key expires after 24 hours (§1.5) and holds no personal data",
    "instance_landing": f"who edited the landing page: {_RECORD}",
    "instance_secret": f"who changed an instance secret: {_RECORD}",
    "instance_setting": f"who changed an instance setting: {_RECORD}",
    "memory_entry": f"who confirmed a project memory entry: {_RECORD}",
    "project": "an archived project of the namespace stays under its name (§2.9); "
    "the deletion reads projects for `namespace_owner` only",
    "project_alias": "an old project name stays reserved for good (§2.9, §6.25)",
    "registration_block": "the instance admin's block of an address (§16.4), not an account's",
    "registration_lock": _OPEN,
    "runner_attachment": f"who attached a runner to a project: {_RECORD}",
    "runner_credential": f"who revoked a runner's credential: {_RECORD}",
}

# The one table in DELETION_KEEPS that the deletion also names: it reads projects to find
# what the human owns (`namespace_owner`), but never deletes or blanks the row.
KEPT_THOUGH_READ = {"project"}

# Tables the export reads through another module rather than in `export.py` itself.
EXPORT_THROUGH: dict[str, ModuleType] = {
    "avatar_image": avatars,  # the avatar URL, never the image
    "notification_settings": notification_preferences,
    "recovery_code": second_factor,  # only how many are left, never a code
    "second_factor": second_factor,  # only whether one is enrolled, never a secret
}

# Tables the export leaves out. It holds what is about the caller or written by them,
# never a secret or a code (§2.9).
_SECRET = "a credential, code or sign-in state: never in the export (§2.9)"
_BOOKKEEPING = "the hub's own bookkeeping, not the caller's data"
_UNLISTED = "not in §2.9's list of what the export holds"
_INSTANCE = f"the instance's, not the caller's; {_UNLISTED}"
EXPORT_LEAVES_OUT = {
    "account_deletion": _UNLISTED,
    "account_lock": _BOOKKEEPING,
    "account_record": _UNLISTED,
    "account_registration": _UNLISTED,
    "address_lock": _BOOKKEEPING,
    "attachment": f"names a person only as who deleted it; {_UNLISTED}",
    "conversation_participant": f"names a person only as who added or removed; {_UNLISTED}",
    "credential": _SECRET,
    "device_code": _SECRET,
    "email_sign_in": _SECRET,
    "email_sign_in_day": _BOOKKEEPING,
    "forge_link_state": _SECRET,
    "human_device": _SECRET,
    "idempotency_key": _BOOKKEEPING,
    "instance_landing": _INSTANCE,
    "instance_secret": _INSTANCE,
    "instance_setting": _INSTANCE,
    "invitation": _UNLISTED,
    "join_link": _UNLISTED,
    "mail_item_sent": _BOOKKEEPING,
    "mail_outbox": _BOOKKEEPING,
    "memory_entry": _UNLISTED,
    "notification_mail_state": _BOOKKEEPING,
    "notification_position": _BOOKKEEPING,
    "notification_read": _BOOKKEEPING,
    "pending_registration": _SECRET,  # the password chosen with it
    "placement": _UNLISTED,
    "preferences_version": f"the current preferences are exported; {_UNLISTED}",
    "project_alias": _UNLISTED,
    "registration_block": _INSTANCE,
    "registration_lock": _BOOKKEEPING,
    "runner_attachment": _UNLISTED,
    "runner_credential": _SECRET,
    "runner_enrollment": _SECRET,
    "second_factor_reset": _SECRET,
    "soul_version": f"the current souls are exported; {_UNLISTED}",
}


def _foreign_to_human(column: Any) -> bool:
    return any(fk.column.table.name == ACCOUNT for fk in column.foreign_keys)


def _names_a_human(table: Table) -> bool:
    return any(
        _foreign_to_human(column)
        or column.name == "human_id"
        or NAMES_A_HUMAN.get((table.name, column.name), False)
        for column in table.columns
    )


def _looks_like_a_person(column: Any) -> bool:
    return bool(LOOKS_LIKE_A_PERSON.search(column.name)) and not column.foreign_keys


HUMAN_TABLES = sorted(
    table.name
    for table in metadata.tables.values()
    if table.name != ACCOUNT and _names_a_human(table)
)


def _code_of(module: ModuleType) -> str:
    """The module's code without comments and docstrings: a table named only in prose is
    not handled."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        first = body[0] if isinstance(body, list) and body else None
        docstring = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
        if docstring and isinstance(first.value.value, str):  # type: ignore[union-attr]
            node.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined, index]
    return ast.unparse(tree)


def _named_in(module: ModuleType, table: str) -> bool:
    """`t.<table>` in the module's code, as a whole name: `t.email_sign_in` is not named by
    `t.email_sign_in_day`."""
    return re.search(rf"\bt\.{table}\b", _code_of(module)) is not None


def test_every_column_that_looks_like_a_person_is_decided() -> None:
    undecided = [
        f"{table.name}.{column.name}"
        for table in metadata.tables.values()
        for column in table.columns
        if _looks_like_a_person(column) and (table.name, column.name) not in NAMES_A_HUMAN
    ]
    assert undecided == [], "decide in NAMES_A_HUMAN: " + ", ".join(undecided)


def test_the_deletion_handles_every_table_that_names_a_human() -> None:
    missing = [
        n
        for n in HUMAN_TABLES
        if not _named_in(account_deletion, n)
        and n not in DELETION_KEEPS
        and n not in DELETION_THROUGH
    ]
    assert missing == [], "decide in account_deletion.py or DELETION_KEEPS: " + ", ".join(missing)


def test_the_export_handles_every_table_that_names_a_human() -> None:
    missing = [
        n
        for n in HUMAN_TABLES
        if not _named_in(export, n) and n not in EXPORT_THROUGH and n not in EXPORT_LEAVES_OUT
    ]
    assert missing == [], "decide in export.py or EXPORT_LEAVES_OUT: " + ", ".join(missing)


def test_the_lists_name_only_what_they_must() -> None:
    """An entry for a column or table that is gone, no longer names a human, or that the
    code handles after all, is stale: the lists say no more than they need to."""
    columns = {(tb.name, c.name): c for tb in metadata.tables.values() for c in tb.columns}
    for key in NAMES_A_HUMAN:
        assert key in columns and _looks_like_a_person(columns[key]), key
    for table in DELETION_KEEPS:
        read_only = table in KEPT_THOUGH_READ  # named, but never deleted or blanked
        assert table in HUMAN_TABLES and (
            read_only or not _named_in(account_deletion, table)
        ), table
    for table, module in DELETION_THROUGH.items():
        assert table in HUMAN_TABLES and _named_in(module, table), table
    for table in EXPORT_LEAVES_OUT:
        assert table in HUMAN_TABLES and not _named_in(export, table), table
    for table, module in EXPORT_THROUGH.items():
        assert table in HUMAN_TABLES and _named_in(module, table), table
