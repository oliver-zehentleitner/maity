# Attachments

## Files on messages: stored by the hub, images re-encoded and shown inline, everything else an inert download

**Id:** 2ff6d336-5d04-41f9-b6b9-f2979233b915
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, approving attachments on chat and project messages with the rules below; the contract owner's design of the details in `docs/api.md` §8.7; the contract owner's rulings of 2026-10-22 on closed projects (adding refused, removal allowed) and on who deletes
**Revisit when:** a browser is found to render an attachment response despite the headers, the per-project quota proves too small, or agents need to share files across projects
**See:** security.md#credentials-never-enter-the-models-context-a-tool-holds-them-the-session-never-sees-them — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-22

Project messages, direct chats and group chats may carry files. The hub
stores them, up to 10 MiB each and 10 per message, within a per-project
quota the instance operator sets. The bytes live in a blob store behind
the hub — a local volume by default, an S3-compatible store as an
operator option — and never in the database, which holds the metadata
and the content hash only; browsers and agents reach the bytes only
through the hub. Images (PNG, JPEG, WebP, GIF's first
frame) are decoded and encoded again under the avatar's decoder rules,
so nothing but their pixels survives, and are the only files served
inline. Every other file is stored byte for byte and only ever
downloaded: `application/octet-stream`, `Content-Disposition:
attachment`, `nosniff` and a sandboxing CSP, never HTML, SVG or script.
Exactly who can read the message can read its attachments, checked
before any cache validation. Agents fetch the content with the CLI
into a folder outside their work tree, never into it (`docs/api.md`
§13, cli/context/commands.md d1d6b49d); events and the resume
packet carry only name, size, type and id. For an agent an attachment is untrusted input,
like a web page. An attachment is deleted by its uploader, by a human
who is a participant of the chat now (for a chat message) or by a human
with `members:admin` (for a project message); observers and former
participants read it but do not delete it, consistent with their being
read-only in the chat (`chat.md`). A redaction deletes the bytes at once, deleting
the project deletes them all, and archiving keeps them readable. In a
closed project (`accepted` or `archived`) an upload, and a message that
names one, are refused; deleting an attachment and redacting its message
stay allowed.

**Reason:** humans and agents already exchange screenshots, logs and
specs, and without attachments they paste them into message bodies
(capped at 16 KiB) or route them through third-party links the hub
cannot govern. The risks are the browser and the agent. In the browser,
a file someone uploaded must never run on the hub's origin, where the
session cookie lives; serving it inert removes that, and re-encoding
images removes both the parser tricks and the metadata (a photo's
location) that an image could carry. For the agent, a file is a new
path for instructions from whoever sent it; keeping content out of
events and the resume packet means nothing reaches the model unless the
agent fetches it on purpose, and the rules tell it to read the file as
data. Binding an attachment to exactly one message gives it exactly one
audience, so the read rule is the message's and cannot drift from it.
Keeping the bytes out of the database keeps it small and portable
across its engines at a gigabyte per project, and serving only through
the hub keeps the read rule on every request. Archiving is a state a
project leaves again, so it keeps the files its messages still show.
A closed project refuses additions and never removal: an upload adds
and is refused, but deleting a file or redacting its message must stay
possible after archiving, because harmful or private content is often
found late and has to be removable whatever the project's state.

**Rejected alternatives:**
- Multipart upload: a second exposed parser (boundaries, part headers,
  several files in one body) the hub otherwise does not need; the raw
  body is already how logos and avatars are uploaded, and one body is
  one file with its size known before reading.
- A separate origin for the files: it isolates the bytes further, but
  the session cookie is host-only, so the files host would need a signed
  link with a secret in the URL, which the hub avoids; the sandboxing
  CSP plus a forced download achieves the isolation that matters. It is
  the revisit if a browser renders one of these responses anyway.
- Storing images as uploaded, as the logo is: an attachment comes from
  any member, agents included, and is shown to others; the avatar's
  reasoning (exposed parser, metadata in photos) applies in full.
- Rendering previews of text, PDF or SVG in the dashboard: each is a
  renderer of attacker-chosen content on the hub's origin.
- The bytes in the database, as for avatars: fine for a few small
  images per member, not for a gigabyte of files per project across
  three database engines.
- Presigned or redirect URLs to the blob store: the read rule would be
  checked once when the link is made, not on every read.
- Deleting the bytes when a project is archived (the contract owner's
  first draft): an unarchived project would show messages whose files
  are gone; deletion belongs to deleting the project.
- An archived project read-only for every write, deletion included (the
  second draft): it would keep a leaked secret or a private file in
  place until someone reopened the project.
- Content in events or the resume packet (inline text, previews): it
  would put untrusted bytes into every agent's context unasked.

## The CLI fetches attachments outside the work tree, never into the working directory

**Id:** b623825e-e5b0-4567-bec6-2aaa03140527
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §13 (`maity files get`) and the description of PR #216, both stating the rule and its reason; neither records it as a maintainer decision
**Revisit when:** `maity files get` gets a different default target, or agents need a fetched file in place in the working tree
**See:** attachments.md#files-on-messages-stored-by-the-hub-images-re-encoded-and-shown-inline-everything-else-an-inert-download — 2ff6d336-5d04-41f9-b6b9-f2979233b915 — as of 2026-10-23
**See:** https://github.com/oliver-zehentleitner/maity — d1d6b49d-17b8-4572-a61d-28fe99a4ac05 — as of 2026-11-13

`maity files get <id>` without `-o` writes the file outside the work
tree: into the state directory's `files/`, under a runner placement into
the clone's `.git/maity-files/` (cli/context/commands.md d1d6b49d).
Until 2026-11-13 it went into `./maity-files/` under the current
directory. `-o PATH` still writes wherever the agent names.

**Reason:** the file's name comes from whoever sent it, and an agent
usually runs in a working tree. Written straight into that directory, a
sender could drop a file that tooling there picks up and executes — in
the words of §13, "a `conftest.py` or a `Makefile`". A subdirectory of
its own in the work tree was not enough: test runners search every folder
below the clone, and `git add -A` commits what is there; outside the work
tree neither sees the file.

**Rejected alternative:** fetching straight into the working directory,
as the attachments entry above first described it: it lets the sender
choose a file name that lands next to the project's own build and test
files.

## Pending uploads are capped per membership, and humans can clear them

**Id:** 5080eb65-475b-487a-9854-80757124ccf0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's ruling of 2026-10-22 on the attachment contract (`docs/api.md` §8.7), after a review found the quota could be filled by one looping agent
**Revisit when:** members hit the pending cap in ordinary use, the project quota becomes per member, or posted attachments fill the quota in practice (then a per-member stored cap)

Each membership holds at most 20 pending uploads and 100 MiB of them at
a time; a pending upload expires after 24 hours. A human with
`members:admin` (an owner or an admin) lists every member's pending
uploads and deletes any of them; an agent's `members:admin` does not
cover that. For another member's upload the listing shows the
uploader, the size, the upload time and the expiry, never the file's
name or type: a pending upload has no message yet, so its audience is
unknown — it may be a file for the uploader's private chat — and freeing
the quota needs the size and the uploader, not what the file is (the
review finding the ruling answered). Deleting all of one agent's
uploads in one call is a follow-up, not part of this contract; until
then they are deleted one by one.

**Reason:** pending uploads count against the project's quota, so
without a per-member bound one membership — an agent in a loop above
all — could keep the quota full and every human's upload refused, with
removing the member as the only remedy. That is an agent reducing what a
human can do, which the role rules exclude. The pending cap bounds what
one member can hold back, the expiry bounds how long, and the human's
delete is the remedy that needs no removal.

**Rejected alternatives:**
- Relying on the upload rate alone (100 MiB per 10 minutes): a looping
  agent fills a gigabyte in under two hours and keeps it full.
- Refusing uploads from a paused agent: a pause is not meant to stop an
  agent putting its work down, and messages with files are part of that.

## The instance caps all attachments together, checked under the project's lock and without numbers for the member

**Id:** 67adfb38-efa6-4636-986c-33fad578a128
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-qa9r26kb2teq; the maintainer's approval of the six proposed points (place, default, counting, refusal without numbers, the check under the project's lock, the wording) through the lead, request req-y4tnqn9grxt5, 2026-11-04; `docs/api.md` §8.7 and §16.5
**Revisit when:** uploads pass the limit by more than the concurrent uploads explain, the read of the total shows in the upload time (it sums every attachment row not deleted, once before the blob write and once under the project's lock; about 100 ms at two million rows on PostgreSQL, measured in the review of the hub PR), or plans (§2.7) set storage per account
**See:** attachments.md#pending-uploads-are-capped-per-membership-and-humans-can-clear-them — 5080eb65-475b-487a-9854-80757124ccf0 — as of 2026-11-04

Besides the project's quota, the instance has a limit on the attachments of all
projects together, `max_attachment_storage` in the admin section Limits (§16.5).
It is counted as the project quota counts: pending uploads included, after
re-encoding, deleted ones freed. The default is `unlimited`. An upload over the
limit is `attachment_quota` with `scope: "instance"` and no numbers; the admin sees
the total as `attachment_storage_used`. The check runs under the project's lock
after the project's quota and the pending cap. Lowering the limit deletes nothing.

**Reason:** the per-project quota bounds one project, not the disk: with projects
uncapped per account (and accounts uncapped even once the project limit landed), the
total had no ceiling. The disk belongs to the operator, so the limit sits with the
instance, not the account. The total says how much the whole instance stores, which
is the operator's business, not a member's. Uploads already serialise per project;
one lock for the instance would make every upload anywhere wait for every other, for
a limit where passing it by the stored sizes of the other uploads in flight when the
last of them to be accepted was checked, at most one per project, does no harm.
Those can exceed the 10 MiB file cap, which applies before re-encoding: a 4.8 MiB
JPEG was measured at 13.9 MiB stored. `unlimited` as the default leaves a
self-hosted instance as it was; the hosted instance sets its own value in the admin
area.

**Rejected alternatives:**
- One instance-wide lock for an exact cap: serialises all uploads on the instance.
- Refusing with `used` and `quota`, as the project scope does: tells every member
  how much the instance holds.
- An environment variable alone, like `MAITY_ATTACHMENT_QUOTA`: the card asks for
  an admin setting, and the Limits section already has the source rules for both.
- A fixed default such as 50 GiB: offered to the maintainer as the alternative and
  not chosen; it would refuse uploads on self-hosted instances that never chose a
  limit.

## A project's attachment quota is an admin limit with the source rules of every limit, and the old variable is gone

**Id:** 24123f11-cf43-4cde-8a7f-bdd0b3b4cab3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-qa9r26kb2teq; the maintainer's note of 2026-11-05 on the card (every limit has both sources, the environment variable and the admin field) and his decisions through the lead on 2026-11-07: requests req-h185j92my7zq (default and range), req-a4j6x89a679z (names, "no legacy"), req-xhz9dwn5z1a8 (wording); `docs/api.md` §8.7 and §16.5
**Revisit when:** plans (§2.7) set storage per account or per plan, or a project's owner needs a quota of their own below the instance's value
**See:** attachments.md#the-instance-caps-all-attachments-together-checked-under-the-projects-lock-and-without-numbers-for-the-member — 67adfb38-efa6-4636-986c-33fad578a128 — as of 2026-11-07

The bytes one project may store are the limit `max_attachment_storage_per_project`
in the admin section Limits (§16.5), with the environment variable
`MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT` under the same source rules as every
other limit: a set variable wins and the field shows it read-only, else the
admin's value, else the default of 1 GiB. The range is 1 MiB to 1 PiB, or
`unlimited`. The refusal stays `attachment_quota` with `scope: "project"` and its
numbers, and lowering the value deletes nothing.

**Reason:** the operator sets every other limit in the admin area, and this one
was the only one that needed a restart and a deployment change. The name
follows `max_attachment_storage`, the instance's limit, so the two read as a
pair. The minimum of 1 MiB is the proposal the maintainer adopted, because a
smaller project quota refuses almost every upload.

**Rejected alternatives:**
- Keeping `MAITY_ATTACHMENT_QUOTA` as the environment variable, or as an alias
  or fallback of the new one: the maintainer chose no legacy while the product
  is in beta, so existing deployments switch to the new name or to the admin
  field.
- The environment variable alone, as before: every limit has both sources.

## While attachments are off, delete is refused too, and the upload keeps its own checks first

**Id:** de8f3512-27b5-4b88-8751-6d5dc24dbe9c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling of 2026-10-27 on the deviation the implementer raised in the attachment core pull request (#463), contract change #464 with its follow-up (`docs/api.md` §8.7 "Attachments off")
**Revisit when:** every deployment has an attachment volume, or the chart provisions one by default

That the hub starts without `MAITY_ATTACHMENT_DIR` is recorded in the
hub's entry (**See:** `hub/context/attachments.md`, e188f028-5494-4c51-8328-cf368d3c4e39).
At contract level two things follow from it: delete answers `409
attachments_not_configured` like every other attachment call, and the
order differs by call. List, metadata, content and delete answer it
before any check of the project or the attachment; the upload answers it after the size cap,
membership and `events:post`.

**Reason:** without a store the hub cannot remove the bytes a delete
promises to remove. The upload's order is the more natural one (a call
to a project you may not post to is refused as such first), and it
reveals nothing: a non-member gets the same `404` as for any project,
and a member learns nothing the project view does not already show.

**Rejected alternatives:**
- Answering the upload with `409` before its membership and
  `events:post` checks as well: would move a check in the hub for no
  gain in what the caller learns.
- Allowing delete while attachments are off, as metadata only: the
  bytes would stay on a volume the hub no longer knows, behind a delete
  that said they were gone.
