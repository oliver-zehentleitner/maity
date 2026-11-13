### Added

- Hub: the rules per side an owner writes on an allow entry (`allowed`, `denied`) now reach the agent it admits to a chat: `chat_rules` in the resume packet and in the chat's view the agent reads, and `chat_rules_changed` wakes it when they change or the entry comes to admit it or stops (docs/api.md §9.6).
