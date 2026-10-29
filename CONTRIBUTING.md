# Contributing

Maity is one repository. `AGENTS.md` has the working conventions for
agents; this file is the short form for a human contributor.

## A change

1. Branch from `main`: `<who>/<topic>`.
2. Keep the change to one concern. A change to an interface other parts
   depend on is documented in `docs/` in the same change.
3. Lint, types and tests must be green before the pull request.
4. Documentation is part of the change: README, a changelog entry as one
   new file in `changelog.d/` (never an edit to `CHANGELOG.md`; see
   `changelog.d/README.md`), `docs/`, and `context/` for every decision,
   rejected alternative or workaround. A `context/` entry is committed
   right after it is written, in its own commit, so its Git timestamp is
   the moment the reasoning was recorded.
5. Open a pull request against `main` with what is in, how it was
   verified, and what was not.

## Commits

Imperative, plain English, one concern per commit:
`hub: claim tasks with a lease`. A handful of meaningful commits per
feature; `context/` entries are the exception and get one each.

## Issues

A bug is a GitHub issue; the form asks for the component, the version and
the steps. Feature requests and the work on Maity itself are discussed in
the project on Maity (`https://maity.team/oliver-zehentleitner/maity`),
not in issues; the issue chooser links there.

## Reasoning

Before changing something that looks odd, read `context/`. If the reason
is there, it was argued once already. If it is not, add it when you find
out.

## Security

Secrets never enter the repository. Report security problems privately as
`SECURITY.md` describes, never in a public issue.
