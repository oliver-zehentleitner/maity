### Security

- The hub reads with the operator's forge token (`MAITY_FORGE_GITHUB_TOKEN`) only repositories the
  forge reports public (docs/api.md §11.4). It checks before the first read, again at most every
  10 minutes, and at once after the forge refuses a read. A private repository, or one the token
  cannot see, answers `probe_not_configured` with `details.reason` `private_without_grant` or
  `no_grant`; only a project admin sees the reason.
- The hub no longer follows a forge redirect, not even within the API host. A renamed or moved
  repository stops reads with `details.reason: repository_moved` until a project admin sets its
  new URL.
