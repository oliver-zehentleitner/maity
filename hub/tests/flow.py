"""Drive the API the way its users do: a logged-in human, joins, agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests import factory
from tests.conftest import ClientFactory


@dataclass
class Human:
    client: TestClient
    csrf: str
    id: str
    handle: str = "maintainer"  # the namespace of the projects it creates (§6.25)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(f"/api/v1{path}", **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.client.post(
            f"/api/v1{path}", json=json, headers={"X-CSRF-Token": self.csrf}, **kwargs
        )

    def patch(self, path: str, json: Any = None) -> Any:
        return self.client.patch(f"/api/v1{path}", json=json, headers={"X-CSRF-Token": self.csrf})

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v1{path}", headers={"X-CSRF-Token": self.csrf})


@dataclass
class Agent:
    client: TestClient
    credential: str
    credential_id: str
    id: str
    instance: str = ""
    key_counter: int = 0

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.credential}"}

    def key(self) -> dict[str, str]:
        self.key_counter += 1
        return {"Idempotency-Key": f"test-key-{self.credential_id}-{self.key_counter:06d}"}

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(f"/api/v1{path}", headers=self.auth, **kwargs)

    def post(self, path: str, json: Any = None) -> Any:
        return self.client.post(f"/api/v1{path}", json=json, headers=self.auth | self.key())

    def patch(self, path: str, json: Any = None) -> Any:
        return self.client.patch(f"/api/v1{path}", json=json, headers=self.auth | self.key())

    def resume(self, **body: Any) -> Any:
        return self.client.post(
            "/api/v1/me/resume", json={"client": "test", **body}, headers=self.auth
        )


def human(make_client: ClientFactory, engine: Engine, handle: str = "maintainer") -> Human:
    human_id = factory.human(engine, handle)
    client = make_client()
    response = client.post(
        "/api/v1/auth/login", json={"handle": handle, "password": factory.PASSWORD}
    )
    assert response.status_code == 200, response.text
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    return Human(client, csrf, human_id, handle)


def project(owner: Human, slug: str = "maity", **body: Any) -> dict[str, Any]:
    response = owner.post("/projects", {"slug": slug, "name": slug.title(), **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def join(owner: Human, slug: str, **body: Any) -> dict[str, Any]:
    body.setdefault("agent", {"handle": f"agent-{_n()}", "display_name": "An agent"})
    if "role" in body and "trust" not in body:  # a single-role name, as most tests say it
        body["trust"], body["role"] = factory.trust_and_role(body["role"])
    name = slug if "/" in slug else f"maintainer/{slug}"  # a full name, or the maintainer's
    response = owner.post(f"/projects/{name}/joins", body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


_COUNTER = [0]


def _n() -> int:
    _COUNTER[0] += 1
    return _COUNTER[0]


def exchange(client: TestClient, created: dict[str, Any], client_name: str = "curl") -> Any:
    token = created["join_url"].rsplit("/", 1)[1]
    return client.post(
        f"/api/v1/join/{token}", json={"code": created["code"], "client": client_name}
    )


def agent(make_client: ClientFactory, owner: Human, slug: str = "maity", **join_body: Any) -> Agent:
    created = join(owner, slug, **join_body)
    client = make_client()
    response = exchange(client, created)
    assert response.status_code == 201, response.text
    return Agent(
        client,
        response.text,
        response.headers["Maity-Credential-Id"],
        response.headers["Maity-Member-Id"],
        response.headers["Maity-Instance"],
    )
