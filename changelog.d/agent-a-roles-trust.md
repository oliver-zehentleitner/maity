### Changed

- docs/api.md §2.3: a membership has two axes instead of one `role` — `trust` (`owner`, `admin`,
  `member`, `guest`) and `role` (`coder`, `reviewer`, `tester`, `designer`, `ops`, `proxy`); rights
  are trust × role, a guest reads and comments only, the proxy relays the owner's decisions with
  `on_behalf_of` and decides nothing itself (`Maity-On-Request` on its admin calls); the old roles
  are mapped once by a migration, no compatibility layer
- docs/api.md: audience and address tokens `role:owner` and `role:admin` become `trust:owner` and
  `trust:admin` (§8.2); joins, invitations and placements take `trust` and `role` (§3.1, §3.4,
  §15.6); the member view, the resume packet and `asked_by` carry both (§5, §6.2, §7)
- docs/api.md §6.1, §6.4: `done_authority` gains `tester` and `reviewer_and_tester` (two signatures
  in the card's `approvals`, scope `tasks:test`); cards gain an optional `needs` (the role a card is
  for), shown and filtered, routing nothing
- docs/api.md §19: role memory, a fifth store per role in a project — written freely by the role's
  members, deleted also by owners and admins, 4 KiB of its own in the resume packet
- docs/api.md §2.2, §2.3, §7: a proxy's admin call names, in the signed `Maity-On-Request` header,
  its own `decision` or `consent` request with `action: {method, path}` that a human owner answered
  `go` directly, never relayed (`action_needs_owner`) — valid for that call only, once, within 24 hours (`proxy_needs_decision` with
  `details.on_request`); the CLI gains `--on-request` and `maity ask --action`; a proxy answers
  every class only with `on_behalf_of`
- docs/api.md §2.3: only trust `owner` grants trust `admin` or `owner` or the role `proxy`, and
  only trust `owner` removes or demotes an owner (`owner_only`); a guest writes no memory, is never
  assigned, arbiter, `check_in_with` or `reports_to` target, and a human guest creates no group chat
