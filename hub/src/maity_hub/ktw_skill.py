"""What a joining agent is told to load Keep the Why (docs/api.md §6.23).

The texts are instructions to the agent, rendered as text: the hub and the CLI never
run them. They come from the instance settings `MAITY_KTW_SKILL_SOURCE` and
`MAITY_KTW_SKILL_GUIDE`.
"""

from __future__ import annotations

from typing import Any

from maity_hub import commitment
from maity_hub.config import Settings

SKILL_NAME = "keep-the-why"
CONFIG_PATH = ".keep-the-why"
LOAD = (
    "Claude Code: invoke the keep-the-why skill (Skill tool). Any other agent: read "
    "<skills directory>/keep-the-why/SKILL.md and follow it."
)


def skill(settings: Settings) -> dict[str, Any]:
    """`name`, `source`, `install`, `load` and `guide` (§6.23). The Git fallback is derived from a
    `/tree/<branch>/<path>` source and is the source itself otherwise."""
    source = settings.ktw_skill_source
    repository, _, tree = source.partition("/tree/")
    branch, _, path = tree.partition("/")
    if tree and branch and path:
        clone = (
            f"git clone --depth 1 --branch {branch} {repository} <tmp> and copy "
            f"<tmp>/{path} into the harness's skills directory"
        )
    else:
        clone = f"fetch {source} and copy it into the harness's skills directory"
    return {
        "name": SKILL_NAME,
        "source": source,
        # -g -y: the skills installer asks for agents and scope otherwise, and an agent
        # without a terminal stalls at that prompt (keepthewhy.com/installation).
        "install": [f"npx skills add {source} -g -y", clone],
        "load": LOAD,
        "guide": settings.ktw_skill_guide,
    }


def loading_block(project: Any, settings: Settings, credential: Any = None) -> dict[str, Any]:
    """The `keep_the_why` block of the resume packet (§5.2): the loading part, and with the
    caller's `credential` the commitment under `required`."""
    block: dict[str, Any] = {
        "enabled": bool(project.keep_the_why),
        "instruction": None,
    }
    if project.keep_the_why:
        block |= {
            "skill": skill(settings),
            "config": CONFIG_PATH,
            "personal_defaults": project.keep_the_why_defaults,
        }
        if credential is not None:
            block |= commitment.packet(project, credential)
    return block
