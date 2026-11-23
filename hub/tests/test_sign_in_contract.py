"""docs/api.md §2.6.5 for three sign-in endpoints (tsk-pm4khj9esvah):
- `GET /auth/methods` follows §2.5 like the rest of §2.6 (docs/api.md:2594-2596);
- `POST /auth/password` voids every open device code of the human, the calling session's own
  included (docs/api.md:2601-2603, 4049-4050);
- with email links off, `GET` and `POST /mail/sign-in/{token}` answer `method_disabled` before
  they read the token, the same for every token (docs/api.md:2597-2600)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select

from maity_hub import tables as t
from maity_hub.auth import sign_in_settings
from maity_hub.routes import email_sign_in
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_email_sign_in import ask, mail, setup

# --- GET /auth/methods over plain HTTP -------------------------------------------------------


def test_the_methods_over_plain_http_off_loopback_are_insecure_transport(
    make_client: ClientFactory, migrated: Engine
) -> None:
    refused = make_client(base_url="http://hub.example").get("/api/v1/auth/methods")
    assert refused.status_code == 403
    assert refused.headers["Maity-Error"] == "insecure_transport"


def test_the_methods_over_tls_on_loopback_or_with_the_flag_answer(
    make_client: ClientFactory, migrated: Engine
) -> None:
    for client in (
        make_client(),
        make_client(base_url="http://localhost:8080", peer="127.0.0.1"),
        make_client(base_url="http://hub.example", allow_plain_http=True),
    ):
        answer = client.get("/api/v1/auth/methods")
        assert answer.status_code == 200, answer.text
        assert answer.json()["password"] is True


# --- POST /auth/password voids the human's open device codes ---------------------------------


def _code_status(engine: Engine, human_id: str) -> str:
    with engine.connect() as conn:
        status: str = conn.execute(
            select(t.device_code.c.status).where(t.device_code.c.human_id == human_id)
        ).scalar_one()
    return status


def test_a_password_change_voids_the_calling_sessions_own_device_code(
    make_client: ClientFactory, migrated: Engine
) -> None:
    desk = flow.human(make_client, migrated)
    assert desk.post("/auth/device-codes").status_code == 201
    assert _code_status(migrated, desk.id) == "waiting"
    changed = desk.post(
        "/auth/password", {"current": factory.PASSWORD, "new": "another long password"}
    )
    assert changed.status_code == 200, changed.text
    assert _code_status(migrated, desk.id) == "denied"


def test_a_password_change_leaves_another_humans_device_code_open(
    make_client: ClientFactory, migrated: Engine
) -> None:
    desk = flow.human(make_client, migrated)
    other = flow.human(make_client, migrated, "other")
    assert other.post("/auth/device-codes").status_code == 201
    changed = desk.post(
        "/auth/password", {"current": factory.PASSWORD, "new": "another long password"}
    )
    assert changed.status_code == 200, changed.text
    assert _code_status(migrated, other.id) == "waiting"


# --- /mail/sign-in/{token} while email links are off -----------------------------------------


def _off(client: Any, engine: Engine, human: str) -> None:
    with engine.begin() as conn:
        sign_in_settings.patch(conn, client.app.state.settings, {"email_link": False}, human)


def _refusal(answer: Any) -> tuple[int, str, bytes]:
    return answer.status_code, answer.headers.get("Maity-Error", ""), answer.content


def test_a_disabled_link_page_answers_the_same_for_a_real_and_a_forged_token(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    ask(client)
    url, _ = mail(migrated)
    _off(client, migrated, human)
    real = client.get(url)
    forged = client.get("/mail/sign-in/not-a-token")
    assert real.status_code == 403
    assert real.headers["Maity-Error"] == "forbidden"
    assert _refusal(real) == _refusal(forged)


def test_a_disabled_link_form_answers_the_same_for_a_real_and_a_forged_token(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, human = setup(make_client, migrated)
    ask(client)
    url, _ = mail(migrated)
    page = client.get(url)  # the form cookie, while links are on
    assert page.status_code == 200, page.text
    form = client.cookies.get(email_sign_in.FORM_COOKIE)
    assert form
    _off(client, migrated, human)
    headers = {
        "sec-fetch-site": "same-origin",
        "content-type": "application/x-www-form-urlencoded",
    }
    real = client.post(url, content=f"form={form}", headers=headers)
    forged = client.post("/mail/sign-in/not-a-token", content=f"form={form}", headers=headers)
    assert real.status_code == 403
    assert real.headers["Maity-Error"] == "forbidden"
    assert _refusal(real) == _refusal(forged)


def test_with_links_on_a_forged_token_is_still_a_dead_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = setup(make_client, migrated)
    assert client.get("/mail/sign-in/not-a-token").status_code == 404
