"""docs/api.md §5.1 "Stars", §5.3, §2.9, §16.5: the public projects a human keeps as tabs
without being a member, kept on the account as project ids in the order starred, private to
the human, bounded by `max_starred_per_human`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import public_pages
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_invitations import accept, issue, token_of
from tests.test_orgs import team

LIMITS = "/admin/settings/limits"


@pytest.fixture
def make_client(make_client: ClientFactory) -> ClientFactory:
    """Every hub here serves public pages: while it serves none, no project is public (§5.1)."""
    return lambda **kw: make_client(**{"public_pages": True, **kw})


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    """The instance admin, whose public projects others star."""
    return flow.human(make_client, migrated)


@pytest.fixture
def reader(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """A human who is no member of the owner's projects."""
    return flow.human(make_client, migrated, "reader")


def _public(owner: flow.Human, slug: str) -> str:
    return str(flow.project(owner, slug, public_page="on")["id"])


def _page(engine: Engine, project_id: str, on: bool) -> None:
    """The project made public or private, as its own setting does it (§16.9)."""
    with engine.begin() as conn:
        conn.execute(
            update(t.project)
            .where(t.project.c.id == project_id)
            .values(public_page="on" if on else "off")
        )


def _starred(human: flow.Human) -> Any:
    return human.get("/me").json()["member"]["starred"]


def _ids(human: flow.Human) -> list[str]:
    return [entry["id"] for entry in _starred(human)]


def _stored(engine: Engine, human_id: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.human.c.starred).where(t.human.c.id == human_id)).scalar()


def _star(human: flow.Human, ids: list[str]) -> Any:
    return human.patch("/me", {"starred": ids})


def _field(response: Any) -> Any:
    assert response.status_code == 400, response.text
    return response.json()["error"]["details"]["fields"]["starred"]


def test_a_human_stars_public_projects_in_order(owner: flow.Human, reader: flow.Human) -> None:
    alpha, _, gamma = (_public(owner, slug) for slug in ("alpha", "beta", "gamma"))
    assert _starred(reader) == []
    done = _star(reader, [gamma, alpha])
    assert done.status_code == 200, done.text
    expected = [
        {"id": gamma, "full_name": "maintainer/gamma"},
        {"id": alpha, "full_name": "maintainer/alpha"},
    ]
    assert done.json()["member"]["starred"] == expected  # the answer is `/me` as it is now
    assert _starred(reader) == expected
    me = reader.get("/bootstrap").json()["me"]  # a part: its status and the route's body (§5.4)
    assert (me["status"], me["body"]["member"]["starred"]) == (200, expected)
    assert _star(reader, []).status_code == 200
    assert _starred(reader) == []


def test_each_refusal_names_its_reason_and_stores_nothing(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    alpha, beta = _public(owner, "alpha"), _public(owner, "beta")
    closed = str(flow.project(owner, "closed")["id"])  # private (§16.9)
    mine = _public(reader, "mine")
    assert _star(reader, [alpha]).status_code == 200
    assert _field(_star(reader, [beta, beta])) == "duplicate"
    assert _field(_star(reader, [alpha, closed])) == "not_public"
    # An id that names no project answers as a private one: nothing says whether it exists.
    assert _field(_star(reader, ["prj-nothere"])) == "not_public"
    assert _field(_star(reader, [alpha, mine])) == "member"
    assert _field(reader.patch("/me", {"starred": None})) == "required"
    assert _stored(migrated, reader.id) == [alpha]


def test_without_public_pages_no_project_is_public_and_the_stars_wait(
    migrated: Engine, settings: Settings, owner: flow.Human, reader: flow.Human
) -> None:
    """Fail closed (hub/context/persistence.md c0e833f1): with `MAITY_PUBLIC_PAGES` off nothing
    is public for an outsider, so a star is refused as for a private project and a stored one is
    hidden: kept, counted, left out of the read and the export."""
    alpha, beta = _public(owner, "alpha"), _public(owner, "beta")
    assert _star(reader, [alpha]).status_code == 200
    public_pages.configure(replace(settings, public_pages=False))
    assert _field(_star(reader, [alpha, beta])) == "not_public"
    assert _starred(reader) == []
    assert reader.get("/me/export").json()["account"]["starred"] == []
    assert _stored(migrated, reader.id) == [alpha]
    assert _star(reader, []).status_code == 200
    assert _stored(migrated, reader.id) == [alpha]  # a hidden entry stays
    public_pages.configure(replace(settings, public_pages=True))
    assert _ids(reader) == [alpha]


def test_only_a_human_stars(make_client: ClientFactory, owner: flow.Human) -> None:
    flow.project(owner)
    alpha = _public(owner, "alpha")
    agent = flow.agent(make_client, owner)
    refused = agent.patch("/me", {"starred": [alpha]})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    assert "starred" not in agent.get("/me").json()["member"]


def test_the_bound_counts_hidden_entries_and_a_lowered_one_keeps_the_stars(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    a, b, c, d = (_public(owner, slug) for slug in ("a-one", "b-two", "c-three", "d-four"))
    assert owner.patch(LIMITS, {"max_starred_per_human": 2}).status_code == 200
    assert _star(reader, [a, b]).status_code == 200
    over = _star(reader, [a, b, c])
    assert _field(over) == "too_many"
    assert over.json()["error"]["details"]["hidden"] == 0
    _page(migrated, b, on=False)  # b is hidden now, and still counts
    hidden = _star(reader, [a, c])
    assert _field(hidden) == "too_many"
    assert hidden.json()["error"]["details"]["hidden"] == 1
    assert _stored(migrated, reader.id) == [a, b]
    _page(migrated, b, on=True)
    assert owner.patch(LIMITS, {"max_starred_per_human": 3}).status_code == 200
    assert _star(reader, [a, b, c]).status_code == 200
    # Lowered below what the reader holds: nothing goes, a list that adds nothing passes.
    assert owner.patch(LIMITS, {"max_starred_per_human": 1}).status_code == 200
    assert _ids(reader) == [a, b, c]
    assert _star(reader, [c, a, b]).status_code == 200
    assert _field(_star(reader, [c, a, d])) == "too_many"
    assert _star(reader, [c, a]).status_code == 200
    assert _ids(reader) == [c, a]


def test_a_hidden_entry_is_kept_unread_and_in_its_place(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    a, b, c = (_public(owner, slug) for slug in ("a-one", "b-two", "c-three"))
    assert _star(reader, [a, b, c]).status_code == 200
    _page(migrated, b, on=False)
    assert _ids(reader) == [a, c]  # left out of the read
    assert _stored(migrated, reader.id) == [a, b, c]  # and kept
    assert _star(reader, [c, a]).status_code == 200
    assert _stored(migrated, reader.id) == [c, a, b]  # b follows a, the entry it followed
    assert _field(_star(reader, [c, a, b])) == "not_public"  # nobody can name it
    _page(migrated, b, on=True)
    assert _ids(reader) == [c, a, b]  # back where it was
    _page(migrated, b, on=False)
    # The entry b followed leaves: b follows the nearest earlier entry the body keeps.
    assert _star(reader, [c]).status_code == 200
    assert _stored(migrated, reader.id) == [c, b]
    assert _star(reader, []).status_code == 200
    assert _stored(migrated, reader.id) == [b]  # none kept before it: first
    assert _starred(reader) == []


def test_a_hidden_first_entry_stays_first(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    a, b, c = (_public(owner, slug) for slug in ("a-one", "b-two", "c-three"))
    assert _star(reader, [a, b]).status_code == 200
    _page(migrated, a, on=False)
    assert _star(reader, [c, b]).status_code == 200
    assert _stored(migrated, reader.id) == [a, c, b]


def test_an_invitation_drops_the_star_and_a_removed_member_stars_again(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    maity = _public(owner, "maity")  # the project of the invitation helpers
    other = _public(owner, "other")
    assert _star(reader, [other, maity]).status_code == 200
    joined = accept(reader, token_of(issue(owner)))
    assert joined.status_code in (200, 201), joined.text
    assert _stored(migrated, reader.id) == [other]
    assert _field(_star(reader, [other, maity])) == "member"
    left = reader.delete(f"/projects/maintainer/maity/members/{reader.id}")  # leaving (§6.2)
    assert left.status_code == 200, left.text
    # A removed member is no member (`access`): the project may be starred again.
    assert _star(reader, [other, maity]).status_code == 200
    assert _ids(reader) == [other, maity]


def test_an_organisations_new_owner_loses_the_star_of_its_project(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    """The second way a human's membership comes about (`org_projects.keep_owner`)."""
    _, people = team(make_client, migrated, owner)
    admin = people["admin"]
    made = owner.post(
        "/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team", "public_page": "on"}
    )
    assert made.status_code in (200, 201), made.text
    shop = made.json()["id"]
    assert _star(admin, [shop]).status_code == 200
    assert owner.patch(f"/orgs/oz-team/members/{admin.id}", {"role": "owner"}).status_code == 200
    assert _stored(migrated, admin.id) == []
    assert _starred(admin) == []


def test_the_export_holds_the_visible_stars_with_full_names(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    alpha, beta = _public(owner, "alpha"), _public(owner, "beta")
    assert _star(reader, [beta, alpha]).status_code == 200
    exported = reader.get("/me/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["account"]["starred"] == [
        {"id": beta, "full_name": "maintainer/beta"},
        {"id": alpha, "full_name": "maintainer/alpha"},
    ]


def test_the_read_costs_the_same_for_two_stars_and_for_six(
    migrated: Engine, owner: flow.Human, reader: flow.Human
) -> None:
    """`GET /me` is polled once a minute per tab: the stars are checked for all at once."""
    ids = [_public(owner, f"p-{n}") for n in range(6)]

    def read() -> None:
        assert reader.get("/me").status_code == 200

    assert _star(reader, ids[:2]).status_code == 200
    read()  # caches warm
    few = count_statements(migrated, read, async_engines=False)
    assert _star(reader, ids).status_code == 200
    read()
    many = count_statements(migrated, read, async_engines=False)
    assert many == few, (few, many)


def test_the_bound_is_one_to_a_thousand_and_never_unlimited(owner: flow.Human) -> None:
    assert owner.get(LIMITS).json()["max_starred_per_human"] == {"value": 100, "source": "default"}
    for good in (1, 1000):
        got = owner.patch(LIMITS, {"max_starred_per_human": good})
        assert got.json()["max_starred_per_human"] == {"value": good, "source": "admin"}, got.text
    for bad in (0, 1001, "unlimited", True, 2.5):
        refused = owner.patch(LIMITS, {"max_starred_per_human": bad})
        assert refused.status_code == 400, (bad, refused.text)
        assert refused.json()["error"]["details"]["fields"] == {
            "max_starred_per_human": "out_of_range"
        }
    back = owner.patch(LIMITS, {"max_starred_per_human": None})
    assert back.json()["max_starred_per_human"] == {"value": 100, "source": "default"}


def test_the_environment_sets_the_bound_and_wins(
    make_client: ClientFactory, migrated: Engine
) -> None:
    name = "MAITY_MAX_STARRED_PER_HUMAN"
    assert Settings.from_env({name: "7"}).max_starred_per_human == 7
    assert Settings.from_env({name: ""}).max_starred_per_human is None
    for bad in ("0", "1001", "unlimited", "x"):
        with pytest.raises(ConfigError):
            Settings.from_env({name: bad})
    who = flow.human(lambda **kw: make_client(max_starred_per_human=1, **kw), migrated)
    assert who.get(LIMITS).json()["max_starred_per_human"] == {"value": 1, "source": "env"}
    refused = who.patch(LIMITS, {"max_starred_per_human": 5})
    assert refused.json()["error"]["details"]["fields"] == {
        "max_starred_per_human": "set_by_environment"
    }


def test_no_account_override_of_the_bound_yet(owner: flow.Human, reader: flow.Human) -> None:
    """§16.5.1: the hub keeps stars with the instance's bound alone, the override is not built."""
    refused = owner.patch(f"/admin/users/{reader.id}/limits", {"max_starred_per_human": 5})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "max_starred_per_human": "extra_forbidden"
    }
