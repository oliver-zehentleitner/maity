### Fixed

- hub: the full render of the public pages (at start and by the worker) no longer deletes the page
  of a target that became public while it ran. Its cleanup reads which targets exist when it runs,
  not the list it started from, and decides each page it would delete again under that target's
  render lock, one target per transaction, so a target switched off and on again meanwhile keeps
  its new page (PostgreSQL) and the cleanup never holds two targets' locks at once.
- hub: an avatar motif whose file name holds a NUL is refused like one with `/` or `\`. The motifs
  are not served and the hub starts, instead of ending its start with a traceback.

### Changed

- docs/api.md §6.1 says that a checklist item is checked only for the Unicode categories Cc, Cf, Zl
  and Zp, so an item made only of characters that show nothing outside them (U+3164, U+2800,
  U+034F) is stored. The hub already behaved this way.
- hub: `PUT /projects/{owner}/{slug}/roles` refuses a guide since #1501, and until the briefings
  routes exist (§6.28) no route sets, changes or clears a project role's guide. A role keeps the
  guide stored before.
