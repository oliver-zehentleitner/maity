### Changed

- runner: a Codex placement starts on a repository whose grant has an
  `allow` list or `pull_requests`, without those two parts, instead of
  being refused. Codex has no command allowlist, so every command runs in
  its sandbox as before; `maity gh` cannot run in that sandbox, so Codex
  gets no pull-request record. `maity runner check` warns about each part
  for every such repository when `[harness.codex]` is configured, and the
  runner logs them at each Codex start.
