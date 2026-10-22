"""docs/api.md §11.3: the Keep the Why family, read from the repository."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import forge, ktw, outbound
from tests import flow
from tests.conftest import ClientFactory

REPO = "https://github.com/acme/widget"
BASE = "https://acme.example/ktw"


def kfile(
    state: str | None = None, ident: str | None = None, kids: list[str] | None = None
) -> bytes:
    lines = ["Machine-readable state.", "", "<!-- keep-the-why:config -->"]
    if ident:
        lines.append(f"- id: {ident}")
    if state:
        lines.append(f"- dashboard-state: {state}")
    lines += ["- context: `context/`", "<!-- /keep-the-why:config -->"]
    if kids is not None:
        lines += ["", "<!-- keep-the-why:children -->", *kids, "<!-- /keep-the-why:children -->"]
    return ("\n".join(lines) + "\n").encode()


def export(*entries: Any, **extra: Any) -> dict[str, Any]:
    return {
        "state-json": 2,
        "generated": "2026-10-22T11:33:15Z",
        "topics": [{"file": "hub.md", "title": "Hub"}],
        "entries": list(entries),
        "findings": {"errors": 0, "warnings": 1},
        "bodies": {"never": "read"},
        **extra,
    }


def entry(n: int, status: str = "active", file: str = "hub.md", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"hub.md#e{n}",
        "uuid": f"uuid-{n}",
        "title": f"Entry {n}",
        "type": ["decision"],
        "status": status,
        "file": file,
        "line": n,
        **extra,
    }


class Fake:
    """The repository's files through the forge, and the exports on the web."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.files: dict[str, Any] = {}
        self.states: dict[str, Any] = {}
        self.file_reads: list[str] = []
        self.state_reads: list[str] = []
        self.in_flight = 0
        self.most_in_flight = 0
        self.delay = 0.0
        self.lock = threading.Lock()
        fake = self

        def file(self: forge.Forge, repository: str, path: str, cap: int) -> bytes | None:
            fake.file_reads.append(path)
            found = fake.files.get(path)
            if isinstance(found, BaseException):
                raise found
            return found

        def read(url: str, *, cap: int, headers: Any = None, **kwargs: Any) -> outbound.Answer:
            with fake.lock:
                fake.in_flight += 1
                fake.most_in_flight = max(fake.most_in_flight, fake.in_flight)
                fake.state_reads.append(url)
            try:
                time.sleep(fake.delay)
                found = fake.states.get(url)
                if isinstance(found, BaseException):
                    raise found
                if isinstance(found, tuple):
                    return outbound.Answer(found[0], {}, found[1])
                if found is None:
                    return outbound.Answer(404, {}, b"")
                if isinstance(found, bytes):
                    return outbound.Answer(200, {}, found)
                return outbound.Answer(200, {}, json.dumps(found).encode())
            finally:
                with fake.lock:
                    fake.in_flight -= 1

        monkeypatch.setattr(forge.Forge, "file", file)
        monkeypatch.setattr(outbound, "read", read)

    def family(self) -> None:
        """A root with two children: hub (with its own child, api) and a URL child."""
        self.files[".keep-the-why"] = kfile(
            f"{BASE}/state.json",
            "acme---widget",
            [
                "- hub: hub — the server",
                "- remote: https://github.com/acme/other — elsewhere",
                "- cli: cli — the command",
            ],
        )
        self.files["hub/.keep-the-why"] = kfile(
            f"{BASE}/hub/state.json", "acme---widget---hub", ["- api: api — the API"]
        )
        self.files["hub/api/.keep-the-why"] = kfile(f"{BASE}/hub/api/state.json", "api")
        self.files["cli/.keep-the-why"] = kfile(f"{BASE}/cli/state.json", "acme---widget---cli")
        self.states[f"{BASE}/state.json"] = export(entry(1), entry(2, "open"))
        self.states[f"{BASE}/hub/state.json"] = export(
            entry(3, "needs-review"), entry(4, "pending-confirmation"), entry(5, "superseded")
        )
        self.states[f"{BASE}/hub/api/state.json"] = export(entry(6, "open"))
        self.states[f"{BASE}/cli/state.json"] = export(entry(7, "weird"))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    return Fake(monkeypatch)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


# --- parsing and rules ---------------------------------------------------------------------------


def test_the_config_block_and_the_children_are_read() -> None:
    source = kfile(
        f"{BASE}/state.json", "x", ["- hub: hub — a — dash", "- odd line", "- cli: `cli`"]
    )
    assert ktw.config(source.decode())["dashboard-state"] == f"{BASE}/state.json"
    assert ktw.config(source.decode())["context"] == "context/"
    assert ktw.children(source.decode()) == [("hub", "hub"), ("cli", "cli")]


@pytest.mark.parametrize(
    ("parent", "location", "path"),
    [
        ("", "hub", "hub"),
        ("", "hub/api/", "hub/api"),
        ("hub", "api", "hub/api"),
        ("", "a.b_c-d", "a.b_c-d"),
        ("", "..", None),
        ("", "hub/../web", None),
        ("", "./hub", None),
        ("", "/etc", None),
        ("", "hub\\api", None),
        ("", "https://github.com/acme/other", None),
        ("", "hub dir", None),
        ("", "", None),
        ("", "hub//api", None),
    ],
)
def test_only_plain_relative_directories_are_followed(
    parent: str, location: str, path: str | None
) -> None:
    assert ktw.child_path(parent, location) == path


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        (f"{BASE}/state.json", True),
        ("https://acme.example:443/s.json", True),
        ("http://acme.example/s.json", False),
        ("https://acme.example:8443/s.json", False),
        ("https://user@acme.example/s.json", False),
        ("https://93.184.215.14/s.json", False),
        ("https://[2606:4700::1111]/s.json", False),
        ("https://acme.example/" + "x" * 2048, False),
        ("javascript:alert(1)", False),
    ],
)
def test_a_state_url_is_https_on_a_host_name(url: str, valid: bool) -> None:
    assert ktw.state_url_valid(url) is valid


def test_the_dashboard_url_drops_the_file_query_and_fragment() -> None:
    assert ktw.dashboard_url(f"{BASE}/hub/state.json?x=1#y") == f"{BASE}/hub/"


def test_untrusted_strings_lose_controls_and_are_cut() -> None:
    assert ktw.text("a\x1b[2Jb‮c\nd", 100) == "a[2Jbcd"
    assert ktw.text("x" * 10, 5) == "xxxx…"
    assert ktw.text(5, 10) is None


def test_the_export_is_read_for_what_the_hub_relies_on() -> None:
    read = ktw.digest(
        export(
            entry(1),
            {"id": "t.md#u", "status": "open", "type": "question", "file": "t.md"},
            {"no": "id"},
            entry(3, "nonsense", type=[f"t{n}" for n in range(12)], title="T" * 300),
            "not an object",
        ),
        "https://d.example/",
    )
    assert read.skipped == 2
    assert read.summary == {
        "generated": "2026-10-22T11:33:15Z",
        "state_json": 2,
        "entries": 3,
        "status": {
            "active": 1,
            "open": 1,
            "needs-review": 0,
            "pending-confirmation": 0,
            "superseded": 0,
            "other": 1,
        },
        "attention": 1,
        "findings": {"errors": 0, "warnings": 1},
    }
    (only,) = read.entries  # counts for all; entries only where attention can use them
    assert only["title"] == "t.md#u" and only["type"] == ["question"]
    assert only["link"] == "https://d.example/#entry/t.md%23u" and only["topic"] is None


def test_attention_entries_are_cleaned_and_cut() -> None:
    read = ktw.digest(
        export(
            entry(1, "needs-review"),
            entry(3, "open", type=[f"t{n}" for n in range(12)], title="T" * 300),
        ),
        "https://d.example/",
    )
    first, second = read.entries
    assert first["link"] == "https://d.example/#entry/uuid-1" and first["topic"] == "Hub"
    assert len(second["type"]) == 8 and len(second["title"]) == 200


def test_a_member_keeps_at_most_one_entry_past_the_attention_cap() -> None:
    entries = [entry(n, "open") for n in range(ktw.MAX_ATTENTION + 50)]
    entries.append(entry(9999, "needs-review"))
    read = ktw.digest(export(*entries), "https://d.example/")
    assert read.summary["entries"] == ktw.MAX_ATTENTION + 51
    assert len(read.entries) == ktw.MAX_ATTENTION + 1
    assert read.entries[0]["status"] == "needs-review"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (export(**{"state-json": 3}), "state_json_version"),
        (export(**{"state-json": "1.9"}), "state_json_version"),
        ({"state-json": 2, "entries": {}}, "shape"),
        ([1, 2], "shape"),
    ],
)
def test_an_export_the_hub_cannot_use(data: Any, reason: str) -> None:
    with pytest.raises(ktw.MemberError) as failed:
        ktw.digest(data, "https://d.example/")
    assert failed.value.reason == reason


def test_a_string_version_with_major_two_is_known() -> None:
    assert ktw.digest(export(**{"state-json": "2.3"}), "https://d/").summary["state_json"] == 2


def test_a_wrong_generated_is_null_and_wrong_findings_are_null() -> None:
    read = ktw.digest(
        export(generated="yesterday", findings={"errors": -1, "warnings": "3"}), "https://d/"
    )
    assert read.summary["generated"] is None
    assert read.summary["findings"] == {"errors": None, "warnings": None}


# --- the endpoint --------------------------------------------------------------------------------


def test_the_family_is_read_depth_first_with_summaries_and_attention(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    body = owner.get("/projects/widget/keep-the-why").json()
    paths = [m["path"] for m in body["members"]]
    assert paths == ["", "hub", "hub/api", "https://github.com/acme/other", "cli"]
    root, hub, api, remote, cli = body["members"]
    assert root["id"] == "acme---widget" and root["name"] is None
    assert root["dashboard_url"] == f"{BASE}/"
    assert hub["name"] == "hub" and hub["summary"]["attention"] == 2
    assert remote["error"] == {"code": "ktw_unavailable", "reason": "location_not_followed"}
    assert cli["summary"]["status"]["other"] == 1
    summary = body["summary"]
    assert summary["members"] == 5 and summary["failed"] == 1
    assert summary["entries"] == 7 and summary["attention"] == 4
    assert summary["findings"] == {"errors": 0, "warnings": 4}
    assert [(a["member"], a["status"]) for a in body["attention"]] == [
        ("hub", "needs-review"),
        ("hub", "pending-confirmation"),
        ("", "open"),
        ("hub/api", "open"),
    ]
    assert body["fresh"] is True and body["error"] is None
    assert body["family_truncated"] is False and body["truncated"] is False
    assert "bodies" not in json.dumps(body)


def test_member_narrows_the_answer(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    hub = owner.get("/projects/widget/keep-the-why", params={"member": "hub"}).json()
    assert [m["path"] for m in hub["members"]] == ["hub"]
    assert hub["summary"]["entries"] == 3
    assert {a["member"] for a in hub["attention"]} == {"hub"}
    root = owner.get("/projects/widget/keep-the-why", params={"member": ""}).json()
    assert [m["path"] for m in root["members"]] == [""]
    missing = owner.get("/projects/widget/keep-the-why", params={"member": "web"})
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "setup",
    ["no_repository", "no_root_file", "no_state_line"],
)
def test_not_configured(owner: flow.Human, fake: Fake, setup: str) -> None:
    if setup == "no_repository":
        flow.project(owner, "widget")
    else:
        flow.project(owner, "widget", repository={"url": REPO})
    if setup == "no_state_line":
        fake.files[".keep-the-why"] = kfile(None, "x", ["- hub: hub — s"])
    answer = owner.get("/projects/widget/keep-the-why")
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "ktw_not_configured"
    assert owner.get("/projects/widget").json()["keep_the_why_export"] is None


@pytest.mark.parametrize(
    ("state", "reason", "extra"),
    [
        (None, "http_status", {"status": 404}),
        ((500, b"oops"), "http_status", {"status": 500}),
        (b"<html>", "not_json", {}),
        (outbound.Refused("timeout"), "timeout", {}),
        (outbound.Refused("unavailable"), "unavailable", {}),
        (outbound.Refused("address_refused"), "address_refused", {}),
        (outbound.Refused("redirect_refused"), "redirect_refused", {}),
        (outbound.Refused("too_large"), "too_large", {}),
        (export(**{"state-json": 9}), "state_json_version", {"version": "9"}),
    ],
)
def test_a_member_that_fails_fails_alone(
    owner: flow.Human, fake: Fake, state: Any, reason: str, extra: dict[str, Any]
) -> None:
    fake.family()
    fake.states[f"{BASE}/hub/state.json"] = state
    flow.project(owner, "widget", repository={"url": REPO})
    body = owner.get("/projects/widget/keep-the-why").json()
    hub = body["members"][1]
    assert hub["error"] == {"code": "ktw_unavailable", "reason": reason, **extra}
    assert hub["summary"] is None
    assert body["members"][0]["error"] is None
    assert body["summary"]["failed"] == 2  # hub and the URL child


@pytest.mark.parametrize(
    ("file", "reason"),
    [
        (None, "config_missing"),
        (forge.ForgeUnavailableError("down"), "forge_unavailable"),
        (ValueError("too large"), "too_large"),
        (kfile(None, "hub"), "no_state_url"),
        (kfile("http://acme.example/s.json", "hub"), "state_url_invalid"),
    ],
)
def test_a_child_config_that_fails(owner: flow.Human, fake: Fake, file: Any, reason: str) -> None:
    fake.family()
    fake.files["hub/.keep-the-why"] = file
    flow.project(owner, "widget", repository={"url": REPO})
    hub = owner.get("/projects/widget/keep-the-why").json()["members"][1]
    assert hub["path"] == "hub"
    assert hub["error"]["reason"] == reason


def test_a_failed_member_keeps_its_last_good_summary(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    good = owner.get("/projects/widget/keep-the-why").json()["members"][1]["summary"]
    fake.states[f"{BASE}/hub/state.json"] = outbound.Refused("timeout")
    now[0] += ktw.FORCE_INTERVAL + 1
    later = owner.get("/projects/widget/keep-the-why", params={"max_age": 0}).json()
    hub = later["members"][1]
    assert hub["error"]["reason"] == "timeout"
    assert hub["summary"] == good
    assert later["summary"]["entries"] == 7  # the last good read counts


def test_a_root_that_cannot_be_read_fails_the_call_with_the_last_answer(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    first = owner.get("/projects/widget/keep-the-why").json()
    fake.files[".keep-the-why"] = forge.ForgeUnavailableError("down")
    now[0] += ktw.FORCE_INTERVAL + 1
    answer = owner.get("/projects/widget/keep-the-why", params={"max_age": 0})
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["code"] == "ktw_unavailable"
    assert error["details"]["reason"] == "forge_unavailable"
    assert error["details"]["last"]["members"] == first["members"]
    view = owner.get("/projects/widget").json()["keep_the_why_export"]
    assert view["error"] == {"code": "ktw_unavailable", "reason": "forge_unavailable"}
    assert view["summary"]["entries"] == 7


def test_a_root_that_was_never_read_fails_without_a_last(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = forge.ForgeUnavailableError("down")
    flow.project(owner, "widget", repository={"url": REPO})
    error = owner.get("/projects/widget/keep-the-why").json()["error"]
    assert error["code"] == "ktw_unavailable" and "last" not in error["details"]


def test_the_caps_on_depth_and_members(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r", ["- a: a — s"])
    path = "a"
    for depth in range(1, 7):  # a chain six levels deep
        fake.files[f"{path}/.keep-the-why"] = kfile(f"{BASE}/{depth}.json", "x", ["- a: a — s"])
        path += "/a"
    flow.project(owner, "widget", repository={"url": REPO})
    body = owner.get("/projects/widget/keep-the-why").json()
    assert [m["path"].count("a") for m in body["members"]] == [0, 1, 2, 3, 4]
    assert body["family_truncated"] is True

    fake.files[".keep-the-why"] = kfile(
        f"{BASE}/s.json", "r", [f"- c{n}: c{n} — s" for n in range(40)] + ["- c1: c1 — again"]
    )
    for n in range(40):
        fake.files[f"c{n}/.keep-the-why"] = kfile(f"{BASE}/c{n}.json", f"c{n}")
    ktw.CACHE.clear()
    wide = owner.get("/projects/widget/keep-the-why").json()
    assert len(wide["members"]) == ktw.MAX_MEMBERS
    assert wide["family_truncated"] is True
    assert fake.file_reads.count("c1/.keep-the-why") == 1  # listed twice, read once


def test_at_most_four_exports_are_read_at_once(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(
        f"{BASE}/s.json", "r", [f"- c{n}: c{n} — s" for n in range(10)]
    )
    for n in range(10):
        fake.files[f"c{n}/.keep-the-why"] = kfile(f"{BASE}/c{n}.json", f"c{n}")
        fake.states[f"{BASE}/c{n}.json"] = export(entry(n))
    fake.delay = 0.05
    flow.project(owner, "widget", repository={"url": REPO})
    assert owner.get("/projects/widget/keep-the-why").status_code == 200
    assert 1 < fake.most_in_flight <= ktw.IN_FLIGHT


def test_the_cache_and_a_forced_read(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    owner.get("/projects/widget/keep-the-why")
    reads = len(fake.state_reads)
    cached = owner.get("/projects/widget/keep-the-why").json()
    assert cached["fresh"] is False and len(fake.state_reads) == reads
    forced_too_soon = owner.get("/projects/widget/keep-the-why", params={"max_age": 0}).json()
    assert forced_too_soon["fresh"] is False and len(fake.state_reads) == reads
    now[0] += ktw.FORCE_INTERVAL + 1
    forced = owner.get("/projects/widget/keep-the-why", params={"max_age": 0}).json()
    assert forced["fresh"] is True and len(fake.state_reads) == 2 * reads
    now[0] += ktw.DEFAULT_MAX_AGE + 1
    assert owner.get("/projects/widget/keep-the-why").json()["fresh"] is True


def test_more_than_200_entries_needing_attention_are_cut(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(f"{BASE}/s.json", "r")
    fake.states[f"{BASE}/s.json"] = export(*[entry(n, "open") for n in range(250)])
    flow.project(owner, "widget", repository={"url": REPO})
    body = owner.get("/projects/widget/keep-the-why").json()
    assert len(body["attention"]) == ktw.MAX_ATTENTION and body["truncated"] is True
    assert body["summary"]["attention"] == 250


def test_untrusted_names_and_ids_are_cleaned(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(
        f"{BASE}/s.json", "root\x1b]0;evil\x07" + "i" * 300, ["- bad‮name: hub — s"]
    )
    fake.files["hub/.keep-the-why"] = kfile(f"{BASE}/hub.json", "hub")
    fake.states[f"{BASE}/s.json"] = export()
    fake.states[f"{BASE}/hub.json"] = export()
    flow.project(owner, "widget", repository={"url": REPO})
    root, hub = owner.get("/projects/widget/keep-the-why").json()["members"]
    assert "\x1b" not in root["id"] and len(root["id"]) == 200 and root["id"].endswith("…")
    assert hub["name"] == "badname"


# --- the project view ----------------------------------------------------------------------------


def test_the_view_shows_the_cached_export_and_never_reads(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(
        ktw, "_refresh_later", lambda reader, pid, url, schedule: scheduled.append(pid)
    )
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    view = owner.get("/projects/widget").json()
    assert view["keep_the_why_export"] is None
    assert fake.file_reads == [] and fake.state_reads == []  # nothing read in the request
    assert scheduled  # but a background read was scheduled
    owner.get("/projects/widget/keep-the-why")
    export_view = owner.get("/projects/widget").json()["keep_the_why_export"]
    assert set(export_view) == {"observed_at", "summary", "members", "family_truncated", "error"}
    assert export_view["summary"]["members"] == 5
    listed = owner.get("/projects").json()["items"][0]["keep_the_why_export"]
    assert listed == export_view


def test_the_background_read_fills_the_cache_once_per_project(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    project_id = _project_id(owner)
    jobs: list[Any] = []
    ktw._refresh_in_background(forge.Forge(None), project_id, REPO, jobs.append)
    ktw._refresh_in_background(forge.Forge(None), project_id, REPO, jobs.append)
    assert len(jobs) == 1  # one pending read per project
    jobs[0]()
    assert owner.get("/projects/widget").json()["keep_the_why_export"]["summary"]["members"] == 5
    ktw._refresh_in_background(forge.Forge(None), project_id, REPO, jobs.append)
    assert len(jobs) == 2  # done: the next one may be scheduled


def _project_id(owner: flow.Human) -> str:
    from sqlalchemy import select

    from maity_hub import tables as t

    engine = owner.client.app.state.engine  # type: ignore[attr-defined]
    with engine.begin() as conn:
        return str(conn.execute(select(t.project.c.id)).scalar_one())


def test_a_new_repository_forgets_the_export(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    owner.get("/projects/widget/keep-the-why")
    owner.patch("/projects/widget", {"repository": {"url": "https://github.com/acme/other"}})
    assert owner.get("/projects/widget").json()["keep_the_why_export"] is None


# --- review: foreign data stays with its member; the budget -------------------------------------


@pytest.mark.parametrize(
    ("body", "reason"),
    [(b"[" * 200000, "not_json"), (json.dumps(export(topics=5)).encode(), None)],
    ids=["deep-nesting", "topics-not-a-list"],
)
def test_a_broken_export_fails_only_its_member(
    owner: flow.Human, fake: Fake, body: bytes, reason: str | None
) -> None:
    fake.family()
    fake.states[f"{BASE}/hub/state.json"] = body
    flow.project(owner, "widget", repository={"url": REPO})
    answer = owner.get("/projects/widget/keep-the-why")
    assert answer.status_code == 200
    hub = answer.json()["members"][1]
    assert (hub["error"] or {}).get("reason") == reason
    assert answer.json()["members"][0]["error"] is None


def test_an_unexpected_error_digesting_an_export_is_shape(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.family()
    real = ktw.digest

    def digest(data: Any, link_base: str) -> ktw.Read:
        if "hub/" in link_base and "api" not in link_base:
            raise ZeroDivisionError("anything")
        return real(data, link_base)

    monkeypatch.setattr(ktw, "digest", digest)
    flow.project(owner, "widget", repository={"url": REPO})
    answer = owner.get("/projects/widget/keep-the-why")
    assert answer.status_code == 200
    assert answer.json()["members"][1]["error"]["reason"] == "shape"


def test_a_slow_family_ends_at_the_deadline(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ktw, "FAMILY_DEADLINE", 0.3)
    fake.family()
    fake.delay = 2.0
    flow.project(owner, "widget", repository={"url": REPO})
    started = time.monotonic()
    body = owner.get("/projects/widget/keep-the-why").json()
    assert time.monotonic() - started < 1.5
    read = [m for m in body["members"] if m["state_url"]]
    assert {m["error"]["reason"] for m in read} == {"timeout"}


def test_configs_past_the_deadline_are_not_read(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ktw, "FAMILY_DEADLINE", 0.0)
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    body = owner.get("/projects/widget/keep-the-why").json()
    assert fake.file_reads == [".keep-the-why"]
    children = [m for m in body["members"][1:] if "://" not in m["path"]]
    assert {m["error"]["reason"] for m in children} == {"timeout"}


def test_a_request_waiting_on_a_long_read_gets_the_cache_or_503(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ktw, "FAMILY_DEADLINE", 0.1)
    monkeypatch.setattr(ktw, "LOCK_WAIT", 0.1)
    fake.family()
    flow.project(owner, "widget", repository={"url": REPO})
    project_id = _project_id(owner)
    lock = ktw.CACHE._lock(project_id)
    lock.acquire()
    try:
        busy = owner.get("/projects/widget/keep-the-why")
        assert busy.status_code == 503
        assert busy.json()["error"]["code"] == "ktw_unavailable"
    finally:
        lock.release()
    owner.get("/projects/widget/keep-the-why")  # cached now
    lock.acquire()
    try:
        cached = owner.get("/projects/widget/keep-the-why", params={"max_age": 0})
        assert cached.status_code == 200 and cached.json()["fresh"] is False
    finally:
        lock.release()


def test_zero_width_and_direction_marks_are_removed() -> None:
    marks = "a​b‌c‍d‎e‏f؜g﻿h"
    assert ktw.text(marks, 100) == "abcdefgh"
