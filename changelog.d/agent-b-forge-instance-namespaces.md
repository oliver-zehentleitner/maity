### Changed

- contract: the instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects in the
  operator's own namespaces, listed in the new setting `MAITY_FORGE_INSTANCE_NAMESPACES`
  (§11.4), and there only public repositories; unset, it serves no project. Every other project
  is read only through its namespace owner's App or token after confirmation, otherwise
  `probe_via` is `null` and the dashboard asks the owner to connect (§6.1, §11.4)
