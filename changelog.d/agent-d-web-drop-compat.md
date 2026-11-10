### Removed

- web: the route `#/admin/users`; the users are the Users section of `#/admin`, and the old address
  is no view.
- web: New project no longer sends the `keep_the_why` alias to a hub before docs/api.md §6.21; such
  a hub is offered no project memory. The fixture hub still takes the alias until the hub drops it.
- web: the fixture hub's `removed_kind` for notification kinds removed earlier; such a kind is
  `unknown` there, as on the hub after its compatibility layer went.
- web: the fixture hub's `POST /me/notifications/read` answers `unknown` for a kind outside the four,
  as the hub does.
