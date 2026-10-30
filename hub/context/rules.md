# Rules

## The hub's generated text is a rules input: a digest per project, counted once at start

**Id:** 0b1f59e8-a61b-4489-8c48-2a5ac48bdbd7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.9 (contract #731) and the coordinator's answers on card tsk-n6b8q0tz9yt2, 2026-10-30 (generated text counts as an input; the storage and the migration number)
**Revisit when:** the generated text grows a part that depends on the caller (then the digest has to cover that input as well), or projects are so many that a start which bumps them all is slow

`rules.generate` renders the text a member reads; its sentences live in constants and inside the
function. `rules.text_digest()` is a SHA-256 over every text constant of `rules.py` and over two
rendered sample documents (supervised and not), so a sentence written inside `generate` moves it as
well. `project.rules_text_digest` holds the digest the project's `rules_version` last counted. At every
start the hub (`rules.sync_text`, in the lifespan) takes each project whose digest is not the current
one (or is null), under that project's lock claims it with a conditional update, and bumps
`rules_version` once with `rules_changed` (`reason: "generated text"`), so an agent that resumes with
a current cursor reads the new text; a new project is created with the current digest and needs no
bump. The first start after the migration counts every existing project once.

The duty line (`DUTY_SELF`, section `## On duty`) is the same text for every harness: it points at
`hints.wait_timeout` in the resume packet and carries no number, so the document stays one text per
project and role and the digest stays small. A supervised session gets the line of §15.11 instead.

**Reason:** the contract says the text the hub generates is an input like the owner's text. Without a
digest a deployed change of a sentence reaches only agents that resume without a cursor or after the
next unrelated bump, so a running agent would go on with the old rules.

**Rejected alternatives:**
- One digest row for the instance (`instance_setting`): that table is for values an admin sets, with a
  registry; and two hubs starting together would race for one row. A column per project, claimed under
  the project lock, bumps each project exactly once.
- A one-time data migration that bumps every project on deploy: it fires once, not on the next change
  of a sentence, so the next text change would have the same gap.
- Bumping at request time when the digest differs: a read would write, and the bump belongs under the
  project lock with its event, not inside a `GET`.
