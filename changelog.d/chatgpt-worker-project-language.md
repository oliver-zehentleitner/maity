### Added

- hub: humans with project administration can choose English or German as
  `settings.language`; project reads default to English, null resets the
  choice, changes emit `project_updated`, and resume includes `project.language`.
  Personal language follows with notification settings in a separate change.

### Fixed

- hub: merge project settings from the row read under the project lock so a
  concurrent checklist edit cannot overwrite a human's language change.
