"""docs/api.md §16.5: at most so many projects in one namespace, a human's or an
organisation's, and an archived project leaves the availability sweep (§6.1); the jour fixe
still reaches it (§20.1, §20.6, tests in test_jour_fixe*.py)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import availability, clock, limits
from maity_hub import tables as t
from maity_hub.jourfixe import rounds
from maity_hub.jourfixe import worker as jourfixe_worker
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import make_org

PATH = "/admin/settings/limits"


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def create(who: flow.Human, slug: str, **body: Any) -> Any:
    return who.post("/projects", {"slug": slug, "name": slug.title(), "public_page": "off", **body})


def error(response: Any) -> tuple[int, str, dict[str, Any]]:
    body = response.json()["error"]
    return response.status_code, body["code"], body["details"]


def test_the_default_is_ten_and_the_eleventh_is_refused(admin: flow.Human) -> None:
    assert admin.get(PATH).json()["max_projects_per_owner"] == {"value": 10, "source": "default"}
    for n in range(10):
        assert create(admin, f"p{n}").status_code == 201
    assert error(create(admin, "p10")) == (409, "project_limit", {"limit": 10, "count": 10})
    assert admin.get(PATH).json()["owners_at_project_limit"] == 1


def test_an_organisation_has_a_cap_of_its_own(admin: flow.Human) -> None:
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    make_org(admin, "oz-team")
    assert create(admin, "mine").status_code == 201
    assert create(admin, "ours", owner="oz-team").status_code == 201
    refused = create(admin, "more", owner="oz-team")
    assert error(refused) == (409, "project_limit", {"limit": 1, "count": 1})
    assert error(create(admin, "more")) == (409, "project_limit", {"limit": 1, "count": 1})
    assert admin.get(PATH).json()["owners_at_project_limit"] == 2


def test_an_archived_project_counts(admin: flow.Human, migrated: Engine) -> None:
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    assert create(admin, "old").status_code == 201
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    assert error(create(admin, "new")) == (409, "project_limit", {"limit": 1, "count": 1})


def test_unlimited_lifts_it_and_lowering_keeps_what_is_there(admin: flow.Human) -> None:
    for n in range(3):
        assert create(admin, f"p{n}").status_code == 201
    lowered = admin.patch(PATH, {"max_projects_per_owner": 2})
    assert lowered.json()["owners_at_project_limit"] == 1  # three of two: at (or over) it
    assert len(admin.get("/projects").json()["items"]) == 3  # nothing is taken away
    assert error(create(admin, "p3")) == (409, "project_limit", {"limit": 2, "count": 3})
    assert admin.patch(PATH, {"max_projects_per_owner": "unlimited"}).status_code == 200
    assert create(admin, "p3").status_code == 201
    back = admin.patch(PATH, {"max_projects_per_owner": None}).json()
    assert back["max_projects_per_owner"] == {"value": 10, "source": "default"}


def test_the_environment_wins(make_client: ClientFactory, migrated: Engine) -> None:
    who = flow.human(lambda **kw: make_client(max_projects_per_owner=1, **kw), migrated)
    assert who.get(PATH).json()["max_projects_per_owner"] == {"value": 1, "source": "env"}
    refused = who.patch(PATH, {"max_projects_per_owner": 9})
    assert refused.json()["error"]["details"]["fields"] == {
        "max_projects_per_owner": "set_by_environment"
    }
    assert create(who, "one").status_code == 201
    assert error(create(who, "two")) == (409, "project_limit", {"limit": 1, "count": 1})


def test_read_only_count_is_refused_in_a_patch(admin: flow.Human) -> None:
    refused = admin.patch(PATH, {"owners_at_project_limit": 0})
    assert refused.json()["error"]["details"]["fields"] == {"owners_at_project_limit": "read_only"}


# --- a transfer into a full namespace -------------------------------------------------------


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine, admin: flow.Human) -> flow.Human:
    """A second owner of maintainer/maity, in a namespace of her own."""
    flow.project(admin, "maity")
    human = flow.human(make_client, migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=human.id)
    return human


def transfer(who: flow.Human, to: str, name: str = "maintainer/maity") -> Any:
    return who.post(f"/projects/{name}/transfer", {"to": to})


def test_a_transfer_into_a_full_namespace_is_refused_when_filed(
    admin: flow.Human, anna: flow.Human
) -> None:
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    flow.project(anna, "hers")
    assert error(transfer(admin, anna.id)) == (409, "project_limit", {"limit": 1, "count": 1})


def test_a_go_into_a_namespace_that_filled_up_withdraws_and_moves_nothing(
    admin: flow.Human, anna: flow.Human
) -> None:
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    filed = transfer(admin, anna.id)
    assert filed.status_code == 202, filed.text
    request = filed.json()
    flow.project(anna, "hers")
    answered = anna.post(
        f"/projects/maintainer/maity/requests/{request['id']}/answer", {"reply_id": "go"}
    )
    assert error(answered) == (409, "project_limit", {"limit": 1, "count": 1})
    got = admin.get(f"/projects/maintainer/maity/requests/{request['id']}").json()
    assert got["status"] == "withdrawn"
    assert admin.get("/projects/maintainer/maity").json()["full_name"] == "maintainer/maity"


def test_a_move_into_a_full_organisation_is_refused(admin: flow.Human) -> None:
    make_org(admin, "oz-team")
    assert create(admin, "ours", owner="oz-team").status_code == 201
    assert create(admin, "shop").status_code == 201
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    org_id = admin.get("/orgs/oz-team").json()["id"]
    refused = transfer(admin, org_id, "maintainer/shop")
    assert error(refused) == (409, "project_limit", {"limit": 1, "count": 1})
    assert admin.get("/projects/maintainer/shop").json()["full_name"] == "maintainer/shop"


# --- an archived project leaves the availability sweep ---------------------------------------


def test_the_availability_sweep_skips_an_archived_project_the_jour_fixe_does_not(
    admin: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    live = flow.project(admin, "live")["id"]
    old = flow.project(admin, "old")["id"]
    seen: list[str] = []
    monkeypatch.setattr(rounds, "handle_deadlines", lambda conn, pid: seen.append(f"jf:{pid}"))
    monkeypatch.setattr(rounds, "handle_schedule", lambda conn, pid: None)
    monkeypatch.setattr(availability, "expire_limits", lambda conn, pid: seen.append(f"av:{pid}"))

    def state(value: str) -> None:
        with migrated.begin() as conn:
            conn.execute(update(t.project).where(t.project.c.id == old).values(state=value))

    def sweep() -> list[str]:
        seen.clear()
        jourfixe_worker.sweep(migrated)
        availability.sweep(migrated)
        return sorted(seen)

    state("archived")
    assert sweep() == sorted([f"av:{live}", f"jf:{live}", f"jf:{old}"])
    state("build")
    assert sweep() == sorted([f"av:{live}", f"jf:{live}", f"av:{old}", f"jf:{old}"])


# --- the owner's row is the lock, and the admin count ---------------------------------------


def test_two_creations_at_nine_give_one_project_and_one_project_limit(
    admin: flow.Human, migrated: Engine
) -> None:
    """The count runs under the namespace owner's row lock (`limits.refuse_project_over`): a
    creation that counts while another one at nine has not committed waits for it and is then
    refused (PostgreSQL, MariaDB)."""
    from tests.concurrency import finished, race, waiting

    for n in range(9):
        assert create(admin, f"p{n}").status_code == 201
    with race(migrated) as r:
        first, second = r.first, r.second
        limits.refuse_project_over(first, admin.id, 10)  # the first creation counts nine
        factory.project(migrated, "tenth", conn=first, owner_id=admin.id)
        step = r.run(second, lambda: create(admin, "eleventh"))
        assert waiting(step)  # on the owner's row, which the first creation holds
        first.commit()
        assert error(finished(step)) == (409, "project_limit", {"limit": 10, "count": 10})
        second.rollback()
    with migrated.connect() as conn:
        owned = select(t.project.c.id).where(t.project.c.owner_id == admin.id)
        assert len(conn.execute(owned).all()) == 10


def test_a_deleted_owner_is_not_counted_at_the_limit(
    admin: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    assert admin.patch(PATH, {"max_projects_per_owner": 1}).status_code == 200
    gone = flow.human(make_client, migrated, "gone")
    flow.project(gone, "left")
    assert admin.get(PATH).json()["owners_at_project_limit"] == 1
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
        conn.execute(update(t.human).where(t.human.c.id == gone.id).values(deleted_at=clock.now()))
    assert admin.get(PATH).json()["owners_at_project_limit"] == 0
