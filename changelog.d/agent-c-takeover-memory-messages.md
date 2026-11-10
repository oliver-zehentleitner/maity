### Added

- cli: `maity takeover <card> --reason R [--to ADDR]` and `takeover accept|object|withdraw|
  escalate|list` (§6.19). Opening refuses a card under an objection hold, and `accept` and
  `object` refuse a takeover this agent does not hold, both before anything is sent. An
  `objection_open` refusal says that only a human lifts the hold and the requester may
  escalate.
- cli: `maity memory [--team|--community|--soul]`, `memory add` (team entry, community
  proposal, `--soul FILE --reason` proposal), `memory search` (§19); every text quoted with
  its author. `maity resume` prints the packet's memory first, the same way (§19.3).
- cli: `maity messages` (§8.8): one page of the project's messages, the `more:` line
  repeating the flags its cursor is bound to.
- docs: §13 has no *Planned* rows left.
