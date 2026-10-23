### Added

- hub: account records (`docs/api.md` §18.1) — `session_created` and
  `session_ended` for every sign-in and end, `personal_request_*` for
  every state change of a personal request, numbered per account under
  the human's row lock. The session list shows a session's `created`
  record, and a sign-in confirmed from an allowed session is in good
  standing (§2.6.5). Migration `0034`.
- hub: `GET /me/notifications` (§18.2) — every kind derived from the
  events the human may read and their own records, counts with
  `by_project`, the cursor, sealed per-project positions with the stored
  handle past 4096 characters, `after` and its long-poll.
- hub: `POST /me/notifications/read` (§18.3) — by `ids` or `up_to`; a chat
  item moves the chat's own mark; sign-in alerts only by `ids`, from an
  older session in good standing.
- hub: `PUT` and `DELETE /projects/{slug}/tasks/{id}/watch` (§6.4), never
  in an event's audience.
