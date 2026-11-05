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
deletes their account in two steps: a request with the password (the
proof of the second-factor enrolment) and a step-up, then a
confirmation link by mail. Deletion ends every access at once, removes
the person's own data, ends their memberships and deletes the agent
profiles they own; what they wrote in shared projects stays, shown as
written by "a deleted account", with every id and field shape kept.
The handle and aliases stay reserved for good. Whoever wants their
words gone redacts them first.

**Reason:** opening registration to other people means each of them
must be able to leave with their data without asking the operator. The
password and the mail together keep both a stolen session and a read
mailbox from deleting an account alone. Keeping ids and reserving the
handle keeps old links, names and mentions from ever meaning someone
else.
Keeping the projects' record keeps other members' history readable.

**Rejected alternatives:**
- Deleting everything the person wrote along with the account: other
  members' threads, decisions and cards would lose their context; the
  person can still redact before deleting.
- Deletion only by the operator on request: does not scale and puts
  the operator in the middle of every exit.
- Deleting at once on the first call: a session left open on a shared
  computer would be enough to destroy an account.

## The pages without inline style allow the product line's one block by its hash

**Id:** 32f18f7d-91c7-40c3-898f-6137cac6969a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's ruling in the review of the hub's product line (2026-11-03), on the reviewers' point that the line was neither centred nor muted on the link, join and maintenance pages; `hub/src/maity_hub/product_line.py`
**See:** scope.md#every-page-of-the-platforms-own-interface-ends-with-one-product-line-also-on-a-self-hosted-instance — ba8583f2-7a56-4435-8c4c-6ab2c9bf7378 — as of 2026-11-03

The hub's pages under its default policy `default-src 'self'` (the mail
link pages, the join page in a browser, the
`503` maintenance page) carry one fixed `<style>` block for the product
line and answer with `default-src 'self'; style-src 'sha256-…'`, the
hash of exactly that block. A test checks that the hash in the header
is the block's.

**Reason:** the contract asks for a centred, muted line on every page,
and these pages allowed no style at all. A hash source admits that one
block and nothing else: an injected `<style>` or `style` attribute
still does not apply. The test keeps an edit to the block from silently
dropping it.

**Rejected alternatives:**
- `style-src 'unsafe-inline'`: any injected style would apply on pages
  whose path holds a token.
- An exception in the contract for pages without a stylesheet: the line
  would look different on exactly the pages a newcomer sees first.
- A stylesheet file: the join host serves no assets (§1.1).

## The mail link pages of §18.6 take the frame's policy, not the product line's hash

**Id:** 8191d964-95b1-4c3b-b12d-d0c7f4cfc422
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-w62n5p0v9d47 (the maintainer found the four pages bare, 2026-11-04) and lotse#wtwy's go on the plan (2026-11-05); contract `docs/api.md` §1.1, §16.7.5, §16.13, §18.6
**See:** security.md#the-pages-without-inline-style-allow-the-product-lines-one-block-by-its-hash — 32f18f7d-91c7-40c3-898f-6137cac6969a — as of 2026-11-05

The pages of §18.6 (verify the address, unsubscribe, second-factor
reset, account deletion) stand in the frame of §16.7.5, as the sign-in
link's page does, and answer with its policy: `default-src 'none'`, the
hub's own stylesheets, fonts and images, the fallback style by its hash,
`form-action 'self'`, `base-uri 'none'`, `frame-ancestors 'none'`. The
frame's footer takes the product line's place. Words, statuses and the
one explicit button stay as they were. Registration's link page keeps
its own shell and the line.

**Reason:** the card asked for the public pages' look under a policy
that stays strict, and at first for the policy itself to stay as it
was. That part cannot hold: the old `style-src 'sha256-…'` admits one
inline block, and a hash source never admits a `<link>` stylesheet. The
frame's policy loads only the hub's own files and is stricter in every
other directive, and one string for all five link pages keeps them
alike. A test pins the string.

**Rejected alternatives:**
- A path source for the one sheet (`style-src 'self'/assets/landing/public-pages.css`):
  a source path ignores the query, so it pins no digest, and the frame
  needs `landing.css` and the fonts as well; it adds nothing over `'self'`.
- The whole look as more inline style allowed by its hash: every change
  to the look changes the header, and the fonts still need `font-src`.
- The product line under the frame's footer: lotse#wtwy chose the same
  ending for every link page, as on `/mail/sign-in` and the framed
  `/login` (req-5k1gvfsmcg9k).

## A page with a token in its path sends no referrer; its outgoing links say so too

**Id:** 4a01739c-d565-4384-b806-3662f935e0a5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's ruling in the review of the product-line contract (2026-11-03), on the reviewer's point that the line ends pages with a token in their path; contract `docs/api.md` §1.1 and §16.13
**See:** scope.md#every-page-of-the-platforms-own-interface-ends-with-one-product-line-also-on-a-self-hosted-instance — ba8583f2-7a56-4435-8c4c-6ab2c9bf7378 — as of 2026-11-03

The pages the hub renders with a token in their path (the join page in a
browser, the `/mail/…/{token}` link pages) answer with
`Referrer-Policy: no-referrer`. The dashboard's invitation page,
`/invite/{token}`, is the app shell: the hub sends the same header on
the shell under `/invite/`, and the page sets
`<meta name="referrer" content="no-referrer">` as well, also when a
maintenance window stands instead of the invitation, for a tab that
reached the page without loading the shell there. The product line's links carry `rel="noopener noreferrer"` on
every page.

**Reason:** the product line puts links to github.com and maity.team on
exactly the pages whose address is a secret, and a click would send that
address on in the `Referer` under a browser's default policy. The
policy on the page covers every link and request on it, not only the
line's; `noreferrer` on the links keeps them safe where a page has no
policy yet.

**Rejected alternatives:**
- `noreferrer` on the line's links alone: any other link or request on
  the page would still send the token, depending on the browser's
  default.
- Relying on the browsers' default policy
  (`strict-origin-when-cross-origin`): it is a default, not a promise,
  and an older or configured browser sends the whole path.
