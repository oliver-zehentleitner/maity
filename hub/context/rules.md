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
bump. `sync_text` runs once in the lifespan after the schema check, in one transaction, and takes the
projects in id order, so two hubs starting together lock them in the same order and cannot deadlock.
The first start after the migration counts every existing project once.

`GET /projects/{slug}/rules` chooses the duty line the way the event stream does: an agent whose session
has a `supervisor` gets §15.11's supervised line, every other caller (a self-waiting agent, a human) the
`DUTY_SELF` line. Rejected: always the self line there (the document an agent reads would then differ from
its resume packet), and a `?supervised=` parameter (the caller could pick a duty its session does not have).

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

## Role rules: the reviewer's narrowing is a line of its own, and the errors carry the settings path

**Id:** 8b9bc48b-4f12-4082-8ca5-c8e00b04ca01
**Type:** decision
**Status:** active
**Evidence:** confirmed

`settings.role_rules` (§6.1, §6.9) adds a section `## Set by the project for your role` after the
naming line and before the owner's text. For a reviewer with `subagent_per_card`, the narrowing the
contract asks for (the fresh context is a subagent's, never the reviewer's own) is a separate line,
`SUBAGENT_REVIEW`, below the subagent line. The review line itself stays one text for every reviewer.
The role a caller reads its lines for is `rules.rule_role`: a project role read as its base, a
security team as the role it counts as (`scopes.counts_as`), and no lines for any other role.

The refusals name the field with its full path, `settings.role_rules.<key>` and
`settings.role_rules.<role>.checklist`, like every other settings error and like pydantic's own
`extra_forbidden` inside the object. The contract first wrote them without `settings.`. The lead
chose the full path and had the contract corrected in the same pull request, so contract and hub
never disagree on main.

**Reason:** one review line per reviewer, whatever the project set, keeps the line and its tests in
one place, and the narrowing reads the same whether or not the review line is changed later. A
settings error without the prefix would be the only one of its kind, and a client that maps errors
to form fields would need a special case.

**Rejected alternatives:**
- Rewriting the review line for a reviewer with `subagent_per_card` ("your own or a fresh
  subagent's" becomes "a fresh subagent's"): two versions of one line, which the digest, the tests
  and any later change of the review line would all have to follow.
- The error fields without `settings.`, exactly as first written: inconsistent with the rest of
  the settings and with the nested path pydantic reports.
