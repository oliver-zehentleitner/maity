### Changed

- hub: a project repository may be an https URL on any DNS host, including
  a nested GitLab group. The hub stores and links it and does not fetch
  the URL. A host is checked as ASCII before it is lower-cased. Off GitHub
  there is no probe and no token; a probe read answers `probe_not_configured`,
  with `forge_not_github` for `project:admin`
  (docs/api.md §6.1, §11).
- hub: `project.repository_url` is 2048 characters, the contract's maximum.
