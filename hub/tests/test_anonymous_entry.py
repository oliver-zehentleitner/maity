"""One rule for every anonymous sign-in and sign-up call (§2.1, §2.6.5, §2.7.1, §2.10).

Each entry point is called with a body its model accepts, so the answer comes from the guard
that runs first in the route (`auth.anonymous.entry`) and not from validation.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import ClientFactory

OTHER_SITE = "a sign-in from another site"

ENTRIES: list[tuple[str, dict[str, Any]]] = [
    ("/api/v1/auth/login", {"email": "ada@example.com", "password": "not this one"}),
    ("/api/v1/auth/register", {"address": "ada@example.com"}),
    ("/api/v1/auth/device-login", {"code": "ABCD-EFGH"}),
    ("/api/v1/auth/device-login/complete", {}),
    ("/api/v1/auth/email-link", {"address": "ada@example.com"}),
    ("/api/v1/auth/email-code", {"code": "123456"}),
    ("/api/v1/auth/password-reset", {"address": "ada@example.com"}),
    ("/api/v1/auth/password-reset/check", {"token": "x"}),
    ("/api/v1/auth/password-reset/complete", {"token": "x", "new": "a new password"}),
    ("/mail/sign-in/x", {}),
]
IDS = [path.removeprefix("/api/v1") for path, _ in ENTRIES]


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
@pytest.mark.parametrize(("path", "body"), ENTRIES, ids=IDS)
def test_another_site_starts_no_sign_in(
    make_client: ClientFactory, path: str, body: dict[str, Any], site: str
) -> None:
    # A sibling host under the same registrable domain is another site too (§2.1).
    answer = make_client().post(path, json=body, headers={"Sec-Fetch-Site": site})
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"] == {"code": "forbidden", "message": OTHER_SITE, "details": {}}


@pytest.mark.parametrize(("path", "body"), ENTRIES, ids=IDS)
def test_a_credential_signs_nobody_in(
    make_client: ClientFactory, path: str, body: dict[str, Any]
) -> None:
    answer = make_client().post(path, json=body, headers={"Authorization": "Bearer mty_x"})
    assert answer.status_code == 403, answer.text
    assert answer.json()["error"]["details"] == {"reason": "humans_only"}


@pytest.mark.parametrize("site", [None, "same-origin", "none"])
@pytest.mark.parametrize(("path", "body"), ENTRIES[:-1], ids=IDS[:-1])
def test_the_own_site_and_no_header_pass_the_guard(
    make_client: ClientFactory, path: str, body: dict[str, Any], site: str | None
) -> None:
    # The dashboard posts same-origin; the CLI and curl send no Sec-Fetch-Site at all.
    headers = {} if site is None else {"Sec-Fetch-Site": site}
    answer = make_client().post(path, json=body, headers=headers)
    if answer.status_code == 403:
        assert answer.json()["error"]["message"] != OTHER_SITE, answer.text
