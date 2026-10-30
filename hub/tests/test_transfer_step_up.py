"""docs/api.md §2.8.4: a transfer of a project and the `go` that moves it ask for the second
factor within the last 10 minutes; a `no` changes nothing and does not."""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import add_member, make_org
from tests.test_two_factor import KEY, Clock, code_now, enrol, login, signed_in
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)


def reason(response: Any) -> tuple[int, str]:
    body = response.json()["error"]
    return response.status_code, body["details"].get("reason", body["code"])


def verified(who: flow.Human, secret: bytes, moment: Clock) -> None:
    assert who.post("/auth/second-factor/verify", {"code": code_now(secret, moment.at)})


def enrolled(
    make_client: ClientFactory, migrated: Engine, moment: Clock, handle: str
) -> tuple[flow.Human, bytes]:
    human_id = factory.human(migrated, handle)
    client = make_client(secret_key=KEY)
    assert login(client, handle).status_code == 200
    csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
    who = flow.Human(client, csrf, human_id)
    started = who.post("/auth/second-factor/totp")
    assert started.status_code == 200, started.text
    secret = base64.b32decode(started.json()["secret"] + "=" * (-len(started.json()["secret"]) % 8))
    confirmed = who.post("/auth/second-factor/totp/confirm", {"code": code_now(secret, moment.at)})
    assert confirmed.status_code == 200, confirmed.text
    return who, secret


def test_a_transfer_to_a_human_and_its_go_ask_for_the_factor_a_no_does_not(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    owner = signed_in(make_client, migrated)
    secret, _ = enrol(owner, moment)
    flow.project(owner, "maity")
    anna, anna_secret = enrolled(make_client, migrated, moment, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=anna.id)
    moment.move(minutes=11)
    path = "/projects/maintainer/maity/transfer"
    assert reason(owner.post(path, {"to": anna.id})) == (403, "step_up_required")
    verified(owner, secret, moment)
    filed = owner.post(path, {"to": anna.id})
    assert filed.status_code == 202, filed.text
    answer = f"/projects/maintainer/maity/requests/{filed.json()['id']}/answer"
    assert reason(anna.post(answer, {"reply_id": "go"})) == (403, "step_up_required")
    assert anna.get("/projects/maintainer/maity").json()["owner"]["id"] == owner.id
    verified(anna, anna_secret, moment)
    moved = anna.post(answer, {"reply_id": "go"})
    assert moved.status_code == 200, moved.text
    assert anna.get("/projects/anna/maity").json()["owner"]["id"] == anna.id
    # a `no` is not asked: file again from the new owner, answer after the factor went stale
    again = anna.post("/projects/anna/maity/transfer", {"to": owner.id})
    assert again.status_code == 202, again.text
    moment.move(minutes=11)
    refused = owner.post(
        f"/projects/anna/maity/requests/{again.json()['id']}/answer", {"reply_id": "no"}
    )
    assert refused.status_code == 200, refused.text


def test_a_move_into_an_organisation_asks_for_the_factor_in_the_call_and_at_the_go(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    boss, boss_secret = enrolled(make_client, migrated, moment, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    adm, adm_secret = enrolled(make_client, migrated, moment, "adm")
    add_member(migrated, org["id"], adm.id, "admin")
    flow.project(adm, "shop")
    moment.move(minutes=11)
    path = "/projects/adm/shop/transfer"
    assert reason(adm.post(path, {"to": org["id"]})) == (403, "step_up_required")
    verified(adm, adm_secret, moment)
    assert adm.post(path, {"to": org["id"]}).status_code == 202
    [asked] = boss.get("/requests", params={"status": "open"}).json()["items"]
    assert reason(boss.post(f"/requests/{asked['id']}/answer", {"reply_id": "go"})) == (
        403,
        "step_up_required",
    )
    verified(boss, boss_secret, moment)
    went = boss.post(f"/requests/{asked['id']}/answer", {"reply_id": "go"})
    assert went.status_code == 200, went.text
    assert adm.get("/projects/oz-team/shop").json()["owner"]["id"] == org["id"]


def test_an_owner_of_an_organisation_hands_its_project_over_with_the_factor(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    """Out of an organisation: to oneself, the move happens in the call; to another owner
    of the project, the call files a request and that owner's `go` moves it. Each asks."""
    boss, boss_secret = enrolled(make_client, migrated, moment, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    second, second_secret = enrolled(make_client, migrated, moment, "second")
    add_member(migrated, org["id"], second.id, "owner")
    made = boss.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"})
    assert made.status_code in (200, 201), made.text
    path = "/projects/oz-team/shop/transfer"
    moment.move(minutes=11)
    # to oneself: the move is in the call
    assert reason(boss.post(path, {"to": boss.id})) == (403, "step_up_required")
    assert boss.get("/projects/oz-team/shop").json()["owner"]["id"] == org["id"]
    # to the other owner: the request, then their go
    assert reason(boss.post(path, {"to": second.id})) == (403, "step_up_required")
    verified(boss, boss_secret, moment)
    filed = boss.post(path, {"to": second.id})
    assert filed.status_code == 202, filed.text
    answer = f"/projects/oz-team/shop/requests/{filed.json()['id']}/answer"
    moment.move(minutes=11)
    assert reason(second.post(answer, {"reply_id": "go"})) == (403, "step_up_required")
    assert boss.get("/projects/oz-team/shop").json()["owner"]["id"] == org["id"]
    verified(second, second_secret, moment)
    moved = second.post(answer, {"reply_id": "go"})
    assert moved.status_code == 200, moved.text
    assert second.get("/projects/second/shop").json()["owner"]["id"] == second.id


def test_the_hand_over_to_oneself_moves_the_project_in_the_call_once_the_factor_is_given(
    make_client: ClientFactory, migrated: Engine, moment: Clock
) -> None:
    boss, boss_secret = enrolled(make_client, migrated, moment, "boss")
    org = make_org(boss, "oz-team", "OZ Team")
    assert (
        boss.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"}).status_code
        == 201
    )
    moment.move(minutes=11)
    path = "/projects/oz-team/shop/transfer"
    assert reason(boss.post(path, {"to": boss.id})) == (403, "step_up_required")
    verified(boss, boss_secret, moment)
    moved = boss.post(path, {"to": boss.id})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["full_name"], moved.json()["owner"]["id"]) == ("boss/shop", boss.id)
    assert org["id"] != boss.id
