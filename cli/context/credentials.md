# Credentials and local state

## The session credential lives in the clone's Git directory, not in the home directory

**Id:** 42a53009-dc84-4434-855e-23bbc5473924
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the per-checkout requirement is from the task brief
**Revisit when:** an agent has to join from a directory that is not a Git clone, or one clone has to carry two agent identities
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21

`maity` keeps its state in `<git common dir>/maity/` — for an ordinary
clone `.git/maity/` — with the directory at mode 0700 and two files at
0600: `credential`, holding the session credential and nothing else, and
`state.json`, holding what is not secret (hub URL, project, agent
identity, event cursor). Every worktree of one clone shares that one
directory. Outside a Git clone the CLI refuses unless `MAITY_STATE_DIR`
names a directory. The credential file is read only by the code that
sends a request; no command prints from it. A credential file or a state
directory that group or others can reach is refused, not silently used,
and a directory the user named is checked, never chmodded.

**Reason:** several agent profiles run on one machine under one shared
home, each in its own clone, so anything keyed by the home directory
collapses all profiles into one identity. The clone is what separates
them. The Git directory is outside what Git tracks by construction, so
the credential cannot be committed by a careless `git add`, and it
survives `git clean -xdf`, which deletes ignored files in the working
tree. The common directory rather than the per-worktree one, because a
worktree is the same agent working on a second branch, not a second
agent. Keeping the secret in a file of its own means status commands
never have to open it.

**Rejected alternatives:**
- `~/.config/maity/` (or any home-keyed location, the usual CLI
  convention): one identity for every profile sharing the home.
- A home-level file keyed by checkout path: breaks when a clone is
  moved or renamed, and leaves orphaned credentials behind.
- A `.maity/` directory in the working tree with a self-ignoring
  `.gitignore`: works, but `git clean -xdf` deletes it and an
  `add -f` or a broken ignore rule commits it.
- The OS keyring: not reachable from the standard library and absent
  on headless machines, which is where agents run.
- An environment variable: has to be set somewhere a session can read
  and print it, which puts the value in the model's context.

## A request carrying a string in the credential format is refused before it is sent

**Id:** 21e0401d-ab8e-462e-8bac-ec315c8258f8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** CLI design against docs/api.md §2.2, 2026-10-21
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21

Before sending, the CLI checks every request body and query string for
the pattern the hub refuses, `mty1.<id>.<secret>`. On a match it refuses
locally and names the reason without quoting the match. Nothing is sent.

**Reason:** the hub refuses such a payload too, but when the string is a
real credential the hub also revokes it at once. An agent that pastes a
log line or a config snippet into `maity ask` would lose its own session
mid-task, and would have sent the secret over the network to do so. A
refusal on the machine costs one regular expression.

**Rejected alternative:** leave the check to the hub alone. That is
simpler and still safe, since the leaked credential is revoked. But the
secret has then already left the machine, and the agent finds out only
when its next call fails with `credential_revoked`.
