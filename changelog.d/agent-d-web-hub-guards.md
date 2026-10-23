### Fixed

- web: New group chat, its form, the blind removal of a closed group chat's message and reading
  along are offered only on a hub whose `openapi.json` lists group chats; without them the chat
  list says "This hub has no group chats yet." instead of looking empty
- web: Attach files is offered only where the hub lists attachments, and hidden once the hub
  answered 404 to the pending list
- web: a personal request (docs/api.md §7) in everything waiting is labelled Personal, answered
  and withdrawn on `/requests/{id}`, and links into no project; a human without any membership still sees theirs on `#/all`
