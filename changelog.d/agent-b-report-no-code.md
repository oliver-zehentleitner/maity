### Added

- hub: a report with `"code": false` (`docs/api.md` §6.6) for a card whose
  result is not code: `head`, `branch`, `upstream`, `remote_head`, `pr` and
  `pr_unknown_reason` null and `pr_status` `none`, otherwise `invalid`
  (`not_with_code_false`); stored with `code`, `mismatch: false`, and never
  probed. `code` defaults to `true`, which still needs every git field.
