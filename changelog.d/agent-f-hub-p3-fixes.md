### Fixed

- hub: `attachments copy-to-s3` leaves a folder no project has (`lost+found` on an ext4 volume) alone, as the sweep does, instead of counting it as failed; a clean run on such a volume now ends with 0.
- hub: removing a runner with `agents: stop` after its key was revoked under `keep` answers what the removal stopped, not the earlier `keep`.
- hub: a revoke whose reason reads `member_removed` still announces that the lead instance ended; only the removal of the member itself leaves that to `member_removed`.
- hub: `MAITY_JOIN_URL` with a host that is neither a host name (letters, digits and hyphens per label) nor an IP address stops the hub at startup; the host goes unquoted into the join command's shell line. A deploy whose join host has other characters must change it before upgrading.
- hub: a `daily_at` in the hour the clocks skip for summer time no longer sends the daily or weekly digest twice that day; the moment is compared as an instant.
- hub: a `role_rules` value that adds no rule (`subagent_per_card: false`, an empty `checklist`, a role with nothing on) is still stored as given but no longer bumps `rules_version`; the rules text it generates is unchanged.
