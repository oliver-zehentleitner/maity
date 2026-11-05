### Added

- hub: cross-project group chats (`/me/cross-chats`, §9.5): the owning human
  creates and manages a room of their own agents, messages stay on the chat,
  and a mention writes one `cross_chat_mention` in one project. The resume
  packet lists the chats an agent is in. The CLI, the dashboard and reporting
  a message here are not part of this change.

### Fixed

- hub: a cross-project group chat drops an agent when the membership just
  removed was the last one that was not isolated, and lifting that isolation
  does not put the agent back. Naming a deleted profile beside an unknown id
  is `not_found`. An instance mention is not written into an isolated
  membership's project.
