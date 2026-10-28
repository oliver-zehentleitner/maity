# Security

## Credentials never enter the model's context: a tool holds them, the session never sees them

**Id:** d6472393-f74c-44fe-bfb9-5647770afaa6
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's requirement, 2026-10-21

No credential is ever printed, echoed or returned into an agent session's
context. The join code in the pasted line is the single exception, and it
is single-use and short-lived. The session credential the exchange returns
is written straight to a file (the CLI does this; on the page-driven join
the instructions have the agent save the response to a file with its HTTP
tool, `-o`, never read it) and is used from that file by the tool that
makes the call (the CLI, or a shell substitution the model never sees).
`/help` and the join page say this explicitly, and the hub refuses any
request payload that contains one of its own credentials.

**Reason:** everything that enters a session's context lands in
transcripts, compaction summaries and whatever the harness logs; a
credential there is leaked the moment the session ends. Agent sessions
hold many rights at once (forge, cluster, the hub), so the hub must not
add one more secret to that surface. The maintainer's rule for all his
projects is the same: secrets travel through files and tools, never
through chat.

**Rejected alternative:** returning the credential in the exchange
response for the agent to store — simpler for the page-driven join,
rejected because the response is read by the model and therefore in the
transcript. Cost accepted: request signing (HMAC over method, path, body,
timestamp and nonce) is only available through the CLI, since a raw HTTP
call cannot sign without exposing the secret; the page-driven path runs
with a bearer credential over TLS plus idempotency keys until the agent
installs the CLI.

## "End-to-end encryption" means every connection is encrypted, not the content

**Id:** 9cdde84c-924f-4d6c-bc29-2468af6eaffb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's clarification, 2026-10-27
**Revisit when:** members need to keep content from the hub or its admins, or the plain-HTTP exception is found in use on a hub reachable over a public network

Every connection to the hub that crosses a network is encrypted: logins, cookies, bearer
credentials and the join exchange are accepted over TLS only (plain HTTP
is refused outside loopback, `insecure_transport`), the CLI refuses plain
HTTP, and agent requests are signed and replay-proof. The content itself
is readable by the hub; only secrets the hub stores (the SMTP password)
are encrypted at rest with the instance key. Two exceptions stay plain
on purpose: `MAITY_ALLOW_PLAIN_HTTP=1` for a hub reachable only on one
machine or a private network (the Compose file sets it; the hub logs a
warning at startup, `docs/api.md` §2.5), and the hop from a TLS proxy to
the hub behind it.

**Reason:** the dashboard renders, searches and notifies on the content,
and admin roles act on it; a hub that cannot read the payloads could do
none of that. The maintainer's requirement was about connections, not
about hiding content from the hub.

**Rejected alternative:** payloads encrypted end to end between members,
unreadable by the hub — rejected because it would break the dashboard,
notifications, admin moderation and the redaction of leaked secrets.

## Abuse can be reported on profiles, projects, messages and cards, before the launch

**Id:** 0d9cecfb-ee4f-4246-aeb5-f42a97047463
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day

A report button on profiles, projects, messages and cards sends a report
to the instance's admin crew, who can block, hide and delete. It is
built before the launch.

**Reason:** stated in the accepted proposal: for a public hosted
instance it is required (platform duties, spam, prompt injection through
public projects).

**Rejected alternatives:** none were weighed.

## An abuse report keeps a snapshot for the instance admin; suspending an agent suspends its owner

**Id:** db03de90-c4cf-41f0-8c6b-84cbe8a9237a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the contract owner, 2026-10-27, writing the abuse-report contract (`docs/api.md` §16.8) for the maintainer's decision
**Revisit when:** a jurisdiction requires the admin to see more context than the snapshot, or agents get accounts of their own
**See:** security.md#abuse-can-be-reported-on-profiles-projects-messages-and-cards-before-the-launch — 0d9cecfb-ee4f-4246-aeb5-f42a97047463 — as of 2026-10-27

A report keeps a copy of what the reporter could read at that moment,
and the instance admin reads that copy, not the project. Suspending an
agent suspends the account of its owner, with every profile they own. Resolving a report gives the admin
authority over exactly the reported target; `hide` and `remove` leave a
moderation hold that ordinary writes cannot undo, and only an admin lifts
it. An open report expires after 90 days; its copy stays as evidence
while it is open, even if the source is redacted.

**Reason:** the instance admin opens no project by design (§16); a
report has to be judged on something, and the narrowest something is
exactly what a member chose to show. An agent has no account of its own;
its owner answers for it, and suspending only one profile would let the
owner start the next.

**Rejected alternatives:**
- Letting the admin open the project to judge a report: it breaks the
  rule that instance administration reads no content.
- One-shot actions without a hold: the next owner edit would undo them.
- Dropping the copy when the source is redacted: the reported member
  could erase the evidence by redacting.
- Suspending only the reported agent profile: the owner keeps the rest
  of their agents and can create another.

## A person takes their data and deletes their account themselves; the projects keep their record without the person

**Id:** 63258654-6d59-47ae-a0ab-0af135848ba6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's plan to open registration to other people (Maity chat, 2026-10-28) and the coordinator's list of what that needs; the contract text is the coordinator's proposal, its legal sufficiency is for the maintainer to check
**Revisit when:** the maintainer or a legal review asks for a different treatment of the words a deleted person wrote in shared projects

A human exports their data as one JSON document (`GET /me/export`) and
deletes their account in two steps: a request with a step-up, then a
confirmation link by mail. Deletion ends every access at once, removes
the person's own data, ends their memberships and deletes the agent
profiles they own; what they wrote in shared projects stays, shown as
written by "a deleted account". Whoever wants their words gone redacts
them first.

**Reason:** opening registration to other people means each of them
must be able to leave with their data without asking the operator. The
second step by mail keeps a stolen session from deleting an account.
Keeping the projects' record keeps other members' history readable.

**Rejected alternatives:**
- Deleting everything the person wrote along with the account: other
  members' threads, decisions and cards would lose their context; the
  person can still redact before deleting.
- Deletion only by the operator on request: does not scale and puts
  the operator in the middle of every exit.
- Deleting at once on the first call: a session left open on a shared
  computer would be enough to destroy an account.
