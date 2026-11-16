"""docs/api.md §16.11, "Addresses that can never be a page": `404` with the app shell as the body
for a path whose words alone show that no page can have it; a handle- or project-shaped address
stays the shell's `200` whether or not the name exists (context/routing.md e34ae588)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import paths, public_pages
from tests import flow
from tests.conftest import ClientFactory

SHELL = '<!doctype html><title>shell</title><main id="main"></main>'

NEVER = [
    # The first segment is no handle by §6.24's syntax, at any depth.
    "/Oliver",
    "/x",
    "/favicon.ico",
    "/.well-known/security.txt",
    "/a_b/project",
    "/%zz",
    "/oliver%2Fsomething",  # split before decoding: the first segment holds the slash
    # A reserved first word that names no route.
    "/components",
    "/health/check",
    "/imprint",
    # More segments than the deepest route, outside a project's Why.
    "/someone/project/team/agt-a/sessions/abcd/more",
    "/someone/project/board/a/b/c/d",
    "/inbox/a/b/c/d/e/f",
    "/observe/someone/project/why/a/b/c",
    # A project's view word that is no view, `members` included, and `/<handle>/agents`.
    "/someone/project/nope",
    "/someone/project/members",
    "/someone/project/%zz",
    "/someone/agents",
]

STAYS = [
    # Handle- and project-shaped: the status must not tell whether the name exists.
    "/nobody-here",
    "/nobody-here/no-project",
    "/nobody-here/no-project/board",
    "/nobody-here/no-project/team/agt-a/sessions/abcd",
    "/nobody-here/agents/some-bot",
    "/nobody-here/no%2Fproject/board",  # an encoded slash stays inside its segment
    # `/observe/<owner>/<slug>` has no views: its one further segment is a chat's id.
    "/observe/nobody-here/no-project",
    "/observe/nobody-here/no-project/cnv-0301",
    "/observe/nobody-here/no-project/cnv-0301/more",  # only the depth counts under `observe`
    # Below a project's Why the depth has no bound.
    "/nobody-here/no-project/why/topic/hub/context/deep/er/still.md",
    # Words under the dashboard's own first words: the hub does not route them.
    "/inbox/anything",
    "/admin/no-such-section/x",
    "/sign-in/code",
    "/",
]


@pytest.fixture
def client(make_client: ClientFactory, web_dir: Any) -> Any:
    (web_dir / "index.html").write_text(SHELL, encoding="utf-8")
    return make_client()


@pytest.mark.parametrize("path", NEVER)
def test_an_address_that_can_never_be_a_page_is_404_with_the_shell(client: Any, path: str) -> None:
    answer = client.get(path, follow_redirects=False)
    assert answer.status_code == 404, path
    assert answer.headers["content-type"].startswith("text/html")
    assert "<title>shell</title>" in answer.text  # the dashboard draws its "not found"
    assert answer.headers["cache-control"] == "no-cache"
    assert answer.headers["x-robots-tag"] == "noindex"
    head = client.head(path, follow_redirects=False)
    assert head.status_code == 404, path


@pytest.mark.parametrize("path", STAYS)
def test_a_handle_or_project_shaped_address_stays_the_shell_with_200(
    client: Any, path: str
) -> None:
    answer = client.get(path, follow_redirects=False)
    assert answer.status_code == 200, path
    assert "<title>shell</title>" in answer.text
    assert answer.headers["x-robots-tag"] == "noindex"


def test_another_method_there_stays_not_found(client: Any) -> None:
    answer = client.post("/Oliver")
    assert answer.status_code == 404
    assert answer.json()["error"]["code"] == "not_found"


def test_the_words_are_the_contracts() -> None:
    assert paths.NO_ROUTE_FIRST <= paths.RESERVED_FIRST
    assert paths.DEEPEST == 6
    # Every reserved first word is itself a handle by syntax, so the syntax rule never hits one.
    assert all(
        paths.never_a_page("/" + word) is (word in paths.NO_ROUTE_FIRST)
        for word in paths.RESERVED_FIRST - paths.HUB_FIRST
    )


def test_an_escape_that_does_not_decode_leaves_the_segment_as_sent() -> None:
    # Invalid UTF-8 (`%C3%28`) is not replaced by U+FFFD: the segment stays as it was sent.
    assert paths.never_a_page("/ow/sl/%C3%28") and paths.never_a_page("/%C3%28")
    assert paths._segment("%C3%28") == "%C3%28"
    assert paths._segment("%zz") == "%zz"
    assert paths._segment("caf%C3%A9") == "café"
    # Strict like the dashboard: a valid escape beside one that is none decodes neither.
    assert paths._segment("%61b%zz") == "%61b%zz"
    assert paths._segment("%77hy%zz") == "%77hy%zz"
    assert paths._segment("a%2") == "a%2"
    assert paths._segment("%61b") == "ab"


def test_no_lookup_decides_it_and_a_session_changes_nothing(
    make_client: ClientFactory, migrated: Engine, web_dir: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The words alone: no public page is looked up, and a member's session gets the same `404`
    as a visitor (§16.11)."""
    (web_dir / "index.html").write_text(SHELL, encoding="utf-8")
    member = flow.human(make_client, migrated)

    def looked_up(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a public page was looked up")

    monkeypatch.setattr(public_pages, "answer", looked_up)
    visitor = make_client()
    for path in NEVER:
        assert visitor.get(path, follow_redirects=False).status_code == 404, path
        assert member.client.get(path, follow_redirects=False).status_code == 404, path
