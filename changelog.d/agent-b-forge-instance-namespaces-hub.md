### Changed

- hub: the instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects in the
  namespaces of the new setting `MAITY_FORGE_INSTANCE_NAMESPACES` (§11.4): the probe, the
  visibility check, the first look at a new project's repository, images, imports and the
  public page's Why. Every other project is read only with its namespace owner's App or token
  after confirmation; without one `probe_via` is `null` and a new project's page starts `off`.
  Unset, the token serves no project: set the variable when upgrading (Helm:
  `forge.github.instanceNamespaces`)
- hub: a listed name that is neither a handle nor an alias is `reserved` at registration,
  `POST /orgs` and a rename (not for `maity-hub owner create`); the hub warns at start about
  such a name and about a listed former name
- web: the repository settings say what the owner connects when no grant reads the repository
