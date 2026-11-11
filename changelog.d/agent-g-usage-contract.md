### Added

- contract: §15.15, tokens and cost per run, card, instance and agent. A runner sends one record per supervised run
  (`POST /runner/placements/{id}/usage`: the four token counts and the harness's own cost figure, never the model,
  prompts or keys); a repeated `run_id` with other numbers is `conflict` (`run_id_reused`). The hub records the cards
  the instance holds, counts a shared run in full for each card, and never prices tokens. Card totals for the
  project's members, member and agent totals for the owner and the human admins, nothing public; the owner's export
  lists the daily totals. The routes are not built yet.
