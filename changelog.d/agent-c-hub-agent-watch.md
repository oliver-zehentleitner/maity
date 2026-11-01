### Added

- hub: agents watch cards too (§6.4): `PUT`/`DELETE …/tasks/{id}/watch` for every member; a status
  change and a message of the new type `update` (`task_id` required, `to` optional) reach and wake a
  card's watchers through `watchers:<task id>`, resolved when the event is written into a list that
  is never served; a member whose own card depends on another watches that one by itself.
