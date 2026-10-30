"""Hang a branch's new hub migration on the head of main, or check there is one head.

    python tools/rechain.py            # after `git fetch` and merging origin/main
    python tools/rechain.py --check    # CI: exit 1 when the migrations have two heads

Parallel pull requests each add a migration on what was main's head when they started; the
one merged second leaves two Alembic heads, and the hub refuses to start on them. Instead of
a hand-kept queue, the branch's author runs this after merging main: it finds the one
migration the branch adds (a file in `hub/src/maity_hub/migrations/versions/` that main does
not have) and sets its `down_revision`, and the `Revises:` line, to main's head. More than one
new migration in a branch is refused: which goes first is the author's to decide.

The files are read as text, never imported, so it runs with no hub installed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VERSIONS = "hub/src/maity_hub/migrations/versions"
_REVISION = re.compile(r'^revision(?:: str)? = "([^"]+)"$', re.M)
# With or without the annotation (0061 has none); group 1 is everything before the value.
_DOWN = re.compile(r'^(down_revision(?:: str \| None)? = )(?:"([^"]+)"|None)$', re.M)
_REVISES = re.compile(r"^Revises: .*$", re.M)


class Refused(Exception):
    """What the tool will not do, said so the author knows the next step."""


@dataclass(frozen=True)
class Migration:
    name: str  # the file name
    revision: str
    down: str | None


def parse(name: str, text: str) -> Migration:
    revision, down = _REVISION.search(text), _DOWN.search(text)
    if revision is None or down is None:
        raise Refused(f'{name}: no `revision = "…"` or `down_revision` line of one revision')
    return Migration(name, revision[1], down[2])


def heads(migrations: list[Migration]) -> list[str]:
    """The revisions nothing revises, in name order."""
    revised = {m.down for m in migrations}
    return sorted(m.revision for m in migrations if m.revision not in revised)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Refused(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def in_tree(root: Path) -> dict[str, Migration]:
    folder = root / VERSIONS
    return {
        p.name: parse(p.name, p.read_text(encoding="utf-8"))
        for p in sorted(folder.glob("*.py"))
        if p.name != "__init__.py"
    }


def at_ref(root: Path, ref: str) -> dict[str, Migration]:
    names = _git(root, "ls-tree", "--name-only", f"{ref}:{VERSIONS}").split()
    return {
        n: parse(n, _git(root, "show", f"{ref}:{VERSIONS}/{n}"))
        for n in names
        if n.endswith(".py") and n != "__init__.py"
    }


def check(root: Path) -> str:
    """One head in the working tree, or `Refused` naming them."""
    found = heads(list(in_tree(root).values()))
    if len(found) != 1:
        raise Refused(
            f"the hub migrations have {len(found)} heads ({', '.join(found)}): merge origin/main "
            "into the branch and run `python tools/rechain.py`, which hangs the branch's new "
            "migration on main's head"
        )
    return found[0]


def rechain(root: Path, base: str) -> str:
    """Set the branch's one new migration's `down_revision` to the head of `base`."""
    on_base = at_ref(root, base)
    base_heads = heads(list(on_base.values()))
    if len(base_heads) != 1:
        raise Refused(f"{base} has {len(base_heads)} migration heads ({', '.join(base_heads)})")
    [base_head] = base_heads
    mine = in_tree(root)
    new = sorted(set(mine) - set(on_base))
    if not new:
        return "no new migration in this branch: nothing to chain"
    if len(new) > 1:
        raise Refused(
            f"{len(new)} new migrations in this branch ({', '.join(new)}): chain them by hand, "
            "each on the one before, or split the pull request"
        )
    missing = set(on_base) - set(mine)
    if missing:
        raise Refused(
            f"the branch lacks {len(missing)} migration(s) of {base} "
            f"({', '.join(sorted(missing))}): merge {base} first"
        )
    [name] = new
    migration = mine[name]
    if migration.down == base_head:
        return f"{name} already follows {base_head}"
    path = root / VERSIONS / name
    text = path.read_text(encoding="utf-8")
    text = _DOWN.sub(lambda m: f'{m[1]}"{base_head}"', text, count=1)
    text = _REVISES.sub(f"Revises: {base_head}", text, count=1)
    path.write_text(text, encoding="utf-8")
    check(root)
    return f"{name}: down_revision {migration.down} -> {base_head}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only check for one head")
    parser.add_argument("--base", default="origin/main", help="the ref to chain onto")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        if args.check:
            print(f"one migration head: {check(args.root)}")
        else:
            print(rechain(args.root, args.base))
    except Refused as exc:
        print(f"rechain: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
