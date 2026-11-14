"""docs/api.md §2.2, §16.2: a credential's verifier is stored sealed with the instance key."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass, replace

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
    return replace(settings, secret_key=KEY)


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
    assert _me(make_client, Holder(agent.credential_id, agent.value)) == (200, 200)
    with caplog.at_level(logging.WARNING, logger="maity_hub.auth.verifiers"):
        assert verifiers.check_at_startup(migrated, KEY) == (0, 1)
    assert "1 live credential verifier(s) are stored unsealed" in caplog.text


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
