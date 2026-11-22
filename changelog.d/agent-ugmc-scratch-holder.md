### Security

- cli: every placement's scratch now sits under one holder,
  `<workspaces>/.scratch/<project>/<placement id>`, and a Claude Code
  placement's sandbox denies that holder for reading and opens only its own
  scratch again. A scratch made after the session started is now hidden from
  it in every project, including one that had no scratch yet at its start,
  which the previous release left open. The runner makes the holder as the
  agents' user and checks it at every start: a link or another user's
  directory there refuses the start, as does a holder it cannot make, and
  a sandboxed Claude Code placement whose own scratch cannot be made is
  refused too. Scratches in the former
  `<workspaces>/<project>/.scratch/` are still measured, removed and denied
  until their placements are gone, and an ssh host whose `maity` is older
  keeps the former layout until it is upgraded. A Claude Code placement
  started before the upgrade can still read a scratch made in the holder:
  the window closes once each Claude Code placement has been restarted
  after the upgrade (step 3 of
  [Upgrading maity on a runner](docs/runners.md#upgrading-maity-on-a-runner));
  restarting the runner service does not restart a placement. Maity's own
  rollout of this release does that on every runner it upgrades; on any
  other runner the operator does it. Until then the runner's log names
  them by id.
