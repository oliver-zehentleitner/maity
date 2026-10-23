"""Opaque ids: a readable prefix and 12 random Crockford base32 characters.

Clients never parse them (docs/api.md §1.1); the prefix only helps a human
reading a log. 60 random bits keep collisions out of reach for one
instance; the primary key catches the impossible case.
"""

from __future__ import annotations

import secrets

CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"

PREFIXES = {
    "human": "hum",
    "agent": "agt",
    "project": "prj",
    "join": "join",
    "credential": "crd",
    "session": "ses",
    "task": "tsk",
    "release": "rel",
    "contract": "ctr",
    "request": "req",
    "runner": "rnr",
    "runner_enrollment": "renr",
    "runner_credential": "rcrd",
    "runner_attachment": "ratt",
    "runner_session": "rses",
    "placement": "plc",
    "memory": "mem",
    "conversation": "cnv",
}


def new_id(entity: str) -> str:
    return f"{PREFIXES[entity]}-{''.join(secrets.choice(CROCKFORD) for _ in range(12))}"


# An agent instance's id (docs/api.md §6.17): no 0, 1, i, l or o, so that it reads
# aloud and types without doubt. Four characters now; the pattern takes five.
INSTANCE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
INSTANCE_LENGTH = 4


def new_instance_id(taken: set[str]) -> str:
    """An id not in `taken`: every id the membership ever gave, revoked ones included."""
    while True:
        candidate = "".join(secrets.choice(INSTANCE_ALPHABET) for _ in range(INSTANCE_LENGTH))
        if candidate not in taken:
            return candidate
