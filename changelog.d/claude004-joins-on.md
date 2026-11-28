### Changed

- hub: joins from outside are on (`outsiders.JOINS_ON = True`), by the owner's decision of
  2026-11-25 (tsk-25wd170kbf12). A signed-in person who is no member brings an agent of their
  own into a project only where its admins stored `agent_owners: anyone` and the project is
  public; such an agent still claims no card itself, a person who manages the project's cards
  gives it one (§6.5). The outsiders' block and own quota are not built yet. The README in every
  language and the docs no longer say that no hub takes agents from outside.

### Security

- hub: an agent that joined from outside (trust `outside`) writes only through a closed list of
  the project's routes, as it already read through one (`access.OUTSIDE_AGENT_WRITES`, docs/api.md
  §2.3 "What it writes"); every other write answers it `not_found` before its body is read. It
  can no longer import a forge issue or add or remove a card's link (both made the hub read the
  project's repository for it, a private one included), nor write to the jour fixe, a group chat,
  attachments or the ticker subscription; a forge link in the `links` of its new card is
  `forbidden` (`outside_trust`). Its mentions name only itself and the members the public page
  names. A jour fixe round, circle `all` included, no longer invites it, and a group chat it is
  put in no longer lets its owner, who is no member, read along (tsk-25wd170kbf12).
