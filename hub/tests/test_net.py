"""docs/api.md §2.5: the client address and scheme behind trusted proxies."""

from __future__ import annotations

from typing import Any

import pytest

from maity_hub.config import parse_networks
from maity_hub.net import Origin, resolve

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


# --- the key of limits per source address -------------------------------------------------


@pytest.mark.parametrize(
    ("address", "key"),
    [
        ("198.51.100.9", "198.51.100.9"),
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:DB8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:3::1", "2001:db8:1:3::/64"),
        ("::ffff:198.51.100.9", "198.51.100.9"),
        ("fe80::1%eth0", "fe80::/64"),
        ("testclient", "testclient"),
        ("", ""),
    ],
)
def test_a_limit_counts_an_ipv6_client_by_its_64(address: str, key: str) -> None:
    origin = Origin(address, "https")
    assert origin.limit_key == key
    assert origin.address == address  # what is recorded or shown stays whole


def test_two_addresses_of_one_64_share_a_key_and_another_64_does_not() -> None:
    def key(address: str) -> str:
        return Origin(address, "https").limit_key

    assert key("2001:db8:1:2::1") == key("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert key("2001:db8:1:2::1") != key("2001:db8:1:3::1")
    assert key("198.51.100.9") != key("198.51.100.10")
    assert key("::ffff:198.51.100.9") == key("198.51.100.9")


def test_the_key_of_a_forwarded_ipv6_client() -> None:
    origin = resolve(
        scope("10.0.0.5", "http", ("x-forwarded-for", "2001:db8:1:2::77")),
        PROXIES,
    )
    assert (origin.address, origin.limit_key) == ("2001:db8:1:2::77", "2001:db8:1:2::/64")
