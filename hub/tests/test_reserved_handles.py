"""Handles kept for the product (docs/api.md §16.11): a new person or organisation may not take
one of three characters or fewer, nor a product word; an agent may; whoever holds one keeps it."""

from __future__ import annotations

import io
import re
import sys
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import namespace, paths
from maity_hub.cli import main
from maity_hub.registration_accounts import check_names
from tests import flow
from tests.conftest import ClientFactory
from tests.test_handles import _organisation_holding
from tests.test_paths import _section

# A 2- and a 3-character handle, and a word new with this list.
KEPT = ["ab", "abc", "pricing"]


def _fields(response: Any) -> dict[str, str]:
    result: dict[str, str] = response.json()["error"]["details"]["fields"]
    return result


def test_the_product_words_are_the_contracts() -> None:
    section = re.sub(r"\s+", " ", _section())
    block = section[section.index("**Handles kept for the product.**") :]
    block = block[block.index("The list:") : block.index("These name no route")]
    assert frozenset(re.findall(r"`([a-z][a-z-]*)`", block)) == paths.PRODUCT_WORDS


def test_the_product_words_are_no_path_words_and_owner_stays_free() -> None:
    """They name no route (robots, the join host, `never_a_page` read `RESERVED_FIRST`), and a
    word that reads as the hub is refused for every handle anyway."""
    assert not paths.PRODUCT_WORDS & paths.RESERVED_FIRST
    assert not paths.PRODUCT_WORDS & paths.MISLEADING_HANDLES
    assert {"owner", "owners"}.isdisjoint(paths.PRODUCT_WORDS)
    assert not paths.handle_reserved("owner")


@pytest.mark.parametrize("handle", KEPT)
def test_sign_up_refuses_a_kept_handle(migrated: Engine, handle: str) -> None:
    with migrated.connect() as conn:
        assert check_names(conn, handle, "Someone") == {"handle": "reserved"}


@pytest.mark.parametrize("handle", KEPT)
def test_a_rename_and_an_organisation_refuse_a_kept_handle(
    make_client: ClientFactory, migrated: Engine, handle: str
) -> None:
    owner = flow.human(make_client, migrated)
    refused = owner.patch("/me", {"handle": handle})
    assert (refused.status_code, _fields(refused)) == (400, {"handle": "reserved"})
    org = owner.post("/orgs", {"handle": handle, "display_name": "Short"})
    assert (org.status_code, _fields(org)) == (400, {"handle": "reserved"})
    made = owner.post("/orgs", {"handle": "real-org", "display_name": "Real"})
    assert made.status_code == 201, made.text
    renamed = owner.patch("/orgs/real-org", {"handle": handle})
    assert (renamed.status_code, _fields(renamed)) == (400, {"handle": "reserved"})


@pytest.mark.parametrize("handle", KEPT)
def test_an_agent_may_take_a_kept_handle(
    make_client: ClientFactory, migrated: Engine, handle: str
) -> None:
    owner = flow.human(make_client, migrated)
    made = owner.post("/agents", {"handle": handle, "display_name": "Short agent"})
    assert made.status_code == 201, made.text
    assert not paths.handle_reserved(handle, of_agent=True)


def test_four_characters_and_a_word_off_the_list_may_be_taken(migrated: Engine) -> None:
    with migrated.connect() as conn:
        assert check_names(conn, "abcd", "Someone") == {}
        assert check_names(conn, "pricing-team", "Someone") == {}


@pytest.mark.parametrize("handle", KEPT)
def test_owner_create_refuses_a_kept_handle(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, handle: str
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("a long password\n"))
    monkeypatch.setenv("MAITY_DATABASE_URL", "sqlite:////no/such/directory/hub.db")
    args = ["--handle", handle, "--display-name", "X", "--email", "x@example.org"]
    assert main(["owner", "create", *args]) == 2
    assert "is reserved" in capsys.readouterr().err


@pytest.mark.parametrize("handle", KEPT)
def test_a_holder_keeps_a_kept_handle_and_may_take_it_back(
    make_client: ClientFactory, migrated: Engine, handle: str
) -> None:
    """An account from before the reservation keeps its handle, its alias and its page
    (§6.24); someone else still cannot take it."""
    holder = flow.human(make_client, migrated, handle)
    assert holder.get("/me").json()["member"]["handle"] == handle
    away = holder.patch("/me", {"handle": f"{handle}-away"})
    assert away.status_code == 200, away.text
    assert away.json()["member"]["aliases"] == [handle]
    other = flow.human(make_client, migrated, "someone-else")
    refused = other.patch("/me", {"handle": handle})
    assert (refused.status_code, _fields(refused)) == (400, {"handle": "reserved"})
    back = holder.patch("/me", {"handle": handle})
    assert back.status_code == 200, back.text
    assert back.json()["member"]["handle"] == handle
    assert not paths.never_a_page(f"/{handle}")


def test_an_organisation_that_holds_a_kept_handle_may_take_it_back(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated, "org-owner")
    _organisation_holding(migrated, owner.id, "abc")
    away = owner.patch("/orgs/abc", {"handle": "abc-away"})
    assert away.status_code == 200, away.text
    back = owner.patch("/orgs/abc-away", {"handle": "abc"})
    assert back.status_code == 200, back.text
    assert back.json()["handle"] == "abc"


def test_holders_are_named_and_stop_neither_the_migration_nor_the_start(
    migrated: Engine,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import factory

    factory.human(migrated, "ab")
    factory.human(migrated, "pricing")
    factory.human(migrated, "lt-7")  # the load-test seed's own: not named
    with migrated.connect() as conn:
        assert namespace.reserved_holders(conn) == []
        assert namespace.kept_holders(conn) == ["handle 'ab'", "handle 'pricing'"]
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    assert main(["migrate"]) == 0
    assert "handle 'ab', handle 'pricing'" in capsys.readouterr().err
