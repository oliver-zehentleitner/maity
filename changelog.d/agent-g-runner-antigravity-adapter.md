### Added

- cli: the runner starts the `antigravity` harness (Google's Antigravity CLI, `agy`), in
  `interactive` and `supervised` mode (§15.3). Each placement gets a workspace folder,
  `<workspaces>/<project id>/<clone>`, with the clone as `repo` inside. agy starts in that
  folder, never in the clone, so the repository's own agy configuration is not loaded, and
  the start prompt sends the agent into `repo`. Every session gets settings the runner
  writes (`--settings`): the default agent mode (not `auto`), `proceed-in-sandbox`, the
  terminal sandbox on, the folder trusted, the clone's `.git/maity` and the other private
  paths denied to the file tools, and `maity`, the repository's `allow` list and the hub's,
  forge's and grant's hosts allowed. `supervised` runs `agy -p` and continues with `-c`;
  `interactive` runs `agy -i` and resumes with `-c`. The sandbox is advertised `off` until
  the runner can see agy's own sandbox start, so an agy placement runs as
  `sandbox_unavailable` and `require_sandbox = true` refuses it. `maity runner check`
  reports whether the namespaces agy's sandbox needs start (a diagnostic), agy's sign-in,
  warns about allow rules and MCP servers in the agents' user's own agy settings, and fails
  when the workspaces root lies inside a git work tree.
- cli: before every antigravity start, and before every run of the supervised loop, the
  runner refuses a workspace folder that holds anything besides `repo`
  (`workspace_not_bare`), lies inside a git work tree or is not at its real path
  (`workspace_in_repository`); it deletes nothing there and logs the names it found.
  `maity runner gc --revoked` lists entries beside `repo` as unsaved work and removes the
  folder as a whole, and `maity runner workspace claim` records a workspace folder as one.
- hub: `antigravity` is a harness id a runner may advertise and a placement may name.
- web: the runner views name the `antigravity` harness "Antigravity".

### Changed

- cli: the supervised loop runs `maity wait` in the clone its spec names, not in its own
  working directory. Sandboxed sessions of every harness no longer read `~/.gemini`.
