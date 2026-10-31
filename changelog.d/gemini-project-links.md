### Added

- hub: a project's links to issues, wiki, discussions and chat (§6.11, §16.9,
  tsk-ayaav7naskbe): stored on `t.project`, validated and merged on
  `PATCH /projects/{owner}/{slug}`, and rendered as plain `rel="nofollow ugc"`
  links on the public project page.
- web: settings form, overview buttons, and header status buttons for a project's
  links to issues, wiki, discussions and chat.

### Changed

- web: the header status button for the project repository is labelled 'Repository'
  across all forges, keeping the forge mark.
