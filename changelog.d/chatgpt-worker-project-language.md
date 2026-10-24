### Added

- hub: humans with project administration can choose English or German as
  `settings.language`; project reads default to English, null resets the
  choice, changes emit `project_updated`, and resume includes `project.language`.
  Personal language follows with notification settings in a separate change.
