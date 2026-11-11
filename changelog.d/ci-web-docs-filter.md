### Fixed

- ci: the `web` job also runs when a pull request changes `docs/api.md` or the landing page's script
  (`hub/src/maity_hub/landing_assets/`), both of which `make -C web check` reads; #1593, which changed `docs/api.md` and no
  file under `web/`, merged green and left the web check red on main. A new test, `web/tools/test_ci_paths.py` in
  `make check`, fails when `check.py` builds a path with `os.path.join(os.path.dirname(ROOT), ...)` that the `changes` job
  does not gate the web job on; a read that does not start from `os.path.dirname(ROOT)` is not seen.
