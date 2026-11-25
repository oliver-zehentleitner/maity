### Changed

- hub: joins from outside are on (`outsiders.JOINS_ON = True`), by the owner's decision of
  2026-11-25 (tsk-25wd170kbf12). A signed-in person who is no member brings an agent of their
  own into a project only where its admins stored `agent_owners: anyone` and the project is
  public; such an agent still claims no card itself, a person who manages the project's cards
  gives it one (§6.5). The outsiders' block and own quota are not built yet. The README in every
  language and the docs no longer say that no hub takes agents from outside.
