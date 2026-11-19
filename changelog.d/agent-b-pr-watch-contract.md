### Added

- Contract: the hub watches a pull request's checks for an agent (§11.6, not built).
  `PUT`/`DELETE /projects/{owner}/{slug}/pulls/{number}/watch`, optionally on one exact
  `head`, and `GET …/pulls/watches` for the calling instance's own. A new event
  `pr_watched` (§8.2) wakes only the watching instances, with `reason` `check_done`,
  `head_changed`, `merged`, `closed` or `ended`. The webhook (§17.4) also accepts
  `check_suite` `completed` and `pull_request` `synchronize`/`reopened` as triggers for
  watched pull requests, and the probe's sweep reads the watches still `pending`; both go
  through the project's forge budget (§11.4). Three instance settings with defaults
  (§16.5): `max_pr_watches_per_instance` 10, `max_pr_watches_per_project` 50 and
  `pr_watch_idle_hours` 24; a new watch beyond a limit is `watch_limit` (409).
