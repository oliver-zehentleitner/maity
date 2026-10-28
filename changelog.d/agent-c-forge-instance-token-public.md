### Security

- The hub reads with the operator's forge token (`MAITY_FORGE_GITHUB_TOKEN`) only repositories the
  forge reports public (docs/api.md §11.4). It checks before the first read and again at most
  every 10 minutes. A private repository, or one the token cannot see, answers
  `probe_not_configured` with `details.reason` `private_without_grant` or `no_grant`; only a
  project admin sees the reason.
