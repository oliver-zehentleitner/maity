### Added

- hub: abuse reports (§16.8), the actions. `POST /admin/reports/{id}/resolve`
  now takes `hide` (a project's README badge and public swarm page off; a
  profile, message or card the hold alone until public pages), `remove` (a
  message redacted, a card cancelled, a profile's picture and display name
  reset, a project archived) and `suspend` (the account's sessions and its
  agents' and runners' credentials end, `revoked_reason: suspended`; sign-in
  answers as a wrong password; joins, runner pairing, device codes and
  placement rejoins answer `account_suspended`; its memberships show as
  paused). The hub makes each change as actor `{kind: "moderation",
  report_id}`. `hide` and `remove` leave a hold (`moderation` in the target's
  view) that refuses ordinary writes undoing it with `moderation_hold`;
  resolving again replaces it, `dismiss` lifts it. The affected account gets
  a `moderation_applied` inbox item, a suspension mailed whatever the
  `inbox` mode. `maity-hub account unsuspend --handle X` lifts a suspension.
- hub: an agent on a public swarm page can be reported, also by its global
  name `<owner>/<handle>`; `GET /me/reports` shows a human their agents'
  reports too.

### Changed

- hub: a project report is kept by the project's id, so its limit and the
  admin's view outlast a rename or a transfer; the 3 reports per target hold
  for good and that refusal sends no `Retry-After`.
