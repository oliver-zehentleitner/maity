"""docs/api.md §2.2: a credential in a body is found whatever stands right before it, also
inside a JSON escape, and a real one is revoked."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from maity_hub.auth import credentials
from tests import factory
from tests.conftest import ClientFactory

DUMMY = "mty1.crd-dummy.abc_DEF-9"


@pytest.mark.parametrize("before", ["\n", "\t", "_", "a", "x9"])
def test_the_pattern_finds_a_credential_after_any_character(before: str) -> None:
    raw = json.dumps({"body": f"cfg:{before}{DUMMY}"}).encode()
    assert [(p.credential_id, p.secret) for p in credentials.find_all(raw)] == [
        ("crd-dummy", "abc_DEF-9")
    ]


def test_a_unicode_escape_hides_no_credential() -> None:
    raw = b'{"body": "see \\u006dty1.crd-dummy.abc_DEF-9"}'
    assert DUMMY.encode() not in raw  # only the decoded string holds it
    assert [p.credential_id for p in credentials.find_all(raw)] == ["crd-dummy"]


def test_a_key_is_read_as_well() -> None:
    raw = json.dumps({f"x\n{DUMMY}": 1}).encode()
    assert [p.credential_id for p in credentials.find_all(raw)] == ["crd-dummy"]


def test_one_credential_is_named_once() -> None:
    raw = json.dumps({"a": f"see {DUMMY}"}).encode()  # raw and decoded both hold it
    assert len(credentials.find_all(raw)) == 1


def test_no_json_and_no_credential_find_nothing() -> None:
    assert credentials.find_all(b"{not json mty1 crd x}") == []
    assert credentials.find_all(b'{"a": "mty1 crd-1 abc"}') == []
    assert credentials.find_all(b"[" * 100_000) == []  # too deep to decode: the raw scan stays


def _escaped(value: str, how: str) -> bytes:
    """A login body whose password holds `value` behind `how`."""
    if how == "unicode":  # the `m` of the prefix as `m`
        return b'{"email": "x", "password": "cfg: \\u006d' + value[1:].encode() + b'"}'
    return json.dumps({"email": "x", "password": f"cfg:{how}{value}"}).encode()


@pytest.mark.parametrize("how", ["\n", "\t", "_", "a", "unicode"])
def test_a_real_credential_after_any_character_is_refused_and_revoked(
    how: str, make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    factory.membership(migrated, project_id, human_id=owner)
    agent = factory.agent(migrated, project_id, owner)
    response = make_client().post(
        "/api/v1/auth/login",
        content=_escaped(agent.value, how),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400, response.text
    assert response.headers["Maity-Error"] == "credential_in_payload"
    with migrated.connect() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
    assert credential.revoked_at is not None
    assert credential.revoked_reason == "leaked_in_payload"


def test_a_dummy_after_a_newline_is_refused_and_revokes_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    response = make_client().post(
        "/api/v1/auth/login",
        content=json.dumps({"email": "x", "password": f"cfg:\n{DUMMY}"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.headers["Maity-Error"] == "credential_in_payload"
    with migrated.connect() as conn:
        assert conn.execute(select(t.credential.c.id)).first() is None
