"""docs/api.md §6.8: the contract's text stays in the repository — the place on the card,
the section read through the probe, the heading rules, the one read kept."""

from __future__ import annotations

import base64
import threading
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import contract_text, forge, probe
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import REPO, SHA, TOKEN, FakeGitHub

OTHER = "e" * 40
API = """# Maity API

## 6 Cards

### 6.2 Members

Who is in a project.

#### 6.2.1 Roles

Roles in detail.

### 6.20 The project badge

A badge.

## 7 Requests
"""


@pytest.fixture
def settings(settings: Settings, request: pytest.FixtureRequest) -> Settings:
    if "github" in request.fixturenames:
        return replace(
            settings, forge_github_token=TOKEN, forge_instance_namespaces=frozenset({"maintainer"})
        )
    return settings


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    contract_text.forget()
    yield
    contract_text.forget()


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path: fake(path))
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    fake.branch("main", SHA)
    put(fake, "docs/api.md", API)
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


def put(fake: FakeGitHub, path: str, text: str | bytes, ref: str = SHA) -> None:
    data = text.encode() if isinstance(text, str) else text
    fake.answers[f"/repos/acme/maity/contents/{path}?ref={ref}"] = {
        "type": "file",
        "size": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode(),
    }


def contract(owner: flow.Human, **place: Any) -> str:
    response = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "A contract", "kind": "contract", "contract": place},
    )
    assert response.status_code == 201, response.text
    card_id: str = response.json()["id"]
    return card_id


def read(owner: flow.Human, card_id: str) -> Any:
    return owner.get(f"/projects/maintainer/maity/tasks/{card_id}/contract")


def error(response: Any) -> tuple[int, str, Any]:
    body = response.json()["error"]
    return response.status_code, body["code"], (body.get("details") or {}).get("fields")


# --- the place on the card ----------------------------------------------------------------


def test_path_and_section_are_set_and_checked(owner: flow.Human) -> None:
    card_id = contract(owner, section="6.2")
    url = f"/projects/maintainer/maity/tasks/{card_id}"
    shown = owner.get(url).json()["contract"]
    assert (shown["path"], shown["section"]) == ("docs/api.md", "6.2")
    moved = owner.patch(url, {"contract": {"path": "docs/agents.md", "section": "2.6.2"}})
    assert moved.status_code == 200, moved.text
    assert moved.json()["contract"]["path"] == "docs/agents.md"
    cleared = owner.patch(url, {"contract": {"section": None}}).json()["contract"]
    assert (cleared["path"], cleared["section"]) == ("docs/agents.md", None)
    for path in (
        "/etc/passwd",
        "../x.md",
        "docs/../x.md",
        "https://e.com/a.md",
        "a\\b",
        "a//b",
        "",
    ):
        refused = owner.patch(url, {"contract": {"path": path}})
        assert error(refused) == (400, "invalid", {"contract.path": "not_a_path"}), path
    assert error(owner.patch(url, {"contract": {"path": None}}))[2] == {
        "contract.path": "not_a_path"
    }
    assert error(owner.patch(url, {"contract": {"section": "6 2"}}))[2] == {
        "contract.section": "invalid"
    }
    created = owner.post(
        "/projects/maintainer/maity/tasks",
        {"title": "x", "kind": "contract", "contract": {"path": "/abs.md"}},
    )
    assert error(created)[2] == {"contract.path": "not_a_path"}


def test_only_an_editor_moves_the_place_not_the_arbiter_alone(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    arbiter = flow.agent(make_client, owner)
    card_id = contract(owner, arbiter=arbiter.id, section="6.2")
    url = f"/projects/maintainer/maity/tasks/{card_id}"
    assert arbiter.patch(url, {"contract": {"section": "6.20"}}).status_code == 403
    assert arbiter.patch(url, {"contract": {"state": "final"}}).status_code == 200


def _history(owner: flow.Human, card_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = owner.get(
        f"/projects/maintainer/maity/tasks/{card_id}/history"
    ).json()["items"]
    return [i for i in items if i["field"].startswith("contract.")]


def _last_update(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated").order_by(t.event.c.seq.desc())
        ).first()


def test_a_changed_place_is_in_the_history_and_its_event(
    owner: flow.Human, migrated: Engine
) -> None:
    card_id = contract(owner, section="6.2")
    url = f"/projects/maintainer/maity/tasks/{card_id}"
    moved = owner.patch(url, {"contract": {"path": "docs/agents.md", "section": "2.6"}})
    assert moved.status_code == 200, moved.text
    entries = {e["field"]: e for e in _history(owner, card_id)}
    assert set(entries) == {"contract.path", "contract.section"}
    assert (entries["contract.path"]["before"], entries["contract.path"]["after"]) == (
        "docs/api.md",
        "docs/agents.md",
    )
    assert (entries["contract.section"]["before"], entries["contract.section"]["after"]) == (
        "6.2",
        "2.6",
    )
    event = _last_update(migrated)
    assert sorted(event.payload["history"]) == sorted(e["id"] for e in entries.values())
    assert event.payload["fields"] == ["contract"]
    assert event.payload["contract"]["section"] == "2.6"
    owner.patch(url, {"contract": {"section": None}})
    cleared = _history(owner, card_id)[0]
    assert (cleared["field"], cleared["before"], cleared["after"]) == (
        "contract.section",
        "2.6",
        None,
    )


def test_the_same_place_again_is_no_change(owner: flow.Human, migrated: Engine) -> None:
    card_id = contract(owner, section="6.2")
    url = f"/projects/maintainer/maity/tasks/{card_id}"
    seq = _last_update(migrated)
    again = owner.patch(url, {"contract": {"path": "docs/api.md", "section": "6.2"}})
    assert again.status_code == 200, again.text
    assert _history(owner, card_id) == []
    assert _last_update(migrated) == seq  # no task_updated either


# --- the read -----------------------------------------------------------------------------


def test_the_section_is_read_at_one_commit(owner: flow.Human, github: FakeGitHub) -> None:
    response = read(owner, contract(owner, section="6.2"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "path",
        "section",
        "ref",
        "heading",
        "text",
        "url",
        "truncated",
        "fetched_at",
    }
    assert (body["path"], body["section"], body["ref"]) == ("docs/api.md", "6.2", SHA)
    assert body["heading"] == "### 6.2 Members"
    # Its subsections belong to it; the next heading of its level ends it.
    assert (
        body["text"]
        == "### 6.2 Members\n\nWho is in a project.\n\n#### 6.2.1 Roles\n\nRoles in detail.\n"
    )
    assert body["url"] == f"https://github.com/acme/maity/blob/{SHA}/docs/api.md"
    assert body["truncated"] is False
    assert f"/repos/acme/maity/contents/docs/api.md?ref={SHA}" in github.calls


def test_a_card_without_a_section_or_of_another_kind(owner: flow.Human, github: FakeGitHub) -> None:
    assert error(read(owner, contract(owner))) == (404, "not_found", {"contract.section": "unset"})
    plain = owner.post("/projects/maintainer/maity/tasks", {"title": "x"}).json()["id"]
    assert error(read(owner, plain))[2] == {"contract": "contracts_only"}
    assert read(owner, "ctr-nothing").status_code == 404


def test_without_a_token_it_is_not_configured(owner: flow.Human) -> None:
    response = read(owner, contract(owner, section="6.2"))
    assert error(response)[:2] == (409, "probe_not_configured")


def test_an_unanswering_forge_is_unavailable(owner: flow.Human, github: FakeGitHub) -> None:
    github.answers["/repos/acme/maity/branches/main"] = forge.ForgeUnavailableError("down")
    assert error(read(owner, contract(owner, section="6.2")))[:2] == (503, "probe_unavailable")


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("missing", (404, "not_found", {"contract.path": "not_found_on_forge"})),
        ("large", (400, "invalid", {"contract.path": "too_large"})),
        ("binary", (400, "invalid", {"contract.path": "not_text"})),
        ("absent", (404, "not_found", {"contract.section": "not_found_in_file"})),
        ("twice", (404, "not_found", {"contract.section": "ambiguous_in_file"})),
    ],
)
def test_nothing_is_shown_when(
    owner: flow.Human, github: FakeGitHub, setup: str, expected: tuple[int, str, Any]
) -> None:
    path, section = "docs/api.md", "6.2"
    if setup == "missing":
        path = "docs/moved.md"
        github.answers[f"/repos/acme/maity/contents/{path}?ref={SHA}"] = None
    elif setup == "large":
        github.answers[f"/repos/acme/maity/contents/{path}?ref={SHA}"] = {
            "type": "file",
            "size": contract_text.FILE_CAP + 1,
        }
    elif setup == "binary":
        put(github, path, b"## 6.2 \xff\xfe\n")
    elif setup == "absent":
        section = "9.9"
    elif setup == "twice":
        put(github, path, "## 6.2 One\n\n## 6.2. Two\n")
    assert error(read(owner, contract(owner, path=path, section=section))) == expected


def test_a_moved_file_or_a_new_commit_is_never_answered_from_an_older_read(
    owner: flow.Human, github: FakeGitHub
) -> None:
    card_id = contract(owner, section="6.2")
    assert read(owner, card_id).json()["ref"] == SHA
    reads = len([c for c in github.calls if "/contents/" in c])
    assert read(owner, card_id).status_code == 200  # within 60 s: the kept read
    assert len([c for c in github.calls if "/contents/" in c]) == reads
    # A new commit on the default branch, seen once the kept head is past HEAD_AGE: read
    # again, at that commit.
    github.branch("main", OTHER)
    age_heads(contract_text.HEAD_AGE)
    put(github, "docs/api.md", "## 6.2 Members, rewritten\n", ref=OTHER)
    again = read(owner, card_id).json()
    assert (again["ref"], again["heading"]) == (OTHER, "## 6.2 Members, rewritten")
    # A changed path: the card's place at the call, never the older one.
    owner.patch(
        f"/projects/maintainer/maity/tasks/{card_id}", {"contract": {"path": "docs/moved.md"}}
    )
    github.answers[f"/repos/acme/maity/contents/docs/moved.md?ref={OTHER}"] = None
    assert error(read(owner, card_id))[2] == {"contract.path": "not_found_on_forge"}


def age_heads(seconds: float) -> None:
    """Every kept branch head read `seconds` earlier than it was."""
    for key, (at, head) in list(contract_text._heads.items()):
        contract_text._heads[key] = (at - seconds, head)


def test_concurrent_reads_ask_the_forge_once(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def file_at(_self: Any, repository: str, path: str, ref: str, cap: int) -> bytes:
        calls.append(path)
        started.set()
        release.wait(5)
        return API.encode()

    monkeypatch.setattr(forge.Forge, "branch", lambda *_a: {"head_sha": SHA, "found": True})
    monkeypatch.setattr(forge.Forge, "file_at", file_at)
    fg = forge.Forge(TOKEN)
    results: list[dict[str, Any]] = []

    def call() -> None:
        results.append(contract_text.read(fg, "acme/maity", "main", "docs/api.md", "6.2"))

    first = threading.Thread(target=call)
    first.start()
    started.wait(5)
    second = threading.Thread(target=call)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert calls == ["docs/api.md"] and len(results) == 2 and results[0] == results[1]


def test_a_read_the_forge_does_not_answer_leaves_no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate of a read that raised is gone too: a new commit is a new key, and every
    failed read would otherwise leave its lock behind for good."""

    def file_at(_self: Any, repository: str, path: str, ref: str, cap: int) -> bytes:
        raise forge.ForgeUnavailableError("the forge did not answer: TimeoutError")

    monkeypatch.setattr(forge.Forge, "branch", lambda *_a: {"head_sha": SHA, "found": True})
    monkeypatch.setattr(forge.Forge, "file_at", file_at)
    for _ in range(3):
        with pytest.raises(forge.ForgeUnavailableError):
            contract_text.read(forge.Forge(TOKEN), "acme/maity", "main", "docs/api.md", "6.2")
    assert contract_text._pending == {}


# --- the heading rules --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "heading"),
    [
        ("6.2", "### 6.2 Members"),
        ("6.20", "### 6.20 The project badge"),
        ("6.2.1", "#### 6.2.1 Roles"),
        ("6", "## 6 Cards"),
    ],
)
def test_a_section_is_a_whole_token(section: str, heading: str) -> None:
    assert contract_text.find_section(API, section).heading == heading


def test_a_period_after_the_number_and_a_closing_sequence() -> None:
    found = contract_text.find_section("## 6.2. Members ##\ntext\n## 6.3\n", "6.2")
    assert found.heading == "## 6.2. Members ##" and found.text == "## 6.2. Members ##\ntext\n"


def test_levels_one_five_and_six_are_no_section() -> None:
    for marks in ("#", "#####", "######"):
        with pytest.raises(contract_text.ContractTextError) as raised:
            contract_text.find_section(f"{marks} 6.2 Members\n", "6.2")
        assert raised.value.reason == "not_found_in_file"


def test_fenced_code_is_skipped() -> None:
    text = (
        "```md\n## 6.2 Example\n```\n\n"
        "~~~~\n## 6.2 Again\n~~~\n## 6.2 Still code\n~~~~\n"  # ~~~ is too short to close ~~~~
        "## 6.2 Real\nbody\n"
    )
    found = contract_text.find_section(text, "6.2")
    assert found.heading == "## 6.2 Real" and found.text == "## 6.2 Real\nbody\n"
    # A heading inside code does not end a section either.
    found = contract_text.find_section("## 6.2 Real\n```\n## 6.3 code\n```\nafter\n", "6.2")
    assert found.text.endswith("after\n")


def test_the_text_is_cut_on_a_character_boundary() -> None:
    body = "ä" * contract_text.TEXT_CAP  # two bytes each
    found = contract_text.find_section(f"## 6.2 Big\n{body}\n", "6.2")
    assert found.truncated is True
    assert len(found.text.encode()) <= contract_text.TEXT_CAP
    assert found.text.startswith("## 6.2 Big\n") and found.text.endswith("ä")


# --- the default branch's head, kept ------------------------------------------------------


class Heads:
    """`forge.Forge.branch` counted per (token, repository, branch); `down` makes it fail
    as a spent budget does."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str | None, str, str]] = []
        self.down = False
        heads = self

        def branch(fg: forge.Forge, repository: str, name: str) -> dict[str, Any]:
            if heads.down:
                raise forge.ForgeUnavailableError("spent", rate_limited=True)
            heads.calls.append((fg.token, repository, name))
            return {"name": name, "head_sha": SHA, "found": True}

        monkeypatch.setattr(forge.Forge, "branch", branch)
        monkeypatch.setattr(forge.Forge, "file_at", lambda *_a: API.encode())


def section(fg: forge.Forge, repository: str = "acme/maity", branch: str = "main") -> Any:
    return contract_text.read(fg, repository, branch, "docs/api.md", "6.2")


def test_two_reads_within_the_head_age_ask_for_the_branch_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heads = Heads(monkeypatch)
    fg = forge.Forge(TOKEN)
    assert section(fg) == section(fg)
    assert heads.calls == [(TOKEN, "acme/maity", "main")]


def test_a_kept_head_answers_while_the_forge_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """A spent budget of the source does not refuse a read that a kept head and a kept
    text answer: nothing is asked of the forge."""
    heads = Heads(monkeypatch)
    fg = forge.Forge(TOKEN)
    first = section(fg)
    heads.down = True
    assert section(fg) == first
    age_heads(contract_text.HEAD_AGE)
    with pytest.raises(forge.ForgeUnavailableError):
        section(fg)  # past its age the head is asked for again, and that read is not kept
    heads.down = False
    assert section(fg) == first


@pytest.mark.parametrize(
    ("token", "repository", "branch"),
    [
        ("other-token", "acme/maity", "main"),
        (TOKEN, "acme/other", "main"),
        (TOKEN, "acme/maity", "dev"),
    ],
)
def test_another_reader_repository_or_branch_shares_no_head(
    monkeypatch: pytest.MonkeyPatch, token: str, repository: str, branch: str
) -> None:
    heads = Heads(monkeypatch)
    section(forge.Forge(TOKEN))
    section(forge.Forge(token), repository, branch)
    assert heads.calls == [(TOKEN, "acme/maity", "main"), (token, repository, branch)]


def test_a_head_past_its_age_is_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    heads = Heads(monkeypatch)
    fg = forge.Forge(TOKEN)
    section(fg)
    age_heads(contract_text.HEAD_AGE - 1)
    section(fg)
    assert len(heads.calls) == 1, "within its age"
    age_heads(1)
    section(fg)
    assert len(heads.calls) == 2, "past its age"


def test_the_kept_heads_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    heads = Heads(monkeypatch)
    monkeypatch.setattr(contract_text, "HEADS_KEPT", 3)
    fg = forge.Forge(TOKEN)
    for n in range(5):
        section(fg, branch=f"b{n}")
    assert len(contract_text._heads) == 3
    assert [key[2] for key in contract_text._heads] == ["b2", "b3", "b4"]
    section(fg, branch="b0")  # dropped: read again
    assert len(heads.calls) == 6
