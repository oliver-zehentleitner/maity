"""docs/api.md §16.9, "Repository visibility": the repository's URL is on a project's page only
while the forge's last answer said it is public; no answer counts as private."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import forge, probe
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, FakeGitHub, github, settings  # noqa: F401  (fixtures)

PATH = "/maintainer/maity"
URL = REPO["url"]


@pytest.fixture
def public(
    make_client: ClientFactory,
    migrated: Engine,
    github: FakeGitHub,  # noqa: F811
) -> flow.Human:
    owner = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated)
    flow.project(owner, "maity", repository=REPO)
    assert owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    return owner


def page(make_client: ClientFactory) -> str:
    got = make_client(public_pages=True).get(PATH)
    assert got.status_code == 200
    return str(got.text)


def stored(engine: Engine) -> bool | None:
    with engine.connect() as conn:
        value = conn.execute(select(t.project.c.repository_public)).scalar_one()
    return None if value is None else bool(value)


def look(engine: Engine) -> None:
    with engine.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    probe.observe_visibility(engine, READER, project_id)


def test_a_repository_the_hub_has_not_looked_at_is_not_on_the_page(
    make_client: ClientFactory, migrated: Engine, public: flow.Human
) -> None:
    assert stored(migrated) is None
    assert URL not in page(make_client)


def test_the_url_is_on_the_page_while_the_forge_says_public(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
) -> None:
    github.answers["/repos/acme/maity"] = {"full_name": "acme/maity", "private": False}
    look(migrated)
    assert stored(migrated) is True
    text = page(make_client)
    assert f'<a href="{URL}" rel="nofollow ugc">{URL}</a>' in text
    # it turns private: the page loses the URL in the same round
    github.answers["/repos/acme/maity"] = {"full_name": "acme/maity", "private": True}
    look(migrated)
    assert stored(migrated) is False
    assert URL not in page(make_client)


@pytest.mark.parametrize(
    "answer",
    [None, {"full_name": "acme/maity"}, {"private": "yes"}, forge.ForgeUnavailableError("down")],
)
def test_an_answer_that_does_not_say_public_counts_as_private(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
    answer: Any,
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    look(migrated)
    assert URL in page(make_client)
    github.answers["/repos/acme/maity"] = answer
    look(migrated)
    assert stored(migrated) is False
    assert URL not in page(make_client)


def test_a_project_without_a_page_is_not_looked_at(
    migrated: Engine, public: flow.Human, github: FakeGitHub  # noqa: F811
) -> None:
    public.patch("/projects/maintainer/maity", {"public_page": "off"})
    github.calls.clear()
    look(migrated)
    assert github.calls == [] and stored(migrated) is None


def test_a_new_repository_forgets_what_was_known(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    look(migrated)
    assert URL in page(make_client)
    changed = public.patch(
        "/projects/maintainer/maity",
        {"repository": {"url": "https://github.com/acme/other", "default_branch": "main"}},
    )
    assert changed.status_code == 200, changed.text
    assert stored(migrated) is None  # the new one is not looked at yet: private
    assert "acme/other" not in page(make_client)


def test_the_sweep_looks_at_a_project_with_a_page(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    probe.sweep(migrated, READER)
    assert stored(migrated) is True
    assert URL in page(make_client)


def test_a_repository_that_turned_private_leaves_the_page_even_when_another_read_fails(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    probe.sweep(migrated, READER)
    assert URL in page(make_client)

    def down(*args: Any) -> None:
        raise forge.ForgeUnavailableError("rate limited")

    monkeypatch.setattr("maity_hub.probe.observe_release", down)
    monkeypatch.setattr("maity_hub.probe.observe_links", down)
    github.answers["/repos/acme/maity"] = {"private": True}
    probe.sweep(migrated, READER)  # the round ends at the failed read, after the visibility
    assert stored(migrated) is False
    assert URL not in page(make_client)


def test_the_forge_reads_the_repository_public_only_on_private_false(
    github: FakeGitHub,  # noqa: F811
) -> None:
    reader = forge.Forge("t")
    github.answers["/repos/acme/maity"] = {"private": False}
    assert reader.repository_public("acme/maity") is True
    github.answers["/repos/acme/maity"] = {"private": True}
    assert reader.repository_public("acme/maity") is False
    github.answers["/repos/acme/maity"] = forge.NotCoveredError("private_without_grant")
    assert reader.repository_public("acme/maity") is False


def test_a_project_the_hub_can_no_longer_read_is_still_looked_at_and_turns_private(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    probe.sweep(migrated, READER)
    assert URL in page(make_client)
    # the hub has no source for the repository any more: the other reads skip it, this one does not
    monkeypatch.setattr(forge.Forge, "configured_for", lambda self, url: False)
    github.answers["/repos/acme/maity"] = forge.NotCoveredError("no_grant")
    probe.sweep(migrated, READER)
    assert stored(migrated) is False
    assert URL not in page(make_client)


def test_an_answer_for_a_repository_that_changed_meanwhile_is_dropped(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    github.answers["/repos/acme/other"] = {"private": False}  # the PATCH looks at it too
    original = forge.Forge.repository_public
    moves = [True]  # once: the PATCH's own look at the new repository passes through here too

    def patched_meanwhile(self: forge.Forge, repository: str) -> bool:
        found = original(self, repository)
        if not moves:
            return found
        moves.pop()
        moved = public.patch(
            "/projects/maintainer/maity",
            {"repository": {"url": "https://github.com/acme/other", "default_branch": "main"}},
        )
        assert moved.status_code == 200, moved.text
        return found

    monkeypatch.setattr(forge.Forge, "repository_public", patched_meanwhile)
    look(migrated)
    assert stored(migrated) is None  # the answer was for the old repository
    assert "acme/other" not in page(make_client)


def test_the_hub_s_own_token_asks_once_and_a_private_answer_drops_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    answer: dict[str, Any] = {"private": False}

    def send(self: forge.Forge, path: str, query: Any = None) -> Any:
        asked.append(path)
        return answer

    monkeypatch.setattr(forge.Forge, "_send", send)
    reader = forge.Forge("t-cache")
    assert reader.repository_public("acme/maity") is True
    assert asked == ["/repos/acme/maity"]  # one request, not the check and the read
    reader._call("/repos/acme/maity")  # a read of the other kind fills the visibility cache
    key = next(k for k in forge._public if k[1] == "acme/maity")
    answer["private"] = True
    assert reader.repository_public("acme/maity") is False
    assert key not in forge._public  # the stale "public" is gone
    answer["private"] = False
    assert reader.repository_public("acme/maity") is True  # fresh, not the ten-minute cache


def test_what_the_forge_said_is_forgotten_when_the_page_goes_off_and_asked_again_when_it_is_on(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
) -> None:
    github.answers["/repos/acme/maity"] = {"private": False}
    look(migrated)
    assert URL in page(make_client)
    assert public.patch("/projects/maintainer/maity", {"public_page": "off"}).status_code == 200
    assert stored(migrated) is None
    # the repository turns private while the page is off; switching it on shows no URL
    github.answers["/repos/acme/maity"] = {"private": True}
    assert public.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    assert URL not in page(make_client)
    look(migrated)
    assert stored(migrated) is False and URL not in page(make_client)


def test_a_transfer_forgets_the_answer_of_the_old_owner(
    make_client: ClientFactory,
    migrated: Engine,
    public: flow.Human,
    github: FakeGitHub,  # noqa: F811
) -> None:
    from tests import factory

    anna = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=anna.id)
    github.answers["/repos/acme/maity"] = {"private": False}
    look(migrated)
    assert stored(migrated) is True
    filed = public.post("/projects/maintainer/maity/transfer", {"to": anna.id})
    assert filed.status_code == 202, filed.text
    done = anna.post(
        f"/projects/maintainer/maity/requests/{filed.json()['id']}/answer", {"reply_id": "go"}
    )
    assert done.status_code == 200, done.text
    assert stored(migrated) is None
    assert anna.patch("/projects/anna/maity", {"public_page": "on"}).status_code == 200
    got = make_client(public_pages=True).get("/anna/maity")
    assert got.status_code == 200 and URL not in got.text
