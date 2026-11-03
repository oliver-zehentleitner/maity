"""docs/api.md §6.13 card links, §6.15 the edit history, §6.16 notes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock, forge, probe
from maity_hub import tables as t
from maity_hub.board import links, notes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

REPOSITORY = "https://github.com/oliver-zehentleitner/maity"
ISSUE = f"{REPOSITORY}/issues/41"
PULL = f"{REPOSITORY}/pull/7"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, repository={"url": REPOSITORY})
    return human


def events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def link(who: Any, card: dict[str, Any], **body: Any) -> Any:
    return who.post(f"/projects/maintainer/maity/tasks/{card['id']}/links", body)


def fields_of(response: Any) -> dict[str, str]:
    assert response.status_code == 400, response.text
    found: dict[str, str] = response.json()["error"]["details"]["fields"]
    return found


def history(who: Any, card: dict[str, Any]) -> list[dict[str, Any]]:
    response = who.get(f"/projects/maintainer/maity/tasks/{card['id']}/history")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


# --- links ----------------------------------------------------------------------------------


def test_a_forge_link_is_parsed_by_the_hub_and_changes_the_card(
    owner: flow.Human, migrated: Engine
) -> None:
    card = task(owner)
    response = link(owner, card, kind="issue", forge_url=ISSUE + "/")
    assert response.status_code == 201, response.text
    shown = response.json()
    assert {k: v for k, v in shown.items() if k not in ("id", "added_at")} == {
        "kind": "issue",
        "forge_url": ISSUE,
        "forge": "github",
        "repository": "oliver-zehentleitner/maity",
        "number": 41,
        "observed": None,
        "added_by": owner.id,
    }
    assert shown["id"].startswith("lnk-")
    view = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()
    assert view["links"] == [shown]
    updated = events(migrated, "task_updated")[-1]
    entry = history(owner, card)[0]
    assert updated.payload["fields"] == ["links"]
    assert updated.payload["links"] == {"added": shown}
    assert updated.payload["history"] == [entry["id"]]
    assert (entry["field"], entry["before"], entry["after"]) == ("links", None, shown)


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        (
            {"kind": "issue", "forge_url": "http://github.com/oliver-zehentleitner/maity/issues/1"},
            {"forge_url": "not_a_forge_url"},
        ),
        ({"kind": "issue", "forge_url": ISSUE + "?x=1"}, {"forge_url": "not_a_forge_url"}),
        ({"kind": "issue", "forge_url": ISSUE + "#c"}, {"forge_url": "not_a_forge_url"}),
        (
            {
                "kind": "issue",
                "forge_url": "https://u@github.com/oliver-zehentleitner/maity/issues/1",
            },
            {"forge_url": "not_a_forge_url"},
        ),
        ({"kind": "pr", "forge_url": ISSUE}, {"forge_url": "kind_mismatch"}),
        (
            {"kind": "issue", "forge_url": "https://github.com/someone/maity/issues/1"},
            {"forge_url": "foreign_repository"},
        ),
        (
            {"kind": "issue", "forge_url": "https://gitlab.com/a/b/issues/1"},
            {"forge_url": "not_a_forge_url"},
        ),
        ({"kind": "issue", "forge_url": ISSUE, "title": "mine"}, {"title": "read_only"}),
        ({"kind": "url", "url": "http://example.com"}, {"url": "not_https"}),
        ({"kind": "url", "url": "https://a:b@example.com"}, {"url": "user_info"}),
        ({"kind": "wiki", "url": "https://example.com"}, {"kind": "unknown"}),
    ],
)
def test_a_link_the_contract_refuses_is_invalid(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    assert fields_of(link(owner, task(owner), **body)) == fields


def test_another_repository_of_the_owner_and_a_url_link_are_accepted(owner: flow.Human) -> None:
    card = task(owner)
    other = link(
        owner, card, kind="pr", forge_url="https://github.com/oliver-zehentleitner/other/pull/2"
    )
    assert other.status_code == 201, other.text
    plain = link(owner, card, kind="url", url="https://keepthewhy.com/linting/", label="docs")
    assert plain.status_code == 201, plain.text
    assert {k: plain.json()[k] for k in ("kind", "url", "label")} == {
        "kind": "url",
        "url": "https://keepthewhy.com/linting/",
        "label": "docs",
    }
    again = link(owner, card, kind="url", url="https://keepthewhy.com/linting/")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_linked"
    assert again.json()["error"]["details"]["link"]["id"] == plain.json()["id"]


def test_a_project_without_a_repository_takes_no_forge_link(
    make_client: ClientFactory, migrated: Engine
) -> None:
    human = flow.human(make_client, migrated)
    flow.project(human)
    assert fields_of(link(human, task(human), kind="issue", forge_url=ISSUE)) == {
        "forge_url": "foreign_repository"
    }


def test_a_card_holds_at_most_twenty_links(owner: flow.Human) -> None:
    card = task(owner)
    for n in range(links.MAX_LINKS):
        assert link(owner, card, kind="url", url=f"https://example.com/{n}").status_code == 201
    assert fields_of(link(owner, card, kind="url", url="https://example.com/x")) == {
        "links": "too_many"
    }


def test_who_removes_a_link(owner: flow.Human, make_client: ClientFactory) -> None:
    adder = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    card = task(owner)
    added = link(adder, card, kind="url", url="https://example.com/a").json()
    path = f"/projects/maintainer/maity/tasks/{card['id']}/links/{added['id']}"
    refused = other.client.delete(f"/api/v1{path}", headers=other.auth)
    assert refused.status_code == 403
    removed = adder.client.delete(f"/api/v1{path}", headers=adder.auth)
    assert removed.status_code == 200 and removed.json() == added
    entry = history(owner, card)[0]
    assert (entry["field"], entry["before"], entry["after"]) == ("links", added, None)
    # The card's creator removes any link on it.
    second = link(adder, card, kind="url", url="https://example.com/b").json()
    assert (
        owner.delete(
            f"/projects/maintainer/maity/tasks/{card['id']}/links/{second['id']}"
        ).status_code
        == 200
    )
    assert owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"] == []


def test_a_closed_project_refuses_a_new_link_and_lets_one_go(owner: flow.Human) -> None:
    card = task(owner)
    added = link(owner, card, kind="url", url="https://example.com/a").json()
    owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    closed = link(owner, card, kind="url", url="https://example.com/b")
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "project_closed"
    gone = owner.delete(f"/projects/maintainer/maity/tasks/{card['id']}/links/{added['id']}")
    assert gone.status_code == 200


def test_a_project_in_review_takes_links_without_a_reason(owner: flow.Human) -> None:
    card = task(owner)
    owner.patch("/projects/maintainer/maity", {"state": "review", "reason": "release"})
    assert link(owner, card, kind="url", url="https://example.com/a").status_code == 201


# --- history ----------------------------------------------------------------------------------


def test_a_new_card_has_one_created_entry_and_its_event_carries_no_body(
    owner: flow.Human, migrated: Engine
) -> None:
    card = task(
        owner, body="the why", label="feature", links=[{"kind": "issue", "forge_url": ISSUE}]
    )
    assert [lnk["number"] for lnk in card["links"]] == [41]
    entries = history(owner, card)
    assert len(entries) == 1
    created = entries[0]
    assert created["field"] == "created" and created["before"] is None
    assert created["after"]["body"] == "the why" and created["after"]["label"] == "feature"
    assert created["after"]["links"] == card["links"]
    assert created["actor"] == {
        "member_id": owner.id,
        "handle": "maintainer",
        "kind": "human",
        "session_id": None,
    }
    event = events(migrated, "task_created")[-1]
    assert "body" not in event.payload
    assert event.payload["history"] == [created["id"]]
    assert "body" in event.payload["fields"] and "links" in event.payload["fields"]


def test_a_patch_writes_one_entry_per_field_and_its_event_names_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = task(owner)
    card = task(owner, title="Old", body="line one\nline two")
    response = owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}",
        {
            "title": "New",
            "body": "line one\nline 2",
            "label": "fix",
            "assigned_to": agent.id,
            "depends_on": [other["id"]],
        },
    )
    assert response.status_code == 200, response.text
    entries = {e["field"]: e for e in history(owner, card) if e["field"] != "created"}
    assert set(entries) == {"title", "body", "label", "assigned_to", "depends_on"}
    assert len({e["at"] for e in entries.values()}) == 1
    assert entries["title"]["diff"] == "@@ -1 +1 @@\n-Old\n+New"
    assert entries["body"]["before"] == "line one\nline two"
    assert entries["body"]["after"] == "line one\nline 2"
    assert "-line two" in entries["body"]["diff"] and entries["label"]["diff"] is None
    assert (entries["assigned_to"]["before"], entries["assigned_to"]["after"]) == (None, agent.id)
    assert (entries["depends_on"]["before"], entries["depends_on"]["after"]) == ([], [other["id"]])
    event = events(migrated, "task_updated")[-1]
    assert event.payload["fields"] == sorted(entries)
    assert sorted(event.payload["history"]) == sorted(e["id"] for e in entries.values())
    assert "body" not in event.payload and event.payload["title"] == "New"


def test_a_move_is_layout_not_history(owner: flow.Human, migrated: Engine) -> None:
    first, second = task(owner), task(owner)
    moved = owner.post(
        f"/projects/maintainer/maity/tasks/{second['id']}/move", {"before": first["id"]}
    )
    assert moved.status_code == 200, moved.text
    event = events(migrated, "task_updated")[-1]
    assert event.payload["fields"] == ["rank"] and event.payload["history"] == []
    assert [e["field"] for e in history(owner, second)] == ["created"]


def test_assigning_is_recorded(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    assert (
        owner.post(
            f"/projects/maintainer/maity/tasks/{card['id']}/assign", {"assignee": agent.id}
        ).status_code
        == 200
    )
    entry = history(owner, card)[0]
    assert (entry["field"], entry["before"], entry["after"]) == ("assigned_to", None, agent.id)


def test_the_history_pages_newest_first(owner: flow.Human) -> None:
    card = task(owner)
    for n in range(3):
        owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"title": f"T{n}"})
    first = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}/history?limit=2").json()
    assert [e["after"] for e in first["items"]] == ["T2", "T1"]
    rest = owner.get(
        f"/projects/maintainer/maity/tasks/{card['id']}/history?limit=2&cursor={first['next_cursor']}"
    ).json()
    assert [e["field"] for e in rest["items"]] == ["title", "created"]
    assert rest["next_cursor"] is None


def test_a_human_redacts_a_history_entry_and_the_events_values(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner, role="admin")
    card = task(owner)
    owner.patch(
        f"/projects/maintainer/maity/tasks/{card['id']}", {"title": "secret-ish", "label": "fix"}
    )
    entry = next(e for e in history(owner, card) if e["field"] == "title")
    path = f"/projects/maintainer/maity/tasks/{card['id']}/history/{entry['id']}/redact"
    refused = agent.post(path, {"reason": "leak"})
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    done = owner.post(path, {"reason": "leak"})
    assert done.status_code == 200, done.text
    shown = done.json()
    assert shown["redacted"] is True and shown["before"]["reason"] == "leak"
    assert shown["after"] == shown["before"] == shown["diff"]
    assert (shown["id"], shown["field"], shown["actor"]["member_id"]) == (
        entry["id"],
        "title",
        owner.id,
    )
    event = events(migrated, "task_updated")[-1]
    assert event.payload["title"]["redacted"] is True  # the same value in the write's event
    assert event.payload["label"] == "fix" and event.payload["history"]
    notice = events(migrated, "event_redacted")
    assert len(notice) == 1
    assert notice[0].payload == {"history_id": entry["id"], "task_id": card["id"], "reason": "leak"}
    assert notice[0].audience == ["trust:owner", "trust:admin"]
    # Again: answered as it is, no second notice.
    assert owner.post(path, {"reason": "again"}).json()["before"]["reason"] == "leak"
    assert len(events(migrated, "event_redacted")) == 1


# --- notes ------------------------------------------------------------------------------------


def note(who: Any, card: dict[str, Any], body: str = "a finding") -> Any:
    return who.post(f"/projects/maintainer/maity/tasks/{card['id']}/notes", {"body": body})


def test_a_note_never_changes_the_card_and_tells_holder_creator_and_mentioned(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    writer = flow.agent(make_client, owner)
    card = task(owner, body="as written")
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    response = note(writer, card, "the CLI needs `--no-code` too, @maintainer")
    assert response.status_code == 201, response.text
    shown = response.json()
    assert shown["state"] == "open" and shown["resolution"] is None
    assert shown["author"] == {
        "member_id": writer.id,
        "handle": shown["author"]["handle"],
        "kind": "agent",
    }
    assert [m["member_id"] for m in shown["mentions"]] == [owner.id]
    view = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()
    assert view["body"] == "as written" and view["notes"] == {"open": 1, "total": 1}
    added = events(migrated, "note_added")[-1]
    assert added.audience == [f"member:{holder.id}", f"member:{owner.id}"]
    assert added.payload["note"] == shown
    assert added.payload["task"] == {"id": card["id"], "title": "A card", "status": "in_progress"}
    assert [e["field"] for e in history(owner, card)] == ["created"]  # no history


def test_the_creator_resolves_a_note_and_the_holder_does_not(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    creator = flow.agent(make_client, owner)
    holder = flow.agent(make_client, owner)
    card = task(creator)
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    posted = note(owner, card).json()
    path = f"/projects/maintainer/maity/tasks/{card['id']}/notes/{posted['id']}/resolve"
    assert holder.post(path, {"state": "dismissed"}).status_code == 403
    done = creator.post(path, {"state": "incorporated", "reason": "in the body now"})
    assert done.status_code == 200, done.text
    assert done.json()["state"] == "incorporated"
    assert done.json()["resolution"]["by"] == creator.id
    again = creator.post(path, {"state": "dismissed"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_transition"
    resolved = events(migrated, "note_resolved")[-1]
    assert resolved.audience == [
        f"member:{owner.id}",
        f"member:{holder.id}",
        f"member:{creator.id}",
    ]
    listed = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}/notes").json()["items"]
    assert listed == []  # default open
    everything = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}/notes?state=all").json()
    assert [n["id"] for n in everything["items"]] == [posted["id"]]


def test_a_redacted_note_keeps_its_place_and_its_event_is_redacted(
    owner: flow.Human, migrated: Engine
) -> None:
    card = task(owner)
    posted = note(owner, card, "token: hunter2 @maintainer").json()
    done = owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/notes/{posted['id']}/redact",
        {"reason": "secret", "base_version": posted["version"]},
    )
    assert done.status_code == 200, done.text
    assert done.json()["body"]["redacted"] is True and done.json()["mentions"] == []
    assert done.json()["state"] == "open"
    added = events(migrated, "note_added")[-1]
    assert added.payload["note"]["body"]["reason"] == "secret"
    notice = events(migrated, "event_redacted")[-1]
    assert notice.payload["note_id"] == posted["id"] and notice.payload["seq"] == added.seq


def test_agents_fill_at_most_150_notes_and_a_card_holds_50_open(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)

    def fill(count: int, kind: str, state: str) -> None:
        with migrated.begin() as conn:
            author = conn.execute(
                select(t.membership.c.id).where(
                    (t.membership.c.agent_id == agent.id)
                    if kind == "agent"
                    else (t.membership.c.human_id == owner.id)
                )
            ).scalar_one()
            for n in range(count):
                conn.execute(
                    insert(t.card_note).values(
                        id=f"nte-fill{kind[0]}{state[0]}{n:04d}",
                        card_id=card["id"],
                        author=author,
                        author_kind=kind,
                        body="x",
                        mentions=[],
                        state=state,
                        created_at=clock.now(),
                        redacted=False,
                    )
                )

    fill(notes.AGENTS_MAX, "agent", "dismissed")
    assert fields_of(note(agent, card)) == {"body": "note_cap"}
    assert note(owner, card).status_code == 201  # the humans' places
    fill(notes.OPEN_MAX - 1, "human", "open")
    assert fields_of(note(owner, card)) == {"body": "note_cap"}


def test_a_member_posts_at_most_20_notes_in_ten_minutes(owner: flow.Human) -> None:
    card = task(owner)
    for n in range(20):
        assert note(owner, card, f"n{n}").status_code == 201
    limited = note(owner, card, "one more")
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_a_closed_project_refuses_notes_but_lets_them_be_resolved(owner: flow.Human) -> None:
    card = task(owner)
    posted = note(owner, card).json()
    owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    assert note(owner, card).json()["error"]["code"] == "project_closed"
    resolved = owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/notes/{posted['id']}/resolve",
        {"state": "dismissed"},
    )
    assert resolved.status_code == 200


def test_a_note_is_at_most_4_kib_and_mentions_are_the_hubs(owner: flow.Human) -> None:
    card = task(owner)
    assert fields_of(note(owner, card, "x" * 4097)) == {"body": "too_long"}
    posted = owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/notes", {"body": "x", "mentions": []}
    )
    assert fields_of(posted) == {"mentions": "read_only"}


# --- observation (the probe's worker) ----------------------------------------------------------


class FakeForge(forge.Forge):
    def __init__(self, answers: dict[int, dict[str, Any] | None], public: bool = True) -> None:
        super().__init__("token")
        self.answers = answers
        self.public = public
        self.reads: list[tuple[str, list[int]]] = []

    def items(
        self, repository: str, numbers: list[int]
    ) -> tuple[dict[int, dict[str, Any] | None], bool]:
        self.reads.append((repository, numbers))
        return {n: self.answers.get(n) for n in numbers}, self.public


@pytest.mark.parametrize("granted", [None, "app", "owner_token"])
def test_a_link_event_names_the_source_that_read_it(
    owner: flow.Human, migrated: Engine, granted: str | None
) -> None:
    """§11.4: of a read through an owner's grant, only the bare count reaches a page without
    sign-in, and only while that read found the repository public."""
    card = task(owner)
    link(owner, card, kind="pr", forge_url=PULL)
    number = int(PULL.rsplit("/", 1)[1])
    answer = {"type": "PullRequest", "title": "A", "state": "closed", "merged": True}
    fg = FakeForge({number: answer})
    object.__setattr__(fg, "granted", granted)
    assert fg.via == (granted or "instance")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    probe.observe_links(migrated, fg, project_id)
    [seen] = events(migrated, "link_observed")
    assert seen.payload["public"] is True  # the read said so
    assert seen.payload["read_via"] == (granted or "instance")


def test_the_probe_reads_own_repository_links_in_one_batch(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    card = task(owner)
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    issue = link(owner, card, kind="issue", forge_url=ISSUE).json()
    mismatch = link(owner, card, kind="issue", forge_url=f"{REPOSITORY}/issues/7").json()
    pull = link(owner, card, kind="pr", forge_url=PULL).json()
    foreign = link(
        owner, card, kind="pr", forge_url="https://github.com/oliver-zehentleitner/other/pull/3"
    ).json()
    fg = FakeForge(
        {
            41: {"type": "Issue", "title": "Board: links", "state": "open", "merged": False},
            7: {"type": "PullRequest", "title": "A PR", "state": "closed", "merged": True},
        }
    )
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    probe.observe_links(migrated, fg, project_id)
    assert fg.reads == [("oliver-zehentleitner/maity", [7, 41])]  # never the other repository
    shown = {
        lnk["id"]: lnk["observed"]
        for lnk in owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"]
    }
    assert {k: v for k, v in shown[issue["id"]].items() if k != "observed_at"} == {
        "found": True,
        "title": "Board: links",
        "state": "open",
    }
    assert shown[mismatch["id"]]["reason"] == "kind_mismatch"
    assert shown[pull["id"]]["state"] == "merged"
    assert shown[foreign["id"]] is None  # not observed
    seen = events(migrated, "link_observed")
    assert {e.payload["link_id"] for e in seen} == {issue["id"], mismatch["id"], pull["id"]}
    assert {e.payload["public"] for e in seen} == {True}  # the read said so (§11.4)
    # The holder too when the state changed; a kind mismatch has none.
    assert {e.payload["link_id"]: e.audience for e in seen} == {
        issue["id"]: ["all", f"member:{holder.id}"],
        mismatch["id"]: ["all"],
        pull["id"]: ["all", f"member:{holder.id}"],
    }
    # Nothing changed: no new event; the card closes, one more read, then never.
    probe.observe_links(migrated, fg, project_id)
    assert len(events(migrated, "link_observed")) == 3
    # A second later the card closes: one more read after that, then never.
    later = datetime.now(UTC) + timedelta(seconds=2)
    clock.set_source(lambda: later)
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"status": "cancelled"})
    probe.observe_links(migrated, fg, project_id)
    probe.observe_links(migrated, fg, project_id)
    assert len(fg.reads) == 3


def test_a_link_job_is_per_project_and_waits_once(migrated: Engine) -> None:
    worker = probe.Worker(migrated, FakeForge({}))  # never started: only the queue is read
    worker.links_added("prj-a")
    worker.links_added("prj-a")
    worker.links_added("prj-b")
    jobs = [worker.jobs.get_nowait() for _ in range(worker.jobs.qsize())]
    assert jobs == [(probe.LINKS, "prj-a"), (probe.LINKS, "prj-b")]


# --- review of #267 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        (
            {"kind": "issue", "forge_url": "https://github.com:bad/o/r/issues/1"},
            {"forge_url": "not_a_forge_url"},
        ),
        (
            {"kind": "issue", "forge_url": "https://[broken/o/r/issues/1"},
            {"forge_url": "not_a_forge_url"},
        ),
        ({"kind": "url", "url": "https://example.com:port/x"}, {"url": "not_a_url"}),
        ({"kind": "url", "url": "https://[broken"}, {"url": "not_a_url"}),
    ],
)
def test_a_malformed_url_is_invalid_not_a_crash(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    assert fields_of(link(owner, task(owner), **body)) == fields


def test_the_diff_keeps_lines_that_start_like_its_headers() -> None:
    from maity_hub.board.history import diff

    shown = diff("-- old\n++ kept", "++ new\n++ kept")
    assert shown.splitlines() == ["@@ -1,2 +1,2 @@", "--- old", "+++ new", " ++ kept"]


def test_a_replayed_add_and_a_repeated_removal_answer_as_the_first(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    path = f"/api/v1/projects/maintainer/maity/tasks/{card['id']}/links"
    keyed = agent.auth | {"Idempotency-Key": "replay-of-a-link-0001"}
    body = {"kind": "url", "url": "https://example.com/a"}
    added = agent.client.post(path, json=body, headers=keyed)
    assert added.status_code == 201, added.text
    gone = agent.client.delete(f"{path}/{added.json()['id']}", headers=agent.auth)
    assert gone.status_code == 200
    replayed = agent.client.post(path, json=body, headers=keyed)
    assert replayed.status_code == 201, replayed.text
    assert replayed.headers.get("Idempotent-Replayed") == "true"
    assert replayed.json() == added.json()
    again = agent.client.delete(f"{path}/{added.json()['id']}", headers=agent.auth)
    assert (again.status_code, again.json()) == (200, added.json())
    nothing = agent.client.delete(f"{path}/lnk-000000000000", headers=agent.auth)
    assert nothing.status_code == 404


def test_a_repeated_removal_shows_the_tombstone_once_its_entry_is_redacted(
    owner: flow.Human,
) -> None:
    card = task(owner)
    added = link(owner, card, kind="url", url="https://example.com/secret").json()
    path = f"/projects/maintainer/maity/tasks/{card['id']}/links/{added['id']}"
    assert owner.delete(path).status_code == 200
    removal = next(e for e in history(owner, card) if e["field"] == "links" and e["after"] is None)
    owner.post(
        f"/projects/maintainer/maity/tasks/{card['id']}/history/{removal['id']}/redact",
        {"reason": "leak"},
    )
    again = owner.delete(path)
    assert again.status_code == 200 and again.json()["redacted"] is True
    assert "url" not in again.json()


def test_a_link_the_card_was_created_with_is_removed_twice_like_any_other(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner, links=[{"kind": "url", "url": "https://example.com/initial"}])
    [initial] = card["links"]
    path = f"/api/v1/projects/maintainer/maity/tasks/{card['id']}/links/{initial['id']}"
    first = agent.client.delete(path, headers=agent.auth)
    assert first.status_code == 403  # not its link, card or admin
    removed = owner.delete(path.removeprefix("/api/v1"))
    assert (removed.status_code, removed.json()) == (200, initial)
    again = owner.delete(path.removeprefix("/api/v1"))
    assert (again.status_code, again.json()) == (200, initial)


# --- commit links (§6.13) -------------------------------------------------------------------

SHA = "d91e294c" + "0" * 32
HEAD = "a" * 40
COMMIT = f"{REPOSITORY}/commit/{SHA}"


class CommitForge(FakeForge):
    """A forge with commits and a default branch head; it counts the reads of each."""

    def __init__(self, head: str | Exception | None = SHA) -> None:
        super().__init__({})
        self.head = head
        self.commits: dict[str, tuple[str, list[dict[str, str]]] | Exception | None] = {
            SHA: ("success", [{"name": "ci-ok", "status": "success"}])
        }
        self.calls: list[str] = []

    def commit(self, repository: str, sha: str) -> dict[str, Any]:
        self.calls.append(f"commit:{sha}")
        known = self.commits.get(sha)
        if isinstance(known, Exception):
            raise known
        if known is None:
            return {"sha": sha, "found": False}
        checks, detail = known
        return {"sha": sha, "found": True, "checks": checks, "checks_detail": detail}

    def branch(self, repository: str, name: str) -> dict[str, Any]:
        self.calls.append(f"branch:{name}")
        if isinstance(self.head, Exception):
            raise self.head
        return {"name": name, "head_sha": self.head, "found": self.head is not None}


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(select(t.project.c.id)).scalar_one())


def _later(seconds: int) -> None:
    moment = datetime.now(UTC) + timedelta(seconds=seconds)
    clock.set_source(lambda: moment)


def test_a_commit_link_names_its_full_sha_in_lower_case(owner: flow.Human) -> None:
    card = task(owner)
    response = link(owner, card, kind="commit", forge_url=f"{REPOSITORY}/commit/{SHA.upper()}")
    assert response.status_code == 201, response.text
    shown = response.json()
    assert {k: v for k, v in shown.items() if k not in ("id", "added_at", "added_by")} == {
        "kind": "commit",
        "forge_url": COMMIT,
        "forge": "github",
        "repository": "oliver-zehentleitner/maity",
        "sha": SHA,
        "observed": None,
    }
    again = link(owner, card, kind="commit", forge_url=COMMIT)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_linked"


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"kind": "commit", "forge_url": f"{REPOSITORY}/commit/d91e294"}, "not_a_forge_url"),
        ({"kind": "commit", "forge_url": f"{REPOSITORY}/commit/{'g' * 40}"}, "not_a_forge_url"),
        ({"kind": "commit", "forge_url": f"{REPOSITORY}/commit/{SHA}0"}, "not_a_forge_url"),
        ({"kind": "commit", "forge_url": PULL}, "kind_mismatch"),
        ({"kind": "pr", "forge_url": COMMIT}, "kind_mismatch"),
    ],
)
def test_a_commit_link_takes_only_a_full_sha_of_its_kind(
    owner: flow.Human, body: dict[str, Any], fields: str
) -> None:
    assert fields_of(link(owner, task(owner), **body)) == {"forge_url": fields}


def test_a_commit_link_is_observed_and_wakes_the_holder_once_it_falls_behind(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    holder = flow.agent(make_client, owner)
    card = task(owner)
    holder.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    added = link(owner, card, kind="commit", forge_url=COMMIT).json()
    fg = CommitForge(head=SHA)
    probe.observe_links(migrated, fg, _project_id(migrated))
    [first] = events(migrated, "link_observed")
    assert first.payload["new"] == {
        "found": True,
        "sha": SHA,
        "checks": "success",
        "required_check": None,
        "branch_head_sha": SHA,
        "ahead": False,
    }
    assert first.audience == ["all"]  # not ahead: the holder sleeps on
    assert first.payload["public"] is False
    observed = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"][0]
    assert observed["id"] == added["id"]
    assert set(observed["observed"]) == {*links.COMMIT_SHOWN, "observed_at"}
    # The branch moves on: `ahead` turns true and wakes the holder, once.
    fg.head = HEAD
    _later(probe.MAX_AGE + 1)
    probe.observe_links(migrated, fg, _project_id(migrated))
    ahead = events(migrated, "link_observed")[-1]
    assert ahead.payload["new"]["ahead"] is True
    assert ahead.audience == ["all", f"member:{holder.id}"]
    fg.head = "b" * 40
    _later(2 * probe.MAX_AGE + 2)
    probe.observe_links(migrated, fg, _project_id(migrated))
    still = events(migrated, "link_observed")[-1]
    assert still.payload["new"]["branch_head_sha"] == "b" * 40
    assert still.audience == ["all"]  # still ahead: nobody woken again


def test_a_spent_budget_keeps_the_last_commit_observation(
    owner: flow.Human, migrated: Engine
) -> None:
    card = task(owner)
    link(owner, card, kind="commit", forge_url=COMMIT)
    fg = CommitForge(head=SHA)
    probe.observe_links(migrated, fg, _project_id(migrated))
    before = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"][0]
    fg.head = forge.ForgeUnavailableError("spent", status=403, rate_limited=True)
    _later(probe.MAX_AGE + 1)
    with pytest.raises(forge.ForgeUnavailableError):
        probe.observe_links(migrated, fg, _project_id(migrated))
    after = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"][0]
    assert after["observed"] == before["observed"]
    assert len(events(migrated, "link_observed")) == 1


def test_a_commit_the_forge_lacks_is_found_false_and_a_refused_branch_null(
    owner: flow.Human, migrated: Engine
) -> None:
    card = task(owner)
    missing = "c" * 40
    link(owner, card, kind="commit", forge_url=f"{REPOSITORY}/commit/{missing}")
    link(owner, card, kind="commit", forge_url=COMMIT)
    fg = CommitForge(head=forge.ForgeUnavailableError("refused", status=403))
    probe.observe_links(migrated, fg, _project_id(migrated))
    shown = {
        lnk["sha"]: lnk["observed"]
        for lnk in owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["links"]
    }
    assert set(shown[missing]) == {"found", "observed_at"} and shown[missing]["found"] is False
    assert (shown[SHA]["branch_head_sha"], shown[SHA]["ahead"]) == (None, None)


def test_commit_links_are_read_once_per_sha_and_never_on_a_closed_card(
    owner: flow.Human, migrated: Engine
) -> None:
    one, two = task(owner), task(owner)
    link(owner, one, kind="commit", forge_url=COMMIT)
    link(owner, two, kind="commit", forge_url=COMMIT)
    fg = CommitForge(head=SHA)
    probe.observe_links(migrated, fg, _project_id(migrated))
    assert fg.calls == [f"commit:{SHA}", "branch:main"]  # one read for both cards
    assert len(events(migrated, "link_observed")) == 2
    owner.patch(f"/projects/maintainer/maity/tasks/{one['id']}", {"status": "cancelled"})
    owner.patch(f"/projects/maintainer/maity/tasks/{two['id']}", {"status": "cancelled"})
    _later(probe.MAX_AGE + 1)
    fg.calls.clear()
    probe.observe_links(migrated, fg, _project_id(migrated))
    assert fg.calls == []  # a commit link is read only while its card is not closed
