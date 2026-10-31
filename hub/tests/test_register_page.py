"""The registration's link page (docs/api.md §2.7.1 steps 5 and 6, §2.7.2)."""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.notifications import tokens
from tests import factory
from tests.conftest import ClientFactory
from tests.test_registration import MAIL, PASSWORD, SIGNING
from tests.test_registration import _fresh as _limits  # noqa: F401  (autouse: fresh limiters)

KEY = base64.b64decode(SIGNING)
TERMS = {"MAITY_TERMS_URL": "https://example.com/terms", "MAITY_TERMS_VERSION": "2026-10"}
SAME = {"sec-fetch-site": "same-origin"}


def hub(**env: str) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_MAIL_SIGNING_KEY": SIGNING,
            "MAITY_REGISTRATION": "open",
            "MAITY_REGISTRATION_APPROVAL": "automatic",
            **MAIL,
            **env,
        }
    )


def start(
    make_client: ClientFactory, migrated: Engine, settings: Settings, address: str = "ada@x.org"
) -> tuple[TestClient, str]:
    """A client of the instance and the link of a registration the way §2.7.1 makes one."""
    factory.human(migrated, "maintainer")  # the first human: the instance admin
    client = make_client(mail=settings.mail, registration=settings.registration)
    asked = client.post("/api/v1/auth/register", json={"address": address, "password": PASSWORD})
    assert asked.status_code == 202, asked.text
    with migrated.connect() as conn:
        mail = conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id.desc())).first()
    assert mail is not None
    found = re.search(r"https://hub\.example(/mail/register/\S+)", mail.body)
    assert found, mail.body
    return client, found.group(1)


def form_of(page: Any) -> dict[str, str]:
    """The hidden fields of the page, as a browser would send them back."""
    return dict(re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)"', page.text))


def answer(client: TestClient, link: str, page: Any, **given: str) -> Any:
    body = {
        "password": PASSWORD,
        "handle": "ada",
        "display_name": "Ada",
        **form_of(page),
        **given,
    }
    return client.post(link, data=body, headers=SAME, follow_redirects=False)


def humans(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.human).where(t.human.c.handle != "maintainer")))


def pending(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.pending_registration)).one()


def test_the_page_shows_the_form_and_changes_nothing(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    before = pending(migrated)
    page = client.get(link)
    assert page.status_code == 200
    assert "ada@x.org" in page.text
    for name in ("password", "handle", "display_name"):
        assert f'name="{name}"' in page.text
    assert "terms_accepted" not in page.text  # the instance has no terms
    assert page.headers["referrer-policy"] == "no-referrer"
    cookie = page.headers["set-cookie"]
    assert cookie.startswith("maity_form=") and "Path=/mail/register" in cookie
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")
    assert "maity_session" not in str(page.headers.get_list("set-cookie"))
    assert humans(migrated) == [] and pending(migrated) == before


def test_the_post_makes_the_account_and_signs_this_browser_in(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    done = answer(client, link, page)
    assert done.status_code == 303 and done.headers["location"] == "/"
    [created] = humans(migrated)
    assert (created.handle, created.display_name, created.account_status) == (
        "ada",
        "Ada",
        "active",
    )
    cookies = done.headers.get_list("set-cookie")
    assert any(c.startswith("maity_session=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("maity_csrf=") for c in cookies)
    me = client.get("/api/v1/me")
    assert me.status_code == 200 and me.json()["member"]["handle"] == "ada"
    with migrated.connect() as conn:
        session = conn.execute(select(t.human_session.c.method)).all()
    assert ("register",) in [tuple(r) for r in session]
    # The link works once.
    assert client.get(link).status_code == 404


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"headers": {}}, id="no-sec-fetch-site"),
        pytest.param({"headers": {"sec-fetch-site": "cross-site"}}, id="cross-site"),
        pytest.param({"headers": {"sec-fetch-site": "same-site"}}, id="same-site"),
        pytest.param({"headers": SAME, "form": "someone-elses"}, id="another-form-value"),
        pytest.param({"headers": SAME, "form": None}, id="no-form-field"),
        pytest.param({"headers": SAME, "cookie": False}, id="no-form-cookie"),
    ],
)
def test_the_post_needs_its_own_form(
    make_client: ClientFactory, migrated: Engine, tamper: dict[str, Any]
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    body = {"password": PASSWORD, "handle": "ada", "display_name": "Ada", **form_of(page)}
    if "form" in tamper:
        if tamper["form"] is None:
            body.pop("form")
        else:
            body["form"] = tamper["form"]
    if tamper.get("cookie") is False:
        client.cookies.clear()
    refused = client.post(link, data=body, headers=tamper["headers"], follow_redirects=False)
    assert refused.status_code == 403
    assert humans(migrated) == [] and pending(migrated).voided_at is None


def test_a_link_that_does_not_work_is_one_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    token = link.rsplit("/", 1)[1]
    row = pending(migrated)
    forged = tokens.make(b"o" * 32, tokens.read(KEY, token) or {})
    other_nonce = tokens.make(KEY, {**(tokens.read(KEY, token) or {}), "n": "another-nonce"})
    other_kind = tokens.make(KEY, {**(tokens.read(KEY, token) or {}), "p": "verify"})
    pages = [
        client.get(f"/mail/register/{bad}") for bad in ("garbage", forged, other_nonce, other_kind)
    ]
    assert {p.status_code for p in pages} == {404} and len({p.text for p in pages}) == 1
    with migrated.begin() as conn:  # expired
        conn.execute(t.pending_registration.update().values(expires_at=row.created_at))
    assert client.get(link).status_code == 404


def test_a_voided_registration_is_a_dead_link(make_client: ClientFactory, migrated: Engine) -> None:
    client, link = start(make_client, migrated, hub())
    with migrated.begin() as conn:
        conn.execute(t.pending_registration.update().values(voided_at=clock.now()))
    assert client.get(link).status_code == 404


def test_a_wrong_password_is_the_pages_error_and_the_fifth_voids(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    for _ in range(4):
        wrong = answer(client, link, page, password="not the one chosen at all")
        assert wrong.status_code == 400 and "not the password chosen" in wrong.text
    assert pending(migrated).wrong_passwords == 4 and humans(migrated) == []
    answer(client, link, page, password="not the one chosen at all")
    assert pending(migrated).voided_at is not None
    assert client.get(link).status_code == 404
    assert humans(migrated) == []


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({"handle": "Ada Lovelace"}, "2 to 31"),
        ({"handle": "x"}, "2 to 31"),
        ({"handle": "maintainer"}, "taken"),
        ({"display_name": ""}, "1 to 64"),
        ({"display_name": "a" * 65}, "1 to 64"),
    ],
)
def test_the_names_are_the_pages_errors_and_the_registration_stays(
    make_client: ClientFactory, migrated: Engine, given: dict[str, str], message: str
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    refused = answer(client, link, page, **given)
    assert refused.status_code == 400 and message in refused.text
    assert humans(migrated) == [] and pending(migrated).voided_at is None
    assert answer(client, link, page).status_code == 303  # the corrected form goes through


def test_the_page_escapes_what_it_shows(make_client: ClientFactory, migrated: Engine) -> None:
    client, link = start(make_client, migrated, hub(), address="a&b@x.org")
    page = client.get(link)
    assert "a&b@x.org" not in page.text and "a&amp;b@x.org" in page.text
    refused = answer(client, link, page, display_name='"><script>alert(1)</script>' + "x" * 60)
    assert "<script>" not in refused.text


def test_the_terms_are_shown_signed_and_must_be_accepted(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub(**TERMS))
    page = client.get(link)
    assert "https://example.com/terms" in page.text and "2026-10" in page.text
    assert 'name="terms_accepted"' in page.text and "checked" not in page.text
    fields = form_of(page)
    signed = tokens.read(KEY, fields["terms_seen"])
    assert signed is not None and signed["v"] == "2026-10" and signed["p"] == "terms"
    unaccepted = answer(client, link, page)
    assert unaccepted.status_code == 400 and "Accept the terms" in unaccepted.text
    assert humans(migrated) == []
    done = answer(client, link, page, terms_accepted="1")
    assert done.status_code == 303
    [created] = humans(migrated)
    assert created.terms_version == "2026-10" and created.terms_accepted_at is not None


def test_a_forged_or_foreign_terms_field_is_no_acceptance(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub(**TERMS))
    page = client.get(link)
    other = tokens.make(b"o" * 32, {"p": "terms", "n": "x", "v": "2026-10"})
    foreign = tokens.make(KEY, {"p": "terms", "n": "not-this-registration", "v": "2026-10"})
    for bad in ("", "garbage", other, foreign):
        refused = answer(client, link, page, terms_accepted="1", terms_seen=bad)
        assert refused.status_code == 409, bad  # asks for a fresh confirmation
        assert humans(migrated) == []


def test_terms_that_changed_while_the_page_was_open_ask_again_unchecked(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub(**TERMS)
    client, link = start(make_client, migrated, settings)
    page = client.get(link)
    newer = make_client(
        mail=settings.mail,
        registration=hub(
            MAITY_TERMS_URL="https://example.com/terms", MAITY_TERMS_VERSION="2026-11"
        ).registration,
    )
    newer.cookies.update(client.cookies)
    changed = answer(newer, link, page, terms_accepted="1")
    assert changed.status_code == 409 and "2026-11" in changed.text
    assert "checked" not in changed.text and humans(migrated) == []
    again = form_of(changed)
    assert tokens.read(KEY, again["terms_seen"])["v"] == "2026-11"  # type: ignore[index]
    done = answer(newer, link, changed, terms_accepted="1")
    assert done.status_code == 303
    [created] = humans(migrated)
    assert created.terms_version == "2026-11"


def test_registration_closed_meanwhile_says_so_and_voids_the_registration(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub()
    client, link = start(make_client, migrated, settings)
    page = client.get(link)
    closed = make_client(
        mail=settings.mail, registration=hub(MAITY_REGISTRATION="closed").registration
    )
    closed.cookies.update(client.cookies)
    refused = answer(closed, link, page)
    assert refused.status_code == 403 and "closed" in refused.text
    assert humans(migrated) == [] and pending(migrated).voided_at is not None


def test_an_agent_credential_is_refused(make_client: ClientFactory, migrated: Engine) -> None:
    client, link = start(make_client, migrated, hub())
    for call in (client.get, client.post):
        refused = call(link, headers={"authorization": "Bearer mt_agent_token", **SAME})
        assert refused.status_code == 403
        assert refused.json()["error"]["details"] == {"reason": "humans_only"}


def test_the_log_masks_the_token(
    make_client: ClientFactory, migrated: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    client, link = start(make_client, migrated, hub())
    token = link.rsplit("/", 1)[1]
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        client.get(link)
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines and all(token not in line for line in lines)
    assert any("/mail/register/…" in line for line in lines)


def test_a_pending_account_is_signed_in_to_the_pending_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub(MAITY_REGISTRATION_APPROVAL="operator"))
    page = client.get(link)
    done = answer(client, link, page)
    assert done.status_code == 303 and done.headers["location"] == "/account/pending"
    [created] = humans(migrated)
    assert created.account_status == "pending"


def test_the_login_limit_covers_the_page(make_client: ClientFactory, migrated: Engine) -> None:
    from maity_hub.routes.auth import LOGIN_BY_ADDRESS

    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    for _ in range(10):
        LOGIN_BY_ADDRESS.hit("203.0.113.7")
    limited = answer(client, link, page)
    assert limited.status_code == 429 and humans(migrated) == []
    LOGIN_BY_ADDRESS._hits.clear()


def test_the_page_follows_the_languages_of_the_request(
    make_client: ClientFactory, migrated: Engine
) -> None:
    factory.human(migrated, "maintainer")
    settings = hub()
    client = make_client(mail=settings.mail, registration=settings.registration)
    client.post(
        "/api/v1/auth/register",
        json={"address": "ada@x.org", "password": PASSWORD},
        headers={"accept-language": "de-AT,de;q=0.9"},
    )
    with migrated.connect() as conn:
        mail = conn.execute(select(t.mail_outbox)).one()
    link = re.search(r"https://hub\.example(/mail/register/\S+)", mail.body)
    assert link
    page = client.get(link.group(1))
    assert "Konto" in page.text


def test_a_form_value_that_is_not_ascii_is_refused_not_a_server_error(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    body = {"password": PASSWORD, "handle": "ada", "display_name": "Ada", **form_of(page)}
    body["form"] = "ünïcode-wert"
    refused = client.post(link, data=body, headers=SAME, follow_redirects=False)
    assert refused.status_code == 403 and humans(migrated) == []
    client.cookies.clear()
    body["form"] = form_of(page)["form"]
    raw: dict[str, Any] = {
        **SAME,
        "cookie": "maity_form=ünïcode".encode(),
    }  # a browser may send any byte
    again = client.post(link, data=body, headers=raw, follow_redirects=False)
    assert again.status_code == 403 and humans(migrated) == []


def test_the_completion_is_a_sign_in_like_the_login(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.auth import sessions

    client, link = start(make_client, migrated, hub())
    # This browser holds a session of someone else: it ends with the sign-in (§2.6.5).
    other = factory.human(migrated, "grace")
    old_id, _, _ = _session_of(migrated, other, "old-cookie-value")
    client.cookies.set("maity_session", "old-cookie-value")
    page = client.get(link)
    done = answer(client, link, page)
    assert done.status_code == 303
    cookies = done.headers.get_list("set-cookie")
    assert any(c.startswith("maity_device=") for c in cookies)
    assert any(
        c.startswith("maity_form=") and "SameSite=strict" in c.replace("Strict", "strict")
        for c in cookies
    )
    [created] = [h for h in humans(migrated) if h.handle == "ada"]
    with migrated.connect() as conn:
        mine = conn.execute(
            select(t.human_session).where(t.human_session.c.human_id == created.id)
        ).one()
        old = conn.execute(
            select(t.human_session).where(t.human_session.c.public_id == old_id)
        ).one()
        record = conn.execute(
            select(t.account_record).where(t.account_record.c.human_id == created.id)
        ).all()
    assert old.ended_at is not None and old.ended_by == "logout"
    assert mine.method == "register" and mine.password_at is not None
    assert mine.sign_in_complete and sessions.good_standing(mine)
    assert [r.type for r in record] == ["session_created"]
    assert created.last_login_at is not None


def _session_of(engine: Engine, human_id: str, cookie: str) -> tuple[str, str, str]:
    from maity_hub.auth import sessions
    from maity_hub.auth.caller import session_id_hash

    with engine.begin() as conn:
        session_id, csrf, public_id = sessions.create(
            conn, human_id, method="password", address="198.51.100.1", user_agent=None
        )
        conn.execute(
            t.human_session.update()
            .where(t.human_session.c.public_id == public_id)
            .values(id_hash=session_id_hash(cookie))
        )
    return public_id, session_id, csrf


def test_terms_set_while_the_page_was_open_ask_first(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub()
    client, link = start(make_client, migrated, settings)
    page = client.get(link)  # it showed no terms
    with_terms = make_client(mail=settings.mail, registration=hub(**TERMS).registration)
    with_terms.cookies.update(client.cookies)
    asked = answer(with_terms, link, page, handle="x")  # a bad handle as well
    assert asked.status_code == 409 and "2026-10" in asked.text
    assert humans(migrated) == []


def test_the_page_links_the_legal_pages_the_instance_serves(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub())
    page = client.get(link)
    assert 'href="/privacy"' not in page.text and 'href="/terms"' not in page.text  # none set
    with migrated.begin() as conn:
        conn.execute(
            t.legal_page.insert(),
            [
                {"page": "privacy", "current": "v1"},
                {"page": "terms", "current": "v2"},
                {"page": "imprint", "current": None},
            ],
        )
    page = client.get(link)
    # The privacy notice and the terms, as the dashboard's registration form links them
    # (§16.7.1); a page that is not set is no link.
    assert '<a href="/privacy">Privacy notice</a> · <a href="/terms">Terms of use</a>' in page.text
    assert 'href="/impressum"' not in page.text
