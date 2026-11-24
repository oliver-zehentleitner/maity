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


# No `-` or `_` in the secret: with one, the pattern backtracks to the boundary before it and
# matches under a Unicode `\b` too, so only a secret of letters and digits shows the difference.
PLAIN = "mty1.crd-dummy.abcDEF9"


@pytest.mark.parametrize("after", ["é", "ß", "日", "."])
def test_the_pattern_ends_a_credential_before_any_non_ascii_letter(after: str) -> None:
    # The hub's `\b` is ASCII (a bytes pattern): a non-ASCII letter ends a credential there.
    assert sign.contains_credential(f"see {PLAIN}{after} here")


@pytest.mark.parametrize("after", ["é", "ß", "日", "."])
def test_a_body_with_a_credential_before_a_non_ascii_letter_is_refused(after: str) -> None:
    body = f"see {PLAIN}{after} here".encode()  # raw UTF-8, as an upload or --on-request sends
    with pytest.raises(hub.HubError, match="refusing to send"):
        hub._guard_payload(body, "")


@pytest.mark.parametrize("after", ["é", "ß", "日", "."])
def test_a_query_with_a_credential_before_a_non_ascii_letter_is_refused(after: str) -> None:
    with pytest.raises(hub.HubError, match="refusing to send"):
        hub._guard_payload(b"", sign.canonical_query([("q", f"{PLAIN}{after}")]))


def test_a_body_without_one_is_sent() -> None:
    hub._guard_payload(json.dumps({"body": "mty1 crd-1 abc"}).encode(), "")
    hub._guard_payload(b"[" * 100_000, "")  # too deep to decode: the raw scan stays


ENCODINGS = ["utf-8-sig", "utf-16", "utf-16-be", "utf-16-le", "utf-32", "utf-32-be", "utf-32-le"]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_a_body_the_hub_reads_as_json_is_checked_in_any_encoding(encoding: str) -> None:
    body = '{"body": "see \\u006dty1.crd-dummy.abc_DEF-9"}'.encode(encoding)
    assert DUMMY.encode() not in body
    with pytest.raises(hub.HubError, match="refusing to send"):
        hub._guard_payload(body, "")
