### Changed

- cli: `maity report --help`, §6.6 and the CLI README say up front that on a card with two
  stacked pull requests, once the card's last report names the first, the second is
  reported only after the first has merged (or closed): while the hub last saw the first
  open, a report from the second's branch is refused unless gh finds it merged or closed
  now. A card linking the first needs the second linked too. Until now an agent learned
  it from the refusal (tsk-2xk7cg5n8a1b).
