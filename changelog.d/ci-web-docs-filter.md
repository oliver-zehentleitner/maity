### Fixed

- ci: the `web` job also runs when a pull request changes `docs/api.md` or the landing page's script
  (`hub/src/maity_hub/landing_assets/`), both of which `make -C web check` reads; a contract-only change such as #1593 merged
  green and left the web check red on main. A new test, `web/tools/test_ci_paths.py` in `make check`, fails when `check.py`
  reads a path outside `web/` that the `changes` job does not gate the web job on.
