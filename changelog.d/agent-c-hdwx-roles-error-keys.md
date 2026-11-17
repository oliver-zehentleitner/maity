### Fixed

- contract: `PUT …/roles` (docs/api.md §2.3) names a per-entry error as the hub
  answers it, `custom[<i>].<field>` (0-based), `custom[<i>]` for an entry that
  is not an object and `custom[].guide` unindexed, instead of
  `details.fields.name`; it also names the list-level errors (`custom:
  "missing"`, `"not_a_list"`, `"too_many"`, `<property>: "extra_forbidden"`).
