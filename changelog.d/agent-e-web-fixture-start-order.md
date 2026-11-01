### Fixed

- web: the fixture hub's start of a jour fixe round by hand refuses in the hub's order (`circle_owner_gone`, `rate_limited`, `project_closed`, `jour_fixe_open`, `no_moderator`, `too_few`) and counts `too_few` as the hub does (the circle without those who opted out, plus the moderator); a smoke check covers the count (tsk-39sjeqre25gw, the two P3 of the review of #995).
