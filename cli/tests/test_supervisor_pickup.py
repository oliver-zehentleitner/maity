"""A refused pickup or join and its `pickup_refused` finding (docs/api.md §15.14, "A refused
pickup is reported at once"; §15.7; tsk-bzmd0avm4yhb)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_supervisor import Reports, placement, recorded, settle
from test_supervisor_watch import make

from maity import hub
from maity.runner import supervisor

FACTS = {"started_at": None, "not_listening_since": None, "paused": False, "dormant": False}
NEW_MEMBER = {"id": "agt-3", "handle": "agent-3", "member": False, "credential_expected": False}


class Hub(Reports):
    """Status reports as test_supervisor's; the pickup refused with `refusal`, if any."""

    def __init__(self, refusal: hub.HubError | None = None) -> None:
        super().__init__()
        self.refusal = refusal

    def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
        if path.endswith("/join"):
            if self.refusal is not None:
                raise self.refusal
            return {"join_url": "https://hub.example/j/tok", "code": "abcd-efgh"}
        return super().call(method, path, body, **kwargs)


def refusal(code: str, status: int, **details: Any) -> hub.HubError:
    exc = hub.HubError(f"see https://hub.example/j/tok ({code})", code=code, status=status)
    exc.details = dict(details)
    return exc


def start(
    tmp_path: Path, client: Hub, session: Any = FACTS, agent: dict[str, Any] | None = None,
    **extra: Any,
) -> tuple[supervisor.Supervisor, Hub]:  # fmt: skip
    sup, _, _, _, _ = make(tmp_path)
    sup.client = client
    sup.login = lambda harness, binary, as_user: "needed"
    recorded(sup.cfg, credential=False)
    data = placement(agent=agent or NEW_MEMBER, **extra)
    if session is not ...:
        data["session"] = session
    sup.update([data])
    settle(sup)
    sup.tick()
    return sup, client


def last(client: Hub) -> dict[str, Any]:
    body: dict[str, Any] = client.sent[-1][1]
    return body


def findings(client: Hub) -> list[dict[str, Any]]:
    return [body["finding"] for _, body in client.sent if "finding" in body]


def test_a_coded_pickup_refusal_carries_its_finding(tmp_path: Path) -> None:
    sup, client = start(tmp_path, Hub(refusal("pickup_used", 409)))
    body = last(client)
    assert (body["state"], body["reason"], body["detail"]) == ("failed", "join_failed",
                                                               "pickup_used")  # fmt: skip
    (finding,) = findings(client)
    assert finding["cause"] == "pickup_refused"
    assert finding["signals"] == {
        "process": "gone", "exit_code": None, "below": "unknown", "pane_match": [],
        "login": "needed", "pickup_code": "pickup_used",
    }  # fmt: skip
    lines = [entry["line"] for entry in finding["log"]]
    assert "plc-0003: warning: join pickup refused: pickup_used (reason -, why -)" in lines
    assert any(line.startswith("plc-0003: join refused by the hub: pickup_used;") for line in lines)
    assert not any("tok" in line for line in lines)  # never the join URL or its token
    sup.tick()
    sup.tick()
    assert len(findings(client)) == 1  # sent once


def test_a_forbidden_pickup_names_its_reason(tmp_path: Path) -> None:
    _, client = start(tmp_path, Hub(refusal("forbidden", 403, reason="member_join_limit")))
    assert last(client)["detail"] == "member_join_limit"
    assert findings(client)[0]["signals"]["pickup_code"] == "member_join_limit"


def test_a_coded_exchange_refusal_carries_its_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervisor, "run_join", lambda *args, **kwargs: (False, "code_invalid"))
    _, client = start(tmp_path, Hub())
    assert last(client)["detail"] == "code_invalid"
    (finding,) = findings(client)
    assert (finding["cause"], finding["signals"]["pickup_code"]) == ("pickup_refused",
                                                                     "code_invalid")  # fmt: skip


def test_a_foreign_placement_gets_the_finding_too(tmp_path: Path) -> None:
    _, client = start(tmp_path, Hub(refusal("pickup_used", 409)), session=None)
    assert findings(client)[0]["cause"] == "pickup_refused"


def test_a_hub_without_session_gets_no_finding(tmp_path: Path) -> None:
    _, client = start(tmp_path, Hub(refusal("pickup_used", 409)), session=...)
    assert last(client)["detail"] == "pickup_used"
    assert findings(client) == []


@pytest.mark.parametrize("why", ["network", None])
def test_an_exchange_without_a_hub_code_gets_no_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, why: str | None
) -> None:
    monkeypatch.setattr(supervisor, "run_join", lambda *args, **kwargs: (False, why))
    _, client = start(tmp_path, Hub())
    body = last(client)
    assert (body["state"], body["reason"], body["detail"]) == ("failed", "join_failed", why)
    assert findings(client) == []


def test_a_bare_404_gets_no_finding(tmp_path: Path) -> None:
    _, client = start(tmp_path, Hub(refusal("not_found", 404)))
    body = last(client)
    assert (body["reason"], body["detail"]) == ("join_failed", None)
    assert findings(client) == []


def test_a_missing_credential_gets_no_finding(tmp_path: Path) -> None:
    expected = {**NEW_MEMBER, "member": True, "credential_expected": True}
    _, client = start(tmp_path, Hub(), agent=expected)
    body = last(client)
    assert (body["reason"], body["detail"]) == ("join_failed", "credential_missing")
    assert findings(client) == []
