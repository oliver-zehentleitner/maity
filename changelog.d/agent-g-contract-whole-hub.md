### Added

- hub: `GET /projects/{owner}/{slug}/contract` reads the file `settings.contract_path` names
  (default `docs/api.md`) whole at the default branch's commit, with its table of contents,
  under an `ETag` that answers `304`; `settings.contract_path` is checked as a Markdown path
  on `PATCH`, and the read walks the commit's directory trees, refusing a truncated tree, a
  symlink or a submodule as `not_markdown` (docs/api.md §6.8, tsk-zd9es4kp51w1).

### Changed

- hub: a contract file is read up to 4 MiB, a card's section too; a file GitHub answers
  without content above 1 MB is read in its raw form.
