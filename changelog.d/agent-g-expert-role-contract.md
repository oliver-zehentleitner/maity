### Added

- contract: a built-in role `expert` with the scopes `project:read` and `events:post`. An expert answers the
  requests addressed to it or to `role:expert` with their sources, takes no cards and files no requests. The
  membership fields `expert_for` and `expert_sources` say what it answers about and which path prefixes it
  learned, and a merge that changes a declared source wakes it through the ticker (`expert_source:<source>`).
- hub: the role `expert` with its scopes, its description and default guide, and its rules text. A join, an
  invitation or a membership `PATCH` may give it, and an outside owner's agent may hold it. A card's `needs`, a
  project role's name or base, `assigned_to`, `assign` and a claim's `holder` refuse it, and area routing skips
  it. The upgrade stops and names each project that still has a project role `expert`.
