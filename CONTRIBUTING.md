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

## Evidence for tests and reports

These checks come from errors encountered during development: a green test
or a repeated status alone is not evidence that the intended behavior was verified.

- Every new test case gets a counter-check without the fix. Run the same
  case with the fix absent and confirm that it fails for the intended reason,
  then restore the fix and confirm that it passes. Record both outcomes; a
  setup failure is not a counter-check of the behavior.
- Report a command's resulting state only after the command has returned
  and you have checked its result. Until then, report it as running or pending.
- Before passing on a state reported in a message, verify it against the
  current source of truth. If you cannot verify it, say that it is unverified
  and attribute it to the message.
- A finding that sends someone investigating includes its counting rule:
  what was counted, over which scope, with which filters or exclusions.
  Include enough evidence to reproduce the count.

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
