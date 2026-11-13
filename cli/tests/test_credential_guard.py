"""The pre-send check refuses what the hub refuses (§2.2): a credential whatever stands right
before it, also inside a JSON escape."""

from __future__ import annotations

import json

import pytest

from maity import hub, sign

DUMMY = "mty1.crd-dummy.abc_DEF-9"


@pytest.mark.parametrize("before", ["\n", "\t", "_", "a"])
def test_the_pattern_finds_a_credential_after_any_character(before: str) -> None:
    assert sign.contains_credential(f"cfg:{before}{DUMMY}")


@pytest.mark.parametrize("before", ["\n", "\t", "_", "a"])
def test_a_json_body_is_refused_before_it_is_sent(before: str) -> None:
    body = json.dumps({"body": f"cfg:{before}{DUMMY}"}).encode()
    with pytest.raises(hub.HubError, match="refusing to send"):
        hub._guard_payload(body, "")


def test_a_unicode_escape_hides_no_credential() -> None:
    body = b'{"body": "see \\u006dty1.crd-dummy.abc_DEF-9"}'
    with pytest.raises(hub.HubError, match="refusing to send"):
        hub._guard_payload(body, "")


def test_a_body_without_one_is_sent() -> None:
    hub._guard_payload(json.dumps({"body": "mty1 crd-1 abc"}).encode(), "")
    hub._guard_payload(b"[" * 100_000, "")  # too deep to decode: the raw scan stays
