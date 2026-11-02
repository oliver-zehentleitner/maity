### Changed

- docs/api.md §6.16: a card note carries a `version`; editing (`PATCH …/notes/{note_id}`) and redacting
  a note require `base_version`, and a stale one is `conflict` (409) with `current_version`,
  `base_version` and the note as it is now, so that a save never brings back a text an admin removed
  meanwhile (tsk-b6wb439f88nr).
