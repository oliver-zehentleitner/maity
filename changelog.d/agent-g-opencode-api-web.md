### Changed

- web: the opencode harness is labelled "OpenCode" on the runner pages and
  in the start form, as the landing page names it.
- docs: `docs/api.md` §15.3 describes `opencode` like the other harnesses:
  what it runs (Grok), its confinement and sandbox, its modes, its models
  and that it has no installer, so no `login_needed`; §15.5 and §15.13 say
  what a placement or a local start without a model means for it.

### Security

- web: the start form on a runner names a model for every OpenCode
  placement. It offers OpenCode only with the models its runner advertises,
  with no "runner's default", sends nothing until one is chosen, and leaves
  OpenCode out, saying why, where the runner names no model: without
  `--model` opencode runs a model opencode hosts, and the clone's
  conversation would go to opencode's servers.
