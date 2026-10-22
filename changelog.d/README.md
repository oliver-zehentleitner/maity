# changelog.d

Unreleased changes, one file per pull request. A pull request adds its
changelog entry here as a new file and does not edit `CHANGELOG.md`; two
pull requests then never touch the same lines, so merging one does not put
the others into conflict. At a release, `tools/changelog.py release` folds
every file into `CHANGELOG.md` and deletes them.

## The file

- One new file per pull request, named after the branch topic:
  `agent-c/runner-r4` → `changelog.d/agent-c-runner-r4.md`. Any unique
  name works; `.md` is required. `README.md` is not a fragment.
- The content is exactly what the pull request would have put under
  `## [Unreleased]`: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
  headings, each followed by `- ` bullets.
- Allowed headings, at level three only: `### Added`, `### Changed`,
  `### Deprecated`, `### Removed`, `### Fixed`, `### Security`. Use only the
  ones you need, in any order.
- A bullet starts with the part it changes, as in `CHANGELOG.md`:
  `- hub: …`, `- cli: …`, `- web: …`, `- deploy: …`, `- ci: …`. A long
  bullet may wrap; continuation lines are indented by two spaces.
- Blank lines are allowed between anything. Nothing else: no prose, no other
  heading levels, no empty file, no heading without a bullet.
- A follow-up commit in the same pull request edits the same file. A later
  pull request that changes an earlier, still unreleased entry adds its own
  file.

```markdown
### Added

- cli: `maity runner start` — runs the paired runner in the foreground
  until it is stopped.

### Fixed

- hub: `GET /runners` pages by the cursor it hands out.
```

## Check and release

```sh
python3 tools/changelog.py check                       # what CI runs on every pull request
python3 tools/changelog.py release 0.2.0 --dry-run     # show the section it would write
python3 tools/changelog.py release 0.2.0 [--date YYYY-MM-DD]
```

`check` prints every finding as `file:line: message` and exits 1.
`release` adds `## [<version>] - <date>` (today by default) below
`## [Unreleased]`: per heading in Keep a Changelog order, first whatever is
still under `[Unreleased]` in `CHANGELOG.md`, then the fragments in file-name
order. `[Unreleased]` keeps only its pointer line, and the fragments are
deleted. It refuses a version already in `CHANGELOG.md`, an invalid
fragment, and a release with nothing in it, without writing anything.

Only a release edits `CHANGELOG.md`.
