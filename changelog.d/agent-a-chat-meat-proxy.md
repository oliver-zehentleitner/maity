### Added

- docs/api.md §9.3: a human switches the meat-proxy mode for one conversation (`PUT
  …/conversations/{id}/meat-proxy`, `true`/`false`/`null` = follow the profile); human participant
  entries carry `meat_proxy` (the value in this chat), `meat_proxy_chat` (the own choice, for the
  human itself) and, while on, `meat_proxy_note`.
