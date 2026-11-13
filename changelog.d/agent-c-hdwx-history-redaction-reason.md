### Security

- hub: a card history entry's redaction tombstone shows its `reason` as §8.5
  says, as a note's does: to the human owners and admins and the redactor,
  `null` for every other reader — in `GET …/tasks/{id}/history`, in the
  field values of `task_created` and `task_updated` on `GET /events`, and in
  a link answered from a redacted entry.
