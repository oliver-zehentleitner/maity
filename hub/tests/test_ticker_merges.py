"""docs/api.md §17.2–§17.4: merges announced from what the probe observes — the
changed paths, the linked cards, the contract's sections, dedupe and the start."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, forge, probe, ticker
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.db import downgrade, migrate
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import READER, REPO, TOKEN, FakeGitHub

BASE_SHA = "b" * 40
MERGE_SHA = "c" * 40
CONTRACT_BEFORE = (
    "# API\n\n## 6. Projects\n\nold six\n\n### 6.5 Claims\n\nold claim\n\n## 13. CLI\n\nold cli\n"
)
CONTRACT_AFTER = (
    "# API\n\n## 6. Projects\n\nold six\n\n### 6.5 Claims\n\nnew claim\n\n"
    "## 13. CLI\n\nold cli\nnew cli line\n"
)
# Line 9 changes in 6.5, line 14 is added in 13.
PATCH = "@@ -9,1 +9,1 @@\n-old claim\n+new claim\n@@ -13,1 +13,2 @@\n old cli\n+new cli line\n"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(settings, forge_github_token=TOKEN)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(forge.Forge, "_get", lambda _self, path: fake(path))
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, github: FakeGitHub) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


@pytest.fixture
def team(make_client: ClientFactory, owner: flow.Human) -> dict[str, flow.Agent]:
    return {
        "admin": flow.agent(make_client, owner, role="admin", areas=["context/"]),
        "hub": flow.agent(make_client, owner, areas=["hub/"]),
        "docs": flow.agent(make_client, owner, areas=["docs/"]),
        "cli": flow.agent(make_client, owner, areas=["cli/"]),
    }


def enable(owner: flow.Human, **extra: Any) -> None:
    body = {
        "enabled": True,
        "contract_files": ["docs/api.md"],
        "contract_implementers": {"6": ["area:hub/"], "13": ["area:cli/"]},
    }
    response = owner.patch(
        "/projects/maintainer/maity", {"settings": {"ticker": {**body, **extra}}}
    )
    assert response.status_code == 200, response.text


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        pid: str = conn.execute(select(t.project.c.id)).scalar_one()
    return pid


def merged(
    github: FakeGitHub,
    number: int,
    files: list[dict[str, Any]],
    *,
    at: str = "2099-01-01T10:00:00Z",
    head: str = "agent-b/x",
    title: str | None = None,
) -> None:
    pulls = github.answers.setdefault(
        "/repos/acme/maity/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=50&page=1",
        [],
    )
    pulls.append(
        {
            "number": number,
            "title": title or f"PR {number}",
            "html_url": f"https://github.com/acme/maity/pull/{number}",
            "merged_at": at,
            "merge_commit_sha": MERGE_SHA,
            "base": {"ref": "main", "sha": BASE_SHA},
            "head": {"ref": head},
            "user": {"login": "agent-b"},
        }
    )
    github.answers[f"/repos/acme/maity/pulls/{number}/files?per_page=100&page=1"] = files


def content(github: FakeGitHub, path: str, sha: str, text: str) -> None:
    data = text.encode()
    github.answers[f"/repos/acme/maity/contents/{path}?ref={sha}"] = {
        "type": "file",
        "size": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode(),
    }


def items(owner: flow.Human) -> list[dict[str, Any]]:
    events = owner.get("/projects/maintainer/maity/events?after=0&limit=200").json()["items"]
    return [e for e in events if e["kind"] == "ticker"]


def reasons(event: dict[str, Any]) -> dict[str, list[str]]:
    return {r["member_id"]: r["why"] for r in event["payload"]["reasons"]}


# --- the sections of a contract file -----------------------------------------------------


def test_headings_name_sections_by_their_number() -> None:
    assert ticker.headings(
        "# t\n## 8. Events\ntext\n### 8.2 Kinds, audience\n#### 8.2.1 deep\n## Notes\n"
    ) == [
        (2, "8"),
        (4, "8.2"),
    ]


def test_changed_lines_by_the_new_and_the_old_file() -> None:
    assert ticker.changed_lines(PATCH) == ([9, 14], [9])


def test_sections_from_the_new_file_and_deleted_lines_from_the_base() -> None:
    assert ticker.sections(CONTRACT_AFTER, CONTRACT_BEFORE, PATCH) == {"6.5", "13"}
    # A changed heading belongs to its own section.
    assert ticker.sections(
        "## 1. A\n## 2. B\n", "## 1. A\n## 2. Bee\n", "@@ -2 +2 @@\n-## 2. Bee\n+## 2. B\n"
    ) == {"2"}


def test_the_longest_key_wins_and_star_takes_the_rest() -> None:
    mapping = {"8": ["area:hub/"], "8.2": ["area:web/"], "*": ["trust:admin"]}
    assert ticker.implementers(mapping, "8.2.1") == ["area:web/"]
    assert ticker.implementers(mapping, "8.3") == ["area:hub/"]
    assert ticker.implementers(mapping, "13") == ["trust:admin"]


# --- announcing --------------------------------------------------------------------------


def test_a_merge_reaches_area_owners_card_holders_and_the_contracts_implementers(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    card = team["hub"].post("/projects/maintainer/maity/tasks", {"title": "Claims"}).json()
    team["hub"].post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    with migrated.begin() as conn:
        conn.execute(
            update(t.card).where(t.card.c.id == card["id"]).values(report={"pr": {"number": 212}})
        )
    merged(
        github,
        212,
        [
            {"filename": "hub/maity_hub/claims.py", "patch": "@@ -1 +1 @@\n-a\n+b\n"},
            {"filename": "docs/api.md", "patch": PATCH},
        ],
        title="hub: the claim lease survives a restart",
    )
    content(github, "docs/api.md", MERGE_SHA, CONTRACT_AFTER)
    content(github, "docs/api.md", BASE_SHA, CONTRACT_BEFORE)
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 1
    [item] = items(owner)
    p = item["payload"]
    assert (
        p["text"] == "#212 hub: the claim lease survives a restart — merged into main;"
        " touches hub/, docs/, docs/api.md (§6.5, §13)"
    )
    assert p["contract"] == {"sections": ["6.5", "13"], "sections_unknown": False}
    assert p["areas"] == ["hub/", "docs/"] and p["tasks"] == [card["id"]]
    assert p["merge"]["pr"] == 212 and p["merge"]["merge_sha"] == MERGE_SHA
    assert (p["origin"], item["subject"], item["actor"]) == (
        {"via": "probe", "delivery": None},
        {"type": "pull_request", "id": "212"},
        None,
    )
    assert reasons(item) == {
        team["hub"].id: [
            "area_owner:hub/",
            f"card_holder:{card['id']}",
            "contract_implementer:6.5",
        ],
        team["docs"].id: ["area_owner:docs/"],
        team["cli"].id: ["contract_implementer:13"],
        team["admin"].id: ["trust:admin"],
    }
    assert (
        probe.announce_merges(migrated, READER, project_id(migrated)) == 0
    ), "one item per pull request"


def test_nothing_merged_before_the_ticker_was_switched_on(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    merged(github, 5, [{"filename": "hub/a.py", "patch": ""}], at="2001-01-01T00:00:00Z")
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 0
    assert items(owner) == []


def test_nothing_while_the_ticker_is_off(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    owner.patch("/projects/maintainer/maity", {"settings": {"ticker": {"enabled": False}}})
    merged(github, 6, [{"filename": "hub/a.py", "patch": ""}])
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 0


def test_a_merge_the_hub_cannot_see_in_full_reaches_every_area_owner(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    merged(github, 7, [{"filename": f"hub/f{n}.py", "patch": ""} for n in range(100)])
    github.answers["/repos/acme/maity/pulls/7/files?per_page=100&page=2"] = None
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 1
    [item] = items(owner)
    assert item["payload"]["paths_truncated"] is True
    # The owner owns "/" (§6.2); every member with an area is reached.
    assert {m for m, why in reasons(item).items() if "area_owner:*" in why} == {
        owner.id,
        *(a.id for a in team.values()),
    }


def test_without_a_patch_the_sections_are_unknown_and_every_implementer_applies(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    merged(github, 8, [{"filename": "docs/api.md"}])
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 1
    [item] = items(owner)
    assert item["payload"]["contract"] == {"sections": [], "sections_unknown": True}
    assert "sections unknown" in item["payload"]["text"]
    assert reasons(item)[team["cli"].id] == ["contract_implementer:13"]
    assert reasons(item)[team["hub"].id] == ["contract_implementer:6"]


def test_switching_on_again_starts_again_from_then(owner: flow.Human, migrated: Engine) -> None:
    enable(owner)
    with migrated.connect() as conn:
        first = ticker.merges_since(conn, project_id(migrated))
    owner.patch("/projects/maintainer/maity", {"settings": {"ticker": {"enabled": False}}})
    enable(owner)
    with migrated.connect() as conn:
        assert ticker.merges_since(conn, project_id(migrated)) >= first
    assert first <= clock.now()


# --- review: the backlog, renames, stale rounds, upgraded installs -------------------


def closed(github: FakeGitHub, page: int, items: list[dict[str, Any]]) -> None:
    github.answers[
        f"/repos/acme/maity/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=50&page={page}"
    ] = items


def test_a_merge_behind_many_closed_pull_requests_is_still_announced(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    unmerged = [
        {
            "number": 1000 + n,
            "merged_at": None,
            "updated_at": "2099-01-02T00:00:00Z",
            "base": {"ref": "main"},
        }
        for n in range(50)
    ]
    for page in (1, 2, 3):
        closed(github, page, unmerged)
    closed(
        github,
        4,
        [
            {
                "number": 9,
                "title": "far back",
                "merged_at": "2099-01-01T10:00:00Z",
                "updated_at": "2099-01-01T10:00:00Z",
                "merge_commit_sha": MERGE_SHA,
                "base": {"ref": "main", "sha": BASE_SHA},
                "head": {"ref": "x"},
            }
        ],
    )
    github.answers["/repos/acme/maity/pulls/9/files?per_page=100&page=1"] = [
        {"filename": "hub/a.py", "patch": ""}
    ]
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 1


def test_the_scan_stops_where_it_reaches_back_before_the_switch(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    closed(github, 1, [{"number": 1, "merged_at": None, "updated_at": "2001-01-01T00:00:00Z"}] * 50)
    probe.announce_merges(migrated, READER, project_id(migrated))
    assert not any("page=2" in c for c in github.calls), "nothing older can follow"


def test_a_renamed_contract_file_is_a_contract_change_and_reaches_both_places(
    owner: flow.Human, team: dict[str, flow.Agent], github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    merged(github, 11, [{"filename": "cli/api.md", "previous_filename": "docs/api.md"}])
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 1
    [item] = items(owner)
    assert item["payload"]["contract"] == {"sections": [], "sections_unknown": True}
    by = reasons(item)
    assert "area_owner:docs/" in by[team["docs"].id] and "area_owner:cli/" in by[team["cli"].id]
    assert by[team["admin"].id] == ["trust:admin"]


def test_a_round_that_outlived_a_switch_off_and_on_writes_nothing(
    owner: flow.Human,
    team: dict[str, flow.Agent],
    github: FakeGitHub,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enable(owner)
    merged(github, 12, [{"filename": "hub/a.py", "patch": ""}])
    real = forge.Forge.pull_files

    def meanwhile(self: forge.Forge, repository: str, number: int, cap: int = 300) -> Any:
        owner.patch("/projects/maintainer/maity", {"settings": {"ticker": {"enabled": False}}})
        owner.patch("/projects/maintainer/maity", {"settings": {"ticker": {"enabled": True}}})
        return real(self, repository, number, cap)

    monkeypatch.setattr(forge.Forge, "pull_files", meanwhile)
    assert probe.announce_merges(migrated, READER, project_id(migrated)) == 0
    assert items(owner) == []


def test_a_project_on_before_the_upgrade_starts_at_the_upgrade(
    owner: flow.Human, migrated: Engine
) -> None:
    enable(owner)
    with migrated.begin() as conn:
        conn.execute(t.ticker_source.delete())
    downgrade(migrated, "0019")
    migrate(migrated)
    with migrated.connect() as conn:
        assert ticker.merges_since(conn, project_id(migrated)) is not None


def test_a_cut_round_goes_on_from_where_it_stopped_and_then_moves_the_bound(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    unmerged = [
        {
            "number": 2000 + n,
            "merged_at": None,
            "updated_at": "2099-01-02T00:00:00Z",
            "base": {"ref": "main"},
        }
        for n in range(50)
    ]
    for page in range(1, 21):
        closed(github, page, unmerged)
    closed(
        github,
        21,
        [
            {
                "number": 13,
                "title": "behind a thousand",
                "merged_at": "2099-01-01T10:00:00Z",
                "updated_at": "2099-01-01T10:00:00Z",
                "merge_commit_sha": MERGE_SHA,
                "base": {"ref": "main", "sha": BASE_SHA},
                "head": {"ref": "x"},
            }
        ],
    )
    github.answers["/repos/acme/maity/pulls/13/files?per_page=100&page=1"] = [
        {"filename": "hub/a.py", "patch": ""}
    ]
    pid = project_id(migrated)
    assert probe.announce_merges(migrated, READER, pid) == 0, "the first round is cut at 20 pages"
    with migrated.connect() as conn:
        scan = ticker.merge_scan(conn, pid)
    assert scan.resume_page == 21 and scan.round_started is not None and scan.scanned_until is None
    assert probe.announce_merges(migrated, READER, pid) == 1, "the next round goes on from page 21"
    with migrated.connect() as conn:
        done = ticker.merge_scan(conn, pid)
    assert done.resume_page is None and done.scanned_until == scan.round_started
    github.calls.clear()
    probe.announce_merges(migrated, READER, pid)
    assert any("page=1" in c for c in github.calls) and not any(
        "page=21" in c for c in github.calls
    )


def moved_during_a_cut_scan(
    owner: flow.Human,
    github: FakeGitHub,
    migrated: Engine,
    started: timedelta,
    moved: timedelta,
) -> int:
    """A merge on unread page 21 moves to page 1 between the rounds of a cut scan; the
    round began `started` after the switch-on, the move came `moved` after it. Returns
    what the interval after the cut scan announces."""
    enable(owner)
    pid = project_id(migrated)
    with migrated.connect() as conn:
        switched = ticker.merges_since(conn, pid)
    # Times from a whole second on; the hub's clock stands after all of them, so the
    # interval after the cut scan begins where that scan began, as in the field.
    epoch = switched.replace(microsecond=0) + timedelta(seconds=1)
    clock.set_source(lambda: epoch + timedelta(hours=3))
    old = {
        "number": 13,
        "title": "merged before the round began",
        "merged_at": clock.rfc3339(epoch + timedelta(minutes=1)),
        "updated_at": clock.rfc3339(epoch + timedelta(minutes=1)),
        "merge_commit_sha": MERGE_SHA,
        "base": {"ref": "main", "sha": BASE_SHA},
        "head": {"ref": "x"},
    }
    unmerged = [
        {
            "number": 2000 + n,
            "merged_at": None,
            "updated_at": "2099-01-02T00:00:00Z",
            "base": {"ref": "main"},
        }
        for n in range(50)
    ]
    for page in range(1, 21):
        closed(github, page, unmerged)
    closed(github, 21, [old])
    github.answers["/repos/acme/maity/pulls/13/files?per_page=100&page=1"] = [
        {"filename": "hub/a.py", "patch": ""}
    ]
    assert probe.announce_merges(migrated, READER, pid) == 0, "cut at 20 pages, before page 21"
    with migrated.begin() as conn:
        conn.execute(
            update(t.ticker_source)
            .where(t.ticker_source.c.project_id == pid)
            .values(round_started=epoch + started)
        )
    # A comment between the rounds: the pull request moves to page 1, page 21 is empty.
    moved_at = clock.rfc3339(epoch + moved)  # whole seconds, as the forge has them
    closed(github, 1, [{**old, "updated_at": moved_at}] + unmerged[:49])
    closed(github, 21, [])
    assert probe.announce_merges(migrated, READER, pid) == 0, "the continuation reads page 21"
    found = probe.announce_merges(migrated, READER, pid)
    assert probe.announce_merges(migrated, READER, pid) == 0, "and only once"
    return found


def test_an_old_merge_that_moves_up_during_a_cut_scan_is_still_announced(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    found = moved_during_a_cut_scan(owner, github, migrated, timedelta(hours=1), timedelta(hours=2))
    assert found == 1, "the next interval admits it by its update"
    assert [i["payload"]["merge"]["pr"] for i in items(owner)] == [13]


@pytest.mark.parametrize("micro", [0, 500_000, 999_999])
def test_a_move_in_the_second_the_scan_began_is_still_announced(
    owner: flow.Human, github: FakeGitHub, migrated: Engine, micro: int
) -> None:
    # The round began at hh:mm:ss.micro; the forge says the update was at hh:mm:ss.
    started = timedelta(hours=1, microseconds=micro)
    assert moved_during_a_cut_scan(owner, github, migrated, started, timedelta(hours=1)) == 1


def test_a_move_a_second_before_the_scan_began_is_the_earlier_scan_s(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    # Older than the bound's second: what the scan that began then already covered.
    started = timedelta(hours=1)
    assert (
        moved_during_a_cut_scan(owner, github, migrated, started, timedelta(minutes=59, seconds=59))
        == 0
    )


def test_a_page_in_the_bound_s_second_does_not_stop_the_scan(
    owner: flow.Human, github: FakeGitHub, migrated: Engine
) -> None:
    enable(owner)
    pid = project_id(migrated)
    with migrated.connect() as conn:
        epoch = ticker.merges_since(conn, pid).replace(microsecond=0) + timedelta(seconds=1)
    clock.set_source(lambda: epoch + timedelta(hours=3))
    with migrated.begin() as conn:
        conn.execute(
            update(t.ticker_source)
            .where(t.ticker_source.c.project_id == pid)
            .values(scanned_until=epoch + timedelta(hours=1, microseconds=250_000))
        )
    second = clock.rfc3339(epoch + timedelta(hours=1))
    same_second = [
        {"number": 3000 + n, "merged_at": None, "updated_at": second, "base": {"ref": "main"}}
        for n in range(50)
    ]
    closed(github, 1, same_second)
    closed(
        github,
        2,
        [
            {
                "number": 14,
                "title": "in the bound's second",
                "merged_at": clock.rfc3339(epoch + timedelta(minutes=5)),
                "updated_at": second,
                "merge_commit_sha": MERGE_SHA,
                "base": {"ref": "main", "sha": BASE_SHA},
                "head": {"ref": "x"},
            }
        ],
    )
    github.answers["/repos/acme/maity/pulls/14/files?per_page=100&page=1"] = []
    assert probe.announce_merges(migrated, READER, pid) == 1, "page 2 is read, its merge announced"


@pytest.mark.parametrize(("offset", "announced"), [(timedelta(0), 1), (timedelta(seconds=-1), 0)])
def test_the_switch_on_second_counts(
    owner: flow.Human,
    github: FakeGitHub,
    migrated: Engine,
    offset: timedelta,
    announced: int,
) -> None:
    # Switched on at hh:mm:ss.4, merged at hh:mm:ss.8: the forge says hh:mm:ss. That
    # second counts (A's ruling on #231); the second before it is older than the switch.
    enable(owner)
    pid = project_id(migrated)
    with migrated.begin() as conn:
        epoch = ticker.merges_since(conn, pid).replace(microsecond=400_000)
        conn.execute(
            update(t.ticker_source)
            .where(t.ticker_source.c.project_id == pid)
            .values(merges_since=epoch)
        )
    merged(github, 15, [], at=clock.rfc3339(epoch + offset))
    assert probe.announce_merges(migrated, READER, pid) == announced
