"""The rule every anonymous sign-in and sign-up call keeps (§2.1, §2.6.5, §2.7.1, §2.10).

The password login, the registration, the device login, the mail link and code and the password
reset are called before a session exists, so no cookie and no `X-CSRF-Token` protects them. They
take no credential (an agent or a runner never signs a person in), need TLS (§2.5), and refuse a
call another site started in a visitor's browser: `Sec-Fetch-Site` of `cross-site` and, since a
sibling host under the same registrable domain is another site too, `same-site`. One guard holds
the rule for all of them (hub/context/auth.md).
"""

from __future__ import annotations

from fastapi import Request

from maity_hub.auth.caller import require_secure_transport
from maity_hub.deps import origin_of, settings_of
from maity_hub.errors import forbidden, humans_only

OTHER_SITES = ("cross-site", "same-site")


def no_credential(request: Request) -> None:
    """No `Authorization` header (`humans_only`), over TLS. A `GET` that only shows a page
    keeps this part; every call that starts, finishes or changes something keeps `entry`."""
    if request.headers.get("authorization"):
        raise humans_only("signing in and signing up are for a person, never a credential")
    require_secure_transport(origin_of(request), settings_of(request).allow_plain_http)


def entry(request: Request) -> None:
    """An anonymous call that starts, finishes or changes a sign-in, a sign-up or a reset."""
    no_credential(request)
    if request.headers.get("sec-fetch-site") in OTHER_SITES:
        raise forbidden(message="a sign-in from another site")
