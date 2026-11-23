"""docs/api.md §11.4: the instance's GitHub App, and a human's links to its installations.

The forge is faked at the App's reads (`user_of_code`, `installation`, `repositories`);
the App's own token, the settings and the installation tokens have tests against a fake
opener below.
"""

from __future__ import annotations

import base64
import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import Engine, select, update

from maity_hub import clock, forge, forge_links, github_app, read_limits, secretbox
from maity_hub import tables as t
from maity_hub.auth.caller import SESSION_COOKIE, session_id_hash
from maity_hub.config import ConfigError, Settings
from maity_hub.seen import SEEN_EVERY
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_two_factor import Clock, code_now, enrol
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
SECRET = "client-secret-never-printed"
APP = github_app.GitHubApp("123", "maity-test", PEM.strip(), "Iv1.client", SECRET)
ENV = {
    "MAITY_FORGE_GITHUB_APP_ID": "123",
    "MAITY_FORGE_GITHUB_APP_SLUG": "maity-test",
    "MAITY_FORGE_GITHUB_APP_PRIVATE_KEY": PEM,
    "MAITY_FORGE_GITHUB_APP_CLIENT_ID": "Iv1.client",
    "MAITY_FORGE_GITHUB_APP_CLIENT_SECRET": SECRET,
}
USER = {"id": 42, "login": "maintainer-gh"}


# --- the settings --------------------------------------------------------------------------


def test_the_app_needs_all_five_settings_or_none() -> None:
    assert github_app.parse({}) is None
    assert github_app.parse(ENV) == APP
    partial = {k: v for k, v in ENV.items() if k != "MAITY_FORGE_GITHUB_APP_CLIENT_SECRET"}
    with pytest.raises(github_app.AppConfigError, match="CLIENT_SECRET") as raised:
        github_app.parse(partial)
    assert SECRET not in str(raised.value) and "PRIVATE KEY" not in str(raised.value)


def test_a_partial_set_stops_the_hub(settings: Settings) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_FORGE_GITHUB_APP_ID": "123"})


def test_a_key_that_is_no_rsa_key_stops_the_hub() -> None:
    with pytest.raises(github_app.AppConfigError, match="PRIVATE_KEY"):
        github_app.parse({**ENV, "MAITY_FORGE_GITHUB_APP_PRIVATE_KEY": "not a key"})


def test_neither_key_nor_secret_is_in_a_repr() -> None:
    shown = repr(APP) + repr(replace(Settings.from_env({}), github_app=APP))
    assert SECRET not in shown and "PRIVATE KEY" not in shown


def test_a_key_with_escaped_newlines_is_read() -> None:
    escaped = {**ENV, "MAITY_FORGE_GITHUB_APP_PRIVATE_KEY": PEM.replace("\n", "\\n")}
    assert github_app.parse(escaped) == APP


# --- the App's token -------------------------------------------------------------------------


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_the_app_token_is_rs256_signed_with_its_key() -> None:
    token = APP.jwt(now=1_800_000_000)
    header, payload, signature = token.split(".")
    assert json.loads(_unb64(header)) == {"alg": "RS256", "typ": "JWT"}
    assert json.loads(_unb64(payload)) == {
        "iat": 1_800_000_000 - 60,
        "exp": 1_800_000_000 + github_app.JWT_SECONDS,
        "iss": "123",
    }
    KEY.public_key().verify(
        _unb64(signature), f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256()
    )


# --- installation tokens -----------------------------------------------------------------


class FakeOpener:
    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        answer = self.answers.get(request.full_url.split("?")[0])
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, "error", {}, None)  # type: ignore[arg-type]
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return io.BytesIO(json.dumps(answer).encode())


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> FakeOpener:
    fake = FakeOpener()
    monkeypatch.setattr(forge, "_opener", fake)
    monkeypatch.setattr(github_app, "_tokens", {})
    return fake


MINT = "https://api.github.com/app/installations/7/access_tokens"


def test_an_installation_token_is_minted_once_and_kept_in_memory(opener: FakeOpener) -> None:
    opener.answers[MINT] = {"token": "ghs_one", "expires_at": "2999-01-01T00:00:00Z"}
    assert APP.token(7) == "ghs_one"
    assert APP.token(7) == "ghs_one"
    [mint] = opener.requests
    assert mint.get_method() == "POST"
    assert dict(mint.header_items())["Authorization"].startswith("Bearer ey")


def test_a_token_close_to_its_expiry_is_minted_again(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener.answers[MINT] = {"token": "ghs_one", "expires_at": "2026-10-28T12:00:00Z"}
    now = [github_app._expiry("2026-10-28T11:00:00Z") or 0.0]
    monkeypatch.setattr("maity_hub.github_app.time.time", lambda: now[0])
    APP.token(7)
    now[0] = (github_app._expiry("2026-10-28T12:00:00Z") or 0.0) - github_app.TOKEN_MARGIN
    APP.token(7)
    assert len(opener.requests) == 2


@pytest.mark.parametrize(("status", "state"), [(403, "suspended"), (None, "removed")])
def test_a_refused_mint_names_the_installation_gone(
    opener: FakeOpener, status: int | None, state: str
) -> None:
    opener.answers[MINT] = status
    with pytest.raises(github_app.InstallationGoneError) as raised:
        APP.token(7)
    assert raised.value.state == state


# --- linking --------------------------------------------------------------------------------


@pytest.fixture
def settings(settings: Settings, request: pytest.FixtureRequest) -> Settings:
    if "sealing" in request.fixturenames:
        settings = replace(settings, secret_key=SEALING_KEY)
    if "no_app" in request.fixturenames:
        return settings
    return replace(settings, github_app=APP)


@pytest.fixture
def no_app() -> None:
    """The instance has no GitHub App configured."""


class Forge:
    """The App's reads, by installation id."""

    def __init__(self) -> None:
        self.user: dict[str, Any] = dict(USER)
        self.installations: dict[int, dict[str, Any]] = {}
        self.repositories: dict[int, Any] = {}
        self.codes: list[str] = []

    def install(self, installation_id: int, account_id: int = 42, kind: str = "User") -> None:
        self.installations[installation_id] = {
            "id": installation_id,
            "account": {"id": account_id, "login": "maintainer-gh", "type": kind},
            "repository_selection": "selected",
            "suspended": False,
        }


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Forge:
    fg = Forge()

    def user_of_code(_app: Any, code: str) -> dict[str, Any]:
        fg.codes.append(code)
        return fg.user

    def repositories(_app: Any, installation_id: int, limit: int = 100) -> list[str]:
        answer = fg.repositories.get(installation_id, [])
        if isinstance(answer, BaseException):
            raise answer
        return list(answer)

    monkeypatch.setattr(github_app.GitHubApp, "user_of_code", user_of_code)
    monkeypatch.setattr(
        github_app.GitHubApp, "installation", lambda _app, i: fg.installations.get(i)
    )
    monkeypatch.setattr(github_app.GitHubApp, "repositories", repositories)
    return fg


@pytest.fixture
def human(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def start(who: flow.Human) -> str:
    started = who.post("/me/forge/github/link")
    assert started.status_code == 200, started.text
    url = urlsplit(started.json()["url"])
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "github.com",
        "/apps/maity-test/installations/new",
    )
    state: str = parse_qs(url.query)["state"][0]
    return state


def setup(who: flow.Human, installation_id: int, state: str, code: str = "c0de") -> str:
    """The redirect's target after the forge sent the browser back."""
    answer = who.client.get(
        "/api/v1/forge/github/setup",
        params={"installation_id": installation_id, "code": code, "state": state},
        follow_redirects=False,
    )
    assert answer.status_code == 303, answer.text
    location: str = answer.headers["location"]
    return location


DONE = "https://hub.example/settings/forge"


def links(who: flow.Human) -> list[dict[str, Any]]:
    body = who.get("/me/forge").json()
    found: list[dict[str, Any]] = body["links"]
    return found


def test_a_link_ends_on_the_settings_and_is_listed(human: flow.Human, fake: Forge) -> None:
    fake.install(7)
    fake.repositories[7] = ["maintainer-gh/maity", "maintainer-gh/private-thing"]
    assert setup(human, 7, start(human)) == DONE
    assert fake.codes == ["c0de"]
    body = human.get("/me/forge").json()
    assert body["app_configured"] is True
    assert body["token"]["configured"] is False
    [link] = body["links"]
    assert link["id"].startswith("fgl-")
    assert {k: link[k] for k in ("forge", "installation_id", "account", "status")} == {
        "forge": "github",
        "installation_id": 7,
        "account": {"login": "maintainer-gh", "type": "User"},
        "status": "active",
    }
    assert link["repository_selection"] == "selected"
    assert link["repositories_shown"] == ["maintainer-gh/maity", "maintainer-gh/private-thing"]


def test_a_state_is_used_once(human: flow.Human, fake: Forge) -> None:
    fake.install(7)
    state = start(human)
    assert setup(human, 7, state) == DONE
    assert setup(human, 7, state) == DONE + "?error=link_state"


def test_a_state_of_another_session_or_human_is_refused(
    human: flow.Human, fake: Forge, make_client: ClientFactory, migrated: Engine
) -> None:
    fake.install(7)
    state = start(human)
    other = flow.human(make_client, migrated, "anna")
    assert setup(other, 7, state) == DONE + "?error=link_state"
    # The same human in another browser: another session.
    again = make_client()
    signed_in = factory.login_handle(again, "maintainer")
    assert signed_in.status_code == 200
    second = flow.Human(again, "", human.id, "maintainer")
    assert setup(second, 7, state) == DONE + "?error=link_state"
    assert links(other) == [] and fake.codes == []
    # Still the starting session's to use.
    assert setup(human, 7, state) == DONE


def test_an_expired_state_is_refused(human: flow.Human, fake: Forge, migrated: Engine) -> None:
    fake.install(7)
    state = start(human)
    with migrated.begin() as conn:
        conn.execute(
            update(t.forge_link_state).values(expires_at=clock.now() - timedelta(seconds=1))
        )
    assert setup(human, 7, state) == DONE + "?error=link_state"
    assert fake.codes == []


@pytest.mark.parametrize("state", [None, "", "s" * 513])
def test_a_missing_or_malformed_state_is_link_state_in_both_forms(
    human: flow.Human, fake: Forge, state: str | None
) -> None:
    """Refused in the setup's own flow, never by the framework's 400, and before any
    forge read."""
    fake.install(7)
    params: dict[str, Any] = {"installation_id": 7, "code": "c0de"}
    if state is not None:
        params["state"] = state
    url = "/api/v1/forge/github/setup"
    back = human.client.get(url, params=params, follow_redirects=False)
    assert (back.status_code, back.headers["location"]) == (303, DONE + "?error=link_state")
    answer = human.client.get(
        url, params=params, headers={"Accept": "application/json"}, follow_redirects=False
    )
    assert answer.status_code == 403
    assert answer.json()["error"]["details"] == {"reason": "link_state"}
    assert fake.codes == [] and links(human) == []


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"code": "c0de"}, "installation_id"),
        ({"installation_id": "seven", "code": "c0de"}, "installation_id"),
        ({"installation_id": 0, "code": "c0de"}, "installation_id"),
        ({"installation_id": 7}, "code"),
        ({"installation_id": 7, "code": ""}, "code"),
        ({"installation_id": 7, "code": "c" * 513}, "code"),
    ],
)
def test_a_query_the_setup_cannot_read_is_invalid_before_the_route_runs(
    human: flow.Human, fake: Forge, params: dict[str, Any], field: str
) -> None:
    """No or a malformed `installation_id` or `code` is the framework's `400 invalid` like any
    malformed request (§1.3), no 303: the route never runs, so the state is not taken."""
    fake.install(7)
    state = start(human)
    answer = human.client.get(
        "/api/v1/forge/github/setup", params={**params, "state": state}, follow_redirects=False
    )
    assert answer.status_code == 400
    error = answer.json()["error"]
    assert error["code"] == "invalid" and field in error["details"]["fields"]
    assert fake.codes == [] and links(human) == []
    assert setup(human, 7, state) == DONE  # the state was not taken


def test_a_malformed_setup_without_a_session_is_unauthenticated(
    make_client: ClientFactory, fake: Forge
) -> None:
    """Authentication comes before the query is read: no session is `unauthenticated`, not
    `invalid` (§11.4)."""
    answer = make_client().get(
        "/api/v1/forge/github/setup", params={"code": "c0de"}, follow_redirects=False
    )
    assert answer.status_code == 401
    assert answer.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(
    ("account_id", "kind", "reason"),
    [
        (43, "User", "installation_not_yours"),
        (42, "Organization", "organisation_installation"),
        (None, None, "installation_not_yours"),
    ],
)
def test_only_an_installation_on_the_users_own_account_is_linked(
    human: flow.Human, fake: Forge, account_id: int | None, kind: str | None, reason: str
) -> None:
    if account_id is not None and kind is not None:
        fake.install(7, account_id, kind)
    assert setup(human, 7, start(human)) == DONE + f"?error={reason}"
    assert links(human) == []


def test_an_installation_is_linked_to_one_human_at_a_time(
    human: flow.Human, fake: Forge, make_client: ClientFactory, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    anna = flow.human(make_client, migrated, "anna")
    assert setup(anna, 7, start(anna)) == DONE + "?error=installation_linked"
    [link] = links(human)
    assert human.delete(f"/me/forge/github/links/{link['id']}").status_code == 204
    assert setup(anna, 7, start(anna)) == DONE
    assert links(human) == [] and len(links(anna)) == 1


def test_links_are_their_humans_own(
    human: flow.Human, fake: Forge, make_client: ClientFactory, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    [link] = links(human)
    anna = flow.human(make_client, migrated, "anna")
    assert links(anna) == []
    assert anna.delete(f"/me/forge/github/links/{link['id']}").status_code == 404
    assert len(links(human)) == 1


def test_an_agent_has_no_forge_access(
    human: flow.Human, fake: Forge, make_client: ClientFactory
) -> None:
    flow.project(human, "maity")
    agent = flow.agent(make_client, human)
    for answer in (agent.get("/me/forge"), agent.post("/me/forge/github/link", {})):
        assert answer.status_code == 403
        assert answer.json()["error"]["details"].get("reason") == "humans_only"


def test_a_refused_mint_shows_the_link_suspended(
    human: flow.Human, fake: Forge, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    fake.repositories[7] = github_app.InstallationGoneError("suspended")
    [link] = links(human)
    assert (link["status"], link["repositories_shown"]) == ("suspended", [])
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link.c.status)).scalar_one() == "suspended"


def test_a_refused_mint_on_the_list_forgets_the_token_as_every_refusal_does(
    human: flow.Human, fake: Forge, settings: Settings
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    assert settings.github_app is not None
    held = (settings.github_app.app_id, 7)
    github_app._tokens[held] = ("from before", time.time() + 3000)
    fake.repositories[7] = github_app.InstallationGoneError("suspended")
    try:
        links(human)
        assert held not in github_app._tokens
    finally:
        github_app._tokens.clear()


def test_a_successful_mint_on_the_list_turns_a_suspended_link_active_again(
    human: flow.Human, fake: Forge, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(status="suspended"))
    assert links(human)[0]["status"] == "active"
    with migrated.connect() as conn:
        assert conn.execute(select(t.forge_link.c.status)).scalar_one() == "active"


def test_a_mint_on_the_list_does_not_undo_a_removal_found_meanwhile(
    human: flow.Human, fake: Forge, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    with migrated.begin() as conn:
        conn.execute(update(t.forge_link).values(status="removed"))
        link_id = conn.execute(select(t.forge_link.c.id)).scalar_one()
        for late in ("active", "suspended"):
            forge_links.set_status(conn, link_id, late)
            assert conn.execute(select(t.forge_link.c.status)).scalar_one() == "removed"


def test_without_an_app_nothing_is_linked(human: flow.Human, no_app: None) -> None:
    refused = human.post("/me/forge/github/link")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "forge_app_missing")
    body = human.get("/me/forge").json()
    assert (body["app_configured"], body["links"]) == (False, [])


@pytest.mark.parametrize(
    ("account_id", "status", "code", "reason"),
    [
        (43, 403, "forbidden", "installation_not_yours"),
        (42, 200, None, None),
    ],
)
def test_a_client_asking_for_json_gets_the_outcome_as_json(
    human: flow.Human,
    fake: Forge,
    account_id: int,
    status: int,
    code: str | None,
    reason: str | None,
) -> None:
    fake.install(7, account_id)
    answer = human.client.get(
        "/api/v1/forge/github/setup",
        params={"installation_id": 7, "code": "c0de", "state": start(human)},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert answer.status_code == status
    if code is None:
        assert answer.json()["installation_id"] == 7
    else:
        assert answer.json()["error"]["code"] == code
        assert answer.json()["error"]["details"] == {"reason": reason}


def test_the_setup_without_an_app_goes_back_with_the_reason(
    human: flow.Human, no_app: None
) -> None:
    assert setup(human, 7, "any-state") == DONE + "?error=forge_app_missing"


def test_a_forge_that_does_not_answer_goes_back_with_the_reason(
    human: flow.Human, fake: Forge, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(_app: Any, code: str) -> dict[str, Any]:
        raise forge.ForgeUnavailableError("down")

    monkeypatch.setattr(github_app.GitHubApp, "user_of_code", down)
    location = setup(human, 7, start(human))
    assert location == DONE + "?error=forge_unavailable"
    assert "c0de" not in location


# --- the forge's redirect is a cross-site navigation (§2.1, tsk-2vtm39ykr7k4) -------------------

# What a browser sends on the forge's redirect back to the hub: a top-level navigation from
# another site.
FROM_THE_FORGE = {
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}
SETUP = "/api/v1/forge/github/setup"


def cross_site(who: flow.Human, params: dict[str, Any], **headers: str) -> Any:
    sent = {**FROM_THE_FORGE, **{k.replace("_", "-"): v for k, v in headers.items()}}
    return who.client.get(SETUP, params=params, headers=sent, follow_redirects=False)


def test_the_forges_redirect_links_the_installation(human: flow.Human, fake: Forge) -> None:
    fake.install(7)
    answer = cross_site(human, {"installation_id": 7, "code": "c0de", "state": start(human)})
    assert (answer.status_code, answer.headers["location"]) == (303, DONE)
    assert [link["installation_id"] for link in links(human)] == [7]


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("Sec-Fetch-Mode", "cors"),  # a cross-site `fetch`
        ("Sec-Fetch-Mode", "no-cors"),
        ("Sec-Fetch-Mode", "same-origin"),
        ("Sec-Fetch-Dest", "iframe"),  # a navigation inside another site's frame
        ("Sec-Fetch-Dest", "empty"),
        ("Sec-Fetch-Dest", "frame"),
    ],
)
def test_a_cross_site_setup_that_is_no_top_level_navigation_is_refused(
    human: flow.Human, fake: Forge, header: str, value: str
) -> None:
    """Refused before the route runs, as every cross-site cookie call: the state stays."""
    fake.install(7)
    state = start(human)
    params = {"installation_id": 7, "code": "c0de", "state": state}
    answer = cross_site(human, params, **{header.replace("-", "_"): value})
    assert answer.status_code == 403
    assert answer.json()["error"]["code"] == "csrf_mismatch"
    assert fake.codes == [] and links(human) == []
    assert setup(human, 7, state) == DONE  # the state was not taken


@pytest.mark.parametrize("missing", ["Sec-Fetch-Mode", "Sec-Fetch-Dest"])
def test_a_cross_site_setup_without_the_navigation_headers_is_refused(
    human: flow.Human, fake: Forge, missing: str
) -> None:
    fake.install(7)
    sent = {k: v for k, v in FROM_THE_FORGE.items() if k != missing}
    answer = human.client.get(
        SETUP,
        params={"installation_id": 7, "code": "c0de", "state": start(human)},
        headers=sent,
        follow_redirects=False,
    )
    assert answer.json()["error"]["code"] == "csrf_mismatch"
    assert fake.codes == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/me"),
        ("GET", "/api/v1/me/forge"),
        ("GET", "/api/v1/auth/session"),
        ("POST", "/api/v1/me/forge/github/link"),
        # The setup in another spelling: the router routes it there, the exception does not
        # admit it. Another method on the setup is no route (405 before any check); the
        # matcher's own cases are in test_permitted_calls.py.
        ("GET", "/api/v1/forge/github/set%75p"),
    ],
)
def test_the_forges_headers_on_any_other_call_are_csrf_mismatch(
    human: flow.Human, fake: Forge, method: str, path: str
) -> None:
    fake.install(7)
    answer = human.client.request(
        method,
        path,
        params={"installation_id": 7, "code": "c0de", "state": start(human)},
        headers={**FROM_THE_FORGE, "X-CSRF-Token": human.csrf},
        follow_redirects=False,
    )
    assert answer.status_code == 403
    assert answer.json()["error"]["code"] == "csrf_mismatch"
    assert fake.codes == [] and links(human) == []


def test_a_cross_site_setup_with_a_missing_state_goes_back_with_link_state(
    human: flow.Human, fake: Forge
) -> None:
    fake.install(7)
    answer = cross_site(human, {"installation_id": 7, "code": "c0de"})
    assert (answer.status_code, answer.headers["location"]) == (303, DONE + "?error=link_state")
    assert fake.codes == [] and links(human) == []


def test_a_cross_site_setup_with_a_used_state_goes_back_with_link_state(
    human: flow.Human, fake: Forge
) -> None:
    fake.install(7)
    params = {"installation_id": 7, "code": "c0de", "state": start(human)}
    assert cross_site(human, params).headers["location"] == DONE
    again = cross_site(human, params)
    assert (again.status_code, again.headers["location"]) == (303, DONE + "?error=link_state")
    assert fake.codes == ["c0de"]


def test_a_cross_site_setup_with_another_sessions_state_goes_back_with_link_state(
    human: flow.Human, fake: Forge, make_client: ClientFactory, migrated: Engine
) -> None:
    """The case the exception exists for: another site sends a victim's browser to the setup
    with a state of the attacker's own session. Nothing is linked to either."""
    fake.install(7)
    attacker = flow.human(make_client, migrated, "anna")
    params = {"installation_id": 7, "code": "c0de", "state": start(attacker)}
    answer = cross_site(human, params)
    assert (answer.status_code, answer.headers["location"]) == (303, DONE + "?error=link_state")
    assert fake.codes == [] and links(human) == [] and links(attacker) == []
    # The same human in another browser is another session, refused alike.
    again = make_client()
    assert factory.login_handle(again, "maintainer").status_code == 200
    second = flow.Human(again, "", human.id, "maintainer")
    own = cross_site(second, {**params, "state": start(human)})
    assert (own.status_code, own.headers["location"]) == (303, DONE + "?error=link_state")
    assert fake.codes == [] and links(human) == []


def traces(engine: Engine, who: flow.Human) -> tuple[Any, ...]:
    """What an authenticated call may change for its human (§2.4, §6.5, §1.7): the session's,
    the human's and the memberships' presence, the leases of its claims, its read count."""
    id_hash = session_id_hash(who.client.cookies[SESSION_COOKIE])
    with engine.connect() as conn:
        found = (
            conn.execute(
                select(t.human_session.c.last_seen_at).where(t.human_session.c.id_hash == id_hash)
            ).scalar_one(),
            conn.execute(select(t.human.c.last_seen_at).where(t.human.c.id == who.id)).scalar(),
            conn.execute(
                select(t.membership.c.last_seen_at).where(t.membership.c.human_id == who.id)
            ).all(),
            conn.execute(
                select(t.card.c.lease_until).where(t.card.c.lease_until.is_not(None))
            ).all(),
        )
    counted = read_limits.COUNTER._counts.get(id_hash)
    window = clock.now().timestamp() // read_limits.WINDOW_SECONDS
    return (*found, counted.current if counted and counted.window == window else 0)


@pytest.mark.parametrize("which", ["foreign", "used"])
def test_a_cross_site_setup_with_a_bad_state_changes_nothing(
    human: flow.Human, fake: Forge, make_client: ClientFactory, migrated: Engine, which: str
) -> None:
    """A navigation another site forces writes no presence, renews no lease and counts no read
    before its `state` refuses it (§2.1, §11.4); an ordinary call at the same moment does."""
    # One window of the read count (§1.7) for the whole test, so its count only grows.
    window = read_limits.WINDOW_SECONDS
    now = [datetime.fromtimestamp((time.time() // window + 1) * window + 1, UTC)]
    clock.set_source(lambda: now[0])
    fake.install(7)
    flow.project(human, "alpha")
    card = human.post("/projects/maintainer/alpha/tasks", {"title": "held"}).json()
    claimed = human.post(f"/projects/maintainer/alpha/tasks/{card['id']}/claim", {})
    assert claimed.status_code == 200, claimed.text
    if which == "foreign":
        state = start(flow.human(make_client, migrated, "anna"))
    else:
        state = start(human)
        assert setup(human, 7, state) == DONE
    # Presence due again (§2.4), and a renewal now would move the lease (§6.5).
    with migrated.begin() as conn:
        aged = now[0] - 2 * SEEN_EVERY
        conn.execute(update(t.human_session).values(last_seen_at=aged))
        conn.execute(update(t.human).values(last_seen_at=aged))
        conn.execute(update(t.membership).values(last_seen_at=aged))
    now[0] += timedelta(seconds=20)
    before = traces(migrated, human)
    answer = cross_site(human, {"installation_id": 7, "code": "c0de", "state": state})
    assert (answer.status_code, answer.headers["location"]) == (303, DONE + "?error=link_state")
    assert traces(migrated, human) == before
    # The same moment, an ordinary read: every one of them changes.
    assert human.client.get("/api/v1/me").status_code == 200
    after = traces(migrated, human)
    assert all(a != b for a, b in zip(after, before, strict=True)), (before, after)


# --- the human's own token -------------------------------------------------------------------

FINE = "github_pat_11AAAA_secret_value_never_printed"
SEALING_KEY = secretbox.parse_key(base64.b64encode(b"k" * 32).decode())


@pytest.fixture
def sealing() -> None:
    """The instance has a MAITY_SECRET_KEY."""


@pytest.fixture
def user_api(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`GET /user` with the token: answers for FINE, refuses anything else."""
    seen: list[str] = []

    def call(path: str, authorization: str, post: bool = False) -> Any:
        seen.append(path)
        if authorization != f"Bearer {FINE}":
            raise forge.ForgeUnavailableError("the forge answered 401", 401)
        return {"id": 42, "login": "maintainer-gh"}

    monkeypatch.setattr(github_app, "_call", call)
    return seen


def put_token(who: flow.Human, token: str) -> Any:
    return who.client.put(
        "/api/v1/me/forge/github/token", json={"token": token}, headers={"X-CSRF-Token": who.csrf}
    )


def test_a_fine_grained_token_is_checked_sealed_and_never_shown(
    human: flow.Human, migrated: Engine, sealing: None, user_api: list[str]
) -> None:
    stored = put_token(human, FINE)
    assert stored.status_code == 200, stored.text
    assert stored.json() == {"configured": True, "login": "maintainer-gh"}
    assert user_api == ["/user"]
    body = human.get("/me/forge").json()
    assert {k: body["token"][k] for k in ("configured", "login", "status")} == {
        "configured": True,
        "login": "maintainer-gh",
        "status": "active",
    }
    assert FINE not in json.dumps(body)
    with migrated.connect() as conn:
        sealed = conn.execute(select(t.forge_token.c.token_sealed)).scalar_one()
    assert FINE.encode() not in sealed
    assert SEALING_KEY is not None
    assert secretbox.open_sealed(SEALING_KEY, f"forge_token:{human.id}", sealed) == FINE.encode()
    assert human.delete("/me/forge/github/token").status_code == 204
    assert human.get("/me/forge").json()["token"]["configured"] is False
    assert human.delete("/me/forge/github/token").status_code == 404


@pytest.mark.parametrize(
    ("token", "reason"),
    [("ghp_classic_token_value", "classic_token"), ("github_pat_refused", "rejected")],
)
def test_a_classic_or_refused_token_is_not_taken(
    human: flow.Human, sealing: None, user_api: list[str], token: str, reason: str
) -> None:
    refused = put_token(human, token)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"] == {"fields": {"token": reason}}
    assert token not in refused.text
    assert human.get("/me/forge").json()["token"]["configured"] is False


def test_without_the_secret_key_no_token_is_stored(human: flow.Human, user_api: list[str]) -> None:
    refused = put_token(human, FINE)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "secret_key_missing")
    assert user_api == []


def test_an_agent_stores_no_token(
    human: flow.Human, make_client: ClientFactory, sealing: None, user_api: list[str]
) -> None:
    flow.project(human, "maity")
    agent = flow.agent(make_client, human)
    refused = agent.client.put(
        "/api/v1/me/forge/github/token",
        json={"token": FINE},
        headers=agent.auth,
    )
    assert refused.status_code == 403 and user_api == []


def test_a_link_and_a_token_need_a_recent_factor(
    human: flow.Human, sealing: None, user_api: list[str], moment: Clock
) -> None:
    """Both give the hub access to a forge account (§2.8.4); a stale factor is refused
    before the token reaches the forge."""
    secret, _ = enrol(human, moment)
    moment.move(minutes=11)
    for refused in (human.post("/me/forge/github/link"), put_token(human, FINE)):
        assert refused.status_code == 403
        assert refused.json()["error"]["details"]["reason"] == "step_up_required"
    assert user_api == []
    assert human.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})
    assert human.post("/me/forge/github/link").status_code == 200
    assert put_token(human, FINE).status_code == 200


# --- the account records (§18.1) -------------------------------------------------------------


def _records(engine: Engine, human_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.account_record)
            .where(
                t.account_record.c.human_id == human_id,
                t.account_record.c.type == "forge_access_changed",
            )
            .order_by(t.account_record.c.n)
        ).all()
    return [dict(row.data) for row in rows]


def _security_titles(who: flow.Human) -> list[str]:
    items = who.get("/me/notifications").json()["items"]
    return [i["title"] for i in items if i["kind"] == "security" and "Forge" in i["title"]]


def test_a_link_and_its_end_are_account_records_and_only_the_link_a_notification(
    human: flow.Human, fake: Forge, migrated: Engine
) -> None:
    fake.install(7)
    setup(human, 7, start(human))
    [link] = links(human)
    fake.repositories[7] = github_app.InstallationGoneError("suspended")
    links(human)
    human.delete(f"/me/forge/github/links/{link['id']}")
    assert [(r["source"], r["change"], r["login"]) for r in _records(migrated, human.id)] == [
        ("app", "linked", "maintainer-gh"),
        ("app", "suspended", "maintainer-gh"),
        ("app", "unlinked", "maintainer-gh"),
    ]
    assert _security_titles(human) == ["Forge access added: maintainer-gh (app)"]


def test_a_token_set_and_removed_are_account_records(
    human: flow.Human, migrated: Engine, sealing: None, user_api: list[str]
) -> None:
    put_token(human, FINE)
    human.delete("/me/forge/github/token")
    changes = [(r["source"], r["change"]) for r in _records(migrated, human.id)]
    assert changes == [("owner_token", "token_set"), ("owner_token", "token_removed")]
    assert FINE not in str(_records(migrated, human.id))
    assert _security_titles(human) == ["Forge access added: maintainer-gh (owner_token)"]


def test_the_forge_notification_reads_in_the_humans_language(
    human: flow.Human, migrated: Engine, sealing: None, user_api: list[str]
) -> None:
    assert (
        human.patch("/me/notification-settings", {"email": {"language": "de"}}).status_code == 200
    )
    put_token(human, FINE)
    assert _security_titles(human) == ["Forge-Zugang hinzugefügt: maintainer-gh (owner_token)"]
