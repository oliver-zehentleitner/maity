"""docs/api.md §2.2, §16.2: with MAITY_SEAL_VERIFIERS on, a credential's verifier is stored
sealed with the instance key; off (the default) it is stored plain, and sealed rows still read."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass, replace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials, verifiers
from maity_hub.config import Settings
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_auth_agent import signed
from tests.test_runners import call, error, paired

KEY = base64.b64decode("q0bS0b3k1uN4b9dW8m2Yx5zR7cJ6vT1eH3gK8pL0aQs=")
OTHER = bytes(32)
HEX = re.compile(r"[0-9a-f]{64}")
RUNNER_ROUTE = "/api/v1/runner/placements"


@dataclass(frozen=True)
class Holder:
    credential_id: str
    value: str


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, secret_key=KEY, seal_verifiers=True)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _joined(make_client: ClientFactory, owner: flow.Human) -> Holder:
    agent = flow.agent(make_client, owner)
    return Holder(agent.credential_id, agent.credential)


def _stored(engine: Engine, holder: Holder) -> str:
    table = t.runner_credential if holder.credential_id.startswith("rcrd-") else t.credential
    with engine.connect() as conn:
        value: str = conn.execute(
            select(table.c.verifier).where(table.c.id == holder.credential_id)
        ).scalar_one()
    return value


def _sealing_off(make_client: ClientFactory) -> ClientFactory:
    def off(**overrides: object) -> Any:
        return make_client(**{"seal_verifiers": False, **overrides})

    return off


def _me(make_client: ClientFactory, holder: Holder, **overrides: object) -> tuple[int, int]:
    client = make_client(**overrides)
    bearer = client.get("/api/v1/me", headers={"Authorization": f"Bearer {holder.value}"})
    by_signature = client.get("/api/v1/me", headers=signed(holder, "GET", "/api/v1/me"))
    return bearer.status_code, by_signature.status_code


def test_a_joined_agent_s_verifier_is_stored_sealed_and_verifies(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = _joined(make_client, owner)
    stored = _stored(migrated, agent)
    verifier = credentials.verifier_of(agent.value.split(".")[2])
    assert stored.startswith("s1:")
    assert verifier not in stored
    assert _me(make_client, agent) == (200, 200)


def test_the_stored_value_alone_signs_nothing(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """What the row holds is no HMAC key: neither its text nor its decoded bytes sign."""
    agent = _joined(make_client, owner)
    stored = _stored(migrated, agent)
    client = make_client()
    for key in (stored.encode(), base64.b64decode(stored[3:])):
        timestamp = str(int(clock.now().timestamp()))
        nonce = secrets.token_urlsafe(16)
        canonical = credentials.canonical_string("GET", b"/api/v1/me", b"", timestamp, nonce, b"")
        signature = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
        headers = {
            "Authorization": f"Maity-HMAC {agent.credential_id}",
            "Maity-Timestamp": timestamp,
            "Maity-Nonce": nonce,
            "Maity-Signature": signature,
        }
        response = client.get("/api/v1/me", headers=headers)
        assert (response.status_code, response.headers["Maity-Error"]) == (
            401,
            "signature_invalid",
        )


def test_a_paired_runner_s_verifier_is_stored_sealed_and_verifies(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    assert _stored(migrated, Holder(runner.credential_id, runner.value)).startswith("s1:")
    assert call(make_client(), runner, "GET", RUNNER_ROUTE).status_code == 200


def test_a_sealed_row_copied_to_another_credential_does_not_open(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    first, second = _joined(make_client, owner), _joined(make_client, owner)
    sealed = _stored(migrated, first)
    with migrated.begin() as conn:
        conn.execute(
            t.credential.update()
            .where(t.credential.c.id == second.credential_id)
            .values(verifier=sealed)
        )
    copied = Holder(
        second.credential_id, first.value.replace(first.credential_id, second.credential_id)
    )
    assert _me(make_client, copied) == (401, 401)


def test_another_instance_key_verifies_no_sealed_credential(
    make_client: ClientFactory,
    owner: flow.Human,
    migrated: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    agent = _joined(make_client, owner)
    runner = paired(make_client, owner)
    assert _me(make_client, agent, secret_key=OTHER) == (401, 401)
    assert _me(make_client, agent, secret_key=None) == (401, 401)
    refused = call(make_client(secret_key=OTHER), runner, "GET", RUNNER_ROUTE)
    assert (refused.status_code, error(refused)) == (401, "signature_invalid")
    with caplog.at_level(logging.ERROR, logger="maity_hub.auth.verifiers"):
        assert verifiers.check_at_startup(migrated, OTHER) == (2, 0)
    assert "2 live credential(s) cannot be verified" in caplog.text
    assert "not the key they were sealed with" in caplog.text
    assert _me(make_client, agent, secret_key=KEY) == (200, 200)  # the key back, all verify


def test_without_a_key_the_verifier_is_stored_plain(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = _joined(lambda **o: make_client(**{"secret_key": None, **o}), owner)
    assert HEX.fullmatch(_stored(migrated, agent))
    assert _me(make_client, agent, secret_key=None) == (200, 200)


def test_a_plain_row_still_verifies_with_a_key_and_is_counted(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    project_id = factory.project(migrated)
    human = factory.human(migrated)
    factory.membership(migrated, project_id, human_id=human)
    agent = factory.agent(migrated, project_id, human)  # written plain, outside an app
    # With sealing off, so that the call does not reseal it (`test_a_plain_row_is_resealed_…`).
    holder = Holder(agent.credential_id, agent.value)
    assert _me(make_client, holder, seal_verifiers=False) == (200, 200)
    with caplog.at_level(logging.WARNING, logger="maity_hub.auth.verifiers"):
        assert verifiers.check_at_startup(migrated, KEY, seal=True) == (0, 1)
    assert "1 live credential verifier(s) are stored unsealed; sealing is on" in caplog.text
    assert "maity-hub seal-verifiers" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="maity_hub.auth.verifiers"):
        assert verifiers.check_at_startup(migrated, KEY) == (0, 1)
    assert "1 live credential verifier(s) are stored unsealed; sealing is off" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_sealed_credential_in_a_payload_is_revoked(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = _joined(make_client, owner)
    runner = paired(make_client, owner)
    for value in (agent.value, runner.value):
        leaked = make_client().post(
            "/api/v1/auth/login", json={"email": "x", "password": f"see {value} here"}
        )
        assert (leaked.status_code, error(leaked)) == (400, "credential_in_payload")
    with migrated.connect() as conn:
        reasons = [
            conn.execute(
                select(table.c.revoked_reason).where(table.c.id == credential_id)
            ).scalar_one()
            for table, credential_id in (
                (t.credential, agent.credential_id),
                (t.runner_credential, runner.credential_id),
            )
        ]
    assert reasons == ["leaked_in_payload", "leaked_in_payload"]


def test_with_sealing_off_and_a_key_the_verifier_is_stored_plain(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """The default: the key is set, MAITY_SEAL_VERIFIERS is not; joins and pairings write hex
    as before sealing existed."""
    off = _sealing_off(make_client)
    agent = _joined(off, owner)
    runner = paired(off, owner)
    assert HEX.fullmatch(_stored(migrated, agent))
    assert HEX.fullmatch(_stored(migrated, Holder(runner.credential_id, runner.value)))
    assert _me(off, agent) == (200, 200)
    assert call(off(), runner, "GET", RUNNER_ROUTE).status_code == 200


def test_a_sealed_row_still_verifies_after_sealing_is_switched_off(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """Switching the setting off again locks no one out while the key stays; without the key
    a sealed row verifies nothing, whatever the setting."""
    agent = _joined(make_client, owner)
    runner = paired(make_client, owner)
    assert _stored(migrated, agent).startswith("s1:")
    assert _me(make_client, agent, seal_verifiers=False) == (200, 200)
    off = make_client(seal_verifiers=False)
    assert call(off, runner, "GET", RUNNER_ROUTE).status_code == 200
    assert _me(make_client, agent, seal_verifiers=False, secret_key=None) == (401, 401)


def test_seal_plain_seals_only_the_plain_rows_and_a_second_run_nothing(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    sealed_before = _joined(make_client, owner)
    off = _sealing_off(make_client)
    plain_agent = _joined(off, owner)
    plain_runner = paired(off, owner)
    kept = _stored(migrated, sealed_before)
    assert verifiers.seal_plain(migrated, KEY) == {"credential": 1, "runner_credential": 1}
    assert _stored(migrated, sealed_before) == kept
    for holder in (plain_agent, Holder(plain_runner.credential_id, plain_runner.value)):
        assert _stored(migrated, holder).startswith("s1:")
    assert _me(make_client, plain_agent) == (200, 200)
    assert _me(off, plain_agent) == (200, 200)
    assert call(make_client(), plain_runner, "GET", RUNNER_ROUTE).status_code == 200
    assert verifiers.seal_plain(migrated, KEY) == {"credential": 0, "runner_credential": 0}
    assert verifiers.check_at_startup(migrated, KEY, seal=True) == (0, 0)


# --- counting, reseal on use, sealed only (tsk-ebc2fhdxttm7) ------------------------------


def _revoke(engine: Engine, holder: Holder) -> None:
    with engine.begin() as conn:
        conn.execute(
            t.credential.update()
            .where(t.credential.c.id == holder.credential_id)
            .values(revoked_at=clock.now(), revoked_reason="replaced")
        )


def test_a_mixed_table_is_counted_then_sealed_with_revoked_rows_too(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """Sealed, plain and revoked plain rows: the dry run counts and writes nothing; the run
    seals every plain row and says what it found sealed already and what is left."""
    _joined(make_client, owner)  # sealed
    off = _sealing_off(make_client)
    plain, revoked = _joined(off, owner), _joined(off, owner)
    paired(off, owner)  # a plain runner
    _revoke(migrated, revoked)
    before = _stored(migrated, plain)
    assert verifiers.count(migrated) == {
        "credential": verifiers.Counted(sealed=0, already=1, left=2),
        "runner_credential": verifiers.Counted(sealed=0, already=0, left=1),
    }
    assert _stored(migrated, plain) == before  # nothing written
    assert verifiers.seal_and_count(migrated, KEY) == {
        "credential": verifiers.Counted(sealed=2, already=1, left=0),
        "runner_credential": verifiers.Counted(sealed=1, already=0, left=0),
    }
    assert _stored(migrated, revoked).startswith("s1:")
    assert verifiers.seal_and_count(migrated, KEY) == {
        "credential": verifiers.Counted(sealed=0, already=3, left=0),
        "runner_credential": verifiers.Counted(sealed=0, already=1, left=0),
    }


def test_a_plain_row_is_resealed_by_its_first_call_while_sealing_is_on(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """A key added later: rows written before stay plain until they are used (or sealed by
    the command); a call with sealing on seals its own row in the `last_used_at` update."""
    off = _sealing_off(make_client)
    agent = _joined(lambda **o: off(**{"secret_key": None, **o}), owner)
    runner = paired(lambda **o: off(**{"secret_key": None, **o}), owner)
    runner_holder = Holder(runner.credential_id, runner.value)
    assert HEX.fullmatch(_stored(migrated, agent))
    assert _me(off, agent) == (200, 200)  # the key, sealing off: read, not resealed
    assert call(off(), runner, "GET", RUNNER_ROUTE).status_code == 200
    assert HEX.fullmatch(_stored(migrated, agent))
    assert HEX.fullmatch(_stored(migrated, runner_holder))
    client = make_client()
    bearer = client.get("/api/v1/me", headers={"Authorization": f"Bearer {agent.value}"})
    assert bearer.status_code == 200
    assert _stored(migrated, agent).startswith("s1:")
    assert call(client, runner, "GET", RUNNER_ROUTE).status_code == 200
    resealed = _stored(migrated, runner_holder)
    assert resealed.startswith("s1:")
    assert _me(make_client, agent) == (200, 200)
    assert call(make_client(), runner, "GET", RUNNER_ROUTE).status_code == 200
    assert _stored(migrated, runner_holder) == resealed  # a sealed row is not written again
    assert verifiers.check_at_startup(migrated, KEY, seal=True) == (0, 0)


def test_reseal_on_use_leaves_a_row_replaced_meanwhile_alone(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    human = factory.human(migrated)
    factory.membership(migrated, project_id, human_id=human)
    agent = factory.agent(migrated, project_id, human)
    make_client()  # configures the key with sealing on
    holder = Holder(agent.credential_id, agent.value)
    read = _stored(migrated, holder)
    replaced = "ab" * 32
    column = t.credential.c.verifier
    with migrated.begin() as conn:
        conn.execute(
            t.credential.update()
            .where(t.credential.c.id == holder.credential_id)
            .values(verifier=replaced)
        )
        conn.execute(
            t.credential.update()
            .where(t.credential.c.id == holder.credential_id)
            .values(
                last_used_via="bearer",
                **verifiers.reseal_value("credential", column, holder.credential_id, read),
            )
        )
    assert _stored(migrated, holder) == replaced
    assert verifiers.reseal_value("credential", column, holder.credential_id, "s1:x") == {}


def test_sealed_only_refuses_a_plain_row_as_a_sealed_row_the_key_does_not_open(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """With MAITY_SEALED_VERIFIERS_ONLY and no plain row left the hub starts; a plain row that
    appears afterwards (an old pod's write) verifies nothing, and the answers are the ones a
    sealed row the key does not open gets: no new detail."""
    sealed_agent = _joined(make_client, owner)
    sealed_runner = paired(make_client, owner)
    only = make_client(sealed_verifiers_only=True)  # starts: every live row is sealed
    # Another app the test makes configures the module anew (`verifiers.configure`), so the
    # sealed-only app's configuration is set again before each of its calls.
    as_only = (KEY, True, True)
    other = make_client(secret_key=OTHER)  # what a sealed row the key does not open answers
    unopened = (
        other.get("/api/v1/me", headers={"Authorization": f"Bearer {sealed_agent.value}"}),
        other.get("/api/v1/me", headers=signed(sealed_agent, "GET", "/api/v1/me")),
        call(other, sealed_runner, "GET", RUNNER_ROUTE),
    )
    project_id = factory.project(migrated)
    factory.membership(migrated, project_id, human_id=owner.id)
    written = factory.agent(migrated, project_id, owner.id)  # plain, as an old pod writes
    plain = Holder(written.credential_id, written.value)
    plain_runner = paired(_sealing_off(make_client), owner, name="old-pod")
    verifiers.configure(*as_only)
    refused = (
        only.get("/api/v1/me", headers={"Authorization": f"Bearer {plain.value}"}),
        only.get("/api/v1/me", headers=signed(plain, "GET", "/api/v1/me")),
        call(only, plain_runner, "GET", RUNNER_ROUTE),
    )
    assert [(r.status_code, error(r)) for r in refused] == [
        (401, "unauthenticated"),
        (401, "signature_invalid"),
        (401, "signature_invalid"),
    ]
    assert [r.json() for r in refused] == [r.json() for r in unopened]
    assert HEX.fullmatch(_stored(migrated, plain))  # refused, so not resealed
    assert _me(lambda **_: only, sealed_agent) == (200, 200)
    assert call(only, sealed_runner, "GET", RUNNER_ROUTE).status_code == 200
    verifiers.configure(KEY, True)  # the setting off: the plain row verifies again
    assert _me(lambda **_: only, plain) == (200, 200)


def test_sealed_only_refuses_the_start_while_a_live_plain_row_is_left(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine, settings: Settings
) -> None:
    from maity_hub.app import check_startup
    from maity_hub.config import ConfigError

    off = _sealing_off(make_client)
    plain, revoked = _joined(off, owner), _joined(off, owner)
    _revoke(migrated, revoked)
    only = replace(settings, sealed_verifiers_only=True)
    with pytest.raises(ConfigError) as refused:
        check_startup(migrated, only)
    assert str(refused.value) == (
        "MAITY_SEALED_VERIFIERS_ONLY=1, but 1 live credential verifier(s) are stored "
        "unsealed; run `maity-hub seal-verifiers` first"
    )
    check_startup(migrated, settings)  # the setting off: the same table starts
    verifiers.seal_plain(migrated, KEY)
    check_startup(migrated, only)
    assert _me(make_client, plain, sealed_verifiers_only=True) == (200, 200)


def test_sealed_only_still_revokes_a_leaked_plain_credential(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """The leak check reads plain rows whatever the setting: a credential refused now would
    verify again once the setting is switched off."""
    only = make_client(sealed_verifiers_only=True)
    project_id = factory.project(migrated)
    factory.membership(migrated, project_id, human_id=owner.id)
    agent = factory.agent(migrated, project_id, owner.id)  # plain, written after the start
    leaked = only.post(
        "/api/v1/auth/login", json={"email": "x", "password": f"see {agent.value} here"}
    )
    assert (leaked.status_code, error(leaked)) == (400, "credential_in_payload")
    with migrated.connect() as conn:
        reason = conn.execute(
            select(t.credential.c.revoked_reason).where(t.credential.c.id == agent.credential_id)
        ).scalar_one()
    assert reason == "leaked_in_payload"
