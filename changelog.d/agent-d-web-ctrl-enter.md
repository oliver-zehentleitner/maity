### Added

- web: Ctrl+Enter (⌘+Enter on a Mac) sends every form with a multi-line field — inbox answers,
  chat and group chat, project messages, ticker posts, new cards, briefings and a join's
  briefing — through one helper, `M.dom.sendOnCtrlEnter`; each label names the shortcut

### Fixed

- web: Ctrl+Enter in a chat no longer sends while the Send button is disabled (a message on its
  way was sent twice)
