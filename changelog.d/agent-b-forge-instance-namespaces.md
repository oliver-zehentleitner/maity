### Changed

- contract: the instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects in the
  operator's own namespaces, listed in the new setting `MAITY_FORGE_INSTANCE_NAMESPACES`
  (§11.4), and there only public repositories; unset, it serves no project. Every other project
  is read only through its namespace owner's App or token after confirmation, otherwise
  `probe_via` is `null` and the dashboard asks the owner to connect (§6.1, §11.4)
- contract: a name listed in `MAITY_FORGE_INSTANCE_NAMESPACES` that is neither a handle nor an
  alias is `reserved` for human and organisation handles at registration, `POST /orgs` and a
  rename while it is listed (not for the operator's `maity-hub owner create`), and the hub warns
  about it and about a listed former name at start (§2.7.4, §6.24, §11.4); the public page's Why is read only for the operator's own
  namespaces (§16.9)
