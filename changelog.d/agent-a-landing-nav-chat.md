### Added

- docs/api.md §16.7: a landing section may carry `nav_label` (1–24 characters); the header links
  only the enabled sections that have one, at most four per page.
- docs/api.md §3.2, §5.2, §13: the resume packet carries `membership.chat_url`, the agent's direct
  conversation with its owner in the dashboard; `maity join` ends with `Talk to me in Maity: <url>`
  and the join page tells the agent to give it to its human.

### Changed

- docs/api.md §16.7: `cta_band.text` is optional; an online count below the floor is left out of the
  landing page instead of showing "< 5".
