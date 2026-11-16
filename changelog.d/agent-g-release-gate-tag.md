### Fixed

- ci: the release gate's upgrade-page check (`tools/release_gate.py --upgrade-page`) also
  refuses a tag that is not `v<version>` of `hub/pyproject.toml`, at once and before any
  wait or build. The image workflow (`publish-image.yml`) already refused such a tag later,
  when the built image reported another version; it now stops in the gate, as the package
  workflow does. Without a tag (a direct run of the script), the page is checked as before.
