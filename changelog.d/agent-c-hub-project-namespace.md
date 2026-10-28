### Changed

- hub: projects live in their owner's namespace (§6.25). Every project route is
  `/projects/{owner}/{slug}/…`; a project carries `id`, `owner`, `full_name` and `legacy_slug`, and
  every project reference, `by_project` key and input (`attach`, `show_reason_in`, the
  notifications filter, preferences) uses the full name; placements for the runner carry
  `project_id` and `project_aliases`. A slug is unique per owner with its aliases and never a route
  word; dashboard route words are no human handles. Old paths answer `client_outdated` (426) to the
  CLI and `project_path_outdated` (410) otherwise; old badge and public swarm addresses redirect
  (301) while served; the forge webhook keeps a pre-migration project's old address. Migration
  `0060` gives every project its namespace owner, `legacy_slug` and the `project_alias` table
- hub: `scripts/namespace_codemod.py` rewrites route and test paths into the namespace; idempotent
