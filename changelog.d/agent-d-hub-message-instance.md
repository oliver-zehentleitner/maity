### Fixed

- hub: a direct or group chat message names the agent instance that sent it (`from_instance`,
  `null` for a human; docs/api.md §9, §6.17), and a request's `asked_by` names the instance that
  asked (`asked_by.instance`, from the asking session's credential; `null` for a human and for a
  request the hub files; §7)
