"""docs/api.md §8.4, "A review result cites what it judged", and §8.8 (tsk-9cmn9xy8zcqt): a
`review_result` carries `review`, checked and stored as given, shown on the listing, gone from a
tombstone."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

HEAD = "7039a4b6fd8b988d71a63338711da188fcd95fba"
CITE = {
    "path": "docs/api.md",
    "line": 11929,
    "quote": "the inbox item appears after the fourth line",
}


def review(**change: Any) -> dict[str, Any]:
    return {
        "subject": "#743",
        "head": HEAD,
        "verdict": "approve",
        "cites": [dict(CITE)],
        **change,
    }


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def post(who: Any, review_: Any = ..., **more: Any) -> Any:
    body: dict[str, Any] = {
        "kind": "message",
        "type": "review_result",
        "to": "all",
        "body": "Approved.",
        **more,
    }
    if review_ is not ...:
        body["review"] = review_
    return who.post("/projects/maintainer/maity/events", body)


def fields(answer: Any) -> dict[str, str]:
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["code"] == "invalid"
    found: dict[str, str] = answer.json()["error"]["details"]["fields"]
    return found


def test_a_review_result_is_stored_as_posted_and_listed(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="reviewer")
    sent = post(agent, review())
    assert sent.status_code == 201, sent.text
    assert sent.json()["payload"]["review"] == review()
    assert sent.json()["payload"]["type"] == "review_result"
    [item] = owner.get("/projects/maintainer/maity/messages").json()["items"]
    assert item["review"] == review() and item["type"] == "review_result"
    events = owner.get("/projects/maintainer/maity/events").json()["items"]
    assert [e["payload"].get("review") for e in events if e["kind"] == "message"] == [review()]


def test_a_cite_without_a_line_is_stored_with_a_null_line(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="reviewer")
    cites = [{"path": "a.py", "quote": "def old():"}, {"path": "b.py", "line": None, "quote": "x"}]
    sent = post(agent, review(cites=cites))
    assert sent.status_code == 201, sent.text
    assert sent.json()["payload"]["review"]["cites"] == [
        {"path": "a.py", "line": None, "quote": "def old():"},
        {"path": "b.py", "line": None, "quote": "x"},
    ]


def test_every_other_type_lists_review_as_null_and_refuses_one(owner: flow.Human) -> None:
    refused = post(owner, review(), type="notice")
    assert fields(refused) == {"review": "not_allowed"}
    assert post(owner, type="notice").status_code == 201
    [item] = owner.get("/projects/maintainer/maity/messages").json()["items"]
    assert item["type"] == "notice" and item["review"] is None


def test_a_review_result_without_a_review_is_invalid(owner: flow.Human) -> None:
    assert fields(post(owner)) == {"review": "required"}
    assert fields(post(owner, None)) == {"review": "required"}
    assert fields(post(owner, "approved")) == {"review": "format"}
    assert fields(post(owner, [])) == {"review": "format"}
    assert owner.get("/projects/maintainer/maity/messages").json()["items"] == []


def test_a_redacted_review_result_is_a_tombstone_without_its_review(owner: flow.Human) -> None:
    seq = post(owner, review()).json()["seq"]
    done = owner.post(f"/projects/maintainer/maity/events/{seq}/redact", {"reason": "typo"})
    assert done.status_code == 200, done.text
    [item] = owner.get("/projects/maintainer/maity/messages").json()["items"]
    assert item["redacted"] is True and item["review"] is None and item["type"] is None
    assert item["body"] is None and item["from"] == owner.id


LONG = "x" * 301


@pytest.mark.parametrize(
    ("value", "path", "reason"),
    [
        (review(subject=None), "review.subject", "required"),
        (review(subject=""), "review.subject", "format"),
        (review(subject=5), "review.subject", "format"),
        (review(subject="s" * 121), "review.subject", "too_long"),
        (review(head=None), "review.head", "required"),
        (review(head=HEAD[:39]), "review.head", "format"),
        (review(head=HEAD + "0"), "review.head", "format"),
        (review(head=HEAD.upper()), "review.head", "format"),
        (review(head="z" * 40), "review.head", "format"),
        (review(verdict=None), "review.verdict", "required"),
        (review(verdict="lgtm"), "review.verdict", "format"),
        (review(verdict="APPROVE"), "review.verdict", "format"),
        (review(cites=None), "review.cites", "required"),
        (review(cites="a"), "review.cites", "format"),
        (review(cites=[]), "review.cites", "too_few"),
        (review(cites=[dict(CITE)] * 51), "review.cites", "too_many"),
        (review(cites=["x"]), "review.cites.0", "format"),
        (review(cites=[{**CITE, "path": None}]), "review.cites.0.path", "required"),
        (review(cites=[{**CITE, "path": ""}]), "review.cites.0.path", "format"),
        (review(cites=[{**CITE, "path": LONG}]), "review.cites.0.path", "too_long"),
        (review(cites=[{**CITE, "quote": None}]), "review.cites.0.quote", "required"),
        (review(cites=[{**CITE, "quote": ""}]), "review.cites.0.quote", "format"),
        (review(cites=[{**CITE, "quote": LONG}]), "review.cites.0.quote", "too_long"),
        (review(cites=[{**CITE, "quote": "two\nlines"}]), "review.cites.0.quote", "format"),
        (review(cites=[{**CITE, "quote": "a\rb"}]), "review.cites.0.quote", "format"),
        (review(cites=[{**CITE, "line": 0}]), "review.cites.0.line", "format"),
        (review(cites=[{**CITE, "line": -3}]), "review.cites.0.line", "format"),
        (review(cites=[{**CITE, "line": "4"}]), "review.cites.0.line", "format"),
        (review(cites=[{**CITE, "line": 1.5}]), "review.cites.0.line", "format"),
        (review(cites=[{**CITE, "line": True}]), "review.cites.0.line", "format"),
        (review(cites=[CITE, CITE, {**CITE, "line": 0}]), "review.cites.2.line", "format"),
        (review(cites=[{**CITE, "extra": 1}]), "review.cites.0.extra", "format"),
        (review(extra="x"), "review.extra", "format"),
    ],
)
def test_a_malformed_review_names_its_field_and_reason(
    owner: flow.Human, value: dict[str, Any], path: str, reason: str
) -> None:
    assert fields(post(owner, value)) == {path: reason}


def test_every_problem_is_reported_at_once(owner: flow.Human) -> None:
    bad = {
        "subject": "",
        "head": "abc",
        "verdict": "maybe",
        "cites": [{"path": "p", "quote": "q"}, {"path": LONG, "quote": "q", "line": 0}],
    }
    assert fields(post(owner, bad)) == {
        "review.subject": "format",
        "review.head": "format",
        "review.verdict": "format",
        "review.cites.1.path": "too_long",
        "review.cites.1.line": "format",
    }


def test_the_limits_are_inclusive_and_counted_in_characters(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner, role="reviewer")
    edge = {"path": "ä" * 300, "line": 1, "quote": "ö" * 300}
    sent = post(agent, review(subject="ü" * 120, cites=[edge] * 50))
    assert sent.status_code == 201, sent.text
    assert len(sent.json()["payload"]["review"]["cites"]) == 50
    for verdict in ("approve", "changes", "comment"):
        assert post(agent, review(verdict=verdict)).status_code == 201


def test_nothing_is_stored_by_a_refused_review(owner: flow.Human) -> None:
    before = owner.get("/projects/maintainer/maity/events").json()["items"]
    assert post(owner, review(head="nope")).status_code == 400
    assert owner.get("/projects/maintainer/maity/events").json()["items"] == before
