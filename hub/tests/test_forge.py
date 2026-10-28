"""docs/api.md §11: the forge reads themselves — `forge._get` against a fake opener,
the redirect guard, check runs and commit statuses, a repository the token cannot see."""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import time
import urllib.error
import urllib.request
from typing import Any

import pytest

from maity_hub import forge

TOKEN = "ghp_test_token_value_never_printed"
SHA = "d91e294c" + "0" * 32


class FakeOpener:
    """Answers by URL path (with query); records each request it was given."""

    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requests.append(request)
        path = request.full_url.removeprefix(f"https://{forge.API_HOST}")
        answer = self.answers.get(path, self.answers.get(path.split("?")[0]))
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):  # (status, headers)
            status, headers = answer
            raise urllib.error.HTTPError(request.full_url, status, "error", headers, None)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, "error", {}, None)  # type: ignore[arg-type]
        if answer is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return io.BytesIO(json.dumps(answer).encode())


READER = forge.Forge(TOKEN)


@pytest.fixture
def opener(monkeypatch: pytest.MonkeyPatch) -> FakeOpener:
    """The reads below are about `a/b`, which the forge reported public a moment ago: the
    visibility check itself has its own tests (`seen`)."""
    fake = FakeOpener()
    monkeypatch.setattr(forge, "_opener", fake)
    monkeypatch.setattr(forge, "_public", {(_digest(TOKEN), "a/b"): (time.monotonic(), None)})
    return fake


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> FakeOpener:
    """A fake forge with no visibility known yet."""
    fake = FakeOpener()
    monkeypatch.setattr(forge, "_opener", fake)
    monkeypatch.setattr(forge, "_public", {})
    return fake


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _paths(opener: FakeOpener) -> list[str]:
    return [r.full_url.removeprefix(f"https://{forge.API_HOST}") for r in opener.requests]


# --- _get ----------------------------------------------------------------------------------


def test_a_read_goes_to_the_api_host_with_the_token_and_the_api_headers(
    opener: FakeOpener,
) -> None:
    opener.answers["/repos/a/b"] = {"full_name": "a/b"}
    assert READER._get("/repos/a/b") == {"full_name": "a/b"}
    [request] = opener.requests
    assert request.full_url == "https://api.github.com/repos/a/b"
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"


def test_a_404_is_none(opener: FakeOpener) -> None:
    opener.answers["/repos/a/b/pulls/9"] = None
    assert READER._get("/repos/a/b/pulls/9") is None


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502])
def test_any_other_status_is_unavailable_and_never_names_the_token(
    opener: FakeOpener, status: int
) -> None:
    opener.answers["/repos/a/b"] = status
    with pytest.raises(forge.ForgeUnavailableError) as raised:
        READER._get("/repos/a/b")
    assert raised.value.status == status
    assert TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    "failure",
    [
        http.client.IncompleteRead(b"partial"),
        http.client.BadStatusLine("garbage"),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
    ],
)
def test_a_protocol_or_network_failure_is_unavailable(
    opener: FakeOpener, failure: BaseException
) -> None:
    opener.answers["/repos/a/b"] = failure
    with pytest.raises(forge.ForgeUnavailableError) as raised:
        READER._get("/repos/a/b")
    assert TOKEN not in str(raised.value)


def test_without_a_token_nothing_is_sent(opener: FakeOpener) -> None:
    with pytest.raises(forge.ForgeUnavailableError):
        forge.Forge(None)._get("/repos/a/b")
    assert opener.requests == []


# --- the redirect guard ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/x",
        "http://api.github.com/repos/a/b",  # plain HTTP would carry the header in clear
        "https://api.github.com:8443/repos/a/b",
        "https://api.github.com:bad/repos/a/b",
        "https://api.github.com.evil.example/repos/a/b",
    ],
)
def test_a_redirect_leaves_https_api_github_com_only_by_refusal(target: str) -> None:
    handler = forge._SameHostOnly()
    request = urllib.request.Request("https://api.github.com/repos/a/b")
    with pytest.raises(forge.ForgeUnavailableError):
        handler.redirect_request(request, None, 301, "Moved", {}, target)


@pytest.mark.parametrize(
    "target", ["https://api.github.com/repositories/1", "https://api.github.com:443/repositories/1"]
)
def test_a_redirect_within_the_api_host_is_followed(target: str) -> None:
    handler = forge._SameHostOnly()
    request = urllib.request.Request("https://api.github.com/repos/a/b")
    assert handler.redirect_request(request, None, 301, "Moved", {}, target).full_url == target


# --- a repository the token cannot see -----------------------------------------------------


def test_a_missing_ref_in_a_visible_repository_is_an_answer(opener: FakeOpener) -> None:
    opener.answers["/repos/a/b"] = {"full_name": "a/b"}
    opener.answers["/repos/a/b/pulls/9"] = None
    opener.answers["/repos/a/b/branches/gone"] = None
    assert READER.pull_request("a/b", 9) == {"number": 9, "found": False}
    assert READER.branch("a/b", "gone")["found"] is False
    visibility = [r for r in opener.requests if r.full_url.endswith("/repos/a/b")]
    assert len(visibility) == 1  # asked once, then remembered


def test_a_repository_the_token_cannot_see_is_unavailable_not_missing(opener: FakeOpener) -> None:
    opener.answers["/repos/a/b"] = None
    opener.answers["/repos/a/b/pulls/9"] = None
    with pytest.raises(forge.ForgeUnavailableError, match="not visible"):
        READER.pull_request("a/b", 9)


# --- the operator's token reads public repositories only (§11.4) ---------------------------


def test_a_public_repository_is_read_after_one_visibility_check(seen: FakeOpener) -> None:
    seen.answers["/repos/a/b"] = {"full_name": "a/b", "private": False}
    seen.answers["/repos/a/b/branches/main"] = {"commit": {"sha": SHA}}
    assert READER.branch("a/b", "main")["head_sha"] == SHA
    assert READER.branch("a/b", "main")["head_sha"] == SHA
    assert _paths(seen) == ["/repos/a/b", "/repos/a/b/branches/main", "/repos/a/b/branches/main"]


@pytest.mark.parametrize(
    ("answer", "reason"), [({"private": True}, "private_without_grant"), (None, "no_grant")]
)
def test_a_private_or_invisible_repository_is_never_read_with_the_token(
    seen: FakeOpener, answer: Any, reason: str
) -> None:
    seen.answers["/repos/a/b"] = answer
    seen.answers["/repos/a/b/branches/main"] = {"commit": {"sha": SHA}}
    for _ in range(2):
        with pytest.raises(forge.NotCoveredError) as raised:
            READER.branch("a/b", "main")
        assert raised.value.reason == reason
    assert _paths(seen) == ["/repos/a/b"]  # the answer is remembered, the read never made


def test_every_kind_of_read_is_checked_graphql_included(seen: FakeOpener) -> None:
    seen.answers["/repos/a/b"] = {"private": True}
    with pytest.raises(forge.NotCoveredError):
        READER.items("a/b", [1])
    with pytest.raises(forge.NotCoveredError):
        READER.social_preview("a/b")
    with pytest.raises(forge.NotCoveredError):
        READER.file("a/b", "README.md", 1000)
    with pytest.raises(forge.NotCoveredError):
        READER.owner_avatar("a/b")
    assert _paths(seen) == ["/repos/a/b"]


def test_the_check_is_per_repository_whatever_the_case(seen: FakeOpener) -> None:
    seen.answers["/repos/a/b"] = {"private": False}
    seen.answers["/repos/A/B/branches/main"] = {"commit": {"sha": SHA}}
    READER.branch("A/B", "main")
    assert _paths(seen) == ["/repos/a/b", "/repos/A/B/branches/main"]


def test_a_visibility_the_forge_does_not_give_is_asked_again(seen: FakeOpener) -> None:
    seen.answers["/repos/a/b"] = {"full_name": "a/b"}  # no `private`
    seen.answers["/repos/a/b/branches/main"] = {"commit": {"sha": SHA}}
    with pytest.raises(forge.ForgeUnavailableError) as raised:
        READER.branch("a/b", "main")
    assert not isinstance(raised.value, forge.NotCoveredError)
    seen.answers["/repos/a/b"] = 502
    with pytest.raises(forge.ForgeUnavailableError):
        READER.branch("a/b", "main")
    assert _paths(seen) == ["/repos/a/b", "/repos/a/b"]


def test_a_repository_turned_private_stops_at_the_next_check(
    seen: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [1000.0]
    monkeypatch.setattr(forge.time, "monotonic", lambda: now[0])
    seen.answers["/repos/a/b"] = {"private": False}
    seen.answers["/repos/a/b/branches/main"] = {"commit": {"sha": SHA}}
    READER.branch("a/b", "main")
    seen.answers["/repos/a/b"] = {"private": True}
    now[0] += forge.PUBLIC_SECONDS - 1
    READER.branch("a/b", "main")  # within the 10 minutes: not asked again
    now[0] += 1
    with pytest.raises(forge.NotCoveredError):
        READER.branch("a/b", "main")
    assert _paths(seen).count("/repos/a/b") == 2


def test_a_read_naming_no_repository_is_not_made_with_the_token(seen: FakeOpener) -> None:
    with pytest.raises(forge.ForgeUnavailableError):
        READER._call("/user")
    with pytest.raises(forge.ForgeUnavailableError):
        READER._call("/graphql", {"query": "{ viewer { login } }"})
    assert seen.requests == []


def test_without_a_token_no_visibility_is_asked(seen: FakeOpener) -> None:
    seen.answers["/repos/a/b/contents/README.md"] = None
    assert forge.Forge(None).file("a/b", "README.md", 1000) is None
    assert _paths(seen) == ["/repos/a/b/contents/README.md"]


# --- checks ----------------------------------------------------------------------------------


def _runs(*conclusions: str | None, total: int | None = None) -> dict[str, Any]:
    return {
        "total_count": total if total is not None else len(conclusions),
        "check_runs": [{"name": f"run {i}", "conclusion": c} for i, c in enumerate(conclusions)],
    }


def _checks_path(page: int) -> str:
    return f"/repos/a/b/commits/{SHA}/check-runs?per_page=100&page={page}"


def test_commit_statuses_count_like_check_runs(opener: FakeOpener) -> None:
    opener.answers[_checks_path(1)] = _runs()
    opener.answers[f"/repos/a/b/commits/{SHA}/status"] = {
        "state": "failure",
        "statuses": [{"context": "ci/jenkins", "state": "failure"}],
    }
    summary, detail = READER.checks("a/b", SHA)
    assert summary == "failure"
    assert detail == [{"name": "ci/jenkins", "status": "failure"}]


def test_a_failure_on_the_second_page_is_a_failure(opener: FakeOpener) -> None:
    opener.answers[_checks_path(1)] = _runs(*["success"] * 100, total=101)
    opener.answers[_checks_path(2)] = _runs("failure", total=101)
    opener.answers[f"/repos/a/b/commits/{SHA}/status"] = {"statuses": []}
    summary, detail = READER.checks("a/b", SHA)
    assert (summary, len(detail)) == ("failure", 101)


def test_more_runs_than_the_cap_are_unknown(opener: FakeOpener) -> None:
    for page in range(1, forge.MAX_PAGES + 1):
        opener.answers[_checks_path(page)] = _runs(*["success"] * 100, total=5000)
    opener.answers[f"/repos/a/b/commits/{SHA}/status"] = {"statuses": []}
    assert READER.checks("a/b", SHA)[0] == "unknown"


def test_no_permission_for_checks_is_unknown_not_a_failed_read(opener: FakeOpener) -> None:
    opener.answers["/repos/a/b/pulls/3"] = {
        "state": "open",
        "head": {"sha": SHA},
        "base": {"ref": "main"},
        "merged_at": None,
    }
    opener.answers[_checks_path(1)] = 403
    pr = READER.pull_request("a/b", 3)
    assert (pr["found"], pr["state"], pr["head_sha"], pr["checks"]) == (
        True,
        "open",
        SHA,
        "unknown",
    )


def test_stale_runs_are_pending(opener: FakeOpener) -> None:
    opener.answers[_checks_path(1)] = _runs("success", "stale")
    opener.answers[f"/repos/a/b/commits/{SHA}/status"] = {"statuses": []}
    assert READER.checks("a/b", SHA)[0] == "pending"


def test_the_token_is_never_in_a_repr() -> None:
    assert TOKEN not in repr(READER) and TOKEN not in str(READER)


@pytest.mark.parametrize("headers", [{"X-RateLimit-Remaining": "0"}, {"Retry-After": "60"}])
def test_a_rate_limit_on_checks_is_no_answer_not_a_missing_permission(
    opener: FakeOpener, headers: dict[str, str]
) -> None:
    opener.answers[_checks_path(1)] = (403, headers)
    with pytest.raises(forge.ForgeUnavailableError) as raised:
        READER.checks("a/b", SHA)
    assert raised.value.rate_limited is True


def test_repository_visibility_is_remembered_per_token(opener: FakeOpener) -> None:
    opener.answers["/repos/a/b"] = {"full_name": "a/b", "private": False}
    opener.answers["/repos/a/b/pulls/9"] = None
    READER.pull_request("a/b", 9)
    other = forge.Forge("another-token")
    other.pull_request("a/b", 9)
    visibility = [r for r in opener.requests if r.full_url.endswith("/repos/a/b")]
    # each token asked for itself; the other one also whether it is public (§11.4)
    assert len(visibility) == 3
    assert all(TOKEN not in str(key) for key in [*forge._visible, *forge._public])


# --- the logo (§11.2) -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        ({"type": "Organization", "avatar_url": "https://avatars.githubusercontent.com/u/1"},
         "https://avatars.githubusercontent.com/u/1"),
        ({"type": "User", "avatar_url": "https://avatars.githubusercontent.com/u/2"}, None),
        ({"avatar_url": "https://avatars.githubusercontent.com/u/3"}, None),
    ],
)  # fmt: skip
def test_the_owners_avatar_is_a_logo_only_for_an_organization(
    opener: FakeOpener, owner: dict[str, Any], expected: str | None
) -> None:
    opener.answers["/repos/a/b"] = {"full_name": "a/b", "owner": owner}
    assert READER.owner_avatar("a/b") == expected
