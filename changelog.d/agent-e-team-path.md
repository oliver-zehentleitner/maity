### Changed

- docs, hub, web: the project's Team view moves from `/<owner>/<slug>/members` to
  `/<owner>/<slug>/team`, with its member pages (`team/<id>[/<tab>[/<instance>]]`), so that the
  path matches the name (the maintainer's decision of 2026-11-10). The public page is at `/team`
  and the public read answers its `kind` as `team`. `members` stays reserved (no slug takes it);
  `/<owner>/<slug>/members` serves no page and does not redirect. The membership API
  (`…/members`) and the Team page's Members tab keep their names.
