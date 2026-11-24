"""docs/api.md §2.2: a credential in a body is found whatever stands right before it, also
inside a JSON escape, and a real one is revoked."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, event, select

from maity_hub import tables as t
from maity_hub.auth import credentials, leaks
from maity_hub.errors import ApiError
from maity_hub.routes import board
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


ENCODINGS = ["utf-8-sig", "utf-16", "utf-16-be", "utf-16-le", "utf-32", "utf-32-be", "utf-32-le"]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_body_the_app_reads_as_json_is_scanned_in_any_encoding(encoding: str) -> None:
    raw = '{"body": "see \\u006dty1.crd-dummy.abc_DEF-9"}'.encode(encoding)
    assert json.loads(raw) == {"body": f"see {DUMMY}"}  # the app's parser reads it
    assert [p.credential_id for p in credentials.find_all(raw)] == ["crd-dummy"]


def _escaped(value: str, how: str) -> bytes:
    """A login body whose password holds `value` behind `how`."""
    if how == "unicode":  # the `m` of the prefix as `\u006d`
        return b'{"email": "x", "password": "cfg: \\u006d' + value[1:].encode() + b'"}'
    if how in ("bom", "utf-16-be"):  # the same, in an encoding the app's parser also reads
        hidden = '{"email": "x", "password": "cfg: \\u006d' + value[1:] + '"}'
        return hidden.encode("utf-8-sig" if how == "bom" else how)
    return json.dumps({"email": "x", "password": f"cfg:{how}{value}"}).encode()


@pytest.mark.parametrize("how", ["\n", "\t", "_", "a", "unicode", "bom", "utf-16-be"])
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


# --- an id the hub could not have made is never looked up (tsk-ehtws6xrxdtf) ------------------

SHAPED = "mty1.crd-0123456789ab.abc_DEF-9"  # an id `new_id("credential")` could make, unknown


@contextlib.contextmanager
def _credential_reads() -> Iterator[list[str]]:
    """The statements any engine sends that read an agent's or a runner's credential row."""
    seen: list[str] = []

    def record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        lowered = statement.lower()
        if "from credential" in lowered or "from runner_credential" in lowered:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _login_with(client: Any, *values: str) -> Any:
    password = "cfg:" + " ".join(values)
    return client.post(
        "/api/v1/auth/login",
        content=json.dumps({"email": "x", "password": password}).encode(),
        headers={"Content-Type": "application/json"},
    )


def test_a_shapeless_id_is_refused_without_a_database_lookup(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """`crd-dummy` is no id the hub makes (`ids.has_shape`): the request is refused as ever,
    and no credential row is read. An unknown id of the right shape is still looked up."""
    client = make_client()  # its start reads the live credentials, before the count begins
    with _credential_reads() as seen:
        response = _login_with(client, DUMMY)
    assert (response.status_code, response.headers["Maity-Error"]) == (
        400,
        "credential_in_payload",
    )
    assert seen == []
    with _credential_reads() as seen:
        assert _login_with(client, SHAPED).status_code == 400
    assert seen  # the shape check lets it through to the lookup


def test_shapeless_ids_take_no_lookup_place_from_a_real_one(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Only `MAX_IDS` distinct ids are looked up; ids that cannot exist take none of those
    places, so a real credential after them is still revoked."""
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    factory.membership(migrated, project_id, human_id=owner)
    agent = factory.agent(migrated, project_id, owner)
    padding = [f"mty1.crd-fake{n:02d}.secret" for n in range(leaks.MAX_IDS)]
    assert _login_with(make_client(), *padding, agent.value).status_code == 400
    with migrated.connect() as conn:
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
    assert credential.revoked_reason == "leaked_in_payload"


def test_the_forge_check_opens_no_transaction_for_a_shapeless_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An issue the forge passes on (`board._refuse_credentials`) is refused all the same, and
    only an id the hub could have made opens a transaction for the lookup."""
    opened: list[str] = []

    @contextlib.contextmanager
    def transaction(_engine: Any) -> Iterator[None]:
        opened.append("transaction")
        yield None

    monkeypatch.setattr(board, "transaction", transaction)
    monkeypatch.setattr(board, "engine_of", lambda _request: None)
    monkeypatch.setattr(board, "revoke_leaked", lambda _conn, _found: [])
    for value, expected in ((DUMMY, []), (SHAPED, ["transaction"])):
        opened.clear()
        with pytest.raises(ApiError) as refused:
            board._refuse_credentials(None, {"title": f"see {value}"})  # type: ignore[arg-type]
        assert refused.value.code == "credential_in_payload"
        assert opened == expected, value
