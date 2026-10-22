# Runner

## The configuration refuses unknown keys and documents every default; tomllib only from 3.11

**Id:** f2a34d72-f074-474c-87bb-2d8c6bccd60e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design v2 §5.1 and §12 question 7; the coordinator's binding answers on the runner configuration, 2026-10-22
**Revisit when:** the CLI's floor moves to Python 3.11, or the dashboard's pairing panel generates keys `check` does not know

`maity runner` reads a TOML file (`~/.config/maity-runner/runner.toml`,
`--config` or `MAITY_RUNNER_CONFIG`). Only `hub.url`, `limits.projects`,
`limits.repositories` and one `[harness.<id>]` are required; every other
key has a default, and `maity runner check --explain` prints them all.
Unknown keys are refused with their full dotted name. `tomllib` is
imported only on 3.11 or newer; on 3.10 every `maity runner` command
refuses, and the rest of the CLI keeps its 3.10 floor.

**Reason:** the dashboard writes a starter file trimmed to the required
keys, so the defaults have to be the documented ones and nothing else; a
typo that silently fell back to a default would widen or narrow what a
runner may do without anyone noticing, which is the same reason the API
refuses unknown fields. Gating `tomllib` keeps agent hosts on 3.10 working,
since agents need `maity join` but not the runner.

**Rejected alternatives:**
- Moving the whole CLI to 3.11 (the design's draft assumption): every agent
  host would need 3.11 for a feature only runner hosts use.
- A vendored TOML parser or JSON configuration on 3.10: a third-party
  parser breaks the stdlib-only rule, and JSON gives operators no comments
  in a file they edit by hand.
- Ignoring unknown keys with a warning: a warning on a service's start is
  easily missed, and the key decides what agents may touch.

## Repository entries and project URLs go through one normalisation

**Id:** b1571548-5a54-476c-bb1c-b32a669cf7e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's binding answers on the runner configuration, 2026-10-22
**Revisit when:** a forge is supported whose repository paths are not `owner/name`, or owners ask for a narrower glob

`limits.repositories` accepts `host/owner/name` and one wildcard form,
`host/owner/*`. Config entries and the project's `repository.url` are
both reduced by `normalise_repository`: scheme and user dropped, trailing
`/` and `.git` stripped, host lowercased; owner and name keep their case.

**Reason:** the dashboard writes `github.com/owner/name` while the hub
stores URLs like `https://GitHub.com/owner/name.git`. Normalising only one
side would make a runner refuse its own project. One owner-wide form
covers the real case (all of an organisation's repositories) without a
glob language whose matches an operator has to reason about.

**Rejected alternatives:**
- General globs in owner and name (an early draft of this module): `*`
  and `?` anywhere make it hard to see what an entry admits, and nothing
  needed them.
- Lowercasing owner and name too: forges differ on case sensitivity of
  paths, so only the host, which is case-insensitive everywhere, is folded.

## `pair` reads only `[hub]` of an existing file and refuses before sending

**Id:** 50e407f3-e2ef-4ee2-a574-932b09e67669
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's binding answers on the runner configuration, 2026-10-22 (starter file, refusal for another hub); `docs/api.md` §13 (`--code`); implementation of runner slice R1, 2026-10-22 (reading only `[hub]`)
**Revisit when:** pairing needs anything from the configuration beyond the hub and the state directory

`maity runner pair` reads only `hub.url` and `hub.state_dir` of an
existing configuration, not the whole file. Without one, it writes a
starter file with those two keys (0600, directory 0700) after a
successful exchange. A configuration for another hub, or a state
directory that already holds a credential, is refused with exit 2 before
the code is sent. The code comes from `--code`, as in the contract, or
`--code-file` (`-` for stdin).

**Reason:** the starter file `pair` writes is incomplete until the
operator adds limits and harnesses; validating the whole file would make
re-pairing after a revocation fail on a file `pair` itself wrote. Refusing
before the exchange keeps a single-use code from being spent on a pairing
that cannot be stored. `--code-file` keeps the code out of the shell
history and the process list.

**Rejected alternatives:**
- Full validation in `pair`: see the reason; `check` is where the whole
  file is validated.
- Overwriting the configuration of another hub: it would orphan that
  runner's credential and state without a word.
