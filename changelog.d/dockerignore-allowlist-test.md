### Added

- hub: a test, `hub/tests/test_image_context.py`, that every file the image's wheel build reads (the requirements
  the Dockerfile names, `pyproject.toml` with its readme, package and build hook, and `hatch_build.py`'s bundled
  dashboard and join page) passes `deploy/Dockerfile.dockerignore`'s allowlist, so a new build input missing from it
  fails locally instead of in the image job, as `hatch_build.py` did in #1424.
