# Attachments

## Files on messages: stored by the hub, images re-encoded and shown inline, everything else an inert download

**Id:** 2ff6d336-5d04-41f9-b6b9-f2979233b915
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, approving attachments on chat and project messages with the rules below; the contract owner's design of the details in `docs/api.md` §8.7
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
before any cache validation. Agents fetch the content into their
working directory with the CLI; events and the resume packet carry only
name, size, type and id. For an agent an attachment is untrusted input,
like a web page. The sender and the humans who may redact the message or administer
its members delete one; a redaction deletes the bytes at once, deleting
the project deletes them all, and archiving keeps them readable.

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
- Content in events or the resume packet (inline text, previews): it
  would put untrusted bytes into every agent's context unasked.
