### Added

- Hub: `PATCH /projects/{owner}/{slug}/tasks/{id}/notes/{note_id}` edits a note in place; the old
  text is rewritten out of the note's `note_added` and earlier `note_edited` events, the new
  `note_edited` event reaches everyone involved in the card, mentions are computed again, and a
  redaction now also clears the edit mark.
