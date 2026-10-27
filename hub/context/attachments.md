# Attachments

## Without MAITY_ATTACHMENT_DIR the hub starts and uploads answer `attachments_not_configured`

**Id:** e188f028-5494-4c51-8328-cf368d3c4e39
**Type:** decision
**Status:** open
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7, §16); the contract says the directory is required and that the hub refuses to start without it
**Revisit when:** the deployment values carry a volume and the variable for it, or the contract owner rules on the deviation

The contract makes `MAITY_ATTACHMENT_DIR` required for the default `local` store
and has the hub refuse to start without it. Every deployment that exists
today, and every test, starts without the variable. A hub that stops there
would not come back on the next rollout until the Helm values and the
compose file gained a volume. So the setting is validated when it is set
(absolute, an existing directory, writable, else the hub stops), and when it
is unset the hub starts and every attachment call answers `409
attachments_not_configured` with the variable's name. `s3` stops the hub with a
plain message: it is documented and not built.

**Open:** which of the two the contract owner wants once a volume is
deployed: enforce the contract (required at start), or keep the hub usable
without attachments.

**Rejected alternative:** enforcing the contract now: it breaks every deployment
that has not added the volume, for a feature that is not yet used.

## The blob is written before the row, and removed when the row never commits or is gone

**Id:** 7dcd4850-9dc4-4b4a-9148-e156c8e11718
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7 fixes "the blob first, the metadata after"; the way to undo it is the implementer's)
**Revisit when:** the sweep (removing blobs without a row) lands, or an `s3` store is built

The upload writes the bytes to a file of its own and moves it into place
(`os.replace`, after an `fsync`), inside the transaction that inserts the row, so
a reader never sees half a blob and no row names a missing one. If the
transaction does not commit, `events.on_rollback` removes the blob. Deleting a
pending upload removes the row in the transaction and the blob after the
commit (`events.on_commit`, new for this), where a failure is logged and left to
the sweep. A crash between the write and the commit leaves a blob without a
row, which only the sweep (a later part) can find.

**Reason:** the order the contract fixes keeps the worse failure, a row
without bytes, impossible; the leftover blob is the harmless one.

**Rejected alternatives:**
- The row first, then the blob: a crash leaves a row that serves nothing.
- Removing the blob inside the transaction: a rollback would then lose bytes
  a row still names.

## A pending upload is its uploader's alone, and the rate counts 64 KiB units

**Id:** d079ff73-8c38-435c-9881-522363f62400
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7: the read rule, "30 uploads and 100 MiB per membership in 10 minutes", a replay counts against nothing)
**Revisit when:** a message can name attachments (the read rule then follows the message), or the limiter can count bytes directly

Until a message names it, an attachment is read, listed in full and deleted
by its uploader only; a human with `members:admin` lists and deletes every
member's pending uploads but sees a size, an uploader and two times, never a
name or type (the contract's reason: a name is content). Another member gets
`not_found`, an agent of the admin role `forbidden` with `humans_only`. The
limiter counts events, so the 100 MiB per 10 minutes is counted in units of
64 KiB (1600 of them) and an upload takes at least one: thirty tiny uploads
cost thirty units. A refused or failed upload gives its count back, and a
replay is answered before anything is counted.

**Reason:** the one rule of the contract, "readable as its message is",
gives a pending upload no audience but its uploader.

**Rejected alternative:** a second limiter with a byte-exact window: new code
for a cap whose exact edge nobody relies on.
