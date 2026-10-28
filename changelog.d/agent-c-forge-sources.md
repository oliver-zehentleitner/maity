### Added

- docs/api.md §11.4: the hub reads a project's repository with the first source that covers it.
  - The order is: the namespace owner's App installation, then the owner's own token, then the
    operator's token, which covers public repositories only. The owner's grants count only while
    the owner has confirmed the project's URL.
  - `repository.probe_via` (`app`, `owner_token`, `instance`, `null`) says which source is used;
    `probe_configured` follows it.
  - When nothing covers the repository, the reason goes to project admins: `unconfirmed`,
    `installation_suspended`, `installation_removed` or `token_rejected`, alongside the existing
    reasons.
  - A grant reads its project's own repository only.
  - The probe worker also runs on an instance without an operator's token when an App or
    `MAITY_SECRET_KEY` is set.
