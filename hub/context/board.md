# Board

## Forge links are read in one GraphQL query per repository, only by the probe's worker

**Id:** 7acf0a83-0a4d-43e9-8be8-cf786c87d5e3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (card links), on the hub owner's review of the plan (no reads from a GET, mind the forge's rate limit)
**See:** https://github.com/oliver-zehentleitner/maity — e346b311-374d-4cf8-9468-23dd001c347a — as of 2026-10-23
**Revisit when:** a second forge is probed, or one project carries more forge links than a few GraphQL reads per round can cover

The probe's sweep, and a job the worker runs right after a link was
added, collect the forge links of each project that name the project's
own repository and read them in one GraphQL query per repository and 50
numbers (`issueOrPullRequest`), instead of one REST call per link. A link
on a closed card is read once more after it closed and never again. The
first observation of a link emits `link_observed` with `old: null`.

**Reason:** links multiply with cards; one REST read per link and round
would spend the operator's token's rate on titles nobody looks at, and a
read on a GET would make every board view wait on the forge. One query
per repository also asks the forge only about the repository the project
names, which is the rule that keeps the token's wider reach out of the
board.

**Rejected alternatives:**
- One REST read per link (`/issues/{n}`, `/pulls/{n}`): a request per
  link per round, and two endpoints to tell an issue from a pull request.
- Reading a link when the card is read: every board load would wait on
  the forge and could fail with it.
