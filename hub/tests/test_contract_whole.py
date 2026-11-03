"""docs/api.md §6.8 "The whole contract" and "The setting": the file `settings.contract_path`
names, read whole with its table of contents, checked segment by segment in the commit's
trees, under an `ETag` (tsk-zd9es4kp51w1)."""

from __future__ import annotations

import base64
import urllib.parse
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import contract_text, forge, probe
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_probe import REPO, SHA, TOKEN, FakeGitHub

OTHER = "e" * 40
URL = "/projects/maintainer/maity/contract"
API = """# Maity API

## 6 Cards

### 6.2 Members

```
## 9 Not a heading
```

#### 6.2.1 Roles

## 8. Events

## Notes

## 6 Again

##### Too deep
"""


class Forge(FakeGitHub):
    """The fake forge with raw reads: `raw[path]` answers a read for a file's raw bytes."""

    def __init__(self) -> None:
        super().__init__()
        self.raw: dict[str, Any] = {}

    def get(self, path: str, raw_cap: int | None = None) -> Any:
        if raw_cap is None:
            return self(path)
        self.calls.append("raw " + path)
        data = self.raw.get(path)
        return None if data is None else data[: raw_cap + 1]


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return replace(
        settings, forge_github_token=TOKEN, forge_instance_namespaces=frozenset({"maintainer"})
    )


@pytest.fixture(autouse=True)
def fresh() -> Iterator[None]:
    contract_text.forget()
    yield
    contract_text.forget()


def tree(fake: Forge, directory: str, entries: dict[str, str], **extra: Any) -> None:
    spec = SHA if directory == "" else f"{SHA}:{directory}"
    fake.answers[f"/repos/acme/maity/git/trees/{urllib.parse.quote(spec, safe='')}"] = {
        "sha": "t" * 40,
        "tree": [{"path": name, "mode": mode, "type": "x"} for name, mode in entries.items()],
        "truncated": False,
        **extra,
    }


def put(fake: Forge, path: str, data: bytes, ref: str = SHA) -> None:
    fake.answers[f"/repos/acme/maity/contents/{path}?ref={ref}"] = {
        "type": "file",
        "size": len(data),
        "encoding": "base64",
        "content": base64.b64encode(data).decode(),
    }


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> Forge:
    fake = Forge()
    monkeypatch.setattr(
        forge.Forge,
        "_get",
        lambda _self, path, uncached=False, raw_cap=None: fake.get(path, raw_cap),
    )
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    fake.branch("main", SHA)
    tree(fake, "", {"docs": "040000", "README.md": "100644"})
    tree(fake, "docs", {"api.md": "100644"})
    put(fake, "docs/api.md", API.encode())
    return fake


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, github: Forge) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity", repository=REPO)
    return owner


def error(response: Any) -> tuple[int, str, Any]:
    body = response.json()["error"]
    return response.status_code, body["code"], (body.get("details") or {}).get("fields")


def setting(owner: flow.Human, path: str | None) -> Any:
    return owner.patch("/projects/maintainer/maity", {"settings": {"contract_path": path}})


# --- the read -----------------------------------------------------------------------------


def test_the_default_file_is_read_whole_with_its_toc(owner: flow.Human) -> None:
    response = owner.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["path"], body["ref"], body["text"], body["size"]) == (
        "docs/api.md",
        SHA,
        API,
        len(API.encode()),
    )
    assert body["url"] == f"https://github.com/acme/maity/blob/{SHA}/docs/api.md"
    assert set(body) == {"path", "ref", "url", "size", "fetched_at", "toc", "text"}
    assert response.headers["Cache-Control"] == "private, no-cache"
    assert response.headers["ETag"].startswith('"')


def test_the_toc_numbers_anchors_and_lines() -> None:
    entries = contract_text.toc(API)
    shown = [(e["level"], e["number"], e["title"], e["anchor"], e["line"]) for e in entries]
    assert shown == [
        (2, "6", "Cards", "h-0", 3),  # `6` occurs twice: positions, never one shared anchor
        (3, "6.2", "Members", "s-6.2", 5),
        (4, "6.2.1", "Roles", "s-6.2.1", 11),  # the heading in the fence is skipped
        (2, "8", "Events", "s-8", 13),  # a trailing period dropped
        (2, None, "Notes", "h-4", 15),
        (2, "6", "Again", "h-5", 17),
    ]  # level 1 and level 5 are no entries


def test_a_toc_keeps_at_most_2000_headings_and_300_characters_a_title() -> None:
    long = "## " + "x" * 400 + "\n"
    entries = contract_text.toc(long + "".join(f"## {n} H\n" for n in range(2100)))
    assert len(entries) == contract_text.TOC_MAX
    assert len(entries[0]["title"]) == contract_text.TITLE_MAX


def test_the_etag_answers_304_and_follows_the_bytes_not_the_commit(
    owner: flow.Human, github: Forge
) -> None:
    first = owner.get(URL)
    etag = first.headers["ETag"]
    again = owner.get(URL, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["ETag"] == etag
    # A new commit with the same file keeps the tag; new bytes make a new one.
    contract_text.forget()
    github.branch("main", OTHER)
    for spec in (SHA, f"{SHA}:docs"):
        key = f"/repos/acme/maity/git/trees/{urllib.parse.quote(spec, safe='')}"
        github.answers[key.replace(SHA, OTHER)] = github.answers[key]
    put(github, "docs/api.md", API.encode(), ref=OTHER)
    same = owner.get(URL, headers={"If-None-Match": etag})
    assert same.status_code == 304
    contract_text.forget()
    put(github, "docs/api.md", (API + "\nmore\n").encode(), ref=OTHER)
    changed = owner.get(URL, headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["ETag"] != etag


def test_a_caller_without_project_read_gets_not_found_never_304(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    etag = owner.get(URL).headers["ETag"]
    stranger = flow.human(make_client, migrated, handle="stranger")
    response = stranger.get(URL, headers={"If-None-Match": etag})
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


def test_a_file_above_one_megabyte_is_read_raw_and_one_above_the_cap_is_too_large(
    owner: flow.Human, github: Forge
) -> None:
    big = ("## 1 Big\n" + "x" * (2 * 1024 * 1024)).encode()
    path = f"/repos/acme/maity/contents/docs/api.md?ref={SHA}"
    github.answers[path] = {"type": "file", "size": len(big), "encoding": "none", "content": ""}
    github.raw[path] = big
    body = owner.get(URL).json()
    assert (body["size"], body["toc"][0]["anchor"]) == (len(big), "s-1")
    assert "raw " + path in github.calls
    contract_text.forget()
    huge = b"x" * (contract_text.FILE_CAP + 1)
    github.answers[path] = {"type": "file", "size": len(huge), "encoding": "none", "content": ""}
    github.raw[path] = huge
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "too_large"})


def test_a_file_that_is_no_utf8_is_not_text(owner: flow.Human, github: Forge) -> None:
    put(github, "docs/api.md", b"\xff\xfe")
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "not_text"})


# --- what the name points to --------------------------------------------------------------


@pytest.mark.parametrize("mode", ["120000", "160000", "040000", "100664"])
def test_a_file_that_is_no_regular_file_is_not_markdown(
    owner: flow.Human, github: Forge, mode: str
) -> None:
    tree(github, "docs", {"api.md": mode})
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "not_markdown"})
    assert not any("/contents/" in call for call in github.calls)  # never the target's text


def test_a_directory_that_is_no_tree_is_not_markdown(owner: flow.Human, github: Forge) -> None:
    tree(github, "", {"docs": "120000"})  # a symlink to a directory
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "not_markdown"})


def test_a_truncated_tree_fails_closed_before_any_lookup(owner: flow.Human, github: Forge) -> None:
    tree(github, "", {"docs": "040000"}, truncated=True)  # the segment is even listed
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "not_markdown"})


def test_a_truncated_tree_without_the_segment_is_not_markdown_not_missing(
    owner: flow.Human, github: Forge
) -> None:
    """A cut tree cannot tell a missing entry from one cut off: the truncated check comes
    before the lookup, so the code is `not_markdown`, never `not_found_on_forge`."""
    tree(github, "", {"README.md": "100644"}, truncated=True)
    assert error(owner.get(URL)) == (400, "invalid", {"settings.contract_path": "not_markdown"})


def test_a_segment_a_complete_tree_does_not_list_is_not_found(
    owner: flow.Human, github: Forge
) -> None:
    tree(github, "docs", {"agents.md": "100644"})
    assert error(owner.get(URL)) == (
        404,
        "not_found",
        {"settings.contract_path": "not_found_on_forge"},
    )


def test_names_compare_byte_for_byte(owner: flow.Human, github: Forge) -> None:
    tree(github, "", {"Docs": "040000"})
    assert error(owner.get(URL))[2] == {"settings.contract_path": "not_found_on_forge"}


def test_a_commits_trees_are_read_once(owner: flow.Human, github: Forge) -> None:
    assert owner.get(URL).status_code == 200
    trees = len([c for c in github.calls if "/git/trees/" in c])
    with contract_text._lock:
        contract_text._reads.clear()  # the kept read gone, the trees stay
    assert owner.get(URL).status_code == 200
    assert len([c for c in github.calls if "/git/trees/" in c]) == trees == 2


# --- the setting --------------------------------------------------------------------------


def test_the_setting_names_a_markdown_file_and_null_restores_the_default(
    owner: flow.Human, github: Forge
) -> None:
    for path, reason in (
        ("../api.md", "not_a_path"),
        ("/docs/api.md", "not_a_path"),
        ("https://e.com/a.md", "not_a_path"),
        ("x/" * 130 + "a.md", "not_a_path"),
        (".env", "not_markdown"),
        ("docs/api.md.txt", "not_markdown"),
    ):
        assert error(setting(owner, path)) == (
            400,
            "invalid",
            {"settings.contract_path": reason},
        ), path
    assert setting(owner, "README.MD").status_code == 200
    tree(github, "", {"docs": "040000", "README.MD": "100644"})
    put(github, "README.MD", b"## 1 Readme\n")
    assert owner.get(URL).json()["path"] == "README.MD"
    assert setting(owner, None).status_code == 200
    assert owner.get(URL).json()["path"] == "docs/api.md"
