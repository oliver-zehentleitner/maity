"""Where this session runs, declared to the hub as two ids (docs/api.md §5.2, §5.3).

`home` stands for this OS user's home directory, `workspace` for this clone's state
directory. Each place keeps a random secret of its own (`~/.local/state/maity/env-secret`,
`<state dir>/env-secret`), and the id is `h-`/`w-` plus the first 12 hex characters of
HMAC-SHA256(secret, the hub's base URL as the CLI stores it). The same place gives unrelated
ids on two hubs, and no path ever leaves the machine. The hub only compares the ids, to warn
when two members share a home or a workspace; it cannot verify them.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

from . import state

SECRET_FILE = "env-secret"  # noqa: S105 - a file name, not a secret
HOME_SECRET = Path("~/.local/state/maity") / SECRET_FILE


def derive(prefix: str, secret: str, hub_base: str) -> str:
    digest = hmac.new(secret.encode(), hub_base.encode(), hashlib.sha256).hexdigest()
    return f"{prefix}-{digest[:12]}"


def ids(hub_base: str, state_dir: Path) -> dict[str, str] | None:
    """`{"home": "h-…", "workspace": "w-…"}` for `resume`; None, with a note on stderr, when a
    secret cannot be made or read: the field is optional, and the session then shows as
    "environment unknown" rather than failing."""
    try:
        home = state.secret_once(HOME_SECRET.expanduser())
        workspace = state.secret_once(state_dir / SECRET_FILE)
    except (OSError, state.StateError) as exc:
        print(f"maity: not declaring this session's environment: {exc}", file=sys.stderr)
        return None
    return {"home": derive("h", home, hub_base), "workspace": derive("w", workspace, hub_base)}
