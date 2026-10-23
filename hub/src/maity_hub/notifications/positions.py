"""Positions in a human's notifications (docs/api.md §18.2): opaque, sealed, bound to the
human they were issued to.

A position is a vector: per project the human is a member of, the highest `seq` it
covers, and for the account the highest record number. It is sealed with AES-256-GCM
under the position key, with the human's id and the purpose as associated data and a
version inside. The key comes from `MAITY_SECRET_KEY` (HKDF) when it is set, else from a
random key the hub stores at first use; changing the instance key invalidates every
position. A vector whose inline form would pass the cap is stored, and the position is
a sealed handle to it.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import Connection, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, ids
from maity_hub import instance_settings as store
from maity_hub import tables as t

PURPOSE = "notifications.position"
VERSION = 1
MAX_LENGTH = 4096
NONCE_BYTES = 12
# The hub's own position key when no instance key is set; not an admin secret, and not
# sealed (there is no key to seal it with): whoever reads the database reads every
# notification anyway (§18.2).
KEY_NAME = "notifications.position_key"

store.register_secret(KEY_NAME)


@dataclass(frozen=True)
class Position:
    projects: dict[str, int] = field(default_factory=dict)  # project id → highest seq
    account: int = 0  # highest record number

    def covers_event(self, project_id: str, seq: int, start: int) -> bool:
        """Whether an event lies behind the position; a project without a component
        starts where the membership began (§18.2)."""
        return seq <= max(self.projects.get(project_id, start), start)

    def covers_record(self, n: int) -> bool:
        return n <= self.account


def _key(conn: Connection, secret_key: bytes | None) -> bytes:
    if secret_key is not None:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=PURPOSE.encode()).derive(
            secret_key
        )
    stored = store.sealed(conn, KEY_NAME)
    if stored is not None and len(stored) == 32:
        return stored
    try:
        with conn.begin_nested():
            store.put_sealed(conn, KEY_NAME, os.urandom(32), None)
    except IntegrityError:
        pass  # another request made it first
    made = store.sealed(conn, KEY_NAME)
    assert made is not None
    return made


def _aad(human_id: str) -> bytes:
    return f"{human_id}|{PURPOSE}".encode()


def _seal(key: bytes, human_id: str, body: dict[str, Any]) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, json.dumps(body).encode(), _aad(human_id))
    return base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")


def _open(key: bytes, human_id: str, token: str) -> dict[str, Any] | None:
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        if len(raw) <= NONCE_BYTES:
            return None
        plain = AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], _aad(human_id))
        body = json.loads(plain)
    except (binascii.Error, ValueError, InvalidTag):
        return None
    return body if isinstance(body, dict) and body.get("v") == VERSION else None


def issue(conn: Connection, secret_key: bytes | None, human_id: str, position: Position) -> str:
    key = _key(conn, secret_key)
    vector = {"p": position.projects, "a": position.account}
    inline = _seal(key, human_id, {"v": VERSION, **vector})
    if len(inline) <= MAX_LENGTH:
        return inline
    handle = ids.new_id("notification_position")
    now = clock.now()
    conn.execute(
        insert(t.notification_position).values(
            id=handle, human_id=human_id, vector=vector, created_at=now, last_used_at=now
        )
    )
    return _seal(key, human_id, {"v": VERSION, "h": handle})


def read(conn: Connection, secret_key: bytes | None, human_id: str, token: str) -> Position | None:
    """The position, or None for one that does not open for this human: forged,
    altered, another human's, an old key, an old version, an expired handle, or the
    two-part form issued before (§18.2)."""
    if not token or len(token) > MAX_LENGTH:
        return None
    body = _open(_key(conn, secret_key), human_id, token)
    if body is None:
        return None
    if "h" in body:
        row = conn.execute(
            select(t.notification_position).where(
                t.notification_position.c.id == str(body["h"]),
                t.notification_position.c.human_id == human_id,
            )
        ).first()
        if row is None:
            return None
        conn.execute(
            update(t.notification_position)
            .where(t.notification_position.c.id == row.id)
            .values(last_used_at=clock.now())
        )
        body = {"v": VERSION, **row.vector}
    projects, account = body.get("p"), body.get("a")
    if not isinstance(projects, dict) or not isinstance(account, int):
        return None
    if not all(isinstance(k, str) and isinstance(v, int) for k, v in projects.items()):
        return None
    return Position(dict(projects), account)
