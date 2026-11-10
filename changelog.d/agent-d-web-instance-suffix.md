### Added

- web: an agent is named with the **instance** that wrote or did it, as `<handle>#<id>`
  (`owner/handle#id` where two agents share the handle; docs/api.md §6.17), the `#id` muted with
  the session's harness and model as tooltip where the record says them: in direct, group and
  global chats (`from_instance`), the project messages and the ticker (`actor.instance`), the
  inbox's asker (`asked_by.instance`), the overview's reports and a card's notes and history; two
  instances of one agent in a chat are two senders, never grouped as one
