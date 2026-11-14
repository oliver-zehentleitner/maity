"""The permitted-call allowlists of the access gates (tsk-f5sdcgr7vzj0, item 3): which calls
an isolated agent (§6.2), a second-factor or enrolment session (§2.8.2, §2.8.5) and a pending
account (§2.7.5) may still make.

Each gate is driven as its call site drives it, with the path in the form that site hands
over: the raw request path as bytes for the isolated agent's authentication, the decoded path
(`request.url.path`, or a part's path in `GET /bootstrap`) for the rest. The cases were
written against the gates before their lists moved to one format, and pin what each gate let
through and refused then, the edges included: a trailing slash, a query, another method on an
allowed path, a path that only starts like an allowed one, percent-encoding, a path without
`/api/v1`."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import deps
from maity_hub import tables as t
from maity_hub.auth import caller as caller_module
from maity_hub.auth import second_factor
from maity_hub.auth.caller import Caller, RequestFacts
from maity_hub.errors import ApiError
from maity_hub.net import Origin
from tests import flow
from tests.conftest import ClientFactory

SINCE = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

# --- an isolated agent (§6.2) ------------------------------------------------------------

ISOLATED_ALLOWED = [
    ("GET", "/api/v1/me"),
    ("POST", "/api/v1/me/resume"),
    ("GET", "/api/v1/bootstrap"),
]
ISOLATED_REFUSED = [
    ("HEAD", "/api/v1/me"),
    ("POST", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("get", "/api/v1/me"),
    ("GET", "/api/v1/me/resume"),
    ("POST", "/api/v1/bootstrap"),
    ("GET", "/api/v1/me/"),
    ("POST", "/api/v1/me/resume/"),
    ("GET", "/api/v1/bootstrap/"),
    ("GET", "/api/v1/me?x=1"),
    ("GET", "/api/v1/mex"),
    ("GET", "/api/v1/me/x"),
    ("GET", "/api/v1/me/notifications"),
    ("GET", "/api/v1/bootstrapx"),
    ("POST", "/api/v1/me/resumex"),
    ("GET", "/api/v1/m%65"),
    ("GET", "/api/v1/me%2F"),
    ("GET", "/api/v1//me"),
    ("GET", "/API/V1/me"),
    ("GET", "/api/v2/me"),
    ("GET", "/api/v1"),
    ("GET", "/api/v1me"),
    ("GET", "/me"),
    ("POST", "/me/resume"),
    ("GET", "/bootstrap"),
    ("GET", "/api/v1/api/v1/me"),
    ("GET", "/api/v1/me\n"),
    ("GET", ""),
]


def _isolated_row() -> Any:
    return SimpleNamespace(
        signing="optional",
        isolated_since=SINCE,
        isolated_reason="it rewrote the release notes",
        isolated_by="h-1",
        agent_id="agt-1",
        owner_id="h-1",
        id="crd-1",
        instance="abcd",
        membership_id=1,
        project_id="p-1",
    )


def _facts(method: str, raw_path: bytes) -> RequestFacts:
    return RequestFacts(
        method=method,
        raw_path=raw_path,
        raw_query=b"",
        headers={},
        cookies={},
        body=b"",
        origin=Origin("127.0.0.1", "https"),
        allow_plain_http=False,
    )


def _isolated_agent_passes(method: str, raw_path: bytes) -> bool:
    """Authentication of an isolated agent's credential (`caller._agent`), on the raw path."""
    try:
        found = caller_module._agent(
            None, _isolated_row(), "signed", False, _facts(method, raw_path)  # type: ignore[arg-type]
        )
    except ApiError as error:
        assert error.details["reason"] == "isolated"
        return False
    assert found.kind == "agent"
    return True


@pytest.mark.parametrize(("method", "path"), ISOLATED_ALLOWED)
def test_an_isolated_agent_authenticates_for_its_few_calls(method: str, path: str) -> None:
    assert _isolated_agent_passes(method, path.encode())


@pytest.mark.parametrize(("method", "path"), ISOLATED_REFUSED)
def test_an_isolated_agent_is_refused_every_other_raw_path(method: str, path: str) -> None:
    assert not _isolated_agent_passes(method, path.encode())


def test_an_isolated_agent_raw_path_is_compared_byte_for_byte() -> None:
    assert not _isolated_agent_passes("GET", "/api/v1/mé".encode())
    assert not _isolated_agent_passes("GET", "/api/v1/mé".encode("latin-1"))
    assert not _isolated_agent_passes("GET", b"/api/v1/me\x00")


class _Conn:
    """The one read `refuse_isolated` makes: the membership's isolation."""

    def execute(self, _query: Any) -> Any:
        return SimpleNamespace(first=_isolated_row)


AN_AGENT = Caller(kind="agent", via="bearer", agent_id="agt-1", membership_id=1)


def _bootstrap_part_passes(method: str, path: str) -> bool:
    """`GET /bootstrap`'s per-part check (`refuse_isolated`), on the part's own path."""
    try:
        caller_module.refuse_isolated(_Conn(), AN_AGENT, method, path)  # type: ignore[arg-type]
    except ApiError as error:
        assert error.details["reason"] == "isolated"
        return False
    return True


@pytest.mark.parametrize(("method", "path"), ISOLATED_ALLOWED)
def test_a_bootstrap_part_of_an_isolated_agent_passes_on_its_few_paths(
    method: str, path: str
) -> None:
    assert _bootstrap_part_passes(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        *ISOLATED_REFUSED,
        ("GET", "/api/v1/mé"),
        ("GET", "/api/v1/auth/session"),
        ("GET", "/api/v1/projects/maintainer/maity/events"),
    ],
)
def test_a_bootstrap_part_of_an_isolated_agent_is_refused_elsewhere(
    method: str, path: str
) -> None:
    assert not _bootstrap_part_passes(method, path)


def test_a_bootstrap_part_of_a_human_or_a_free_agent_is_never_refused_here() -> None:
    human = Caller(kind="human", via="cookie", human_id="h-1")
    caller_module.refuse_isolated(None, human, "GET", "/api/v1/projects")  # type: ignore[arg-type]
    unbound = Caller(kind="agent", via="bearer", agent_id="agt-1")
    caller_module.refuse_isolated(None, unbound, "GET", "/api/v1/projects")  # type: ignore[arg-type]


# --- a second-factor or enrolment session (§2.8.2, §2.8.5) --------------------------------

SECOND_STEP_ALLOWED = [
    ("GET", "/api/v1/bootstrap"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/second-factor/verify"),
    ("POST", "/api/v1/auth/second-factor/email"),
    ("POST", "/api/v1/auth/logout"),
]
ENROLMENT_ALLOWED = [
    ("GET", "/api/v1/bootstrap"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/reauthenticate"),
    ("GET", "/api/v1/auth/second-factor"),
    ("POST", "/api/v1/auth/second-factor/totp"),
    ("POST", "/api/v1/auth/second-factor/totp/confirm"),
]
MOVED_ALLOWED = [
    ("GET", "/api/v1/me/notifications"),
    ("POST", "/api/v1/me/notifications/read"),
    ("POST", "/api/v1/auth/sessions/s-1/confirm"),
    ("POST", "/api/v1/auth/sessions/a b/confirm"),
    ("POST", "/api/v1/auth/sessions/a\nb/confirm"),
    ("POST", "/api/v1/auth/sessions/%2F/confirm"),
    # The gate takes `/api/v1` off where it is there, and reads a path without it alike.
    ("GET", "/me/notifications"),
    ("POST", "/auth/sessions/s-1/confirm"),
]
MOVED_REFUSED = [
    ("GET", "/api/v1/auth/sessions/s-1/confirm"),
    ("DELETE", "/api/v1/auth/sessions/s-1/confirm"),
    ("POST", "/api/v1/auth/sessions//confirm"),
    ("POST", "/api/v1/auth/sessions/a/b/confirm"),
    ("POST", "/api/v1/auth/sessions/s-1/confirm/"),
    ("POST", "/api/v1/auth/sessions/s-1/confirmx"),
    ("POST", "/api/v1/auth/sessions/s-1/confirm?x=1"),
    ("POST", "/api/v1/auth/sessions/s-1"),
    ("POST", "/api/v1/auth/sessions/end-others"),
    ("POST", "/api/v1/me/notifications"),
    ("GET", "/api/v1/me/notifications/read"),
    ("GET", "/api/v1/me/notifications/"),
    ("GET", "/api/v1/me/notificationsx"),
    ("GET", "/api/v1/me/notification-settings"),
    ("GET", "/api/v1/me"),
    ("HEAD", "/api/v1/me/notifications"),
    ("post", "/api/v1/auth/sessions/s-1/confirm"),
    ("POST", "/api/v1/api/v1/auth/sessions/s-1/confirm"),
    ("POST", "/api/v2/auth/sessions/s-1/confirm"),
]
# Refused in both states.
STEP_REFUSED = [
    ("GET", "/api/v1/me"),
    ("POST", "/api/v1/auth/session"),
    ("HEAD", "/api/v1/auth/session"),
    ("get", "/api/v1/auth/session"),
    ("GET", "/api/v1/auth/session/"),
    ("GET", "/api/v1/auth/sessionx"),
    ("GET", "/api/v1/auth/session?x=1"),
    ("GET", "/api/v1/auth/sessi%6Fn"),
    ("GET", "/api/v1/auth/sessions"),
    ("POST", "/api/v1/auth/logout/"),
    ("GET", "/api/v1/bootstrap/"),
    ("GET", "/api/v1/bootstrapx"),
    ("GET", "/api/v1/api/v1/auth/session"),
    ("GET", "/api/v2/auth/session"),
    ("GET", "/API/V1/auth/session"),
    ("GET", "/api/v1//auth/session"),
    ("GET", "/api/v1"),
    ("GET", "/api/v1auth/session"),
    ("POST", "/api/v1/auth/second-factor/recovery-codes"),
    ("DELETE", "/api/v1/auth/second-factor"),
    ("POST", "/api/v1/auth/password"),
    ("GET", "/api/v1/projects"),
    ("POST", "/api/v1/me/resume"),
    ("GET", ""),
]


def _human_session(sign_in_complete: bool = True, standing: bool = True) -> Caller:
    row = SimpleNamespace(
        id_hash="s-1",
        sign_in_complete=sign_in_complete,
        method="password" if standing else "email",
        confirmed_at=None,
        second_factor=None,
    )
    return Caller(kind="human", via="cookie", human_id="h-1", human_session="s-1", session_row=row)


def _gate_passes(
    monkeypatch: pytest.MonkeyPatch, current: str, who: Caller, method: str, path: str
) -> bool:
    monkeypatch.setattr(second_factor, "state", lambda *_a, **_k: current)
    try:
        second_factor.gate(None, None, who, method, path)  # type: ignore[arg-type]
    except ApiError as error:
        assert error.details["reason"] in (
            "second_factor_required",
            "second_factor_enrolment_required",
        )
        return False
    return True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        *SECOND_STEP_ALLOWED,
        # Read without `/api/v1` as well (the gate's `removeprefix`).
        ("GET", "/auth/session"),
        ("GET", "/bootstrap"),
        ("POST", "/auth/second-factor/verify"),
    ],
)
def test_a_second_factor_session_reaches_its_few_calls(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    assert _gate_passes(monkeypatch, "second_factor", _human_session(), method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        *STEP_REFUSED,
        *[call for call in ENROLMENT_ALLOWED if call not in SECOND_STEP_ALLOWED],
        *MOVED_ALLOWED,
        *MOVED_REFUSED,
    ],
)
def test_a_second_factor_session_is_refused_everything_else(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    assert not _gate_passes(monkeypatch, "second_factor", _human_session(), method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        *ENROLMENT_ALLOWED,
        ("GET", "/auth/session"),
        ("POST", "/auth/second-factor/totp/confirm"),
    ],
)
@pytest.mark.parametrize(("complete", "standing"), [(True, True), (False, True), (True, False)])
def test_an_enrolment_session_reaches_its_few_calls(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, complete: bool, standing: bool
) -> None:
    who = _human_session(complete, standing)
    assert _gate_passes(monkeypatch, "enrolment", who, method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        *STEP_REFUSED,
        ("POST", "/api/v1/auth/second-factor/verify"),
        ("POST", "/api/v1/auth/second-factor/email"),
        *MOVED_REFUSED,
    ],
)
@pytest.mark.parametrize(("complete", "standing"), [(True, True), (False, True), (True, False)])
def test_an_enrolment_session_is_refused_everything_else(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, complete: bool, standing: bool
) -> None:
    who = _human_session(complete, standing)
    assert not _gate_passes(monkeypatch, "enrolment", who, method, path)


@pytest.mark.parametrize(("method", "path"), MOVED_ALLOWED)
def test_a_session_moved_into_enrolment_in_good_standing_keeps_this_was_me(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    assert _gate_passes(monkeypatch, "enrolment", _human_session(), method, path)
    fresh = _human_session(sign_in_complete=False)
    assert not _gate_passes(monkeypatch, "enrolment", fresh, method, path)
    weak = _human_session(standing=False)
    assert not _gate_passes(monkeypatch, "enrolment", weak, method, path)


def test_a_full_session_an_agent_and_a_runner_pass_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _gate_passes(monkeypatch, "full", _human_session(), "GET", "/api/v1/projects")
    agent = Caller(kind="agent", via="bearer", agent_id="agt-1")
    assert _gate_passes(monkeypatch, "second_factor", agent, "GET", "/api/v1/projects")
    runner = Caller(kind="runner", via="bearer", runner_id="r-1")
    assert _gate_passes(monkeypatch, "enrolment", runner, "GET", "/api/v1/projects")


# --- a pending account (§2.7.5) ----------------------------------------------------------

PENDING_ALLOWED = [
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/sessions"),
    ("POST", "/api/v1/auth/sessions/end-others"),
    ("POST", "/api/v1/auth/password"),
    # Every DELETE below `/api/v1/auth/sessions/`: its own session by id, and whatever else
    # starts so (the gate's `startswith`).
    ("DELETE", "/api/v1/auth/sessions/s-1"),
    ("DELETE", "/api/v1/auth/sessions/"),
    ("DELETE", "/api/v1/auth/sessions/a/b"),
    ("DELETE", "/api/v1/auth/sessions/s-1/"),
    ("DELETE", "/api/v1/auth/sessions/a\nb"),
    ("DELETE", "/api/v1/auth/sessions/end-others"),
    ("DELETE", "/api/v1/auth/sessions/%2F"),
]
PENDING_REFUSED = [
    ("HEAD", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("get", "/api/v1/me"),
    ("POST", "/api/v1/auth/session"),
    ("DELETE", "/api/v1/auth/sessions"),
    ("delete", "/api/v1/auth/sessions/s-1"),
    ("GET", "/api/v1/auth/sessions/s-1"),
    ("POST", "/api/v1/auth/sessions/s-1"),
    ("POST", "/api/v1/auth/sessions/s-1/confirm"),
    ("DELETE", "/api/v1/auth/sessionsx/s-1"),
    ("DELETE", "/api/v1//auth/sessions/s-1"),
    ("DELETE", "/auth/sessions/s-1"),
    ("DELETE", "/api/v2/auth/sessions/s-1"),
    ("DELETE", "/api/v1/api/v1/auth/sessions/s-1"),
    ("GET", "/api/v1/me/"),
    ("GET", "/api/v1/me?x=1"),
    ("GET", "/api/v1/mex"),
    ("GET", "/api/v1/me/x"),
    ("GET", "/api/v1/m%65"),
    ("GET", "/api/v1/me/notifications"),
    ("POST", "/api/v1/me/resume"),
    ("GET", "/api/v1/auth/sessions/"),
    ("POST", "/api/v1/auth/password/"),
    ("POST", "/api/v1/auth/logoutx"),
    ("GET", "/api/v1/bootstrap"),
    ("GET", "/API/V1/me"),
    ("GET", "/api/v1"),
    ("GET", "/api/v1me"),
    ("GET", "/me"),
    ("GET", "/auth/session"),
    ("GET", "/api/v1/projects"),
    ("GET", ""),
]


def _pending_passes(method: str, path: str, status: str = "pending") -> bool:
    who = Caller(kind="human", via="cookie", human_id="h-1", account_status=status)
    try:
        deps._confine_pending(None, who, method, path)  # type: ignore[arg-type]
    except ApiError as error:
        assert error.details == {"reason": "account_pending"}
        return False
    return True


@pytest.mark.parametrize(("method", "path"), PENDING_ALLOWED)
def test_a_pending_account_reaches_its_own_account_and_sessions(method: str, path: str) -> None:
    assert _pending_passes(method, path)


@pytest.mark.parametrize(("method", "path"), PENDING_REFUSED)
def test_a_pending_account_is_refused_everything_else(method: str, path: str) -> None:
    assert not _pending_passes(method, path)
    assert _pending_passes(method, path, status="active")


# --- the path each call site hands over, through the app ---------------------------------


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def test_an_isolated_agent_is_judged_on_the_raw_path(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    isolated = owner.post(f"/projects/maintainer/maity/members/{agent.id}/isolate", {"reason": "x"})
    assert isolated.status_code == 200, isolated.text
    assert agent.client.get("/api/v1/me", headers=agent.auth).status_code == 200
    # The router decodes `%65` to `e` and runs `GET /me`; the raw path is not `/api/v1/me`.
    encoded = agent.client.get("/api/v1/m%65", headers=agent.auth)
    assert encoded.status_code == 403, encoded.text
    assert encoded.json()["error"]["details"]["reason"] == "isolated"
    assert agent.client.get("/api/v1/me?x=1", headers=agent.auth).status_code == 200


def test_a_pending_account_is_judged_on_the_decoded_path(
    make_client: ClientFactory, migrated: Engine
) -> None:
    person = flow.human(make_client, migrated)
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(account_status="pending"))
    assert person.client.get("/api/v1/m%65").status_code == 200
    assert person.client.get("/api/v1/me?x=1").status_code == 200
    refused = person.client.get("/api/v1/projects")
    assert refused.json()["error"]["details"] == {"reason": "account_pending"}, refused.text


def test_a_second_factor_session_is_judged_on_the_decoded_path(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_two_factor import KEY, Clock, enrol, second_step, signed_in

    moment = Clock()
    human = signed_in(make_client, migrated)
    enrol(human, moment)
    client = make_client(secret_key=KEY)
    second_step(client)
    assert client.get("/api/v1/auth/sessi%6Fn").status_code == 200
    assert client.get("/api/v1/auth/session?x=1").status_code == 200
    refused = client.get("/api/v1/m%65")
    assert refused.json()["error"]["details"]["reason"] == "second_factor_required"
