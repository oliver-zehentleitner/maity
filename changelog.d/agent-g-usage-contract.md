### Added

- contract: §15.15, tokens and cost per run, card, instance and agent. A runner sends one record per supervised run
  (`POST /runner/placements/{id}/usage`: the four token counts and the harness's own cost figure, never the model,
  prompts or keys) while the run is open; one that arrives after the run ended is `conflict` (`run_closed`) and is lost
  from the totals. The `run_id` is its key instead of an `Idempotency-Key`; a repeated `run_id` with other numbers is
  `conflict` (`run_id_reused`) while the record is kept. The cards are picked by hub time alone: every card the
  instance held between `run_opened_at`, the time the placement's run last opened, and the record's arrival, from a
  holding per card and instance the hub is to keep for this; the runner's `started_at` and `ended_at` are shown only,
  because every rule built on the runner's clock left a way to count a run on cards it never touched. A shared run
  counts in full for each card, and the hub never prices tokens. Card totals for the project's human members and the
  agents whose runs counted, member and agent totals for the owner and the human admins, nothing public; the owner's
  export lists the daily totals. The routes, `run_opened_at` and the holding table are not built yet.
