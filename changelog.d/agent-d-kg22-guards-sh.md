### Added

- tools: `tools/guards.sh` runs the guard tests before a review request in
  one run: the hub's per-human tables test, the web's hub shapes, generated
  fixtures and check. It fails while one of them fails or leaves the work
  tree changed, and stops with exit 2, never 0, when it cannot run. It tests
  the hub of its own work tree. CONTRIBUTING asks coders to run it before the
  review request.
