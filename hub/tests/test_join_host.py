"""docs/api.md §1.1, §3.1–3.3: the optional join host."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from maity_hub.config import ConfigError, parse_join_url
from tests import factory, flow
from tests.conftest import ClientFactory

PUBLIC = "https://hub.example"
JOIN = "https://join.example"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Any) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def join_client(make_client: ClientFactory, **overrides: Any) -> TestClient:
    return make_client(base_url=JOIN, join_url=JOIN, **overrides)


def hosted_human(make_client: ClientFactory, migrated: Any, handle: str) -> flow.Human:
    """A human logged in on the public host of an app that has a join host."""
    human_id = factory.human(migrated, handle)
    client = make_client(join_url=JOIN)
    login = client.post("/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD})
    assert login.status_code == 200, login.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, human_id)


def create(owner: flow.Human, **body: Any) -> dict[str, Any]:
    body.setdefault("agent", {"handle": "agent-j", "display_name": "Agent J"})
    response = owner.post("/projects/maity/joins", body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def token_of(created: dict[str, Any]) -> str:
    token: str = created["join_url"].rsplit("/", 1)[1]
    return token


# --- configuration --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "http://join.example",
        "https://join.example/j",
        "https://join.example/?x=1",
        "https://user@join.example",
        "https://hub.example",
        "join.example",
    ],
)
def test_a_join_url_that_is_not_a_bare_https_host_stops_the_hub(value: str) -> None:
    with pytest.raises(ConfigError):
        parse_join_url(value, PUBLIC)


def test_a_join_url_is_normalised() -> None:
    assert parse_join_url("https://join.example/", PUBLIC) == JOIN
    assert parse_join_url("", PUBLIC) is None


# --- join links -------------------------------------------------------------------------------


def test_links_go_to_the_join_host_by_default(make_client: ClientFactory, migrated: Any) -> None:
    owner = hosted_human(make_client, migrated, "hosted")
    flow.project(owner)
    assert owner.get("/auth/session").json()["join_url"] == JOIN
    via_join = create(owner)
    assert via_join["via"] == "join"
    assert via_join["join_url"] == f"{JOIN}/{token_of(via_join)}"
    assert via_join["paste_line"].startswith(f"maity join {JOIN}/")
    via_public = create(owner, agent={"handle": "agent-p", "display_name": "P"}, via="public")
    assert via_public["join_url"] == f"{PUBLIC}/join/{token_of(via_public)}"
    listed = {j["id"]: j["via"] for j in owner.get("/projects/maity/joins").json()["items"]}
    assert listed == {via_join["id"]: "join", via_public["id"]: "public"}


def test_via_join_without_a_join_host_is_invalid(owner: flow.Human) -> None:
    response = owner.post(
        "/projects/maity/joins",
        {"agent": {"handle": "agent-x", "display_name": "X"}, "via": "join"},
    )
    assert response.json()["error"]["details"]["fields"] == {"via": "no_join_host"}


# --- the join host's routes -------------------------------------------------------------------


def test_the_join_page_on_the_join_host(make_client: ClientFactory, owner: flow.Human) -> None:
    token = token_of(create(owner))
    page = join_client(make_client).get(f"/{token}")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/markdown")
    assert f"{JOIN}/{token})" in page.text  # the exchange posts to the same URL
    assert f"maity join {JOIN}/{token} --code" in page.text
    assert f"{PUBLIC}/api/v1/help" in page.text  # everything after it is public
    html = join_client(make_client).get(f"/{token}", headers={"Accept": "text/html"})
    assert html.headers["content-type"].startswith("text/html")
    assert f'href="{PUBLIC}/"' in html.text
    public = make_client().get(f"/j/{token}")
    assert f"{PUBLIC}/api/v1/join/{token})" in public.text  # both shapes stay valid


def test_the_exchange_on_the_join_host_ignores_credentials_and_cookies(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    created = create(owner)
    client = join_client(make_client)
    client.cookies.set("maity_session", "anything")
    response = client.post(
        f"/{token_of(created)}",
        json={"code": created["code"], "client": "curl"},
        headers={"Authorization": "Bearer whatever"},
    )
    assert response.status_code == 201, response.text
    assert response.headers["Maity-Hub"] == PUBLIC
    assert "set-cookie" not in response.headers
    assert response.text.startswith("mty1.")


def test_a_dead_link_says_so(make_client: ClientFactory, owner: flow.Human) -> None:
    created = create(owner)
    owner.delete(f"/projects/maity/joins/{created['id']}")
    dead = join_client(make_client).get(f"/{token_of(created)}")
    assert dead.status_code == 404
    assert "no longer works" in dead.text and "new join line" in dead.text
    html = join_client(make_client).get(f"/{token_of(created)}", headers={"Accept": "text/html"})
    assert html.status_code == 404 and "<h1>This join link no longer works</h1>" in html.text
    unknown = join_client(make_client).get("/" + "A" * 22)
    assert unknown.status_code == 404 and unknown.text == dead.text  # never says why
    exchange = join_client(make_client).post(
        f"/{token_of(created)}", json={"code": created["code"], "client": "curl"}
    )
    assert exchange.status_code == 404 and exchange.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/join/" + "A" * 22,
        "/j/" + "A" * 22,
        "/api/v1/help",
        "/api/v1/health",
        "/r/xyz",
        "/anything/else",
    ],
)
def test_every_other_get_goes_to_the_public_start_page(
    make_client: ClientFactory, path: str
) -> None:
    response = join_client(make_client).get(path, follow_redirects=False)
    assert (response.status_code, response.headers["location"]) == (302, f"{PUBLIC}/")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/" + "A" * 22),
        ("DELETE", "/"),
        ("POST", "/api/v1/join/" + "A" * 22),
        ("POST", "/api/v1/runners/pair/xyz"),
        ("POST", "/api/v1/auth/login"),
    ],
)
def test_every_other_method_is_not_found(
    make_client: ClientFactory, method: str, path: str
) -> None:
    response = join_client(make_client).request(method, path, json={})
    assert (response.status_code, response.json()["error"]["code"]) == (404, "not_found")


def test_the_public_host_is_unchanged(make_client: ClientFactory, owner: flow.Human) -> None:
    client = make_client(join_url=JOIN)
    assert client.get("/api/v1/help").status_code == 200
    token = token_of(create(owner))
    assert client.get(f"/j/{token}").status_code == 200
    assert client.get(f"/{token}", follow_redirects=False).status_code != 302


def test_the_log_masks_the_join_hosts_token(
    make_client: ClientFactory, owner: flow.Human, caplog: pytest.LogCaptureFixture
) -> None:
    token = token_of(create(owner))
    with caplog.at_level(logging.INFO, logger="maity_hub.access"):
        join_client(make_client).get(f"/{token}")
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.access"]
    assert lines == ["GET /join/… 200"]
    assert not any(token in line for line in lines)


def test_pairing_lines_stay_on_the_public_url(make_client: ClientFactory, migrated: Any) -> None:
    owner = hosted_human(make_client, migrated, "hosted")
    enrolled = owner.post("/runners/enrollments", {"name": "box"}).json()
    assert enrolled["pair_url"].startswith(f"{PUBLIC}/r/")


# --- the page's path and install line (#104, #113) ------------------------------------------


def test_the_page_lives_at_join_with_j_as_an_alias(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    token = token_of(create(owner))
    client = make_client()
    canonical, alias = client.get(f"/join/{token}"), client.get(f"/j/{token}")
    assert canonical.status_code == alias.status_code == 200
    assert canonical.text == alias.text  # the same document, no redirect


def test_the_page_names_the_instances_install_line_and_the_state_directory(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    token = token_of(create(owner))
    page = make_client(cli_install="pipx install maity-fork").get(f"/join/{token}").text
    assert "pipx install maity-fork\nmaity join" in page
    assert "pip install --user" in page and "Python\n3.10" in page.replace(" 3.10", "\n3.10")
    assert "export MAITY_STATE_DIR=~/.local/state/maity/agent-j" in page
    assert "pipx install maity\n" not in page
    help_text = make_client(cli_install="pipx install maity-fork").get("/api/v1/help").text
    assert "(`pipx install maity-fork`)" in help_text
