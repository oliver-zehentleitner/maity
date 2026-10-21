# Credentials and local state

## The session credential lives in the clone's Git directory, not in the home directory

**Id:** 42a53009-dc84-4434-855e-23bbc5473924
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the per-checkout requirement is from the task brief
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21
**Revisit when:** an agent has to join from a directory that is not a Git clone, or one clone has to carry two agent identities

`maity` keeps its state in `<git common dir>/maity/` — for an ordinary
clone `.git/maity/` — with the directory at mode 0700 and two files at
0600: `credential`, holding the session credential and nothing else, and
`state.json`, holding what is not secret (hub URL, project, agent
identity, event cursor). Every worktree of one clone shares that one
directory. Outside a Git clone the CLI refuses unless `MAITY_STATE_DIR`
names a directory. The credential file is read only by the code that
sends a request; no command prints from it, and a credential file
readable by group or others is refused, not silently used.

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
