### Fixed

- docs: the §13 row for `maity report` in `docs/api.md` now says what the code does in three
  places it said more: the git-fact refusals come before any hub request except for a branch
  gone from the remote, where the card and the probe are read first; a pull request the card
  links, read by the hub's probe, can stand in for gh; and a pull request the card links or its
  last report names needs no confirmation. It also says that gh rechecks a still-open pull
  request of the last report before the refusal. The behaviour is unchanged (tsk-0nhgzdsek8dx).
