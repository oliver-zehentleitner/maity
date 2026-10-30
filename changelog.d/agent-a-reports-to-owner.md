### Changed

- docs: an agent's owner may set its `reports_to` to any member of a project, whatever their trust and role there; a boss of another owner waits for that side's consent (§2.3 now follows §6.2 "Own consent").
- docs: a consenting owner who is not a member of the project reads, answers and withdraws the cross-owner `reports_to` request under `/requests/{id}`, the routes of a personal request; the project route stays `not_found` for them (§6.2, §7).
- docs: §8.4 names the malformed `review` fields that are `format` (an unknown key, an empty text, a quote with a line break); the CLI's `--review-file -` and a message from standard input together are a usage error (§13); the export carries a review result's `review` (§2.9).
