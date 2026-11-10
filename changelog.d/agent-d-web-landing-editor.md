### Added

- web: the landing page's editor in sections (docs/api.md §16.7): per language the page's title and
  description and its ordered sections of the contract's types (add, move, show or hide, remove;
  their items the same way), the footer for every language; one save of the whole draft, each
  refusal said at the field its path names; **Preview the draft** opens the hub's rendering of the
  unsaved draft in a new tab (`POST /admin/settings/landing/preview`); **View as a visitor** opens
  the saved page at `/?as=public` while it is on.
- web: **Legal pages** in the instance administration (§16.7.1): the imprint, privacy notice and
  terms per language, one page per save as a new version, earlier versions linked, a page taken
  down, each draft previewed the same way; the login and registration pages link to the pages that
  are set.

### Removed

- web: the old Markdown landing editor, the dashboard's own drawing of the landing page at the root
  (the hub renders it), and the Markdown renderer's mode for path links that served it.
