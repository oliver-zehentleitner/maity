### Added

- web: Forge access shows an installation of the GitHub App on a GitHub organisation as one. A link
  that GitHub no longer reports its human as an owner of (`not_admin`) says so, and that it serves
  nothing; once the human is an owner again it serves after a check confirms it (the hub checks
  when it needs the installation or the page opens, at most once every 10 minutes), and until then
  another owner may link it. An active one that lists no repositories says that it either covers
  none on GitHub or had no check in the last 10 minutes that GitHub still reports the human as an
  owner. The human docs also say when a link's reads stop showing. The setup's refusals for an organisation are said in words:
  not an owner of it, another owner's link (link it again once GitHub no longer reports them as an
  owner), and GitHub not answering, with a hint that the instance's App must be allowed to read
  the organisation's members (tsk-2m5jbwemb21x).

### Fixed

- web: a bell item about forge access (added, or stopped because the human is no longer an owner)
  leads to Forge access; it led to the sessions, like every other security item.
