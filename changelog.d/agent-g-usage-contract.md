### Added

- contract: §15.15, tokens and cost per run, card, instance and agent. A runner sends one record per supervised run
  (`POST /runner/placements/{id}/usage`: the four token counts and the harness's own cost figure, never the model,
  prompts or keys); the `run_id` is its key instead of an `Idempotency-Key`, a repeated `run_id` with other numbers is `conflict`
  (`run_id_reused`), a record that started more than 30 days ago is `invalid` (`too_old`), and one that overlaps a stored
  run is `conflict` (`run_overlaps`). The hub records every card the instance held during the run, from a holding per card
  and instance it keeps for this, with the run's start taken as the hub saw the run open, counts a shared run in full for each card, and never prices tokens. Card totals for the
  project's human members and the agents whose runs counted, member and agent totals for the owner and the human admins, nothing public; the owner's export
  lists the daily totals. The routes are not built yet.
