# Keep the Why export

## The export lives in memory, read on request and refreshed in the background for the view

**Id:** f5af1bd9-bb11-4310-b751-334de2668dfe
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (docs/api.md §11.3), with the hub owner's notes on caches; waiting rule and the 30 s floor from the coordinator's adversarial review, 2026-10-22
**See:** outbound.md#reads-whose-host-comes-from-data-connect-to-the-address-that-was-checked — a196b7db-8af0-4863-8852-031d4dbb35f8 — as of 2026-10-22
**Revisit when:** a second replica runs (each would read the families on its own), or the families grow so large that a cold read after a restart is felt

`ktw.Cache` holds, per project, the last read of the whole family and
each member's last good export.
- **The endpoint** reads through when the entry is older than `max_age`.
  One read per project runs at a time. While it runs, other requests get
  the cached answer at once (`fresh: false`); a request with nothing
  cached waits at most half a second, then gets `503`.
- **No read more often than every 30 seconds:** `max_age=0`, and any
  other `max_age` below 30, is answered from the cache within 30 seconds
  of the last read.
- **The project view** only reads the cache. A missing or stale entry
  schedules one background read per project on a pool of two threads,
  so a view built right after a restart shows `null` until that read
  lands.
- **What is stored:** the summaries and the entries that need
  attention, cleaned, never the export itself.
- **Ending:** all of it ends with the process.
- **Budget:** one read of a family has 30 seconds, configs and exports
  together. A member not read by then is `timeout`. Anyone who can push
  to the repository could otherwise name a slow host and tie up threads.

**Reason:**
- §11.3 forbids storing the export: Keep the Why stays external, and
  the database holds nothing from `context/`.
- A view must never wait on up to 32 outbound reads, nor let anyone who
  can list projects trigger them in the request.
- A restart is rare, and the first request after it reads the family
  anyway.

**Rejected alternatives:**
- A table for the summaries: against §11.3 and its rule that only the
  cache keeps entries.
- Reading the family inside the project view when the cache is stale:
  up to 32 reads of 10 seconds behind a page load.
- Requests waiting for a running read to share its result: the route
  runs on the server's request thread pool, so every waiter holds a
  thread for up to the whole budget, and a few dozen requests for one
  slow family stall unrelated requests.
- Only `max_age=0` held to 30 seconds: `max_age=1` would re-read up to
  32 configs and exports every second against the operator's token.
- The probe's worker sweeping all families: it exists only with a
  forge token, and a public repository's families are readable without
  one.

## The Keep the Why policy stores only what a human set; the provider keeps its boolean column

**Id:** a0966b9e-2263-44c1-9098-3c1f5d709911
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the card for the memory provider and the Keep the Why policy, 2026-10-27; `docs/api.md` §6.1, §6.23
**Revisit when:** a second memory provider is added, or the policy needs a third value

`policy.keep_the_why` is read as `required` while the provider is `keep-the-why`
and nobody set it, `optional` under `none`. The column `keep_the_why_policy`
holds only a human's own value and is `NULL` otherwise; the policy object
carries the effective value, and `policy.columns()` never writes it back. The
provider stays in the boolean `keep_the_why`; `memory.provider` is derived from
it, so no data migration and no second source of truth. A project's
`keep_the_why_defaults` is a plain column with the default `adopt`.
`MAITY_KTW_SKILL_SOURCE` must be an `https` URL and the hub stops at start
otherwise: the three texts it produces are instructions that an agent reads.

**Reason:** every policy write rewrites all policy columns from the current policy
object. Storing the effective value would freeze the default on the first
unrelated policy change (a badge, a preset), so a project on `none` would
come back from `none` as `optional` instead of `required`. A provider
column would have had to be kept equal to the boolean the view and the rules
text already read.

**Rejected alternatives:**
- Store the effective value in every policy write: freezes the default, as
  above.
- A `memory_provider` string column with the boolean as a mirror: two columns
  that must agree, for one provider and one alias.
- Accept any URL scheme for the skill source: the value ends up in an
  agent's instructions, so a `file:` or `javascript:` source is refused.

## Setup options live in a column of the project; the setup cards are the hub's, found by their kind

**Id:** 56fcd342-aa6a-4191-8701-e76fc49be399
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the setup-cards pull request of the memory-provider card, 2026-10-28; `docs/api.md` §6.21
**Revisit when:** a project may change its setup options after creation, or setup cards need to be told apart by option

`project.setup` is a JSON column holding the three booleans and `cards`: `null`
before the cards exist, the list of ids after (`[]` when no option was on),
and the whole column `NULL` for a project that predates it. The cards carry
`kind: setup`, which only the hub creates (`POST …/tasks` answers `kind: hub_only`).
The packet's `setup` is read from the cards by kind and status, not from the
stored id list, so a cancelled or done card drops out without any bookkeeping.
The body of `setup` is validated in code: the contract names the reasons
`not_a_boolean` and `unknown_field`, which pydantic's own types would not give.

**Reason:** the options are chosen once at creation and the cards do not change
them, so the column is the record of the choice, and `cards` being `null` is
what tells "no repository yet" from "processed, nothing to create". The
packet has to follow the board, where owners cancel and agents finish cards,
and the board is the cards.

**Rejected alternatives:**
- Derive `setup` from the cards alone: a project with no repository has no
  cards yet, so the choice would have to live somewhere else anyway.
- Keep the options in `settings`: that object is merged and shown to clients
  as editable, and `setup` is read-only after creation.

## The commitment's deadline is fixed on the credential; a minute-sweep and the policy change reconcile what is owed

**Id:** 2ac9f413-eaad-4e40-9637-af4430cb0128
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session of the commitment pull request of the memory-provider card, 2026-10-28; `docs/api.md` §6.23
**Revisit when:** a deadline or an owner's request has to be visible without a credential row, or the sweep's one-minute delay is a problem for a withdrawal

An instance is a credential, so its commitment lives on the credential row:
when it confirmed and in which session, its deadline `acknowledge_by`, the
time of the reminder and the id of the owner's request. The first resume under
`required` sets the deadline once; later resumes change nothing. One
reconcile function does the rest, and a worker runs it once a minute for
projects that still have an unconfirmed instance with a deadline: it sends the
reminder to an instance with an open session, files the owner's request 30
minutes after the deadline, and withdraws that request when its cause has ended
(the instance revoked or replaced, the membership ended, the profile deleted,
the policy `optional`, the provider `none`). A change of the policy or the
provider runs it at once. A new owner of the profile gets the request, the
old owner's is withdrawn.

**Reason:** the causes that end a request live in many modules (credentials,
memberships, profile deletion, ownership); one function that compares the
state to what is owed cannot miss one, where a hook in each place can. The
policy change is the one a human watches, so it runs at once; the other causes
wait for the next sweep, at most a minute.

**Rejected alternatives:**
- A withdrawal hook in every place that ends a cause: seven places, and a
  missed one leaves the owner with a request about something that is over.
- Remind at the next resume only: an agent that is already working would never
  hear of its deadline.
