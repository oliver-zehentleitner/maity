### Added

- docs: an upgrade page per hub release, `docs/upgrade/<version>.md`, from the template in
  `docs/upgrade/README.md`: what changes for users, what the operator must do, what happens by
  itself on upgrade, what cannot be undone, and the way back. The install guide's Upgrades
  steps start with reading the pages of every version between yours and the new one.
- tools: ci refuses a hub version folded into `CHANGELOG.md` without its complete upgrade page
  (`tools/upgrade_page.py check`), and the release gate of `release-hub.yml` and
  `publish-image.yml` refuses the tag (`tools/release_gate.py --upgrade-page`). A hub release
  pull request also carries a docs pass over the quickstart, getting started and the install
  guide (hub/README.md, Releases).
