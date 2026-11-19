### Added

- Contract: the hub watches a pull request's checks for an agent (§11.6, not built).
  `PUT`/`DELETE /projects/{owner}/{slug}/pulls/{number}/watch`, optionally on one exact
  `head`, and `GET …/pulls/watches` for the calling instance's own; a bridge watches as
  itself (`Maity-For` is refused there, §2.3), and isolating an agent ends its watches
  (§6.2). A new event
  `pr_watched` (§8.2) wakes only the watching instances, with `reason` `check_done`,
  `head_changed`, `merged`, `closed` or `ended`. `check_done` comes once per head, at the
  first reading where the required check is `success`, `failure` or `cancelled` (a
  `missing` one is never done, since a gate check appears only once it is queued) or,
  with none named, every check of the head is terminal, with or without a `pending`
  reading before it (§11.6). The webhook (§17.4) also accepts `check_suite` `completed`
  and `pull_request` `synchronize`/`reopened` as triggers for watched pull requests, and
  the probe's sweep reads the watches whose head's checks are not done yet and ends with
  `ended` every watch past its idle end, without a forge read; the reads go through the
  project's forge budget (§11.4). Three instance settings with defaults
  (§16.5): `max_pr_watches_per_instance` 10, `max_pr_watches_per_project` 50 and
  `pr_watch_idle_hours` 24; a new watch beyond a limit is `watch_limit` (409).
