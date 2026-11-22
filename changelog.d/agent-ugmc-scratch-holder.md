### Security

- cli: every placement's scratch now sits under one holder,
  `<workspaces>/.scratch/<project>/<placement id>`, and a Claude Code
  placement's sandbox denies that holder for reading and opens only its own
  scratch again. A scratch made after the session started is now hidden from
  it in every project, including one that had no scratch yet at its start,
  which the previous release left open. The runner makes the holder as the
  agents' user and checks it at every start: a link or another user's
  directory there refuses the start, as does a holder it cannot make. Scratches in the former
  `<workspaces>/<project>/.scratch/` are still measured, removed and denied
  until their placements are gone, and an ssh host whose `maity` is older
  keeps the former layout until it is upgraded. A Claude Code placement
  started before the upgrade can still read a scratch made in the holder
  until the placements are restarted after the upgrade, which the release
  does. Until then the runner's log names them by id
  ([Upgrading maity on a runner](docs/runners.md#upgrading-maity-on-a-runner)).
