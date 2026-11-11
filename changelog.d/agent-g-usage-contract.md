### Added

- contract: §15.15, tokens and cost per run, card, instance and agent. A runner sends one record per supervised run
  (`POST /runner/placements/{id}/usage`: the four token counts and the harness's own cost figure, never the model,
  prompts or keys) while the run is open. When a status report changes `run` to `open`, the hub issues the run an id
  and keeps the report's time (the placement's new `open_run`, §15.5, §15.7); the record names that id as `run`, so it
  cannot land on a later run's cards. A record for a run that is not open, or one whose generation was replaced, is
  `conflict` (`run_closed`) and is lost from the totals. The `run` is its key instead of an `Idempotency-Key`, and a
  run takes one record: a second one with other numbers is `conflict` (`run_recorded`). The cards are picked by hub
  time alone: every card the instance held between the run's opening and the record's arrival, from a holding per
  card and instance the hub is to keep for this; the runner's `started_at` and `ended_at` are shown only, because
  every rule built on the runner's clock left a way to count a run on cards it never touched. A shared run counts in
  full for each card, and the hub never prices tokens. Card totals for the project's human members and the agents
  whose runs counted, member and agent totals for the owner and the human admins, nothing public; the owner's export
  lists the daily totals. The routes, `open_run` and the holding table are not built yet.
