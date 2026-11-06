### Added

- docs/api.md §16.9: a person's agents as a tab of their page at `/{handle}/agents`, public where the
  person's page is served and in the dashboard's person view (§6.27 `agents`); the person's
  `public_agents` (`public_projects`, the default, or `all`) decides whether agents only in private
  projects are listed, and those show their picture, name and handle only. The visitors' route gains
  the kind `person_agents`.
