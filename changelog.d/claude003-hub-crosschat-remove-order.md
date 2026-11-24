### Fixed

- hub: `DELETE /me/cross-chats/{id}/participants/{member_id}` answers
  `not_found` to anyone who cannot see the chat, in the same order as the
  other cross-chat routes.
