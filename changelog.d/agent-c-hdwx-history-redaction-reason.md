### Security

- hub: a card history entry's redaction tombstone shows its `reason` as §8.5
  says, as a note's does: to the human owners and admins and the redactor,
  `null` for every other reader — in `GET …/tasks/{id}/history`, in the
  answer of `POST …/history/{id}/redact`, in the field values of
  `task_created` and `task_updated` on `GET /events`, and in a link answered
  from a redacted entry. A replayed `Idempotency-Key` of these calls shows
  the reason as the caller's own read does at the time of the replay. A
  redacted card title copied into `mentioned`, `note_added` and
  `note_edited` events (§20.8) follows the same rule, and a mention
  notification of such an event shows the card's redacted title.
