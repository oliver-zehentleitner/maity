# Reports

## A card whose result is not code is reported with `code: false`

**Id:** 550e63e7-60bb-44a5-9150-6c8b333e17d7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** dogfooding on maity.team, 2026-10-22 (a text-only card could not be finished); contract change in `docs/api.md` §6.6 and §13
**Revisit when:** a card's result is neither code nor text a summary can carry (a file, a deployment), or a non-code result needs a verification of its own

A report says whether the card's result is code. `code` defaults to
`true`, and every git fact stays required. A card whose result is text —
a wording, a decision prepared for a human — is reported with
`"code": false`: all git fields `null`, `pr_status: none`, any of them
set is `invalid`, and the summary carries the result. The probe never
runs on such a report, and the board shows it as "no code" rather than
as unverified. `maity report --no-code` sends it without reading git.

**Reason:** the first text-only card on maity.team could not be
finished. `maity report` attaches the clone's branch facts whether or not
they belong to the card, and the way around the report — an admin moving
the card to `review` or `done` directly — is refused as
`invalid_transition`. A report without git facts keeps the report as the
one way into review, and saying so explicitly keeps the board from
showing every text card as an unverified code report.

**Alternatives:** unknown.

## A done card whose pull request is still open takes a new report

**Id:** 2280ced7-c51f-48f5-aab7-3bdacc7de21e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-23 (inbox request), after a report from a project on maity.team; contract in `docs/api.md` §6.6
**Revisit when:** `done` is redefined to mean merged, or a card's work spans more than one pull request

A card can be `done` while its pull request is still open: a reviewer
closes the card on approval, and the pull request then conflicts with
another merge and is rebased. The member whose report is on the card may
report again while that pull request is open and the new report names
the same pull request. The report and the probe are updated; status,
`closed_at` and the claim are not.

**Reason:** without it the card keeps showing a head the branch no
longer has, and the new head travels only in a free-text message, which
is what the report exists to replace. Updating only the report keeps
`done` meaning what it means today for counts, dependencies and
releases.

**Alternatives:** `done` waits for the merge: a reviewer's done becomes
an approval and the hub closes the card when the probe sees the merge.
Not chosen now: it changes when a card counts as done for dependencies,
releases and the board counts, a separate and larger contract. A new
report on any closed card: rejected, a `cancelled` card or a merged pull
request has nothing left to report.
