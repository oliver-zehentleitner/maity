"""docs/api.md §2.5: the client address and scheme behind trusted proxies."""

from __future__ import annotations

from typing import Any

import pytest

from maity_hub.config import parse_networks
from maity_hub.net import resolve

PROXIES = parse_networks("10.0.0.0/8")


def scope(peer: str, scheme: str = "http", *headers: tuple[str, str]) -> dict[str, Any]:
    return {
        "client": (peer, 1234),
        "scheme": scheme,
        "headers": [(k.encode(), v.encode()) for k, v in headers],
    }


def test_an_untrusted_peer_changes_nothing() -> None:
    origin = resolve(
        scope(
            "198.51.100.9", "http", ("x-forwarded-for", "127.0.0.1"), ("x-forwarded-proto", "https")
        ),
        PROXIES,
    )
    assert (origin.address, origin.scheme, origin.loopback) == ("198.51.100.9", "http", False)


def test_one_proxy() -> None:
    origin = resolve(
        scope(
            "10.0.0.5", "http", ("x-forwarded-for", "198.51.100.9"), ("x-forwarded-proto", "https")
        ),
        PROXIES,
    )
    assert (origin.address, origin.scheme) == ("198.51.100.9", "https")


def test_a_client_line_before_the_proxys_appended_line_does_not_win() -> None:
    # The client sent its own X-Forwarded-For; the proxy appended a second line.
    origin = resolve(
        scope(
            "10.0.0.5",
            "http",
            ("x-forwarded-for", "127.0.0.1"),
            ("x-forwarded-for", "198.51.100.9"),
            ("x-forwarded-proto", "https"),
        ),
        PROXIES,
    )
    assert origin.address == "198.51.100.9"
    assert not origin.loopback


def test_the_scheme_is_read_at_the_clients_hop() -> None:
    # client --http--> 10.0.0.7 --https--> 10.0.0.5 --> hub: the client spoke http.
    origin = resolve(
        scope(
            "10.0.0.5",
            "http",
            ("x-forwarded-for", "198.51.100.9, 10.0.0.7"),
            ("x-forwarded-proto", "http, https"),
        ),
        PROXIES,
    )
    assert (origin.address, origin.scheme) == ("198.51.100.9", "http")


@pytest.mark.parametrize("proto", ["https, http", "http,https"])
def test_a_spoofed_leftmost_scheme_is_ignored(proto: str) -> None:
    origin = resolve(
        scope(
            "10.0.0.5", "http", ("x-forwarded-for", "198.51.100.9"), ("x-forwarded-proto", proto)
        ),
        PROXIES,
    )
    assert origin.scheme == proto.replace(" ", "").split(",")[-1]
