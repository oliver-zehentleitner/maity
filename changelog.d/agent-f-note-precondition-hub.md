### Changed

- hub: a card note carries `version` (1 when posted, one more with every edit and with its
  redaction). `PATCH …/notes/{note_id}` and `POST …/notes/{note_id}/redact` require
  `base_version`: without it the hub answers `invalid` (`base_version: "required"`), and on a
  stale one `409 conflict` with `current_version`, `base_version` and the note as the caller
  reads it now. Nothing changes in that case (§6.16). Notes posted before have the version 1;
  their earlier `note_added`/`note_edited` events carry no `version` until an edit or a
  redaction rewrites them.
  Breaking for clients: an edit or a redaction from an older client is refused. Deploy the hub
  together with the dashboard that sends `base_version` (the web part of the card); the CLI
  neither edits nor redacts notes.
