### Added

- hub: the jour fixe, part 3a (`docs/api.md` §20.6) — the moderator's
  report (`POST …/rounds/{id}/report`) with its summary, findings and
  proposals; a proposal decided by the moderator within the rules and its
  owner's preferences (`basis` checked as §19.4 says) or filed to the owner
  as a `decision` request with `jour_fixe` set; `humans_only` proposals only
  to the owner; an `adopt` from either path opening one open, unassigned
  card with `jour_fixe`, none in a closed project (`proposals_not_carded`);
  the report the hub builds from the statement when none comes in time;
  `jour_fixe_reported`; the ticker's `jour_fixe` item.
- hub: `jour_fixe` on the request and card views.
