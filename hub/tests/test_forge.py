"""docs/api.md §11: the forge reads themselves — `forge._get` against a fake opener,
the redirect guard, check runs and commit statuses, a repository the token cannot see."""

from __future__ import annotations

import http.client
import io
import json
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
    fake = FakeOpener()
    monkeypatch.setattr(forge, "_opener", fake)
    return fake


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
    opener.answers["/repos/a/b"] = {"full_name": "a/b"}
    opener.answers["/repos/a/b/pulls/9"] = None
    READER.pull_request("a/b", 9)
    other = forge.Forge("another-token")
    other.pull_request("a/b", 9)
    visibility = [r for r in opener.requests if r.full_url.endswith("/repos/a/b")]
    assert len(visibility) == 2  # each token asked once for itself
    assert all(TOKEN not in str(key) for key in forge._visible)


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


# --- the rate limit budget per source (§11.4) ------------------------------------------------


class Answered(io.BytesIO):
    """A 200 with the forge's rate limit headers."""

    def __init__(self, body: Any, headers: dict[str, str]) -> None:
        super().__init__(json.dumps(body).encode())
        self.headers = headers


def _limits(remaining: int, reset: float, limit: int = 5000) -> dict[str, str]:
    return {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(int(reset))}  # fmt: skip


def test_a_spent_budget_stops_reads_until_the_reset_and_says_when(opener: FakeOpener) -> None:
    import time

    reset = time.time() + 600
    opener.answers["/repos/acme/maity"] = (403, _limits(0, reset))
    with pytest.raises(forge.ForgeUnavailableError) as first:
        READER._get("/repos/acme/maity")
    assert first.value.rate_limited and first.value.retry_at is not None
    assert abs(first.value.retry_at.timestamp() - int(reset)) < 1
    sent = len(opener.requests)
    with pytest.raises(forge.ForgeUnavailableError) as second:
        READER._get("/repos/acme/other")
    assert second.value.retry_at == first.value.retry_at
    assert len(opener.requests) == sent  # nothing went out while the budget is spent
    assert READER.retry_at() == first.value.retry_at


def test_a_budget_under_five_percent_is_kept_for_the_reset(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    reset = time.time() + 900
    answers = iter(
        [Answered({"ok": 1}, _limits(249, reset)), Answered({"ok": 2}, _limits(240, reset))]
    )
    monkeypatch.setattr(
        forge, "_opener", type("O", (), {"open": lambda _s, r, timeout: next(answers)})()
    )
    assert READER._get("/repos/acme/maity") == {"ok": 1}  # 249 of 5000 is under 5 %
    with pytest.raises(forge.ForgeUnavailableError) as held:
        READER._get("/repos/acme/maity")
    assert held.value.rate_limited and held.value.status is None


def test_a_budget_above_five_percent_reads_on(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    answers = iter([Answered({"ok": 1}, _limits(251, time.time() + 900)), Answered({"ok": 2}, {})])
    monkeypatch.setattr(
        forge, "_opener", type("O", (), {"open": lambda _s, r, timeout: next(answers)})()
    )
    assert READER._get("/repos/acme/maity") == {"ok": 1}
    assert READER._get("/repos/acme/maity") == {"ok": 2}
    assert READER.retry_at() is None


def test_a_retry_after_holds_that_long(opener: FakeOpener) -> None:
    import time

    opener.answers["/repos/acme/maity"] = (429, {"Retry-After": "120"})
    with pytest.raises(forge.ForgeUnavailableError) as error:
        READER._get("/repos/acme/maity")
    assert error.value.rate_limited and error.value.retry_at is not None
    assert 110 < error.value.retry_at.timestamp() - time.time() <= 121


def test_the_budget_is_per_token(opener: FakeOpener) -> None:
    import time

    opener.answers["/repos/acme/maity"] = (403, _limits(0, time.time() + 600))
    with pytest.raises(forge.ForgeUnavailableError):
        READER._get("/repos/acme/maity")
    other = forge.Forge("ghp_another_owners_token")
    opener.answers["/repos/acme/maity"] = {"name": "maity"}
    assert other._get("/repos/acme/maity") == {"name": "maity"}
    assert other.retry_at() is None and READER.retry_at() is not None


def test_after_the_reset_the_source_is_read_again(
    opener: FakeOpener, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    now = time.time()
    opener.answers["/repos/acme/maity"] = (403, _limits(0, now + 60))
    with pytest.raises(forge.ForgeUnavailableError):
        READER._get("/repos/acme/maity")
    monkeypatch.setattr(forge.time, "time", lambda: now + 61)
    opener.answers["/repos/acme/maity"] = {"name": "maity"}
    assert READER._get("/repos/acme/maity") == {"name": "maity"}


def test_a_plain_403_is_no_spent_budget(opener: FakeOpener) -> None:
    opener.answers["/repos/acme/maity"] = (403, {"X-RateLimit-Remaining": "4000"})
    with pytest.raises(forge.ForgeUnavailableError) as error:
        READER._get("/repos/acme/maity")
    assert not error.value.rate_limited and error.value.retry_at is None
    assert READER.retry_at() is None


def test_parallel_reads_never_spend_more_than_was_left() -> None:
    """Reads are counted before they are sent: with 6 of 100 left, one more fits above
    the 5 % kept; the others wait for the reset instead of going out together."""
    import time

    source = forge._source(TOKEN)
    forge._note(source, _limits(6, time.time() + 600, limit=100), spent=False)
    sent = [forge._take(source) is None for _ in range(8)]
    assert sent.count(True) == 1
    assert READER.retry_at() is not None


def test_a_late_answer_does_not_raise_what_is_left() -> None:
    """Answers arrive in any order: within one window the lowest count stands; a later
    reset starts a new window."""
    import time

    source = forge._source(TOKEN)
    reset = time.time() + 600
    forge._note(source, _limits(2000, reset), spent=False)
    forge._note(source, _limits(3000, reset), spent=False)  # sent earlier, answered later
    assert forge._budgets[source].remaining == 2000
    forge._note(source, _limits(4999, reset + 3600), spent=False)
    assert forge._budgets[source].remaining == 4999


def test_a_read_without_an_answer_is_no_longer_counted(opener: FakeOpener) -> None:
    source = forge._source(TOKEN)
    opener.answers["/repos/acme/maity"] = TimeoutError()
    with pytest.raises(forge.ForgeUnavailableError):
        READER._get("/repos/acme/maity")
    assert forge._budgets[source].in_flight == 0
