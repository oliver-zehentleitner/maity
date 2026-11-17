### Changed

- runner: a Codex placement with its sandbox on starts on a repository
  whose grant has an `allow` list or `pull_requests`, without those two
  parts, instead of being refused. Codex has no command allowlist, so
  every command runs in its sandbox as before; the runner gives Codex no
  pull-request grant. With its sandbox off, such a grant
  still refuses the Codex start. `maity runner check` warns about each
  part for every such repository when `[harness.codex]` is configured,
  and the runner logs them at each Codex start.
