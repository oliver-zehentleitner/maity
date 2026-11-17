### Changed

- docs: §2.3 "Project roles" gives the list a `version`, read with `GET …/roles`; a
  `PUT` names the version it was made on as `base_version`, required, and one that is
  no longer current is `409 conflict` with `details.current_version` and
  `details.base_version`, as for a card's restricted text, a note and a soul. A `PUT`
  that changes nothing keeps the version. Marked not built yet (tsk-pw0aagxnydr9); the
  hub and the dashboard follow in part 2.
