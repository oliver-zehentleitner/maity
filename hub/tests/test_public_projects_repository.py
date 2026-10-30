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
