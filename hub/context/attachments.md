# Attachments

## Without MAITY_ATTACHMENT_DIR the hub starts with attachments off and every attachment call answers `attachments_not_configured`

**Id:** e188f028-5494-4c51-8328-cf368d3c4e39
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling of 2026-10-27 on this change, and the contract change it led to (#464); `docs/api.md` §8.7 and §16 said before that the directory is required and the hub refuses to start without it
**Revisit when:** every deployment carries a volume for the directory, or an operator asks for a hub that refuses to start without it

`MAITY_ATTACHMENT_DIR` is validated when it is set (an absolute path to an
existing, writable directory, else the hub stops). When it is unset the hub
starts with attachments switched off: every attachment call, and a message
that names an attachment, answers `409 attachments_not_configured` with the
variable's name. `s3` stops the hub with a plain message: it is documented and
not built.

**Reason:** every deployment that exists today starts without the variable,
and a hub that stopped there would not come back on the next rollout until its
Helm values and compose file had gained a volume, for a feature nobody uses
yet.

**Rejected alternative:** the contract as first written, the directory
required and the hub refusing to start without it: it breaks every deployment
that has not yet added the volume.

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

## A message names its attachments in the transaction that writes it, and its payload always carries the list

**Id:** 627630f3-2e12-46bc-9831-55c6b75f865a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7: "the post and the binding are one transaction", the error values per id); the payload shape and the body rule are the implementer's reading
**Revisit when:** a message kind other than a project message or a chat can carry files, or the contract lets a message name an attachment of another member
**See:** attachments.md#the-blob-is-written-before-the-row-and-removed-when-the-row-never-commits-or-is-gone — 7dcd4850-9dc4-4b4a-9148-e156c8e11718 — as of 2026-10-27

`post_message` checks the named ids before it writes (no store, a closed
project, more than ten, each id: unknown or already attached; a repeated id
counts as already attached), puts `attachments` into the payload (metadata
only, in the order named, `[]` when there are none, so every message has the
key the contract describes), emits the event, and binds the rows to its
`seq` in the same transaction. A row that was taken or deleted between the
check and the bind refuses the whole post, so a message never names a file it
does not own. The body may be empty when attachments are named: the check is
a field validator that raises pydantic's own `string_too_short` otherwise, so
the answer for an empty message is the one it always was.

**Reason:** one transaction means a failed post leaves the uploads pending,
which the contract asks for, and a bound attachment always has its message.

**Rejected alternative:** relaxing the body's `min_length` and checking in
`post_message`: it changes the error an empty message has always had.

## Redacting a message tombstones its attachments in the redaction's transaction

**Id:** 588c979f-8c75-4ad4-ab2d-cd19a1921738
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7, Retention)
**Revisit when:** the sweep lands and can take over removing the bytes

`_tombstone` marks every attachment of the message deleted
(`deleted_reason` `redacted`, `deleted_by` the redactor) in the transaction that
replaces the payload, and the bytes are removed once it commits
(`events.on_commit`). No `attachment_deleted` is emitted: `event_redacted` covers
them. A redacted message has no readable attachments, so the metadata and the
content answer `not_found`, to its sender too. With the store switched off the
redaction still goes through and the rows are tombstoned; the bytes then wait
for the sweep, so a redaction never fails on `attachments_not_configured`.

**Reason:** the payload that named them is gone in the same step, so the rows
cannot outlive it readable.

## The project view's quota is filled where the caller is known

**Id:** 33db5e76-fc25-413e-9998-dd2a718ff346
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7, Quota: `attachments: {used, quota}` for callers with `project:admin`, else `null`)
**Revisit when:** project views are built with their reader known

`views.project_view` knows no caller, so it takes the pair as an argument and
the project routes compute it: the caller's membership in the project, then
`project:admin`, then the sum of the bytes of every attachment not deleted.
A list of projects does that per project.

**Rejected alternative:** a reader argument on `project_view` for every caller of it
(replays, the creation answer, events): a wide change for one field.

## The sweep keeps the database and the blob store equal, and does not trust a young blob

**Id:** 02fb33e3-0fc5-4140-8e33-016045fefdbb
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7: pending uploads expire after 24 hours, a blob without a row "is removed by the hub's sweep", a failed removal "is retried by the sweep", `hub/` documents the interval); the interval and the grace are the implementer's
**Revisit when:** a second replica runs (each would sweep), or the `s3` store is built
**See:** attachments.md#the-blob-is-written-before-the-row-and-removed-when-the-row-never-commits-or-is-gone — 7dcd4850-9dc4-4b4a-9148-e156c8e11718 — as of 2026-10-27

A worker thread, started when a store is configured, runs every five
minutes (`attachments.SWEEP_EVERY`). One pass deletes pending uploads older
than 24 hours with their bytes, removes the bytes of a tombstoned row that
are still there (a removal that failed after a commit), and removes a blob no
row names. That last rule only touches a blob older than ten minutes
(`BLOB_GRACE`): an upload writes the blob before its row is committed, so a
younger blob without a row may belong to a transaction still open. A removed
member's pending uploads are deleted as rows in the removal's transaction and
their bytes go by this last rule.

The sweep takes the project's lock for each expired candidate and deletes it with its
conditions repeated (still pending, not deleted, still past the cutoff), and removes the bytes
only of a row that this delete removed: a message that named the upload since the sweep
chose it has bound it, the delete finds nothing, and the file stays. A stray blob's row is
looked up again right before the removal. A message cannot name an upload past its 24
hours either (`unknown`), so the two cannot disagree about the same row.

**Reason:** the write order of the contract leaves exactly one kind of
leftover, a blob without a row, and every clean-up that cannot run in the
request (a crash, a failed delete, a removed member) ends up as that kind, so
one rule removes all of them.

**Rejected alternatives:**
- Removing a member's blobs in the removal itself: the removal has no store,
  and a failed delete there would have to fail the removal or be forgotten.
- No grace: the sweep could delete the bytes of an upload a moment before it
  commits.

## An owner outside the project reads a group chat's attachments through a stand-in row

**Id:** 0ac62e3d-4c33-4745-8b2f-48a45f1d397e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7: whoever can read a message reads its attachments, "an owner outside the project included")
**Revisit when:** the read rule takes a reader that is not a membership row

The one read rule (`events.readable_by`) takes a membership row, and an owner
outside the project has none. For attachments the reader gets a stand-in row
(no role, no agent) and two gates in front of it: the message must be a group
chat's, and the group chat's own `access` must call the owner an observer.
Without the gates the stand-in would reach any project message addressed to
`all`. Such an owner reads the attachment and its tombstone, and deleting is
`forbidden` with `reason: observer`.

**Rejected alternative:** a second copy of the read rule for outsiders: the two
would drift.

## Deleting a sent attachment follows who the message is for

**Id:** 77b7e1d8-ec10-40f1-9447-0764eef69b4f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7, Deleting one)
**Revisit when:** a chat kind other than direct and group exists

A sent attachment is readable as its message is. Its uploader may delete it;
no other agent may (`humans_only`); a human may delete it if they are the human
party of a direct chat, a participant now of a group chat (an observer or a
former participant: `not_a_participant`), or have `members:admin` for a project
message. The row becomes a tombstone, the bytes go after the commit, and
`attachment_deleted` goes to the message's audience (a group chat's current
participants), in the chat's own scope so no see-all role reaches it. It wakes
nobody. Deleting a deleted attachment answers with its tombstone.

**Reason:** the log is append-only, so the message keeps naming the file; the
tombstone is how readers learn it is gone.
