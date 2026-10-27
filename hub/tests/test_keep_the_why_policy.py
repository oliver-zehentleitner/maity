"""docs/api.md §6.1 and §6.23: the memory provider, the Keep the Why policy and the
loading block of the resume packet."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.config import KTW_SKILL_SOURCE, ConfigError, Settings
from tests import flow
from tests.conftest import ClientFactory

SOURCE = "https://github.com/oliver-zehentleitner/keep-the-why/tree/latest/skills/keep-the-why"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def _patch(owner: flow.Human, slug: str, body: dict[str, Any]) -> Any:
    return owner.patch(f"/projects/{slug}", body)


def test_the_default_provider_is_keep_the_why(owner: flow.Human) -> None:
    body = flow.project(owner)
    assert body["memory"] == {"provider": "keep-the-why"}
    assert body["keep_the_why"] is True
    assert body["policy"]["keep_the_why"] == "required"
    assert body["policy"]["keep_the_why_defaults"] == "adopt"


def test_the_alias_and_the_provider_are_the_same_setting(owner: flow.Human) -> None:
    off = flow.project(owner, "off", keep_the_why=False)
    assert off["memory"] == {"provider": "none"}
    assert off["policy"]["keep_the_why"] == "optional"
    named = flow.project(owner, "named", memory={"provider": "none"})
    assert named["keep_the_why"] is False
    response = _patch(owner, "off", {"memory": {"provider": "keep-the-why"}})
    assert response.status_code == 200, response.text
    assert response.json()["keep_the_why"] is True
    assert response.json()["policy"]["keep_the_why"] == "required"


def test_a_provider_the_hub_does_not_know_is_invalid(owner: flow.Human) -> None:
    flow.project(owner)
    response = _patch(owner, "maity", {"memory": {"provider": "notion"}})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"memory.provider": "unknown_provider"}


def test_both_spellings_must_agree(owner: flow.Human) -> None:
    flow.project(owner)
    response = _patch(owner, "maity", {"memory": {"provider": "none"}, "keep_the_why": True})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {
        "keep_the_why": "conflicts_with_memory"
    }
    created = owner.post(
        "/projects",
        {"slug": "x", "name": "X", "memory": {"provider": "keep-the-why"}, "keep_the_why": False},
    )
    assert created.status_code == 400


def test_required_needs_a_provider_and_a_reason(owner: flow.Human) -> None:
    flow.project(owner, "bare", keep_the_why=False)
    refused = _patch(owner, "bare", {"policy": {"keep_the_why": "required"}, "reason": "r"})
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {
        "policy.keep_the_why": "no_memory_provider"
    }
    flow.project(owner)
    no_reason = _patch(owner, "maity", {"policy": {"keep_the_why": "optional"}})
    assert no_reason.status_code == 400
    assert no_reason.json()["error"]["details"]["fields"] == {"reason": "required"}
    done = _patch(owner, "maity", {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    assert done.status_code == 200, done.text
    assert done.json()["policy"]["keep_the_why"] == "optional"


def test_a_set_policy_survives_a_preset_change_and_a_provider_round_trip(
    owner: flow.Human,
) -> None:
    flow.project(owner)
    _patch(owner, "maity", {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    again = _patch(owner, "maity", {"policy": {"preset": "solo"}, "reason": "solo"})
    assert again.json()["policy"]["keep_the_why"] == "optional"
    _patch(owner, "maity", {"memory": {"provider": "none"}})
    back = _patch(owner, "maity", {"memory": {"provider": "keep-the-why"}})
    assert back.json()["policy"]["keep_the_why"] == "optional"


def test_an_unset_policy_follows_the_provider_after_an_unrelated_policy_change(
    owner: flow.Human,
) -> None:
    flow.project(owner, "bare", keep_the_why=False)
    _patch(owner, "bare", {"policy": {"badge": "members"}, "reason": "badge"})
    back = _patch(owner, "bare", {"memory": {"provider": "keep-the-why"}})
    assert back.json()["policy"]["keep_the_why"] == "required"


def test_the_defaults_take_adopt_or_ask(owner: flow.Human) -> None:
    flow.project(owner)
    bad = _patch(owner, "maity", {"policy": {"keep_the_why_defaults": "never"}, "reason": "r"})
    assert bad.status_code == 400
    assert bad.json()["error"]["details"]["fields"] == {"policy.keep_the_why_defaults": "unknown"}
    ok = _patch(owner, "maity", {"policy": {"keep_the_why_defaults": "ask"}, "reason": "ask"})
    assert ok.json()["policy"]["keep_the_why_defaults"] == "ask"
    kept = _patch(owner, "maity", {"policy": {"preset": "solo"}, "reason": "solo"})
    assert kept.json()["policy"]["keep_the_why_defaults"] == "ask"


def test_the_packet_tells_the_agent_how_to_load_the_skill(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    packet = agent.resume().json()
    block = packet["keep_the_why"]
    assert block["enabled"] is True
    assert block["skill"]["name"] == "keep-the-why"
    assert block["skill"]["source"] == SOURCE
    assert block["skill"]["install"][0] == f"npx skills add {SOURCE}"
    assert block["skill"]["install"][1].startswith(
        "git clone --depth 1 --branch latest https://github.com/oliver-zehentleitner/keep-the-why"
    )
    assert "Skill tool" in block["skill"]["load"]
    assert block["config"] == ".keep-the-why"
    assert block["personal_defaults"] == "adopt"
    assert packet["project"]["memory"] == {"provider": "keep-the-why"}


def test_the_block_stays_under_optional_and_goes_under_none(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    _patch(owner, "maity", {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    assert "skill" in agent.resume().json()["keep_the_why"]
    _patch(owner, "maity", {"memory": {"provider": "none"}})
    assert agent.resume().json()["keep_the_why"] == {"enabled": False, "instruction": None}


def test_a_mirror_is_set_by_the_environment() -> None:
    assert Settings.from_env({}).ktw_skill_source == KTW_SKILL_SOURCE
    mirror = "https://git.example.org/mirror/ktw/tree/main/skill"
    assert Settings.from_env({"MAITY_KTW_SKILL_SOURCE": mirror}).ktw_skill_source == mirror
    with pytest.raises(ConfigError):
        Settings.from_env({"MAITY_KTW_SKILL_SOURCE": "file:///etc/passwd"})
