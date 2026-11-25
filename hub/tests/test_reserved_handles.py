"""Handles kept for the product (docs/api.md §16.11): a new person or organisation may not take
one of five characters or fewer, nor a product word; an agent may; the operator's
`owner create` is held to the words only; whoever holds one keeps it."""

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

# A 2- and a 5-character handle, a word of the first list and one naming a part of Maity.
KEPT = ["ab", "abcde", "pricing", "reviewer"]
WORDS = ["pricing", "reviewer"]


def _fields(response: Any) -> dict[str, str]:
    result: dict[str, str] = response.json()["error"]["details"]["fields"]
    return result


def test_the_product_words_are_the_contracts() -> None:
    section = re.sub(r"\s+", " ", _section())
    block = section[section.index("**Handles kept for the product.**") :]
    block = block[block.index("The list:") : block.index("These name no route")]
    assert frozenset(re.findall(r"`([a-z][a-z-]*)`", block)) == paths.PRODUCT_WORDS


def test_the_contract_names_the_length() -> None:
    section = re.sub(r"\s+", " ", _section())
    assert "may not take a handle of five characters or fewer" in section
    assert paths.SHORT_HANDLE == 5


def test_the_product_words_are_no_path_words_and_owner_stays_free() -> None:
    """They name no route (robots, the join host, `never_a_page` read `RESERVED_FIRST`), and a
    word that reads as the hub is refused for every handle anyway."""
    assert not paths.PRODUCT_WORDS & paths.RESERVED_FIRST
    assert not paths.PRODUCT_WORDS & paths.MISLEADING_HANDLES
    assert {"owner", "owners"}.isdisjoint(paths.PRODUCT_WORDS)
    assert not paths.handle_reserved("owner", by_operator=True)
    assert not paths.handle_reserved("owners")


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


def test_owner_is_free_for_the_operator_but_too_short_to_register(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """`owner create` takes `owner` (below); a sign-up, a rename and an organisation do not."""
    with migrated.connect() as conn:
        assert check_names(conn, "owner", "Someone") == {"handle": "reserved"}
    person = flow.human(make_client, migrated)
    assert _fields(person.patch("/me", {"handle": "owner"})) == {"handle": "reserved"}
    org = person.post("/orgs", {"handle": "owner", "display_name": "Owner"})
    assert _fields(org) == {"handle": "reserved"}


def test_six_characters_and_a_word_off_the_list_may_be_taken(migrated: Engine) -> None:
    with migrated.connect() as conn:
        assert check_names(conn, "abcdef", "Someone") == {}
        assert check_names(conn, "pricing-team", "Someone") == {}


def _owner_create(handle: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "stdin", io.StringIO("a long password\n"))
    monkeypatch.setenv("MAITY_DATABASE_URL", "sqlite:////no/such/directory/hub.db")
    args = ["--handle", handle, "--display-name", "X", "--email", "x@example.org"]
    return main(["owner", "create", *args])


@pytest.mark.parametrize("handle", WORDS)
def test_owner_create_refuses_a_product_word(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, handle: str
) -> None:
    assert _owner_create(handle, monkeypatch) == 2
    assert "is reserved" in capsys.readouterr().err


@pytest.mark.parametrize("handle", ["ab", "abcde", "owner"])
def test_owner_create_is_not_held_to_the_length(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, handle: str
) -> None:
    """The operator's command (req-x0efaacq8zyh): it fails later, on the missing database,
    never on the reservation."""
    _owner_create(handle, monkeypatch)
    assert "is reserved" not in capsys.readouterr().err


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
    _organisation_holding(migrated, owner.id, "abcde")
    away = owner.patch("/orgs/abcde", {"handle": "abcde-away"})
    assert away.status_code == 200, away.text
    back = owner.patch("/orgs/abcde-away", {"handle": "abcde"})
    assert back.status_code == 200, back.text
    assert back.json()["handle"] == "abcde"


def test_holders_are_named_and_stop_neither_the_migration_nor_the_start(
    migrated: Engine,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests import factory

    with migrated.connect() as conn:
        before = namespace.kept_holders(conn)
    factory.human(migrated, "ab")
    factory.human(migrated, "pricing")
    factory.human(migrated, "lt-7")  # the load-test seed's own: not named
    with migrated.connect() as conn:
        assert namespace.reserved_holders(conn) == []
        assert namespace.kept_holders(conn) == sorted([*before, "handle 'ab'", "handle 'pricing'"])
    monkeypatch.setenv("MAITY_DATABASE_URL", database_url)
    assert main(["migrate"]) == 0
    err = capsys.readouterr().err
    assert "handle 'ab'" in err and "handle 'pricing'" in err and "lt-7" not in err
