"""Autogenerate the next numbered migration: `make revision m="add tasks"`.

Runs the existing migrations on a scratch SQLite file and compares the result
with the tables defined in `maity_hub`; the new revision lands in
`src/maity_hub/migrations/versions/`. Review it before committing: autogenerate
does not see renames and writes nothing for data changes.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from maity_hub.db import create_revision, make_engine

MIGRATIONS = Path(__file__).resolve().parents[1] / "src" / "maity_hub" / "migrations"


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print('usage: make revision m="what the migration does"', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as scratch:
        engine = make_engine(f"sqlite:///{Path(scratch) / 'revision.db'}")
        try:
            path = create_revision(engine, sys.argv[1], MIGRATIONS)
        finally:
            engine.dispose()
    print(f"created {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
