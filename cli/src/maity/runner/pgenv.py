"""Hands a placement's test cluster and its password to its session (hub/scripts/with_postgres.sh).

`python -I -m maity.runner.pgenv <workspaces root> <password file> <cluster dir> -- <command> …`,
or on an ssh host `maity runner pgenv …`: the runner starts the session's command through it.
It runs outside the session's sandbox, as the agents' user, reads the placement's password file
from the holder every sandbox is denied (scratchop.PG_HOLDER), sets MAITY_PG_DIR and
MAITY_PG_PASSWORD in its own process environment, and replaces itself with the command, which
inherits them. So the password never passes a command line, the tmux server's environment, the
loop's spec or a log, and no session reads the file (the review of #2032).

Only the placement's own file is read: the runner starts this with the session's MAITY_PLACEMENT
set, and a call naming another placement's file, or none, gets nothing. When the password cannot
be read (the file missing, or not one scratchop would vouch for), the command starts with
neither variable: a cluster directory without its password would be made with trust.

Only the standard library: the module runs with `-I` on the agents' side.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from . import scratchop

PASSWORD = "MAITY_PG_PASSWORD"  # noqa: S105 - the variable's name, not a password
PG_DIR = "MAITY_PG_DIR"
PLACEMENT = "MAITY_PLACEMENT"  # clonecheck.PLACEMENT_ENV, named here: this module runs with -I


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 5 or args[3] != "--":
        print("usage: pgenv <workspaces root> <password file> <cluster dir> -- <command> ...",
              file=sys.stderr)  # fmt: skip
        return 2
    under, path, cluster, command = args[0], args[1], args[2], args[4:]
    own = os.environ.get(PLACEMENT) or ""
    password = None
    if own and os.path.basename(path) == own and scratchop.supported():
        password = scratchop.pg_read(under, path)
    os.environ.pop(PASSWORD, None)
    os.environ.pop(PG_DIR, None)
    if password is None:
        print(f"pgenv: no test cluster password in {path}; starting without MAITY_PG_DIR",
              file=sys.stderr)  # fmt: skip
    else:  # both or neither
        os.environ[PG_DIR] = cluster
        os.environ[PASSWORD] = password
    try:
        os.execvp(command[0], command)  # noqa: S606 - the runner's own launch argv
    except OSError as exc:
        print(f"pgenv: cannot start {command[0]}: {exc}", file=sys.stderr)
        return 127
    return 0  # not reached: execvp replaced this process


if __name__ == "__main__":
    sys.exit(main())
