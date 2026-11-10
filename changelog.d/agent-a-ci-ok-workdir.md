### Fixed

- ci: the `ci-ok` gate runs in the workspace root: it has no checkout, so the workflow-wide
  `hub/` working directory does not exist there and the gate failed with every suite green
