"""docs/api.md §1.3: an error answer always encodes. A client's key holding a lone surrogate (JSON
accepts one, UTF-8 does not encode it) is shown in a field path as its escape text `\\ud800`."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import Engine

from maity_hub.errors import envelope, error_response
from tests import flow
from tests.conftest import ClientFactory

KEY = b"k\\ud800"  # on the wire: the JSON escape of a lone surrogate
SHOWN = "k\\ud800"  # in the answer: the same six characters of escape text, as a string
AUTH = "/admin/settings/auth-pages"
LANDING = "/admin/settings/landing"
LEGAL = "/admin/settings/legal"
SECTION = b'{"type": "text", "enabled": true, "markdown": "x", "%s": 1}'


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def test_the_envelope_escapes_a_lone_surrogate_and_leaves_a_valid_path() -> None:
    fields = {"pages.k\ud800.title": "extra_forbidden", "pages.en.title": "required"}
    shown = envelope("invalid", "the request does not validate", {"fields": fields})
    assert shown["error"]["details"]["fields"] == {
        "pages.k\\ud800.title": "extra_forbidden",
        "pages.en.title": "required",
    }
    answer = error_response(400, "invalid", "the request does not validate", {"fields": fields})
    rendered = json.loads(bytes(answer.body))["error"]["details"]["fields"]
    assert rendered["pages.k\\ud800.title"] == "extra_forbidden"
    emoji = envelope("invalid", "m", {"fields": {"pages.\U0001f642": "invalid"}})
    assert emoji["error"]["details"]["fields"] == {"pages.\U0001f642": "invalid"}


@pytest.mark.parametrize(
    ("method", "path", "sent", "field", "reason"),
    [
        # the sign-in and sign-up pages' check
        (
            "POST",
            f"{AUTH}/check",
            b'{"pages": {"sign_in": {"de": {"%s": "x"}}}}' % KEY,
            f"pages.sign_in.de.{SHOWN}",
            "extra_forbidden",
        ),
        (
            "POST",
            f"{AUTH}/check",
            b'{"pages": {"%s": {}}}' % KEY,
            f"pages.{SHOWN}",
            "extra_forbidden",
        ),
        ("POST", f"{AUTH}/check", b'{"%s": 1}' % KEY, SHOWN, "extra_forbidden"),
        # the landing page
        ("PATCH", LANDING, b'{"%s": 1}' % KEY, SHOWN, "extra_forbidden"),
        (
            "PATCH",
            LANDING,
            b'{"pages": {"en": {"title": "T", "%s": 1}}}' % KEY,
            f"pages.en.{SHOWN}",
            "extra_forbidden",
        ),
        (
            "PATCH",
            LANDING,
            b'{"pages": {"en": {"title": "T", "sections": [%s]}}}' % (SECTION % KEY),
            f"pages.en.sections.0.{SHOWN}",
            "extra_forbidden",
        ),
        (
            "PATCH",
            LANDING,
            b'{"variants": {"%s": {"pages": {}}}}' % KEY,
            f"variants.{SHOWN}",
            "invalid",
        ),
        (
            "PATCH",
            LANDING,
            b'{"variants": {"spring": {"pages": {"%s": {"title": "T"}}}}}' % KEY,
            f"variants.spring.pages.{SHOWN}",
            "invalid",
        ),
        (
            "PATCH",
            LANDING,
            b'{"variants": {"spring": {"pages": {}, "%s": 1}}}' % KEY,
            f"variants.spring.{SHOWN}",
            "extra_forbidden",
        ),
        (
            "PATCH",
            LANDING,
            b'{"campaigns": [{"code": "c1", "label": "L", "%s": 1}]}' % KEY,
            f"campaigns.0.{SHOWN}",
            "extra_forbidden",
        ),
        # the legal pages
        ("PATCH", LEGAL, b'{"%s": 1}' % KEY, SHOWN, "extra_forbidden"),
        (
            "PATCH",
            LEGAL,
            b'{"imprint": {"en": {"title": "T", "markdown": "x", "%s": 1}}}' % KEY,
            f"imprint.en.{SHOWN}",
            "extra_forbidden",
        ),
    ],
)
def test_a_key_holding_a_lone_surrogate_is_shown_escaped_in_its_path(
    owner: flow.Human, method: str, path: str, sent: bytes, field: str, reason: str
) -> None:
    refused = owner.raw(method, path, sent)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {field: reason}
