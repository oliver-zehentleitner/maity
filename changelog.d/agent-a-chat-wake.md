### Added

- docs: an agent participant of a group chat has `wake` (`mentions` by default, or `all`); with `all` every message of a human participant wakes it and reaches its packet, an agent's message still only by a mention. Set when adding (`POST …/participants`, `wake`) and with the new `PATCH …/conversations/{id}/participants/{member_id}` by those who manage the chat, the agent itself and its owner (§9.2, §8.2, §5.2).
