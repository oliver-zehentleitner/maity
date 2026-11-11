### Added

- contract, hub: an expert's two membership fields. `expert_for` says what it answers about (plain text, at most 120
  characters), and `expert_sources` lists the path prefixes it learned (at most 20, in the form of areas). A human
  member who owns the agent or holds `members:admin`, or an admin agent within §2.3 ᵃ, sets them on their own in a
  member `PATCH`, only on an expert, and a role change away from `expert` clears them. Every member view carries both.
  A merge that changes a declared source wakes the expert through the ticker (`expert_source:<source>`, or
  `expert_source:*` when the hub cannot see the merge in full).
