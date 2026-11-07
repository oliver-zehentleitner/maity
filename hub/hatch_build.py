"""Puts the join page and the dashboard into the hub's sdist and wheel.

Both live outside `hub/`: the join page in `docs/`, next to the contract it follows, and
the dashboard in `web/`. A wheel built from the checkout takes them from `..`; an sdist
carries them under `bundled/`, and a wheel built from that sdist takes them from there.
web/'s fixtures/, tools/ and context/ stay in the checkout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# Path below the repository root (or below `bundled/` in an sdist) -> path in the wheel.
BUNDLED = {
    "docs/join-page.md": "maity_hub/join-page.md",
    "web/index.html": "maity_hub/web/index.html",
    "web/css": "maity_hub/web/css",
    "web/js": "maity_hub/web/js",
    "web/brand": "maity_hub/web/brand",
    "web/vendor": "maity_hub/web/vendor",
}
SDIST_DIR = "bundled"


def source_root(hub: Path) -> Path:
    """`bundled/` in an unpacked sdist, the repository root in a checkout."""
    bundled = hub / SDIST_DIR
    return bundled if bundled.is_dir() else hub.parent


class BundleHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = source_root(Path(self.root))
        for source, target in BUNDLED.items():
            path = root / source
            if not path.exists():
                raise FileNotFoundError(f"maity-hub build: {path} is missing")
            build_data["force_include"][str(path)] = (
                f"{SDIST_DIR}/{source}" if self.target_name == "sdist" else target
            )
