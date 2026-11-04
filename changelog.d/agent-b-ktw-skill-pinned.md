### Changed

- Keep the Why: the install instructions in `AGENTS.md`, the hub's default `MAITY_KTW_SKILL_SOURCE`
  and its Git fallback name the release `v0.20.3` instead of `latest`, and the installer is
  `npx skills@1.7.6`. The `ktw-lint` action is pinned by commit SHA. `tools/ktw_pin.py` (run in CI)
  checks that every copy names the release `.keep-the-why`'s `context-schema` is on.
