### Fixed

- ci: the release gate's upgrade-page check (`tools/release_gate.py --upgrade-page`) also
  refuses a tag that is not `v<version>` of `hub/pyproject.toml`. Before, the image workflow
  (`publish-image.yml`), which has no tag-and-pyproject step of its own, would have let a tag
  through on another version's complete page. A hand-started run, which is not a tag, is checked
  as before.
