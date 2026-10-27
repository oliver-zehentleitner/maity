### Added

- docs/api.md §6.23: the resume packet's `keep_the_why` block tells every agent how to install and
  load the skill (`skill.install`, `skill.load`, from `MAITY_KTW_SKILL_SOURCE`), where the project's
  `.keep-the-why` is (`config`), and whether to adopt the repository's personal defaults
  (`personal_defaults`, the new policy field `keep_the_why_defaults`, default `adopt`). The CLI prints
  the block first, before the briefing.
