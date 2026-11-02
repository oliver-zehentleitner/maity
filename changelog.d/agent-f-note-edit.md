### Changed

- docs/api.md §6.16, §8, §8.6, §12: a note's author edits their own note with
  `PATCH …/notes/{note_id}` `{body, reason?}`, a human with `events:admin` any note with a required
  reason, an agent never another member's; no version is kept, the old text is rewritten out of the
  note's `note_added` and earlier `note_edited` events; the new event `note_edited` reaches everyone
  involved in an open card, on a closed card to the author and the newly mentioned, with
  mentions computed again; `edited: {by, at, reason}` on the note.
