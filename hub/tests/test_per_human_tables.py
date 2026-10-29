"""docs/api.md §2.9: every table that names a human is handled by the account deletion and
by the export, or left out on purpose with a reason. A new table that names a human fails
here until someone decides which (forge links and sign-in links were missed once, #586)."""

from __future__ import annotations

import inspect
from types import ModuleType

from sqlalchemy import Table

from maity_hub import account_deletion, export
from maity_hub import tables as t  # noqa: F401  (registers every table on the metadata)
from maity_hub.auth import second_factor
from maity_hub.db import metadata
from maity_hub.notifications import preferences as notification_preferences

# The account row itself stays with its id, so that every stored id keeps resolving (§2.9).
ACCOUNT = "human"

# Tables the deletion leaves as they are: their column points at the account row, which
# stays, and every view shows it as `Deleted account` (§2.9).
_RECORD = "the projects' or the instance's record, kept without the person (§2.9)"
DELETION_KEEPS = {
    "instance_secret": f"who changed an instance secret: {_RECORD}",
    "instance_setting": f"who changed an instance setting: {_RECORD}",
    "memory_entry": f"who confirmed a project memory entry: {_RECORD}",
    "project_alias": "an old project name stays reserved for good (§2.9, §6.25)",
    "runner_attachment": f"who attached a runner to a project: {_RECORD}",
}

# Tables the export reads through another module rather than in `export.py` itself.
EXPORT_THROUGH: dict[str, ModuleType] = {
    "notification_settings": notification_preferences,
    "recovery_code": second_factor,  # only how many are left, never a code
    "second_factor": second_factor,  # only whether one is enrolled, never a secret
}

# Tables the export leaves out. It holds what is about the caller or written by them,
# never a secret or a code (§2.9).
_SECRET = "a credential, code or sign-in state: never in the export (§2.9)"
_BOOKKEEPING = "the hub's own bookkeeping, not the caller's data"
_UNLISTED = "not in §2.9's list of what the export holds"
EXPORT_LEAVES_OUT = {
    "account_deletion": _UNLISTED,
    "account_lock": _BOOKKEEPING,
    "account_record": _UNLISTED,
    "account_registration": _UNLISTED,
    "device_code": _SECRET,
    "email_sign_in": _SECRET,
    "email_sign_in_day": _BOOKKEEPING,
    "forge_link_state": _SECRET,
    "human_device": _SECRET,
    "instance_secret": f"the instance's, not the caller's; {_UNLISTED}",
    "instance_setting": f"the instance's, not the caller's; {_UNLISTED}",
    "invitation": _UNLISTED,
    "join_link": _UNLISTED,
    "mail_item_sent": _BOOKKEEPING,
    "mail_outbox": _BOOKKEEPING,
    "memory_entry": _UNLISTED,
    "notification_mail_state": _BOOKKEEPING,
    "notification_position": _BOOKKEEPING,
    "notification_read": _BOOKKEEPING,
    "placement": _UNLISTED,
    "preferences_version": f"the current preferences are exported; {_UNLISTED}",
    "project_alias": _UNLISTED,
    "runner_attachment": _UNLISTED,
    "runner_enrollment": _SECRET,
    "second_factor_reset": _SECRET,
    "soul_version": f"the current souls are exported; {_UNLISTED}",
}


def _names_a_human(table: Table) -> bool:
    """A column with a foreign key to `human`, or one called `human_id` without one."""
    return any(
        column.name == "human_id"
        or any(fk.column.table.name == ACCOUNT for fk in column.foreign_keys)
        for column in table.columns
    )


HUMAN_TABLES = sorted(
    table.name
    for table in metadata.tables.values()
    if table.name != ACCOUNT and _names_a_human(table)
)


def _named_in(module: ModuleType, table: str) -> bool:
    return f"t.{table}" in inspect.getsource(module)


def test_the_deletion_handles_every_table_that_names_a_human() -> None:
    missing = [
        n for n in HUMAN_TABLES if not _named_in(account_deletion, n) and n not in DELETION_KEEPS
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
    """A list entry for a table that no longer names a human, or that the code handles
    after all, is stale: the list says no more than it needs to."""
    for table in DELETION_KEEPS:
        assert table in HUMAN_TABLES and not _named_in(account_deletion, table), table
    for table in EXPORT_LEAVES_OUT:
        assert table in HUMAN_TABLES and not _named_in(export, table), table
    for table, module in EXPORT_THROUGH.items():
        assert table in HUMAN_TABLES and _named_in(module, table), table
