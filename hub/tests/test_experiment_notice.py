"""docs/api.md §5.1 "Experiment notice", §5.3, §2.9: a human confirms the notice once with
`PATCH /me`; `/me` and the export carry when, and the account's deletion takes it."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_account_deletion import admin_first, ask_deletion, person, press, token_of
from tests.test_two_factor import Clock
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

FIELD = "experiment_notice_understood"


def _understood(human: flow.Human) -> Any:
    return human.get("/me").json()["member"]["experiment_notice_understood_at"]


def test_a_new_account_has_not_confirmed_it_and_an_agent_has_no_field(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert _understood(owner) is None
    assert "experiment_notice_understood_at" not in agent.get("/me").json()["member"]


def test_the_first_confirmation_sets_the_time_and_a_later_one_keeps_it(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    owner = flow.human(make_client, migrated)
    first = clock.rfc3339(clock.now())
    done = owner.patch("/me", {FIELD: True})
    assert done.status_code == 200, done.text
    assert done.json()["member"]["experiment_notice_understood_at"] == first  # `/me` as it is
    moment.move(hours=3)
    again = owner.patch("/me", {FIELD: True})
    assert again.status_code == 200, again.text
    assert again.json()["member"]["experiment_notice_understood_at"] == first
    assert _understood(owner) == first


def test_only_true_confirms_and_only_a_human_may(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    for value in (False, None, "yes", 1):
        refused = owner.patch("/me", {FIELD: value})
        assert refused.status_code == 400, (value, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {FIELD: "must_be_true"}
    assert _understood(owner) is None  # nothing refused was stored
    by_agent = agent.patch("/me", {FIELD: True})
    assert by_agent.status_code == 403
    assert by_agent.json()["error"]["details"]["reason"] == "humans_only"


def test_the_export_holds_it(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.patch("/me", {FIELD: True}).status_code == 200
    when = _understood(owner)
    assert when is not None
    exported = owner.get("/me/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["account"]["experiment_notice_understood_at"] == when


def test_it_goes_with_the_account(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    admin_first(migrated, moment)
    pat = person(make_client, migrated, moment)
    assert pat.patch("/me", {FIELD: True}).status_code == 200
    assert ask_deletion(pat).status_code == 202
    assert press(pat, token_of(migrated)).status_code == 200
    with migrated.connect() as conn:
        gone = conn.execute(
            select(t.human.c.experiment_notice_understood_at).where(t.human.c.id == pat.id)
        ).scalar()
    assert gone is None
