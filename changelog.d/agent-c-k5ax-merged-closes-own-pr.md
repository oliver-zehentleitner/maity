### Security

- hub: under `merged_closes: auto` a merged pull request closes a card on its own only when it
  is that card's own: its head branch as the forge reports it is the reported remote branch in
  the project's own repository, its title or body names the card, it was merged after the
  report, and no other card names it or was closed by it, so one pull request closes at most one
  card. A branch the forge no longer has no longer stands in for that match. In every other case
  `task_merged` says `closed: false` with the reason in `blocked_by` (`head_ref`,
  `pull_request_unnamed`, `merged_before_report`, `pull_request_shared`), and the done authority
  closes the card. `GET …/probe` shows a pull request's `head_ref`, `head_repo` and `card_ids`.
