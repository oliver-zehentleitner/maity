### Added

- cli: an isolated agent (§6.2) is told so. `maity resume` starts with ISOLATED, who isolated it,
  since when and why, and says to stop; every other command, `maity wait` included, prints one
  line with the same facts and exits 5 instead of retrying.
