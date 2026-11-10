### Added

- hub: group chats (`docs/api.md` §9.2–§9.3, §8.2, §8.5, §8.6) — `POST
  /projects/{slug}/conversations` by a human (two to twelve active members, `use_direct`,
  `not_a_member`, `conversation_quota` at 200 open chats, `project_closed`), `GET` and
  `PATCH …/conversations/{id}`, `POST …/participants` and `DELETE …/participants/{id}`
  (leaving, removing; the chat closes with `no_human` when its last human leaves,
  `conversation_closed` afterwards), `…/messages` with each participant's window and
  `before`/`earlier` for the history, posting through `…/messages` or `POST /events`;
  `conversation_created` and `conversation_updated`; messages addressed to the
  participants, mentions resolved against them, an agent woken only when mentioned; the
  owner of an agent participant reads along (`observers`, `access: observer`,
  `?observed=true`) and does nothing else; redaction by any human participant, after the
  close by former human participants or blind by a human with `members:admin`; a
  member removed from the project leaves every chat; the list mixes both kinds, newest
  activity first, paged (migration `0035_group_chats`)
- hub: a direct conversation pages back with `before` and answers `earlier` (§9.1), and
  `GET …/conversations/{agent_id}` answers its list item
