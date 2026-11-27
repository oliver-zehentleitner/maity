### Added

- The built-in role `steward` keeps a project's Keep the Why complete. It is built on the
  expert and has the coder's scopes. It answers why questions across `context/` with the
  source, and it asks the authors of missing or open entries until each is done or someone
  has said why not. Every member still writes its own entries. A join gives a steward the
  sources `context/`, and every merge on the ticker has every steward in its audience,
  with the ticker's usual mutes and the dashboard's "for me" for humans. A steward is never
  routed a card, never a cover's substitute and never a card's `needs`. It is no base for a
  project role and is not offered to outsiders' agents. Its rules carry a steward line. The
  dashboard offers it after `expert` in Join an agent and Manage, with Expert for and Sources,
  and hides it there and in Invite user where the memory provider is `none`. The Way of
  working tab of Settings gains a Keep the Why steward section, where a human admin sets
  `policy.steward_writes`: `cards_only` to open a card for the author, or `self` to write
  where no author can.

### Changed

- The `steward_writes` policy sentences in the rules text say that the steward asks the
  author first and, under `self`, writes an entry itself only where no author can.
- The upgrade renames a project role named `steward` to `steward-custom`. Where that name is
  taken too, it uses the next free one (`steward-custom-2`, `-3`, …), and the log says which
  project got which name. Where a project role `steward` was removed while a change waited
  to apply it, approving that change after the upgrade is refused with `409 role_unknown`,
  so it cannot make the agent the built-in steward or store a `role:steward` substitute that
  now names the built-in stewards. Before, only another owner's consent naming the removed
  role was refused that way.
