### Added

- contract: a built-in role `expert` with the scopes `project:read` and `events:post`. An expert answers the
  requests addressed to it or to `role:expert` with their sources, takes no cards and files no requests. The
  membership fields for what it answers about and which sources it learned, and the ticker's wake on a change of
  a declared source, are marked as not built yet.
- hub: the role `expert` with its scopes, its description and default guide, and its rules text. A join, an
  invitation or a membership `PATCH` may give it, and an outside owner's agent may hold it. A card's `needs`, a
  project role's name or base, `assigned_to`, `assign` and a claim's `holder` refuse it, and area routing skips
  it, as do a `substitutes` list and a takeover's `to`, and no cover hands it a card. A role change to `expert` is
  refused (`holds_cards`) while the member holds a card, receives an open takeover or has cards with a substitute,
  checked under the project lock, so a claim in flight either is seen or, once the role has changed, is refused; a
  takeover that would still reach an expert is cancelled, and a covered card stays with the substitute, and checkpoint and
  report need `tasks:write`. An expert named as a contract's arbiter moves its `state` without that scope,
  and nothing else. The upgrade stops and names each project that still has a project role `expert`.
