### Changed

- Web: Project settings and New project take a repository URL on any forge host, a GitLab group path too, and say the hub's `not_a_repository_url` at the field. A GitLab, Bitbucket or Gitea repository gets its merge or pull request list linked in the header.
- Hub: a repository off github.com is never read by any path, including one that skipped its own check. Every probe read there answers `details.reason: forge_not_github` to a project admin, whatever grants the hub holds.
