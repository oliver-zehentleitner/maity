### Changed

- docs/api.md §2.3 "The bridge": refusals named (`agent_owner` for a human who does not own the
  served agent, the full lists of `details.fields.member` and `details.fields.bridge`), a purpose
  change across owners needs the same two consents as the connection, the project's consent goes
  to `owner` and is answered by a human with `members:admin`, a second request of a pair supersedes
  the first while an existing connection answers `already`; §9.1: a bridge does not write in the
  direct conversation; §13: `maity --for <agent>` acts for a served agent with its own wait cursor.
- docs/api.md §2.8.8: the "ever verified" flag is set at the upgrade for addresses that are
  `verified` or `disabled`; §9.3: a meat-proxy value in an event is the value at that event's time.
