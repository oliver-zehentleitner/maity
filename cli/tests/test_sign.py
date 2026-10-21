from __future__ import annotations

import hashlib
import hmac

import pytest

from maity import sign
from maity.state import Secret

CREDENTIAL = Secret("mty1.crd-b-0003.yq3Zt0kQ2vXy9aBcDeFgHiJkLmNoPqRsTuVwXyZ0123")
EMPTY_SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_canonical_string_follows_the_contract_line_by_line() -> None:
    text = sign.canonical_string("get", "/api/v1/projects/maity/events", "after=1", "17", "n", b"")
    assert text.split("\n") == [
        "MAITY-HMAC-V1",
        "GET",
        "/api/v1/projects/maity/events",
        "after=1",
        "17",
        "n",
        EMPTY_SHA,
    ]
    assert not text.endswith("\n")


def test_canonical_query_sorts_bytewise_and_keeps_repeats_in_order() -> None:
    pairs = [("wait", "55"), ("b", "2"), ("a", "z"), ("a", "y"), ("B", ""), ("q", "a b/ü")]
    assert sign.canonical_query(pairs) == "B=&a=z&a=y&b=2&q=a%20b%2F%C3%BC&wait=55"


def test_empty_query_is_an_empty_line() -> None:
    assert sign.canonical_query([]) == ""
    assert sign.canonical_string("POST", "/p", "", "1", "n", b"{}").split("\n")[3] == ""


def test_signature_uses_the_sha256_of_the_secret_text_as_key() -> None:
    key = sign.signing_key(CREDENTIAL)
    headers = sign.sign_headers(key, "POST", "/api/v1/me/resume", "", b'{"a":1}', 1792000000)
    assert headers["Authorization"] == "Maity-HMAC crd-b-0003"
    assert headers["Maity-Timestamp"] == "1792000000"
    assert len(headers["Maity-Nonce"]) >= 22
    verifier = hashlib.sha256(b"yq3Zt0kQ2vXy9aBcDeFgHiJkLmNoPqRsTuVwXyZ0123").digest()
    canonical = "\n".join(
        [
            "MAITY-HMAC-V1",
            "POST",
            "/api/v1/me/resume",
            "",
            "1792000000",
            headers["Maity-Nonce"],
            hashlib.sha256(b'{"a":1}').hexdigest(),
        ]
    )
    expected = hmac.new(verifier, canonical.encode(), hashlib.sha256).hexdigest()
    assert headers["Maity-Signature"] == expected


def test_nonces_differ() -> None:
    assert sign.new_nonce() != sign.new_nonce()


def test_signing_key_never_shows_the_secret() -> None:
    key = sign.signing_key(CREDENTIAL)
    assert "yq3Z" not in repr(key) and "yq3Z" not in str(key)


@pytest.mark.parametrize("value", ["", "mty1.only", "mty2.a.b", "mty1.a.b.c", "mty1.a b.c"])
def test_malformed_credentials_are_refused(value: str) -> None:
    with pytest.raises(sign.CredentialFormatError) as info:
        sign.signing_key(Secret(value))
    assert value not in str(info.value) or not value


def test_credential_pattern_in_text() -> None:
    assert sign.contains_credential("see mty1.crd-1.abc_DEF-9 here")
    assert not sign.contains_credential("mty1 crd-1 abc")
