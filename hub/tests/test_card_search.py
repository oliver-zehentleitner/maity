"""The contract's Unicode form and fields, independent of database collation."""

from types import SimpleNamespace

import pytest
from sqlalchemy import Engine

from maity_hub import card_search
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task


@pytest.mark.parametrize(
    ("text", "query", "expected"),
    [
        ("Ärger", "är", True),
        ("ＡＲ", "ar", True),
        ("Cafe\u0301", "CAFÉ", True),
        ("Straße", "STRASSE", False),
        ("100% literal_", "%", True),
        ("100% literal_", "_", True),
        ("plain", "%", False),
        ("plain", "_", False),
    ],
)
def test_defined_unicode_substring(text: str, query: str, expected: bool) -> None:
    row = SimpleNamespace(id="tsk-1", title=text, body=None, report=None)
    assert bool(card_search.matches(row, query)) is expected


def test_match_order() -> None:
    row = SimpleNamespace(id="tsk-match", title="MATCH", body="match", report={"summary": "match"})
    assert card_search.matches(row, "match", ["a Match"]) == [
        "id",
        "title",
        "body",
        "note",
        "report",
    ]


def test_only_latest_report_summary_is_searched() -> None:
    row = SimpleNamespace(
        id="tsk-1",
        title="ordinary",
        body=None,
        report={"summary": "latest", "branch": "hidden", "observed": {"body": "hidden"}},
    )
    assert card_search.matches(row, "hidden") == []
    row.report = {"summary": "replacement"}
    assert card_search.matches(row, "latest") == []


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:

    who = flow.human(make_client, migrated)
    flow.project(who)
    return who


@pytest.mark.parametrize("order", ["board", "updated"])
def test_unicode_search_and_paging_after_filtering(owner: flow.Human, order: str) -> None:

    cards = [
        task(owner, title=("Ärger" if i % 2 else "unrelated"), body="literal % _") for i in range(9)
    ]
    expected = {c["id"] for i, c in enumerate(cards) if i % 2}
    path = f"/projects/maintainer/maity/tasks?q=är&order={order}&limit=2"
    seen: list[str] = []
    while True:
        response = owner.get(path)
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) == 2
        assert all(c["match"] == ["title"] for c in page["items"])
        seen.extend(c["id"] for c in page["items"])
        if page["next_cursor"] is None:
            break
        path = (
            f"/projects/maintainer/maity/tasks?q=är&order={order}&limit=2&cursor="
            + page["next_cursor"]
        )
    assert set(seen) == expected and len(seen) == 4
    assert all(
        "match" not in c for c in owner.get("/projects/maintainer/maity/tasks").json()["items"]
    )


@pytest.mark.parametrize("query", ["%", "_"])
def test_wildcards_are_literal(owner: flow.Human, query: str) -> None:

    hit = task(owner, body="100% literal_")
    task(owner, body="100X literalY")
    page = owner.get("/projects/maintainer/maity/tasks", params={"q": query}).json()
    assert [(c["id"], c["match"]) for c in page["items"]] == [(hit["id"], ["body"])]


def test_match_order_and_latest_report_via_api(owner: flow.Human) -> None:

    hit = task(owner, title="TSK", body="tsk")
    path = f"/projects/maintainer/maity/tasks/{hit['id']}"
    owner.post(path + "/claim", {})
    assert owner.post(path + "/report", _report(summary="tsk")).status_code == 200
    result = owner.get("/projects/maintainer/maity/tasks?q=tsk").json()["items"]
    assert result[0]["match"] == ["id", "title", "body", "report"]
    owner.post(path + "/report", _report(summary="new phrase"))
    assert owner.get("/projects/maintainer/maity/tasks?q=new%20phrase").json()["items"][0][
        "match"
    ] == ["report"]
    assert owner.get("/projects/maintainer/maity/tasks?q=agent-b/lease").json()["items"] == []


@pytest.mark.parametrize("query", ["", "x" * 201])
def test_query_length_is_validated(owner: flow.Human, query: str) -> None:
    result = owner.get("/projects/maintainer/maity/tasks", params={"q": query})
    assert result.headers["Maity-Error"] == "invalid"


def test_query_boundary_and_normalization(owner: flow.Human) -> None:

    hit = task(owner, title="plain", body="x" * 200 + " ＡＲ")
    assert (
        owner.get("/projects/maintainer/maity/tasks", params={"q": "x" * 200}).json()["items"][0][
            "id"
        ]
        == hit["id"]
    )
    result = owner.get("/projects/maintainer/maity/tasks?q=ar").json()["items"][0]
    assert result["id"] == hit["id"] and "body" in result["match"]


@pytest.mark.parametrize("order", ["board", "updated"])
def test_filters_and_cursor_bind_the_query(owner: flow.Human, order: str) -> None:

    for _ in range(3):
        task(owner, title="needle", area="hub/", label="fix")
    task(owner, title="needle", area="web/", label="fix")
    task(owner, title="needle", area="hub/", label="feature")
    params = {
        "q": "needle",
        "area": "hub/",
        "label": "fix",
        "status": "open",
        "order": order,
        "limit": 2,
    }
    page = owner.get("/projects/maintainer/maity/tasks", params=params).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    last = owner.get(
        "/projects/maintainer/maity/tasks", params={**params, "cursor": page["next_cursor"]}
    ).json()
    assert len(last["items"]) == 1 and last["next_cursor"] is None
    refused = owner.get(
        "/projects/maintainer/maity/tasks",
        params={**params, "q": "different", "cursor": page["next_cursor"]},
    )
    assert refused.headers["Maity-Error"] == "invalid"


def test_search_includes_closed_cards_and_replaces_old_report_text(owner: flow.Human) -> None:
    hit = task(owner, title="ordinary")
    path = f"/projects/maintainer/maity/tasks/{hit['id']}"
    owner.post(path + "/claim", {})
    owner.post(path + "/report", _report(summary="older report phrase"))
    owner.post(path + "/report", _report(summary="latest report phrase"))
    assert owner.patch(path, {"status": "done"}).status_code == 200
    assert owner.get("/projects/maintainer/maity/tasks?q=older").json()["items"] == []
    page = owner.get("/projects/maintainer/maity/tasks?q=latest&status=done").json()["items"]
    assert [(c["id"], c["match"]) for c in page] == [(hit["id"], ["report"])]
    assert owner.get("/projects/maintainer/maity/tasks?q=latest&status=open").json()["items"] == []


@pytest.mark.parametrize("state", ["open", "incorporated", "dismissed"])
def test_a_note_in_every_state_is_searched(owner: flow.Human, state: str) -> None:
    card = task(owner, title="plain", body=None)
    path = f"/projects/maintainer/maity/tasks/{card['id']}/notes"
    posted = owner.post(path, {"body": "Überlauf im Cache"}).json()
    if state != "open":
        resolved = owner.post(f"{path}/{posted['id']}/resolve", {"state": state})
        assert resolved.status_code == 200, resolved.text
    [found] = owner.get("/projects/maintainer/maity/tasks?q=überlauf&status=all").json()["items"]
    assert found["id"] == card["id"] and found["match"] == ["note"]


def test_a_redacted_note_is_not_searched(owner: flow.Human) -> None:
    card = task(owner, title="plain", body=None)
    path = f"/projects/maintainer/maity/tasks/{card['id']}/notes"
    posted = owner.post(path, {"body": "the token is s3cret"}).json()
    assert owner.get("/projects/maintainer/maity/tasks?q=s3cret").json()["items"][0]["match"] == [
        "note"
    ]
    redacted = owner.post(f"{path}/{posted['id']}/redact", {"reason": "secret"})
    assert redacted.status_code == 200, redacted.text
    assert owner.get("/projects/maintainer/maity/tasks?q=s3cret").json()["items"] == []
