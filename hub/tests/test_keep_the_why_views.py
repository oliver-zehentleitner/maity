"""docs/api.md §11.5: the Keep the Why views' reads, an export whole and a lean export's texts."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import forge, ktw, ktw_reads, outbound
from tests import flow
from tests.conftest import ClientFactory
from tests.test_keep_the_why import BASE, REPO, Fake, entry, export, kfile

PATH = "/projects/maintainer/widget/keep-the-why"
# §11.4's own visibility check, kept before the fixture replaces it for the other tests
REAL_REQUIRE_PUBLIC = forge.Forge._require_public
OTHER = "https://github.com/acme/other"
OTHER_BASE = "https://other.example/ktw"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Fake:
    """§11.3's fake, with files per repository: `files` for acme/widget, `foreign` for others,
    and the repositories the forge reports public."""
    found = Fake(monkeypatch)
    found.foreign = {}  # type: ignore[attr-defined]
    found.public = {"acme/other"}  # type: ignore[attr-defined]
    found.public_asked = []  # type: ignore[attr-defined]

    found.readers = []  # type: ignore[attr-defined]

    def file(self: forge.Forge, repository: str, path: str, cap: int) -> bytes | None:
        found.file_reads.append(f"{repository}:{path}")
        found.readers.append((repository, self.token, self.granted))  # type: ignore[attr-defined]
        source = (
            found.files
            if repository.lower() == "acme/widget"
            else found.foreign.get(repository.lower(), {})  # type: ignore[attr-defined]
        )
        value = source.get(path)
        if isinstance(value, BaseException):
            raise value
        return value

    found.moved = set()  # type: ignore[attr-defined]

    def visibility(reader: forge.Forge, repository: str) -> str | None:
        found.public_asked.append(repository)  # type: ignore[attr-defined]
        found.readers.append((repository, reader.token, reader.granted))  # type: ignore[attr-defined]
        if repository in found.moved:  # type: ignore[attr-defined]
            return "repository_moved"
        return None if repository in found.public else "not_public"  # type: ignore[attr-defined]

    monkeypatch.setattr(forge.Forge, "file", file)
    monkeypatch.setattr(ktw_reads, "_visibility", visibility)
    # A source that covers the project (§11.4): the owner's grant, or with `instance` the
    # operator's token, whose visibility check `own_private` fails; refusals are tests below.
    found.refused = None  # type: ignore[attr-defined]
    found.instance = False  # type: ignore[attr-defined]
    found.own_private = False  # type: ignore[attr-defined]

    def for_project(self: forge.Forge, project_id: str) -> forge.Forge:
        if found.instance:  # type: ignore[attr-defined]
            return forge.Forge("instance-token", refused=found.refused)  # type: ignore[attr-defined]
        return forge.Forge(
            "owner-grant",
            granted="owner_token",
            repository="acme/widget",
            refused=found.refused,  # type: ignore[attr-defined]
        )

    def require_public(self: forge.Forge, repository: str) -> None:
        if found.own_private:  # type: ignore[attr-defined]
            raise forge.NotCoveredError("private_without_grant")

    monkeypatch.setattr(forge.Forge, "for_project", for_project)
    monkeypatch.setattr(forge.Forge, "_require_public", require_public)
    return found


def lean(fake: Fake, url: str, *entries: Any) -> None:
    """A lean export at `url`, its bodies in state.body.json beside it."""
    fake.states[url] = export(*entries, bodies="state.body.json")
    fake.states[url.rsplit("/", 1)[0] + "/state.body.json"] = {
        "state-json": 2,
        "bodies": {e["id"]: {"text": f"text of {e['id']}"} for e in entries},
    }


def project(owner: flow.Human) -> None:
    flow.project(owner, "widget", repository={"url": REPO})


# --- the project's own repository ---------------------------------------------------------------


def test_the_root_export_is_served_whole(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    fake.states[f"{BASE}/state.json"] = export(entry(1), extra={"kept": ["as", "published"]})
    project(owner)
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 200
    body = answer.json()
    assert body["canonical"] == "https://github.com/acme/widget"
    assert body["root"] == "" and body["url"] == f"{BASE}/state.json"
    assert body["fork_of"] is None and isinstance(body["observed_at"], str)
    # whole: nothing removed or added, unknown keys and `bodies` included
    assert body["state"] == fake.states[f"{BASE}/state.json"]
    assert answer.headers["Cache-Control"] == "private, no-cache"
    assert answer.headers["ETag"].startswith('"')


def test_a_member_is_served_by_its_path(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    project(owner)
    hub = owner.get(f"{PATH}/export", params={"root": "hub"}).json()
    assert hub["root"] == "hub" and hub["url"] == f"{BASE}/hub/state.json"
    assert [e["id"] for e in hub["state"]["entries"]] == ["hub.md#e3", "hub.md#e4", "hub.md#e5"]
    nested = owner.get(f"{PATH}/export", params={"root": "hub/api"}).json()
    assert nested["url"] == f"{BASE}/hub/api/state.json"
    own = owner.get(f"{PATH}/export", params={"canonical": REPO + "/", "root": "cli"}).json()
    assert own["url"] == f"{BASE}/cli/state.json"


def test_a_path_outside_the_family_is_not_in_family(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    project(owner)
    for root in ("web", "hub/..", "https://github.com/acme/other"):
        answer = owner.get(f"{PATH}/export", params={"root": root})
        assert answer.status_code == 404, root
        assert answer.json()["error"]["details"]["reason"] == "not_in_family"


def test_the_export_read_for_the_summary_is_answered_from_the_store(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    project(owner)
    owner.get(PATH)  # §11.3 reads every member's export
    reads = len(fake.state_reads)
    for root in ("", "hub", "hub/api", "cli"):
        assert owner.get(f"{PATH}/export", params={"root": root}).status_code == 200
    assert len(fake.state_reads) == reads, "a second read of an export §11.3 had just read"


def test_the_etag_revalidates_after_authorization(
    owner: flow.Human, fake: Fake, make_client: ClientFactory, migrated: Engine
) -> None:
    fake.family()
    project(owner)
    first = owner.get(f"{PATH}/export")
    etag = first.headers["ETag"]
    again = owner.get(f"{PATH}/export", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert owner.get(f"{PATH}/export", params={"root": "hub"}).headers["ETag"] != etag
    stranger = flow.human(make_client, migrated, handle="stranger")
    refused = stranger.get(f"{PATH}/export", headers={"If-None-Match": etag})
    assert refused.status_code == 404


def test_a_member_that_failed_is_ktw_unavailable_with_its_reason(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    fake.states[f"{BASE}/cli/state.json"] = (500, b"")
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"root": "cli"})
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["code"] == "ktw_unavailable"
    assert error["details"]["reason"] == "http_status" and error["details"]["status"] == 500


@pytest.mark.parametrize(
    ("published", "reason"),
    [
        (b'{"state-json": 2, "entries": [], "x": NaN}', "not_json"),
        ('{"state-json": 2, "entries": []}'.encode("utf-16"), "not_json"),
        ({"state-json": 3, "entries": []}, "state_json_version"),
        ({"state-json": 2, "entries": {}}, "shape"),
    ],
)
def test_an_export_a_browser_could_not_read_is_refused(
    owner: flow.Human, fake: Fake, published: Any, reason: str
) -> None:
    fake.family()
    fake.states[f"{BASE}/cli/state.json"] = published
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"root": "cli"})
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == reason


def test_a_failed_refresh_answers_with_the_last_good_export(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    project(owner)
    good = owner.get(f"{PATH}/export", params={"root": "cli"}).json()
    fake.states[f"{BASE}/cli/state.json"] = (502, b"")
    now[0] += ktw.DEFAULT_MAX_AGE + 1
    ktw.CACHE.clear()  # the family is read again, the member fails
    answer = owner.get(f"{PATH}/export", params={"root": "cli"})
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["details"]["reason"] == "http_status"
    assert error["details"]["last"]["state"] == good["state"]
    assert error["details"]["last"]["fresh"] is False


# --- bodies ------------------------------------------------------------------------------------


def test_a_lean_exports_bodies_are_served_from_beside_it(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    lean(fake, f"{BASE}/hub/state.json", entry(3), entry(4))
    project(owner)
    answer = owner.get(f"{PATH}/bodies", params={"root": "hub"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["url"] == f"{BASE}/hub/state.body.json"
    assert body["bodies"] == {
        "hub.md#e3": {"text": "text of hub.md#e3"},
        "hub.md#e4": {"text": "text of hub.md#e4"},
    }
    assert "fork_of" not in body
    again = owner.get(
        f"{PATH}/bodies", params={"root": "hub"}, headers={"If-None-Match": answer.headers["ETag"]}
    )
    assert again.status_code == 304


def test_an_export_with_its_bodies_inline_has_no_bodies_file(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    fake.states[f"{BASE}/state.json"] = {k: v for k, v in export(entry(1)).items() if k != "bodies"}
    project(owner)
    answer = owner.get(f"{PATH}/bodies")
    assert answer.status_code == 404
    assert answer.json()["error"]["details"]["reason"] == "no_bodies_file"


@pytest.mark.parametrize(
    "name",
    [
        "../secret.json",
        "https://evil.example/x.json",
        "//evil.example/x.json",
        "a/b.json",
        "state.body.txt",
        "x.json?y=1",
        "",
        ".json",
        "%2e%2e/x.json",
        "x" * 200 + ".json",
        "state.body.json\n",
        "st\u0430te.json",
    ],
)
def test_a_bodies_file_is_one_segment_beside_the_state(
    owner: flow.Human, fake: Fake, name: str
) -> None:
    fake.family()
    fake.states[f"{BASE}/state.json"] = export(entry(1), bodies=name)
    project(owner)
    owner.get(PATH)  # §11.3 reads the family's exports first
    reads = len(fake.state_reads)
    answer = owner.get(f"{PATH}/bodies")
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "bodies_url_invalid"
    assert len(fake.state_reads) == reads, "a bodies URL outside the state's directory was read"


def test_a_bodies_file_of_the_wrong_shape_is_refused(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    fake.states[f"{BASE}/state.json"] = export(entry(1), bodies="state.body.json")
    fake.states[f"{BASE}/state.body.json"] = {"bodies": ["not", "an", "object"]}
    project(owner)
    answer = owner.get(f"{PATH}/bodies")
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "shape"


def test_a_bodies_file_past_its_cap_is_too_large(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.family()
    lean(fake, f"{BASE}/state.json", entry(1))
    project(owner)
    caps: list[int] = []
    read = outbound.read

    def capped(url: str, *, cap: int, **kwargs: Any) -> Any:
        caps.append(cap)
        if url.endswith("state.body.json"):
            raise outbound.Refused("too_large")
        return read(url, cap=cap, **kwargs)

    monkeypatch.setattr(outbound, "read", capped)
    answer = owner.get(f"{PATH}/bodies")
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "too_large"
    assert ktw_reads.BODIES_CAP in caps


# --- repositories the family names ---------------------------------------------------------------


def other_repository(fake: Fake) -> None:
    fake.foreign["acme/other"] = {  # type: ignore[attr-defined]
        ".keep-the-why": kfile(f"{OTHER_BASE}/state.json", "acme---other", ["- lib: lib — a lib"]),
        "lib/.keep-the-why": kfile(f"{OTHER_BASE}/lib/state.json", "acme---other---lib"),
    }
    fake.states[f"{OTHER_BASE}/state.json"] = export(entry(10))
    fake.states[f"{OTHER_BASE}/lib/state.json"] = export(entry(11))


def test_a_public_repository_the_family_names_is_served(owner: flow.Human, fake: Fake) -> None:
    fake.family()  # names https://github.com/acme/other as a URL child
    other_repository(fake)
    project(owner)
    root = owner.get(f"{PATH}/export", params={"canonical": OTHER}).json()
    assert root["canonical"] == OTHER and root["url"] == f"{OTHER_BASE}/state.json"
    lib = owner.get(f"{PATH}/export", params={"canonical": OTHER, "root": "lib"}).json()
    assert lib["state"]["entries"][0]["id"] == "hub.md#e11"
    assert "acme/other" in fake.public_asked  # type: ignore[attr-defined]
    assert "acme/other:.keep-the-why" in fake.file_reads  # through the forge, not a raw host


def test_a_parent_line_names_a_repository(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(f"{BASE}/state.json", "acme---widget").replace(
        b"- context:", f"- parent: {OTHER}\n- context:".encode()
    )
    fake.states[f"{BASE}/state.json"] = export(entry(1))
    other_repository(fake)
    project(owner)
    assert owner.get(f"{PATH}/export", params={"canonical": OTHER}).status_code == 200


def test_a_private_named_repository_is_not_public(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    other_repository(fake)
    fake.public.clear()  # type: ignore[attr-defined]
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"canonical": OTHER})
    assert answer.status_code == 404
    assert answer.json()["error"]["details"]["reason"] == "not_public"
    assert not any(r.startswith("acme/other:") for r in fake.file_reads)


@pytest.mark.parametrize(
    "canonical",
    [
        "https://github.com/acme/elsewhere",
        "https://evil.example/acme/other",
        "http://github.com/acme/other",
        "https://github.com/acme",
        "javascript:alert(1)",
    ],
)
def test_a_repository_the_family_does_not_name_is_not_in_family(
    owner: flow.Human, fake: Fake, canonical: str
) -> None:
    fake.family()
    other_repository(fake)
    project(owner)
    owner.get(PATH)  # warm §11.3's cache
    reads = (len(fake.file_reads), len(fake.state_reads))
    answer = owner.get(f"{PATH}/export", params={"canonical": canonical})
    assert answer.status_code == 404
    assert answer.json()["error"]["details"]["reason"] == "not_in_family"
    assert (len(fake.file_reads), len(fake.state_reads)) == reads


def test_one_hop_a_named_repositorys_own_named_ones_are_not_followed(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    other_repository(fake)
    fake.foreign["acme/other"][".keep-the-why"] = kfile(  # type: ignore[attr-defined]
        f"{OTHER_BASE}/state.json", "acme---other", ["- far: https://github.com/acme/far — far"]
    )
    fake.foreign["acme/far"] = {".keep-the-why": kfile("https://far.example/state.json")}  # type: ignore[attr-defined]
    fake.public.add("acme/far")  # type: ignore[attr-defined]
    project(owner)
    assert owner.get(f"{PATH}/export", params={"canonical": OTHER}).status_code == 200
    far = owner.get(f"{PATH}/export", params={"canonical": "https://github.com/acme/far"})
    assert far.status_code == 404
    assert far.json()["error"]["details"]["reason"] == "not_in_family"


def test_at_most_eight_named_repositories(owner: flow.Human, fake: Fake) -> None:
    kids = [f"- r{n}: https://github.com/acme/r{n} — r" for n in range(10)]
    fake.files[".keep-the-why"] = kfile(f"{BASE}/state.json", "acme---widget", kids)
    fake.states[f"{BASE}/state.json"] = export(entry(1))
    for n in range(10):
        fake.foreign[f"acme/r{n}"] = {".keep-the-why": kfile(f"https://r{n}.example/state.json")}  # type: ignore[attr-defined]
        fake.states[f"https://r{n}.example/state.json"] = export(entry(n + 20))
        fake.public.add(f"acme/r{n}")  # type: ignore[attr-defined]
    project(owner)
    assert (
        owner.get(f"{PATH}/export", params={"canonical": "https://github.com/acme/r7"}).status_code
        == 200
    )
    past = owner.get(f"{PATH}/export", params={"canonical": "https://github.com/acme/r8"})
    assert past.status_code == 404
    assert past.json()["error"]["details"]["reason"] == "family_cap"


def test_named_repositories_keep_the_family_order(fake: Fake) -> None:
    members = [
        ktw.Member(path="", name=None, parent="https://github.com/acme/up"),
        ktw.Member(
            path="https://github.com/acme/kid",
            location="https://github.com/acme/kid",
            name="kid",
            error={"code": "ktw_unavailable", "reason": "location_not_followed"},
        ),
        ktw.Member(path="hub", name="hub", parent="https://github.com/ACME/up"),
        ktw.Member(
            path="https://gitlab.example/a/b",
            location="https://gitlab.example/a/b",
            name="x",
            error={"code": "ktw_unavailable", "reason": "location_not_followed"},
        ),
        ktw.Member(path="cli", name="cli", parent="https://github.com/acme/widget"),
    ]
    assert ktw_reads.named(members, "acme/widget") == ["acme/up", "acme/kid"]


# --- what the hub does not do -------------------------------------------------------------------


def test_no_project_read_no_answer(
    owner: flow.Human, fake: Fake, make_client: ClientFactory, migrated: Engine
) -> None:
    fake.family()
    project(owner)
    stranger = flow.human(make_client, migrated, handle="stranger")
    for kind in ("export", "bodies"):
        assert stranger.get(f"{PATH}/{kind}").status_code == 404
    assert fake.state_reads == []


def test_without_a_source_for_the_repository_it_is_probe_not_configured(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    fake.refused = "no_grant"  # type: ignore[attr-defined]
    project(owner)
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 409
    error = answer.json()["error"]
    assert error["code"] == "probe_not_configured" and error["details"]["reason"] == "no_grant"
    assert fake.state_reads == []


def test_without_a_repository_it_is_not_configured(owner: flow.Human, fake: Fake) -> None:
    flow.project(owner, "widget")
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "ktw_not_configured"


def test_the_store_keeps_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    store = ktw.RawStore()
    monkeypatch.setattr(ktw, "RAW_BUDGET", 100)
    store.put("state", "https://a.example/1", {"x": "a" * 40})
    store.put("state", "https://a.example/2", {"x": "b" * 40})
    store.get("state", "https://a.example/1")  # used: the second is the least recent
    store.put("state", "https://a.example/3", {"x": "c" * 40})
    assert store.get("state", "https://a.example/2") is None
    assert store.get("state", "https://a.example/1") is not None
    assert store.size <= 100
    store.put("state", "https://a.example/big", {"x": "d" * 500})  # larger than the budget
    assert store.get("state", "https://a.example/big") is None and store.size <= 100


def test_the_answer_splices_the_kept_bytes_as_valid_json() -> None:
    raw = ktw.RawStore().put("state", "https://a.example/s.json", {"t": 'ä   "q"'})
    served = ktw_reads.Served("https://github.com/a/b", "", raw, True)
    doc = json.loads(served.document("state"))
    assert doc["state"] == {"t": 'ä   "q"'} and doc["fresh"] is True


# --- the review round: names, redirects, holds, budgets ---------------------------------------


@pytest.mark.parametrize(
    ("url", "repository"),
    [
        ("https://github.com/acme/other", "acme/other"),
        ("https://github.com/ACME/Other.git", "acme/other"),
        ("https://github.com/acme/other/", "acme/other"),
        ("https://github.com/acme/other.git/", "acme/other"),
        ("https://github.com/acme/my.repo_1-x", "acme/my.repo_1-x"),
        ("https://github.com/acme/other/tree/main", None),
        ("https://github.com/acme/other?x=1", None),
        ("https://github.com/acme/other#x", None),
        ("https://user@github.com/acme/other", None),
        ("https://github.com:443/acme/other", None),
        ("https://github.com/acme/%2e%2e", None),
        ("https://github.com/acme/..", None),
        ("https://github.com/acme/.", None),
        ("https://github.com/ac_me/other", None),
        ("https://github.com/" + "a" * 40 + "/other", None),
        ("https://github.com/acme/other//", None),
        ("https://github.com/acme/ other", None),
        ("https://GITHUB.com/acme/other", None),
        ("http://github.com/acme/other", None),
        ("https://gitlab.com/acme/other", None),
        ("git@github.com:acme/other.git", None),
        ("../other", None),
        ("https://github.com/acme/other\n", None),
        ("https://github.com/acme/.git", None),
        ("https://github.com/acme/other.git.git", None),
        ("https://github.com/acme/other.GIT.git", None),
        ("https://github.com/acme/.git/", None),
        ("https://github.com/ac\u200bme/other", None),  # zero-width space
        ("https://github.com/\u043ewner/repo", None),  # Cyrillic о
        ("https://github.com/owner/r\u0435po", None),  # Cyrillic е
        ("https://github.com/owner/r\u0130po", None),  # dotted capital I, which lower() changes
        ("https://github.com/owner/\uff52epo", None),  # fullwidth r
        ("https://github.com/" + "a" * 39 + "/" + "b" * 100, "a" * 39 + "/" + "b" * 100),
        ("https://github.com/acme/" + "b" * 101, None),
    ],
)
def test_a_repository_is_named_in_exactly_one_form(url: str, repository: str | None) -> None:
    assert ktw_reads._repository(url) == repository


def test_a_name_in_another_form_takes_no_place(fake: Fake) -> None:
    def child(path: str) -> ktw.Member:
        return ktw.Member(
            path=path,
            location=path,
            name="x",
            error={"code": "ktw_unavailable", "reason": "location_not_followed"},
        )

    members = [child(f"https://github.com/acme/r{n}/tree/main") for n in range(4)]
    members += [child(f"https://github.com/acme/r\u0435po{n}") for n in range(4)]  # Cyrillic е
    members.append(child("https://github.com/acme/real"))
    assert ktw_reads.named(members, "acme/widget") == ["acme/real"]


def test_a_named_repository_that_moved_is_not_followed(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    other_repository(fake)
    fake.moved.add("acme/other")  # type: ignore[attr-defined]
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"canonical": OTHER})
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "repository_moved"
    assert not any(r.startswith("acme/other:") for r in fake.file_reads)


def test_a_repository_that_turns_private_is_dropped_on_the_next_refresh(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    other_repository(fake)
    project(owner)
    first = owner.get(f"{PATH}/export", params={"canonical": OTHER})
    assert first.status_code == 200
    fake.public.clear()  # type: ignore[attr-defined]
    again = owner.get(
        f"{PATH}/export",
        params={"canonical": OTHER},
        headers={"If-None-Match": first.headers["ETag"]},
    )
    assert again.status_code == 304, "inside max_age the cached family answers"
    now[0] += ktw.DEFAULT_MAX_AGE + 1
    gone = owner.get(
        f"{PATH}/export",
        params={"canonical": OTHER},
        headers={"If-None-Match": first.headers["ETag"]},
    )
    assert gone.status_code == 404, "a refusal comes before If-None-Match"
    assert gone.json()["error"]["details"]["reason"] == "not_public"


def test_a_file_dropped_for_room_is_not_read_again_within_30_seconds(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    lean(fake, f"{BASE}/state.json", entry(1))
    project(owner)
    assert owner.get(f"{PATH}/bodies").status_code == 200
    ktw.RAW.files.pop(("bodies", f"{BASE}/state.body.json"))  # dropped for room
    reads = len(fake.state_reads)
    held = owner.get(f"{PATH}/bodies")
    assert held.status_code == 503
    assert held.json()["error"]["details"]["reason"] == "timeout"
    assert len(fake.state_reads) == reads
    now[0] += ktw.FORCE_INTERVAL + 1
    assert owner.get(f"{PATH}/bodies").status_code == 200
    assert len(fake.state_reads) == reads + 1


def test_a_spent_budget_is_probe_unavailable_with_retry_at(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    fake.family()
    project(owner)
    when = datetime(2099, 11, 3, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(forge.Forge, "retry_at", lambda self: when)
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["code"] == "probe_unavailable"
    assert error["details"]["retry_at"].startswith("2099-11-03T12:00:00")
    assert fake.state_reads == []


# --- the review of #1280: surrogates, finite numbers, raw names, visibility -------------------


def test_a_lone_surrogate_is_served_escaped_not_a_500(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    fake.states[f"{BASE}/state.json"] = (
        b'{"state-json": 2, "entries": [{"id": "a", "title": "x\\ud800y", "status": "open"}],'
        b' "bodies": "state.body.json"}'
    )
    fake.states[f"{BASE}/state.body.json"] = b'{"bodies": {"a": {"text": "t\\udc00"}}}'
    project(owner)
    summary = owner.get(PATH).json()
    root = next(m for m in summary["members"] if m["path"] == "")
    assert root["error"] is None, "§11.3 reads it as before"
    state = owner.get(f"{PATH}/export")
    assert state.status_code == 200
    assert (
        b"\\ud800" in state.content and state.json()["state"]["entries"][0]["title"] == "x\ud800y"
    )
    bodies = owner.get(f"{PATH}/bodies")
    assert bodies.status_code == 200
    assert bodies.json()["bodies"]["a"]["text"] == "t\udc00"
    state.content.decode("ascii")  # escaped: the answer is plain ASCII


@pytest.mark.parametrize("number", [b"1e400", b"-1e400", b"1" + b"0" * 400 + b".0"])
def test_a_number_too_large_to_be_finite_is_not_json(
    owner: flow.Human, fake: Fake, number: bytes
) -> None:
    fake.family()
    fake.states[f"{BASE}/cli/state.json"] = (
        b'{"state-json": 2, "entries": [], "x": ' + number + b"}"
    )
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"root": "cli"})
    assert answer.status_code == 503
    assert answer.json()["error"]["details"]["reason"] == "not_json"


def test_a_name_is_checked_as_written_before_cleaning(owner: flow.Human, fake: Fake) -> None:
    fake.files[".keep-the-why"] = kfile(
        f"{BASE}/state.json", "acme---widget", ["- other: https://github.com/ac\u200bme/other — x"]
    ).replace(b"- context:", "- parent: https://github.com/acme/oth\u200ber\n- context:".encode())
    fake.states[f"{BASE}/state.json"] = export(entry(1))
    other_repository(fake)
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"canonical": OTHER})
    assert answer.status_code == 404
    assert answer.json()["error"]["details"]["reason"] == "not_in_family"


def test_the_visibility_is_read_again_within_600_seconds_whatever_max_age(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    other_repository(fake)
    project(owner)
    params = {"canonical": OTHER, "max_age": 86400}
    assert owner.get(f"{PATH}/export", params=params).status_code == 200
    asked = len(fake.public_asked)  # type: ignore[attr-defined]
    now[0] += 599
    assert owner.get(f"{PATH}/export", params=params).status_code == 200
    assert len(fake.public_asked) == asked  # type: ignore[attr-defined]
    fake.public.clear()  # type: ignore[attr-defined]
    now[0] += 2
    gone = owner.get(f"{PATH}/export", params=params)
    assert gone.status_code == 404 and gone.json()["error"]["details"]["reason"] == "not_public"


class _Reader:
    """A forge reader whose `_get` answers as told (§11.5's `_visibility` against it)."""

    token = "instance"

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.asked: list[tuple[str, bool]] = []

    def _get(self, path: str, *, uncached: bool = False) -> Any:
        self.asked.append((path, uncached))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"private": False}, None),
        ({"private": True}, "not_public"),  # also when the token can read it: never served
        ({}, "not_public"),
        ({"private": None}, "not_public"),
        ({"private": "false"}, "not_public"),
        (None, "not_public"),  # 404
        ([], "not_public"),
        (forge.NotCoveredError("no_grant"), "not_public"),
        (forge.NotCoveredError("private_without_grant"), "not_public"),
        (forge.NotCoveredError("repository_moved"), "repository_moved"),
        (forge.ForgeUnavailableError("down"), "not_public"),
    ],
)
def test_the_real_visibility_check(answer: Any, expected: str | None) -> None:
    reader = _Reader(answer)
    assert ktw_reads._visibility(reader, "acme/other") == expected  # type: ignore[arg-type]
    assert reader.asked == [("/repos/acme/other", True)], "asks the forge itself, by the name"


def test_the_visibility_check_passes_a_spent_budget_on() -> None:
    from datetime import UTC, datetime

    spent = forge.ForgeUnavailableError("rate limited")
    spent.retry_at = datetime(2099, 11, 3, 12, 0, tzinfo=UTC)
    with pytest.raises(forge.ForgeUnavailableError):
        ktw_reads._visibility(_Reader(spent), "acme/other")  # type: ignore[arg-type]


def test_the_project_slots_stay_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ktw_reads, "SLOTS_KEPT", 3)
    busy = ktw_reads._slot("busy")
    busy.acquire()
    try:
        for n in range(10):
            ktw_reads._slot(f"p{n}")
        assert len(ktw_reads._slots) <= 4 and ktw_reads._slots["busy"] is busy
    finally:
        busy.release()


# --- be2n's review and the ruling on named repositories ---------------------------------------


def test_a_removed_grant_ends_the_cached_export_at_once(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    project(owner)
    first = owner.get(f"{PATH}/export")
    assert first.status_code == 200
    fake.refused = "no_grant"  # type: ignore[attr-defined]  # the owner unlinked the App
    for kind in ("export", "bodies"):
        answer = owner.get(f"{PATH}/{kind}", headers={"If-None-Match": first.headers["ETag"]})
        assert answer.status_code == 409, "never the export held in memory, never a 304"
        error = answer.json()["error"]
        assert error["code"] == "probe_not_configured" and error["details"]["reason"] == "no_grant"
        assert b"hub.md#e1" not in answer.content


def test_a_repository_turned_private_ends_the_cached_export_with_the_visibility_check(
    owner: flow.Human, fake: Fake
) -> None:
    fake.instance = True  # type: ignore[attr-defined]
    fake.family()
    project(owner)
    first = owner.get(f"{PATH}/export")
    assert first.status_code == 200
    fake.own_private = True  # type: ignore[attr-defined]
    answer = owner.get(f"{PATH}/export", headers={"If-None-Match": first.headers["ETag"]})
    assert answer.status_code == 409
    assert answer.json()["error"]["details"]["reason"] == "private_without_grant"


def test_the_reason_is_for_a_project_admin_only(
    owner: flow.Human, fake: Fake, make_client: ClientFactory
) -> None:
    fake.family()
    project(owner)
    member = flow.agent(make_client, owner, "widget")
    fake.refused = "unconfirmed"  # type: ignore[attr-defined]
    answer = member.get(f"{PATH}/export")
    assert answer.status_code == 409
    assert answer.json()["error"]["code"] == "probe_not_configured"
    assert answer.json()["error"]["details"] == {}
    assert owner.get(f"{PATH}/export").json()["error"]["details"]["reason"] == "unconfirmed"


def test_a_refusal_while_reading_the_family_is_probe_not_configured(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    fake.files[".keep-the-why"] = forge.NotCoveredError("repository_moved")
    project(owner)
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 409
    error = answer.json()["error"]
    assert error["code"] == "probe_not_configured"
    assert error["details"]["reason"] == "repository_moved"
    summary = owner.get(PATH)  # §11.3 answers as before
    assert summary.json()["error"]["code"] == "ktw_unavailable"


def _spent() -> forge.ForgeUnavailableError:
    from datetime import UTC, datetime

    return forge.ForgeUnavailableError(
        "rate limited", 403, rate_limited=True, retry_at=datetime(2099, 11, 3, 12, 0, tzinfo=UTC)
    )


def test_a_budget_spent_while_reading_the_family_is_probe_unavailable(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    fake.files[".keep-the-why"] = _spent()
    project(owner)
    answer = owner.get(f"{PATH}/export")
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["code"] == "probe_unavailable"
    assert error["details"]["retry_at"].startswith("2099-11-03T12:00:00")


def test_a_budget_spent_reading_a_named_repository_is_probe_unavailable(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    other_repository(fake)
    fake.foreign["acme/other"][".keep-the-why"] = _spent()  # type: ignore[attr-defined]
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"canonical": OTHER})
    assert answer.status_code == 503
    assert answer.json()["error"]["code"] == "probe_unavailable"


def test_named_repositories_are_never_read_with_the_owners_grant(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    other_repository(fake)
    project(owner)
    assert (
        owner.get(f"{PATH}/export", params={"canonical": OTHER, "root": "lib"}).status_code == 200
    )
    theirs = [r for r in fake.readers if r[0] == "acme/other"]  # type: ignore[attr-defined]
    ours = [r for r in fake.readers if r[0] == "acme/widget"]  # type: ignore[attr-defined]
    assert theirs and all(
        token != "owner-grant" and granted is None for _r, token, granted in theirs
    )
    assert ours and all(token == "owner-grant" for _r, token, _g in ours)


def test_a_cold_read_is_fresh_and_the_next_is_not(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    lean(fake, f"{BASE}/state.json", entry(1))
    project(owner)
    assert owner.get(f"{PATH}/export").json()["fresh"] is True
    assert owner.get(f"{PATH}/export").json()["fresh"] is False
    assert owner.get(f"{PATH}/bodies").json()["fresh"] is True
    assert owner.get(f"{PATH}/bodies").json()["fresh"] is False


def test_a_stale_file_whose_refresh_failed_is_not_read_again_within_30_seconds(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    lean(fake, f"{BASE}/state.json", entry(1))
    project(owner)
    assert owner.get(f"{PATH}/bodies").status_code == 200
    fake.states[f"{BASE}/state.body.json"] = (502, b"")
    now[0] += ktw.DEFAULT_MAX_AGE + 1
    failed = owner.get(f"{PATH}/bodies")
    assert failed.status_code == 503
    reads = len(fake.state_reads)
    now[0] += 5
    held = owner.get(f"{PATH}/bodies")
    assert held.status_code == 200 and held.json()["fresh"] is False, "the last good, held"
    assert len(fake.state_reads) == reads, "no upstream read inside the 30 s"
    now[0] += ktw.FORCE_INTERVAL
    owner.get(f"{PATH}/bodies")
    assert len(fake.state_reads) > reads


class _Anonymous:
    """A reader without a token: `_visibility` asks the forge anonymously (`_send`)."""

    token = None

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.sent: list[str] = []

    def _get(self, path: str, *, uncached: bool = False) -> Any:
        raise AssertionError("_get needs a token")

    def _send(self, path: str) -> Any:
        self.sent.append(path)
        return self.answer


def test_the_visibility_is_read_anonymously_without_a_token() -> None:
    reader = _Anonymous({"private": False})
    assert ktw_reads._visibility(reader, "acme/other") is None  # type: ignore[arg-type]
    assert reader.sent == ["/repos/acme/other"]
    assert ktw_reads._visibility(_Anonymous({"private": True}), "acme/other") == "not_public"  # type: ignore[arg-type]


def test_the_named_reader_is_the_instance_token_only_where_it_serves_the_project() -> None:
    base = forge.Forge("instance", access=object())
    grant = forge.Forge("owner-grant", granted="owner_token", repository="acme/widget")
    served = forge.Forge("instance")  # the project's own source is the instance (§11.4)
    refused = forge.Forge("instance", refused="no_grant")
    assert ktw_reads.named_reader(base, served).token == "instance"
    assert ktw_reads.named_reader(base, grant).token is None, "an owner's project: anonymous"
    assert ktw_reads.named_reader(base, refused).token is None
    assert ktw_reads.named_reader(forge.Forge(None), served).token is None
    reader = ktw_reads.named_reader(base, served)
    assert reader.granted is None and reader.access is None and reader.project_id is None


def test_a_budget_spent_reading_a_childs_config_is_probe_unavailable(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    fake.files["hub/.keep-the-why"] = _spent()
    project(owner)
    answer = owner.get(f"{PATH}/export", params={"root": "hub"})
    assert answer.status_code == 503
    error = answer.json()["error"]
    assert error["code"] == "probe_unavailable" and error["details"]["retry_at"].startswith("2099")
    assert owner.get(f"{PATH}/export", params={"root": "cli"}).status_code == 200


def test_a_retry_at_that_passed_is_read_again_not_repeated(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime

    now = [1000.0]
    monkeypatch.setattr(ktw, "_now", lambda: now[0])
    fake.family()
    root = fake.files[".keep-the-why"]
    past = forge.ForgeUnavailableError(
        "rate limited", 403, rate_limited=True, retry_at=datetime(2000, 1, 1, tzinfo=UTC)
    )
    fake.files[".keep-the-why"] = past
    project(owner)
    first = owner.get(f"{PATH}/export")
    assert first.status_code == 503  # the walk found the budget spent; its time is long past
    fake.files[".keep-the-why"] = root  # the forge answers again
    now[0] += ktw.FORCE_INTERVAL + 1
    again = owner.get(f"{PATH}/export")
    assert again.status_code == 200, "not the same 503 until the cached snapshot expires"


def test_a_repository_turned_private_ends_within_the_ten_minutes_of_the_real_check(
    owner: flow.Human, fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With §11.4's own visibility check and its cache, not a stub: served while the check's
    answer is younger than PUBLIC_SECONDS, refused after it is read again."""
    import time as real_time

    monkeypatch.setattr(forge.Forge, "_require_public", REAL_REQUIRE_PUBLIC)
    fake.family()
    private = [False]
    sent: list[str] = []

    def send(self: forge.Forge, path: str, *args: Any, **kwargs: Any) -> Any:
        sent.append(path)
        return {"private": private[0]}

    clock_now = [real_time.monotonic()]
    monkeypatch.setattr(forge.Forge, "_send", send)
    monkeypatch.setattr(real_time, "monotonic", lambda: clock_now[0])
    monkeypatch.setattr(
        forge.Forge, "for_project", lambda self, project_id: forge.Forge("instance")
    )
    project(owner)
    first = owner.get(f"{PATH}/export")
    assert first.status_code == 200
    private[0] = True
    clock_now[0] += forge.PUBLIC_SECONDS - 5
    within = owner.get(f"{PATH}/export")
    assert within.status_code == 200, "inside the check's 10 minutes, as §11.5 says"
    clock_now[0] += 10
    after = owner.get(f"{PATH}/export", headers={"If-None-Match": first.headers["ETag"]})
    assert after.status_code == 409
    assert after.json()["error"]["details"]["reason"] == "private_without_grant"
    assert sent.count("/repos/acme/widget") == 2


# --- be2n's second review ----------------------------------------------------------------------


def test_the_visibility_verdict_is_dropped_whatever_the_case_of_the_name() -> None:
    """`_require_public` keys its verdict as `_forget` drops it: lower case (forge.py)."""
    reader = forge.Forge("instance")
    key = (forge.hashlib.sha256(b"instance").hexdigest(), "acme/widget")  # type: ignore[attr-defined]
    forge._public[key] = (forge.time.monotonic(), None)  # type: ignore[attr-defined]
    reader.require_covered("Acme/Widget")  # the verdict found under its lower-case key
    reader._forget("Acme/Widget")
    assert key not in forge._public


def test_an_owners_reason_is_given_and_the_project_told(monkeypatch: pytest.MonkeyPatch) -> None:
    told: list[str] = []

    class Access:
        def not_covered(self, project_id: str) -> None:
            told.append(project_id)

    def refuse(self: forge.Forge, repository: str) -> None:
        raise forge.NotCoveredError("private_without_grant")

    monkeypatch.setattr(forge.Forge, "_require_public", refuse)
    reader = forge.Forge("instance", project_id="p1", owner_reason="unconfirmed", access=Access())
    with pytest.raises(forge.NotCoveredError) as error:
        reader.require_covered("acme/widget")
    assert error.value.reason == "unconfirmed" and told == ["p1"]
    plain = forge.Forge("instance", project_id="p1", access=Access())
    with pytest.raises(forge.NotCoveredError) as error:
        plain.require_covered("acme/widget")
    assert error.value.reason == "private_without_grant"
    forge.Forge("grant", granted="app").require_covered("acme/widget")  # nothing to check


def test_a_cold_named_repository_with_a_spent_budget_stays_probe_unavailable(
    owner: flow.Human, fake: Fake
) -> None:
    fake.family()
    other_repository(fake)
    fake.foreign["acme/other"][".keep-the-why"] = _spent()  # type: ignore[attr-defined]
    project(owner)
    for _ in range(2):  # the second inside 30 s: still the budget, not a timeout
        answer = owner.get(f"{PATH}/export", params={"canonical": OTHER})
        assert answer.status_code == 503
        assert answer.json()["error"]["code"] == "probe_unavailable"


def test_a_failed_read_answers_its_own_error_inside_the_hold(owner: flow.Human, fake: Fake) -> None:
    fake.family()
    lean(fake, f"{BASE}/state.json", entry(1))
    fake.states[f"{BASE}/state.body.json"] = (502, b"")
    project(owner)
    first = owner.get(f"{PATH}/bodies")
    reads = len(fake.state_reads)
    second = owner.get(f"{PATH}/bodies")
    for answer in (first, second):
        assert answer.status_code == 503
        assert answer.json()["error"]["details"] == {"reason": "http_status", "status": 502}
    assert len(fake.state_reads) == reads, "not read again inside the 30 s"
