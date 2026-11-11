"""`GET /bootstrap` (§5.4): each part is its single route's answer for the same caller."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_maintenance import FROM, Clock, admin, now, put, running  # noqa: F401
from tests.test_registration_accounts import pending_account
from tests.test_runners import call, paired
from tests.test_two_factor import enrol, second_step, signed_in

PROJECT = "maintainer/maity"
SINGLE = {
    "maintenance": "/maintenance",
    "session": "/auth/session",
    "me": "/me",
    "head": f"/projects/{PROJECT}/events?after=latest&wait=0",
    "project": f"/projects/{PROJECT}",
    "members": f"/projects/{PROJECT}/members",
}


def singles(client: TestClient, headers: dict[str, str] | None = None) -> dict[str, Any]:
    found = {}
    for part, path in SINGLE.items():
        answer = client.get(f"/api/v1{path}", headers=headers or {})
        found[part] = {"status": answer.status_code, "body": answer.json()}
    return found


def bootstrap(
    client: TestClient, headers: dict[str, str] | None = None, project: str | None = PROJECT
) -> Any:
    query = f"?project={project}" if project is not None else ""
    return client.get(f"/api/v1/bootstrap{query}", headers=headers or {})


def same(client: TestClient, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """The bundle, asserted equal part by part to the single routes asked right after it."""
    answer = bootstrap(client, headers)
    assert answer.status_code == 200, answer.text
    parts: dict[str, Any] = answer.json()
    assert parts == singles(client, headers)
    return parts


def test_a_member_gets_each_single_answer(admin: flow.Human, now: Clock) -> None:  # noqa: F811
    flow.project(admin)
    parts = same(admin.client)
    assert [parts[p]["status"] for p in SINGLE] == [200] * 6
    assert parts["session"]["body"]["csrf_token"] == admin.csrf


def test_without_project_the_project_parts_are_absent(
    admin: flow.Human, now: Clock  # noqa: F811
) -> None:
    answer = bootstrap(admin.client, project=None)
    assert answer.status_code == 200, answer.text
    assert sorted(answer.json()) == ["maintenance", "me", "session"]


def test_answer_is_not_stored_nor_compressed(admin: flow.Human, now: Clock) -> None:  # noqa: F811
    flow.project(admin)
    answer = admin.client.get(
        f"/api/v1/bootstrap?project={PROJECT}", headers={"Accept-Encoding": "gzip"}
    )
    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    assert "content-encoding" not in answer.headers


def test_signed_out_gets_the_window_and_401s(
    admin: flow.Human, make_client: ClientFactory, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    parts = same(make_client())
    assert [parts[p]["status"] for p in SINGLE] == [200, 401, 401, 401, 401, 401]


def test_an_agent_gets_its_own_answers(
    admin: flow.Human, make_client: ClientFactory, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    agent = flow.agent(make_client, admin)
    parts = same(agent.client, agent.auth)
    assert [parts[p]["status"] for p in SINGLE] == [200, 403, 200, 200, 200, 200]


def test_an_agent_outside_the_project_gets_404s(
    admin: flow.Human, make_client: ClientFactory, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    flow.project(admin, "other")
    agent = flow.agent(make_client, admin, "other")
    parts = same(agent.client, agent.auth)
    assert [parts[p]["status"] for p in ("head", "project", "members")] == [404] * 3


def test_an_unknown_or_malformed_project_is_404_in_all_three(
    admin: flow.Human, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    for project in ("maintainer/nothing", "nothing", "a/b/c"):
        parts = bootstrap(admin.client, project=project).json()
        assert [parts[p]["body"]["error"]["code"] for p in ("head", "project", "members")] == [
            "not_found"
        ] * 3, project


def test_a_second_factor_session_gets_its_session_and_403s(
    make_client: ClientFactory, migrated: Engine, now: Clock  # noqa: F811
) -> None:
    human = signed_in(make_client, migrated)
    flow.project(human)
    enrol(human, now)  # type: ignore[arg-type]  # the same clock, as test_maintenance keeps it
    human.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": human.csrf})
    second_step(human.client)
    parts = same(human.client)
    assert parts["session"]["status"] == 200
    assert parts["session"]["body"]["second_factor"] == "required"
    refused = [parts[p]["body"]["error"]["details"]["reason"] for p in list(SINGLE)[2:]]
    assert refused == ["second_factor_required"] * 4


def test_a_pending_account_gets_its_account_and_account_pending(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    _, person = pending_account(make_client, migrated)
    parts = same(person.client)
    assert [parts[p]["status"] for p in SINGLE] == [200, 200, 200, 403, 403, 403]
    assert {parts[p]["body"]["error"]["details"]["reason"] for p in list(SINGLE)[3:]} == {
        "account_pending"
    }


def test_a_running_window_refuses_only_the_project_parts(
    admin: flow.Human, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    assert put(admin).status_code == 200
    running(now)
    answer = bootstrap(admin.client)
    assert answer.status_code == 200, answer.text
    parts = answer.json()
    assert [parts[p]["status"] for p in SINGLE] == [200, 200, 200, 503, 503, 503]
    single = admin.client.get(f"/api/v1/projects/{PROJECT}")
    assert single.status_code == 503 and "Retry-After" in single.headers
    assert parts["project"]["body"] == single.json()
    assert parts["maintenance"] == singles(admin.client)["maintenance"]


def test_a_cross_site_cookie_is_refused_whole(admin: flow.Human, now: Clock) -> None:  # noqa: F811
    answer = admin.client.get("/api/v1/bootstrap", headers={"Sec-Fetch-Site": "cross-site"})
    assert (answer.status_code, answer.json()["error"]["code"]) == (403, "csrf_mismatch")


def test_maity_for_is_refused_whole(
    admin: flow.Human, make_client: ClientFactory, now: Clock  # noqa: F811
) -> None:
    flow.project(admin)
    agent = flow.agent(make_client, admin)
    answer = bootstrap(agent.client, agent.auth | {"Maity-For": "agt-anything"})
    assert answer.status_code == 400
    assert answer.json()["error"]["details"]["fields"] == {"Maity-For": "route"}


def test_a_runner_is_refused_whole(make_client: ClientFactory, migrated: Engine) -> None:
    # The real clock: a signed call carries its own time (§15.1).
    runner = paired(make_client, flow.human(make_client, migrated))
    answer = call(make_client(), runner, "GET", "/api/v1/bootstrap")
    assert (answer.status_code, answer.json()["error"]["code"]) == (403, "forbidden")


def test_the_head_is_read_before_the_project(
    admin: flow.Human, now: Clock, monkeypatch: Any  # noqa: F811
) -> None:
    """A change committed after the head is read and before the project is read arrives as
    an event past the head's cursor (§5.4; the interleaving fmzu asked for)."""
    from maity_hub.routes import bootstrap as route

    flow.project(admin)
    order: list[str] = []
    real_head, real_project, real_thread = (
        getattr(route, name) for name in ("head_body", "project_body", "run_in_threadpool")
    )

    ran = threading.local()
    head_returned = threading.Event()

    def head(*args: Any) -> Any:
        order.append("head")
        ran.head = True
        return real_head(*args)

    def project(*args: Any) -> Any:
        # Read in the head's wave, the project's thread would begin before the head's read
        # has returned, whenever the database lets its read go on.
        order.append("project in the head's wave" if ran.early else "project")
        return real_project(*args)

    def rename() -> None:
        assert admin.patch(f"/projects/{PROJECT}", {"name": "Renamed"}).status_code == 200
        order.append("rename")

    async def thread(fn: Any) -> Any:
        def run() -> tuple[Any, bool]:
            ran.head, ran.early = False, not head_returned.is_set()
            return fn(), ran.head

        found, was_head = await real_thread(run)
        if was_head:  # the head's transaction has ended; the project's has not begun
            head_returned.set()
            await real_thread(rename)
        return found

    monkeypatch.setattr(f"{route.__name__}.head_body", head)
    monkeypatch.setattr(f"{route.__name__}.project_body", project)
    monkeypatch.setattr(f"{route.__name__}.run_in_threadpool", thread)
    parts = bootstrap(admin.client).json()
    assert order == ["head", "rename", "project"]
    assert parts["project"]["body"]["name"] == "Renamed"
    cursor = parts["head"]["body"]["cursor"]
    later = admin.get(f"/projects/{PROJECT}/events?after={cursor}&wait=0").json()
    # Nothing but the rename wrote since the head: what it announced lies past the cursor.
    assert later["items"] and all(e["seq"] > cursor for e in later["items"]), later


def test_the_server_time_of_me_is_the_single_routes(
    admin: flow.Human, now: Clock  # noqa: F811
) -> None:
    now.set(FROM - timedelta(days=1))
    parts = bootstrap(admin.client, project=None).json()
    assert parts["me"]["body"]["server_time"] == admin.get("/me").json()["server_time"]
