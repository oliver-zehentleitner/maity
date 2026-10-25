"""The instance's mail settings and the test send (docs/api.md §16.2, §16.3)."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import replace
from email import message_from_bytes
from email.policy import default
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, secretbox
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.mail import address, headers, settings, smtp
from maity_hub.mail.environment import Sender
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.smtpfake import FakeSmtp, Script, certificate
from tests.test_mentions import agent_named

KEY = base64.b64encode(b"k" * 32).decode()
OTHER_KEY = base64.b64encode(b"o" * 32).decode()
SIGNING = base64.b64encode(b"s" * 32).decode()
PASSWORD = "smtp secret 9Xq!"
PATH = "/admin/settings/mail"


def env_of(**values: str) -> Settings:
    return Settings.from_env({"MAITY_DATABASE_URL": "sqlite://", **values})


def admin(make_client: ClientFactory, engine: Engine, hub: Settings) -> flow.Human:
    """The instance admin (the first human, made on first use), signed in to a hub with
    these mail settings."""
    with engine.begin() as conn:
        found = conn.execute(select(t.human.c.id).where(t.human.c.handle == "maintainer"))
        human_id = found.scalar() or None
    if human_id is None:
        human_id = factory.human(engine, "maintainer")
    client = make_client(mail=hub.mail, secret_key=hub.secret_key)
    response = client.post(
        "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
    )
    assert response.status_code == 200, response.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, human_id)


@pytest.fixture
def smtp_server() -> Iterator[list[FakeSmtp]]:
    started: list[FakeSmtp] = []
    yield started
    for server in started:
        server.close()


def serve(started: list[FakeSmtp], script: Script) -> FakeSmtp:
    server = FakeSmtp(script)
    started.append(server)
    return server


def local_env(port: int, **more: str) -> Settings:
    return env_of(
        MAITY_SMTP_HOST="127.0.0.1",
        MAITY_SMTP_PORT=str(port),
        MAITY_SMTP_FROM="Maity <maity@example.org>",
        MAITY_MAIL_SIGNING_KEY=SIGNING,
        **{"MAITY_SMTP_TLS": "none", **more},
    )


# --- the environment ----------------------------------------------------------------


def test_the_environment_sets_every_value(tmp_path: Path) -> None:
    secret_file = tmp_path / "pw"
    secret_file.write_text(PASSWORD + "\n")
    hub = env_of(
        MAITY_SMTP_HOST="smtp.example.org",
        MAITY_SMTP_PORT="2525",
        MAITY_SMTP_TLS="implicit",
        MAITY_SMTP_USERNAME="maity@example.org",
        MAITY_SMTP_PASSWORD_FILE=str(secret_file),
        MAITY_SMTP_FROM="Maity Hub <maity@example.org>",
        MAITY_SMTP_REPLY_TO="ops@example.org",
        MAITY_MAIL_MAX_PER_HOUR="10",
        MAITY_MAIL_SECURITY_MAX_PER_HOUR="20",
        MAITY_MAIL_SIGN_IN_MAX_PER_HOUR="30",
        MAITY_MAIL_REGISTRATION_MAX_PER_HOUR="40",
        MAITY_SECRET_KEY=KEY,
        MAITY_MAIL_SIGNING_KEY=SIGNING,
        KUBERNETES_SERVICE_HOST="10.0.0.1",
    )
    mail = hub.mail
    assert (mail.host, mail.port, mail.tls, mail.password) == (
        "smtp.example.org",
        2525,
        "implicit",
        PASSWORD,
    )
    assert mail.sender == Sender("maity@example.org", "Maity Hub")
    budgets = (
        mail.max_per_hour,
        mail.security_max_per_hour,
        mail.sign_in_max_per_hour,
        mail.registration_max_per_hour,
    )
    assert budgets == (10, 20, 30, 40)
    assert mail.in_kubernetes and hub.secret_key == b"k" * 32
    assert PASSWORD not in repr(hub) and KEY not in repr(hub) and "kkkk" not in repr(hub)


@pytest.mark.parametrize(
    "values",
    [
        {"MAITY_SMTP_TLS": "none", "MAITY_SMTP_HOST": "smtp.example.org"},
        {"MAITY_SMTP_TLS": "ssl"},
        {"MAITY_SMTP_HOST": "smtp.example.org:25"},
        {"MAITY_SMTP_PORT": "0"},
        {"MAITY_SMTP_PORT": "x"},
        {"MAITY_SMTP_FROM": "a@b.co, c@d.co"},
        {"MAITY_SMTP_FROM": "Maity <maity@localhost>"},
        {"MAITY_SMTP_REPLY_TO": "<ops@example.org>"},
        {"MAITY_SECRET_KEY": base64.b64encode(b"short").decode()},
        {"MAITY_SECRET_KEY": "not base64!"},
        {"MAITY_MAIL_SIGNING_KEY": base64.b64encode(b"s" * 31).decode()},
        {"MAITY_SMTP_PASSWORD": "a", "MAITY_SMTP_PASSWORD_FILE": "/nonexistent"},
        {"MAITY_SMTP_PASSWORD_FILE": "/nonexistent/password"},
        {"MAITY_SMTP_PASSWORD": "line\nbreak"},
        {"MAITY_SMTP_ALLOW_PLAINTEXT": "maybe"},
        {"MAITY_SMTP_CA_FILE": "/nonexistent/ca.pem"},
        {"MAITY_MAIL_MAX_PER_HOUR": "-1"},
        {"MAITY_SMTP_PASSWORD": "pässword"},
        {"MAITY_SMTP_USERNAME": "mäity"},
    ],
)
def test_an_unusable_value_in_the_environment_stops_the_hub(values: dict[str, str]) -> None:
    with pytest.raises(ConfigError) as raised:
        env_of(**values)
    assert "line\nbreak" not in str(raised.value) and "pässword" not in str(raised.value)


def test_tls_none_is_allowed_for_a_loopback_host() -> None:
    for host in ("localhost", "LOCALHOST.", "127.0.0.1", "::1"):
        assert env_of(MAITY_SMTP_TLS="none", MAITY_SMTP_HOST=host).mail.tls == "none"


# --- reading and changing the settings ----------------------------------------------


def test_the_defaults_and_who_may_read_them(make_client: ClientFactory, migrated: Engine) -> None:
    owner = admin(make_client, migrated, env_of())
    flow.project(owner)
    got = owner.get(PATH).json()
    assert (got["enabled"], got["complete"], got["missing"]) == (
        True,
        False,
        ["host", "from", "signing_key"],
    )
    assert got["port"] == {"value": 587, "source": "default"}
    assert got["tls"] == {"value": "starttls", "source": "default"}
    assert got["password"] == {"set": False, "source": None}
    assert got["signing_key"] == {"set": False} and got["secret_key"] == {"set": False}
    assert got["max_per_hour"] == {"value": 500, "source": "default"}
    assert got["security_max_per_hour"]["value"] == 100
    assert got["sign_in_max_per_hour"]["value"] == 60
    assert got["registration_max_per_hour"] == {"value": 30, "source": "default"}
    assert got["registration_sent_last_hour"] == got["registration_dropped_last_hour"] == 0
    assert got["warnings"] == [] and got["last_test"] is None
    assert got["sent_last_hour"] == got["failed_last_hour"] == got["security_queued"] == 0

    other = flow.human(make_client, migrated, "someone")
    for call in (other.get(PATH), other.patch(PATH, {"enabled": False})):
        assert (call.status_code, call.json()["error"]["details"]) == (
            403,
            {"scope": "instance:admin"},
        )
    agent = agent_named(make_client, owner, "agent-a")
    assert agent.get(PATH).status_code == 403
    assert agent.patch(PATH, {"enabled": False}).status_code == 403
    assert agent.post(f"{PATH}/test", {"to": "a@example.org"}).status_code == 403


def test_the_admin_sets_values_and_the_environment_wins(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(
        make_client,
        migrated,
        env_of(MAITY_SMTP_HOST="smtp.example.org", MAITY_MAIL_SIGNING_KEY=SIGNING),
    )
    changed = owner.patch(
        PATH,
        {
            "port": 2525,
            "from": {"address": "maity@example.org", "name": "Maity"},
            "reply_to": "ops@example.org",
            "max_per_hour": 50,
            "enabled": False,
        },
    )
    assert changed.status_code == 200, changed.text
    got = changed.json()
    assert got["host"] == {"value": "smtp.example.org", "source": "env"}
    assert got["port"] == {"value": 2525, "source": "admin"}
    assert got["from"]["value"] == {"address": "maity@example.org", "name": "Maity"}
    assert (got["enabled"], got["complete"], got["missing"]) == (False, True, [])
    assert owner.get(PATH).json() == got

    refused = owner.patch(PATH, {"host": "other.example.org"})
    assert refused.json()["error"]["details"]["fields"] == {"host": "set_by_environment"}
    back = owner.patch(PATH, {"port": None, "reply_to": None}).json()
    assert back["port"] == {"value": 587, "source": "default"}
    assert back["reply_to"] == {"value": None, "source": "default"}


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        (
            {"signing_key": "x", "secret_key": "y"},
            {"signing_key": "environment_only", "secret_key": "environment_only"},
        ),
        ({"hostname": "x"}, {"hostname": "extra_forbidden"}),
        ({"port": 70000}, {"port": "invalid"}),
        ({"port": "25"}, {"port": "invalid"}),
        ({"port": True}, {"port": "invalid"}),
        ({"tls": "ssl"}, {"tls": "invalid"}),
        ({"host": "smtp.example.org/x"}, {"host": "invalid"}),
        ({"from": {"address": "Maity <maity@example.org>"}}, {"from": "invalid"}),
        (
            {"from": {"address": "maity@example.org", "name": "a\r\nBcc: x@y.z"}},
            {"from": "invalid"},
        ),
        ({"from": {"address": "maity@example.org", "extra": 1}}, {"from": "invalid"}),
        ({"reply_to": "a@b.co,c@d.co"}, {"reply_to": "invalid"}),
        ({"max_per_hour": 0}, {"max_per_hour": "invalid"}),
        ({"enabled": "yes"}, {"enabled": "invalid"}),
        ({"tls": "none", "host": "smtp.example.org"}, {"tls": "loopback_host_only"}),
        ({"username": "mäity"}, {"username": "invalid"}),
        ({"password": "pässword"}, {"password": "secret_key_missing"}),
    ],
)
def test_a_refused_patch_names_each_field_and_changes_nothing(
    make_client: ClientFactory, migrated: Engine, body: dict[str, Any], fields: dict[str, str]
) -> None:
    owner = admin(make_client, migrated, env_of())
    response = owner.patch(PATH, body)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == fields
    with migrated.begin() as conn:
        assert conn.execute(select(t.instance_setting)).all() == []
        assert conn.execute(select(t.instance_secret)).all() == []


def test_tls_none_stays_tied_to_a_loopback_host(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of())
    assert owner.patch(PATH, {"tls": "none", "host": "localhost"}).status_code == 200
    assert owner.get(PATH).json()["port"] == {"value": 25, "source": "default"}
    moved = owner.patch(PATH, {"host": "smtp.example.org"})
    assert moved.json()["error"]["details"]["fields"] == {"host": "loopback_host_only"}


def test_the_password_is_stored_encrypted_and_never_returned(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of())
    refused = owner.patch(PATH, {"password": PASSWORD})
    assert refused.json()["error"]["details"]["fields"] == {"password": "secret_key_missing"}
    assert PASSWORD not in refused.text

    keyed = admin(make_client, migrated, env_of(MAITY_SECRET_KEY=KEY))
    response = keyed.patch(PATH, {"username": "maity@example.org", "password": PASSWORD})
    assert response.status_code == 200
    assert PASSWORD not in response.text
    got = response.json()
    assert got["password"] == {"set": True, "source": "admin"}
    assert got["secret_key"] == {"set": True}
    with migrated.begin() as conn:
        secrets_row = conn.execute(select(t.instance_secret)).one()
        settings_rows = conn.execute(select(t.instance_setting)).all()
    assert (secrets_row.name, secrets_row.updated_by) == ("mail.smtp_password", keyed.id)
    assert PASSWORD not in secrets_row.sealed
    assert PASSWORD not in json.dumps([r.value for r in settings_rows])
    assert [r.name for r in settings_rows] == ["mail.username"]
    sealed = base64.b64decode(secrets_row.sealed)
    assert secretbox.open_sealed(b"k" * 32, "mail.smtp_password", sealed).decode() == PASSWORD
    with pytest.raises(secretbox.SealedError):  # bound to its field
        secretbox.open_sealed(b"k" * 32, "forge.webhook_secret", sealed)

    # Another instance key cannot decrypt it: not set, and missing while a username is.
    rekeyed = admin(make_client, migrated, env_of(MAITY_SECRET_KEY=OTHER_KEY)).get(PATH).json()
    assert rekeyed["password"] == {"set": False, "source": None}
    assert "password" in rekeyed["missing"]
    assert rekeyed["warnings"] == ["smtp_password_unreadable"]
    keyless = admin(make_client, migrated, env_of()).get(PATH).json()
    assert keyless["warnings"] == ["smtp_password_unreadable"]

    removed = keyed.patch(PATH, {"password": None}).json()
    assert removed["password"] == {"set": False, "source": None}
    assert removed["warnings"] == []


def test_a_password_from_the_environment_wins_and_cannot_be_patched(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of(MAITY_SMTP_PASSWORD=PASSWORD, MAITY_SECRET_KEY=KEY))
    assert owner.get(PATH).json()["password"] == {"set": True, "source": "env"}
    refused = owner.patch(PATH, {"password": "another one"})
    assert refused.json()["error"]["details"]["fields"] == {"password": "set_by_environment"}
    assert "another one" not in refused.text


def test_kubernetes_flags_a_password_from_the_database(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    keyed = admin(make_client, migrated, env_of(MAITY_SECRET_KEY=KEY))
    keyed.patch(PATH, {"password": PASSWORD})
    in_cluster = env_of(MAITY_SECRET_KEY=KEY, KUBERNETES_SERVICE_HOST="10.0.0.1")
    with caplog.at_level("WARNING"):
        owner = admin(make_client, migrated, in_cluster)
    assert owner.get(PATH).json()["warnings"] == ["smtp_password_in_database"]
    assert any("Secret" in r.getMessage() for r in caplog.records)
    health = owner.client.get("/api/v1/health")
    assert health.status_code == 200 and "smtp" not in health.text
    plaintext = admin(make_client, migrated, env_of(MAITY_SMTP_ALLOW_PLAINTEXT="true"))
    # That hub has no instance key, so the stored password is flagged as well.
    assert plaintext.get(PATH).json()["warnings"] == [
        "smtp_plaintext_allowed",
        "smtp_password_unreadable",
    ]


# --- the test send ------------------------------------------------------------------


def test_the_test_send_delivers_one_fixed_mail(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp]
) -> None:
    server = serve(smtp_server, Script())
    owner = admin(make_client, migrated, local_env(server.port))
    sent = owner.post(f"{PATH}/test", {"to": "admin@example.org"})
    assert sent.status_code == 200, sent.text
    outcome = sent.json()
    assert (outcome["ok"], outcome["stage"], outcome["smtp_code"]) == (True, None, 250)
    assert server.record.commands == ["EHLO", "MAIL", "RCPT", "DATA", "QUIT"]
    mail = message_from_bytes(server.record.data, policy=default)
    assert mail["Subject"] == "Maity test mail from https://hub.example"
    assert mail["From"] == "Maity <maity@example.org>"
    assert mail["To"] == "admin@example.org"
    assert mail["Auto-Submitted"] == "auto-generated"
    assert mail.get_content().strip() == "Maity test mail from https://hub.example"
    last = owner.get(PATH).json()["last_test"]
    assert last == {"at": outcome["at"], "ok": True, "stage": None, "smtp_code": 250}
    # A connection field that changes clears it; an unchanged one does not.
    owner.patch(PATH, {"max_per_hour": 7})
    assert owner.get(PATH).json()["last_test"] == last
    owner.patch(PATH, {"username": "maity"})
    assert owner.get(PATH).json()["last_test"] is None


def test_the_test_send_refuses_before_it_connects(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of())
    for body, fields in [
        ({}, {"to": "no_verified_address"}),
        (None, {"to": "no_verified_address"}),
        ({"to": "a@b.co, c@d.co"}, {"to": "invalid"}),
        ({"to": "a@example.org", "host": "evil.example"}, {"host": "extra_forbidden"}),
    ]:
        response = owner.post(f"{PATH}/test", body)
        assert response.json()["error"]["details"]["fields"] == fields, body
    unconfigured = owner.post(f"{PATH}/test", {"to": "a@example.org"})
    assert unconfigured.status_code == 409
    assert unconfigured.json()["error"]["code"] == "mail_not_configured"


def test_five_test_sends_per_hour(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp]
) -> None:
    owner = admin(make_client, migrated, local_env(1))  # nothing listens on port 1
    for _ in range(5):
        outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
        assert (outcome["ok"], outcome["stage"]) == (False, "connect")
    limited = owner.post(f"{PATH}/test", {"to": "a@example.org"})
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_the_test_send_works_while_mail_is_disabled(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp]
) -> None:
    server = serve(smtp_server, Script())
    owner = admin(make_client, migrated, local_env(server.port))
    owner.patch(PATH, {"enabled": False})
    assert owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()["ok"] is True


@pytest.mark.parametrize(
    ("script", "stage", "code"),
    [
        (Script(rcpt_reply="550 5.1.1 no such user"), "rcpt_to", 550),
        (Script(data_reply="554 5.6.0 rejected"), "data", 554),
        (Script(greeting="554 go away"), "connect", 554),
        (Script(silent_after_greeting=True), "connect", None),
    ],
)
def test_a_failed_test_send_names_the_stage(
    make_client: ClientFactory,
    migrated: Engine,
    smtp_server: list[FakeSmtp],
    script: Script,
    stage: str,
    code: int | None,
) -> None:
    server = serve(smtp_server, script)
    owner = admin(make_client, migrated, local_env(server.port))
    response = owner.post(f"{PATH}/test", {"to": "a@example.org"})
    assert response.status_code == 200
    outcome = response.json()
    assert (outcome["ok"], outcome["stage"], outcome["smtp_code"]) == (False, stage, code)
    assert owner.get(PATH).json()["last_test"]["ok"] is False


def test_starttls_is_required_and_never_falls_back(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp]
) -> None:
    server = serve(smtp_server, Script(starttls=False))
    owner = admin(make_client, migrated, local_env(server.port, MAITY_SMTP_TLS="starttls"))
    outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert (outcome["ok"], outcome["stage"]) == (False, "tls")
    assert "MAIL" not in server.record.commands


def test_plaintext_only_with_the_insecure_flag_and_never_auth(
    make_client: ClientFactory,
    migrated: Engine,
    smtp_server: list[FakeSmtp],
    caplog: pytest.LogCaptureFixture,
) -> None:
    server = serve(smtp_server, Script(starttls=False))
    flagged = local_env(server.port, MAITY_SMTP_TLS="starttls", MAITY_SMTP_ALLOW_PLAINTEXT="1")
    owner = admin(make_client, migrated, flagged)
    with caplog.at_level("WARNING"):
        outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert outcome["ok"] is True
    assert any("in clear" in r.getMessage() for r in caplog.records)

    server = serve(smtp_server, Script(starttls=False))
    with_user = local_env(
        server.port,
        MAITY_SMTP_TLS="starttls",
        MAITY_SMTP_ALLOW_PLAINTEXT="1",
        MAITY_SMTP_USERNAME="maity",
        MAITY_SMTP_PASSWORD=PASSWORD,
    )
    owner = admin(make_client, migrated, with_user)
    outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert (outcome["ok"], outcome["stage"]) == (False, "auth")
    assert "AUTH" not in server.record.commands


def test_starttls_with_a_verified_certificate_and_auth(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp], tmp_path: Path
) -> None:
    ca_file, context = certificate(tmp_path)
    server = serve(smtp_server, Script(starttls=True, tls=context))
    mail = local_env(
        server.port,
        MAITY_SMTP_TLS="starttls",
        MAITY_SMTP_CA_FILE=str(ca_file),
        MAITY_SMTP_USERNAME="maity",
        MAITY_SMTP_PASSWORD=PASSWORD,
    )
    owner = admin(make_client, migrated, mail)
    outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert outcome["ok"] is True, outcome
    assert server.record.tls_used
    assert server.record.commands[:4] == ["EHLO", "STARTTLS", "EHLO", "AUTH"]

    # Without the CA file the self-signed certificate is not trusted: stage tls.
    server = serve(smtp_server, Script(starttls=True, tls=context))
    untrusted = local_env(server.port, MAITY_SMTP_TLS="starttls")
    owner = admin(make_client, migrated, untrusted)
    outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert (outcome["ok"], outcome["stage"]) == (False, "tls")
    assert "MAIL" not in server.record.commands


def test_implicit_tls(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp], tmp_path: Path
) -> None:
    ca_file, context = certificate(tmp_path)
    server = serve(smtp_server, Script(implicit=True, tls=context))
    mail = local_env(server.port, MAITY_SMTP_TLS="implicit", MAITY_SMTP_CA_FILE=str(ca_file))
    owner = admin(make_client, migrated, mail)
    assert owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()["ok"] is True
    assert server.record.tls_used


def test_the_detail_never_carries_the_username_or_the_password(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp], tmp_path: Path
) -> None:
    user = "maity-user"
    forms = [
        user,
        PASSWORD,
        base64.b64encode(user.encode()).decode(),
        base64.b64encode(PASSWORD.encode()).decode(),
        base64.b64encode(f"\0{user}\0{PASSWORD}".encode()).decode(),
    ]
    echo = " ".join(forms)
    ca_file, context = certificate(tmp_path)
    server = serve(
        smtp_server,
        Script(starttls=True, tls=context, auth_reply=f"535 5.7.8 bad credentials {echo}"),
    )
    mail = local_env(
        server.port,
        MAITY_SMTP_TLS="starttls",
        MAITY_SMTP_CA_FILE=str(ca_file),
        MAITY_SMTP_USERNAME=user,
        MAITY_SMTP_PASSWORD=PASSWORD,
    )
    owner = admin(make_client, migrated, mail)
    response = owner.post(f"{PATH}/test", {"to": "a@example.org"})
    outcome = response.json()
    assert (outcome["ok"], outcome["stage"], outcome["smtp_code"]) == (False, "auth", 535)
    assert outcome["detail"].startswith("5.7.8 bad credentials")
    for secret_form in forms:
        assert secret_form not in response.text
    assert len(outcome["detail"]) <= 200


def test_a_non_ascii_password_or_username_is_refused(
    make_client: ClientFactory, migrated: Engine
) -> None:
    keyed = admin(make_client, migrated, env_of(MAITY_SECRET_KEY=KEY))
    refused = keyed.patch(PATH, {"password": "pässword long enough"})
    assert refused.json()["error"]["details"]["fields"] == {"password": "invalid"}
    assert "pässword" not in refused.text


def test_an_encoding_error_at_auth_is_a_stage_and_leaks_nothing(
    smtp_server: list[FakeSmtp],
    migrated: Engine,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ca_file, context = certificate(tmp_path)
    server = serve(smtp_server, Script(starttls=True, tls=context))
    hub = local_env(
        server.port,
        MAITY_SMTP_TLS="starttls",
        MAITY_SMTP_CA_FILE=str(ca_file),
        MAITY_SMTP_USERNAME="maity",
        MAITY_SMTP_PASSWORD="ascii-for-now",
    )
    with migrated.begin() as conn:
        resolved = settings.resolve(conn, hub.mail, hub.secret_key)
    # Whatever let it through, a password SMTP cannot encode stops at `auth`, quietly.
    resolved = replace(resolved, password="pässword-Ä")
    mail = headers.message(
        sender="maity@example.org", sender_name=None, to="a@example.org", subject="s", body="b"
    )
    with caplog.at_level("DEBUG"):
        outcome = smtp.send(resolved, mail)
    assert (outcome.ok, outcome.stage, outcome.detail) == (False, "auth", None)
    assert all("Ä" not in r.getMessage() and "ä" not in r.getMessage() for r in caplog.records)


def test_tls_none_with_a_remote_host_from_two_sources_stops_and_never_sends(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = admin(make_client, migrated, env_of())
    assert owner.patch(PATH, {"tls": "none", "host": "127.0.0.1"}).status_code == 200
    remote = env_of(
        MAITY_SMTP_HOST="10.0.0.200",
        MAITY_SMTP_FROM="maity@example.org",
        MAITY_MAIL_SIGNING_KEY=SIGNING,
    )
    with pytest.raises(ConfigError, match="loopback"):
        make_client(mail=remote.mail)
    with migrated.begin() as conn:
        resolved = settings.resolve(conn, remote.mail, None)
    mail = headers.message(
        sender="maity@example.org", sender_name=None, to="a@example.org", subject="s", body="b"
    )
    outcome = smtp.send(resolved, mail)
    assert (outcome.ok, outcome.stage) == (False, "tls")


def test_a_certificate_for_another_name_is_refused(
    make_client: ClientFactory, migrated: Engine, smtp_server: list[FakeSmtp], tmp_path: Path
) -> None:
    ca_file, context = certificate(tmp_path)  # names 127.0.0.1 only
    server = serve(smtp_server, Script(starttls=True, tls=context))
    hub = local_env(server.port, MAITY_SMTP_TLS="starttls", MAITY_SMTP_CA_FILE=str(ca_file))
    hub = replace(hub, mail=replace(hub.mail, host="localhost"))
    owner = admin(make_client, migrated, hub)
    outcome = owner.post(f"{PATH}/test", {"to": "a@example.org"}).json()
    assert (outcome["ok"], outcome["stage"]) == (False, "tls")
    assert "MAIL" not in server.record.commands


def test_a_stored_name_without_a_registry_entry_is_ignored(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    owner = admin(make_client, migrated, env_of())
    with migrated.begin() as conn:
        conn.execute(
            insert(t.instance_setting).values(
                name="mail.retired", value="x", updated_at=clock.now(), updated_by=None
            )
        )
    with caplog.at_level("WARNING"):
        got = owner.get(PATH)
    assert got.status_code == 200 and "retired" not in got.text
    assert any("mail.retired" in r.getMessage() for r in caplog.records)


# --- addresses and header values ----------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a@b.co", "first.last@example.org", '"a@b"@example.org', "x+tag@sub.example.org"],
)
def test_one_address(value: str) -> None:
    assert address.valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a@b",
        "a@[192.0.2.1]",
        "A <a@b.co>",
        "<a@b.co>",
        "a,b@c.de",
        "a;b@c.de",
        "a b@c.de",
        "a@b.co\n",
        "ä@b.co",
        "a@@b.co",
        "a@b@c.co",
        ".a@b.co",
        "a..b@c.de",
        '"a b"@c.de',
        '"a,b"@c.de',
        "a@-b.co",
        "x" * 65 + "@b.co",
        "a@" + ("b" * 63 + ".") * 4 + "co",
        None,
        42,
    ],
)
def test_not_one_address(value: object) -> None:
    assert not address.valid(value)


def test_header_values_lose_control_characters_and_are_encoded() -> None:
    mail = headers.message(
        sender="maity@example.org",
        sender_name="Mäity\r\nBcc: x@example.org",
        to="a@example.org",
        subject="Hällo \nBcc: y@example.org",
        body="text",
    )
    raw = mail.as_bytes()
    assert b"\nBcc:" not in raw
    assert b"=?utf-8?" in raw
    parsed = message_from_bytes(raw, policy=default)
    assert parsed["Subject"] == "HälloBcc: y@example.org"
    assert parsed["Bcc"] is None
