### Fixed

- docs: the §13 row for `maity report` in `docs/api.md` now says what the code does in the
  places it said more: the git-fact refusals come before any hub request except for a branch
  gone from the remote, where the card read and any eligible linked-PR probes come first; a pull
  request the card links, read by the hub's probe, can stand in for gh, the first match among
  the links wins, and linked pull requests that do not match refuse only when none matches,
  while a probe that cannot be asked leaves the links read before it refusing nothing; for a
  gone branch the probe's own refusal comes before the git-fact one; a pull request the card
  links or its last report names needs no confirmation; and the stderr line names the title and
  that the probe read it. It also says that gh rechecks a still-open pull request of the last
  report before the refusal, and `cli/context/report.md` no longer says every non-matching
  linked pull request refuses, nor that only links in the project's repository are asked (links
  to other repositories are asked too and count toward the five). The behaviour is unchanged
  (tsk-0nhgzdsek8dx).
