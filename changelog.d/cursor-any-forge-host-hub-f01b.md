### Changed

- hub: a project repository may be an https URL on any DNS host, including
  a nested GitLab group. The hub stores and links it and does not fetch
  the URL. Off GitHub there is no probe and no token; a probe read answers
  `forge_not_github` (docs/api.md §6.1, §11).
- hub: `project.repository_url` is 2048 characters, the contract's maximum.
