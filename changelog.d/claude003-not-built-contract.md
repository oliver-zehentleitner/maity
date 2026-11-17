### Changed

- docs: the contract marks what the hub does not build yet (tsk-m80nbn1k7axh). §6.19
  "Between two owners" now states that the hub refuses every cross-owner takeover with
  403 `forbidden`, `details.reason: cross_owner`, on `POST …/takeover` and on an agent's
  move after the lease, and keeps the owner's notice and objection as the target; the
  error table names `cross_owner`, and §7 marks the takeover notice and its fields.
- docs: §6.28 "Briefings" marks every part the hub does not build yet, item by item,
  and says what is built today: the layers (`guide_trust`, `guide_role`,
  `own_owner_global`, `owner_global`, `role`), the account texts `/me/briefings`, the
  project texts `/projects/{owner}/{slug}/briefings`, their lengths, the `red_team_guard`
  warning, the notice and consent for another owner's agent with the profile's
  `project_texts` (§6.3), `briefing_changed` and the public assembled briefing are
  marked not built, planned in tsk-ssd3gcxvnrkm. Built today are `membership.guide`, the
  one-text `membership.briefing` from the membership or the project's onboarding
  briefing, and the membership briefing's versions (`GET …/members/{id}/briefings`).
  §2.3, §5.2, §7, §19.3.1, the caps table, the endpoint index and the event table carry
  the same markers. No hub change.
