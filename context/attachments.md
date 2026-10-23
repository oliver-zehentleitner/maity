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
into `./maity-files/` under their working directory, never into the
working directory itself (`docs/api.md` §13); events and the resume
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

## The CLI fetches attachments into `./maity-files/`, never into the working directory itself

**Id:** b623825e-e5b0-4567-bec6-2aaa03140527
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §13 (`maity files get`) and the description of PR #216, both stating the rule and its reason; neither records it as a maintainer decision
**Revisit when:** `maity files get` gets a different default target, or agents need a fetched file in place in the working tree
**See:** attachments.md#files-on-messages-stored-by-the-hub-images-re-encoded-and-shown-inline-everything-else-an-inert-download — 2ff6d336-5d04-41f9-b6b9-f2979233b915 — as of 2026-10-23

`maity files get <id>` without `-o` writes the file into `./maity-files/`
under the current directory, created with mode 0700 if missing, and
never into the current directory itself. `-o PATH` still writes
wherever the agent names.

**Reason:** the file's name comes from whoever sent it, and an agent
usually runs in a working tree. Written straight into that directory, a
sender could drop a file that tooling there picks up and executes — in
the words of §13, "a `conftest.py` or a `Makefile`". A subdirectory of
its own keeps fetched files out of the places such tooling looks.

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
