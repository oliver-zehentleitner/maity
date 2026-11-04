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
variable's name. The `s3` store, opt-in, needs no directory (replicas.md
a70d7269).

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
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7 fixes "the blob first, the metadata after"; the way to undo it is the implementer's); the coordinator's ruling of 2026-11-03 for the `s3` store: the blob outside the project's lock, an orphan after a failed transaction left to the sweep; the reviews of #1281 on 2026-11-03 (the clocks the sweep compares, a write whose answer is lost, a COMMIT whose answer is lost, a COMMIT still running when the client gave up); the 15-minute limit on a request's time is the SigV4 rule of AWS S3 and MinIO; the S3 service this project runs on refused a request signed 20 minutes off with `RequestTimeTooSkewed` and answered the same read with the right time (a read-only check, 2026-11-03)
**Revisit when:** the time from the start of an upload's write to its commit can come near `UPLOAD_FRESH`, a store answers without a `Date` header and does not refuse requests with a skewed clock, or the contract changes the write order
**See:** replicas.md#attachments-move-to-s3-compatible-object-storage — a70d7269-a0a9-45aa-94c5-54715f112c10 — as of 2026-11-03

The upload checks the project's quota and the membership's pending bounds in a
short read without the lock, so that a refusal costs no write, and then writes
the bytes before the transaction that inserts the row begins, outside the
project's lock: one `PutObject` for `s3`, a file of its own moved into place for
`local` (`os.replace`, after an `fsync`), so a reader never sees half a blob and
no row names a missing one. The transaction then takes the lock and checks the
quota, the right to post and the project's state again, and inserts the row only
while less than `UPLOAD_FRESH` (5 minutes) has passed since the write began, on a
clock that keeps counting while the host is suspended; past it the upload is
refused with `503 upload_expired`, a code of its own: the database was reached, so
`database_unavailable` would name the wrong cause. The sweep measures a blob's age
on one clock. For `local` that is the hub's wall clock (the file's mtime against
`time.time()`), while the upload's bound runs on boot time, so a jump of the wall clock
acts like a skew of that size; for `s3` both times come from the store, the `Date`
header of its HEAD answer against the object's LastModified, so the hub's clock may
be off by any amount. A `Date` without a zone (asctime, `-0000`) is read as UTC, as
HTTP dates are. A negative age is logged. Only an answer without a
`Date` falls back to the hub's clock. For that case, a store that checks request
signatures refuses a request whose time is more than 15 minutes (`CLOCK_SKEW`) off
its own. `BLOB_GRACE` (30 minutes) is larger than both together: a blob the sweep
sees older than the grace can no longer get its row. From the write on, even a write that failed, the rate stays charged
whatever follows: a write whose answer was lost may still have stored the bytes, so
refusals and failures cannot buy writes past the rate. When it
does not commit (a refusal, a failure, or a concurrent call with the same
idempotency key that won), the route removes the blob afterwards, outside the
lock, but only once a fresh read finds no row with the upload's id: an error
does not prove the row is absent, a COMMIT whose answer was lost, or a retry
refused after an attempt that did commit, leaves a row that names the blob.
The read takes the project's lock first: the upload's transaction holds it
until the server has ended that transaction, also when the client already
gave up on the answer, so a COMMIT still running on the server is waited for
instead of missed. When the row is there the blob stays; when the read fails,
the blob stays for the sweep. When the removal fails, or the process dies before it, the blob is
one without a row, which the sweep removes after `BLOB_GRACE`. Deleting a
pending upload removes the row in the transaction and the blob after the
commit (`events.on_commit`, new for this), where a failure is logged and left to
the sweep. A crash between the write and the commit leaves a blob without a
row, which only the sweep (a later part) can find.

**Reason:** the order the contract fixes keeps the worse failure, a row
without bytes, out of reach of a crash or a failed write; the leftover blob is
the harmless one. Until 2026-11-03 the route removed the blob on every error
after the write, so a lost COMMIT answer could still leave a row without bytes;
the read before the removal closes that.

**Rejected alternatives:**
- The row first, then the blob: a crash leaves a row that serves nothing.
- Removing the blob inside the transaction: a rollback would then lose bytes
  a row still names.
- Removing the blob on every error after the write, as until 2026-11-03: an
  error from the commit does not say whether the row was written, and a
  removal on a guess can leave a row without bytes, the failure the order is
  there to avoid. Keeping the blob on every error instead would leave each
  refusal's blob to the sweep for `BLOB_GRACE`, though the fresh read can
  tell it apart.
- The fresh read without the project's lock, as in the first version of the
  fix: on PostgreSQL a read can come before a COMMIT the server is still
  running becomes visible (a review reproduced it with a deferred trigger),
  and the removal then takes the bytes of the row that commits after it.
- Writing the blob inside the transaction, under the project's lock, as until
  2026-11-03: for `s3` a network call of up to three times 60 seconds while the
  lock and a database connection are held, the kind of wait that ends in a
  statement timeout for every other writer of the project. For `local` it made
  no difference, and one order for both stores keeps one rule for the sweep.
- Removing the blob in `on_rollback`: the idempotent run may retry the
  transaction, and a retry after the removal would insert a row whose bytes are
  gone.
- A reservation the sweep honours (a row written before the write, or a
  tombstone set under the lock and the store asked after): a durable bound, but
  one more transaction and write per upload and per stray, and a table to keep
  in step with the store; the freshness bound needs neither. It rests on the
  stores' own limit on clock skew instead, which holds for the stores the hub
  supports (`local` has one clock).
- The hub's clock against the object's LastModified: the first version under
  `s3`. It is right only while the two clocks agree, which the hub cannot see.
- Timing the bound from the end of the write: a write that returns late (a slow
  answer, a suspended process) could find its blob already counted as a stray.
- Giving the rate back on every refusal, as before the write moved: a refusal
  found under the lock comes after the write, and a caller could buy writes
  past the rate with uploads that are refused each time.

## A pending upload is its uploader's alone, and the rate counts 64 KiB units

**Id:** d079ff73-8c38-435c-9881-522363f62400
**Type:** decision
**Status:** needs-review
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
**Status:** needs-review
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
**Status:** needs-review
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7: pending uploads expire after 24 hours, a blob without a row "is removed by the hub's sweep", a failed removal "is retried by the sweep", `hub/` documents the interval); the interval and the grace are the implementer's
**Revisit when:** a second replica runs (each would sweep), or the `s3` store is built
**See:** attachments.md#the-blob-is-written-before-the-row-and-removed-when-the-row-never-commits-or-is-gone — 7dcd4850-9dc4-4b4a-9148-e156c8e11718 — as of 2026-10-27

A worker thread, started when a store is configured, runs every five
minutes (`attachments.SWEEP_EVERY`). One pass deletes pending uploads older
than 24 hours with their bytes, removes the bytes of a tombstoned row that
are still there (a removal that failed after a commit), and removes a blob no
row names. That last rule only touches a blob older than 30 minutes
(`BLOB_GRACE`): an upload writes the blob before its row is committed, so a
younger blob without a row may belong to a transaction still open. A removed
member's pending uploads are deleted as rows in the removal's transaction and
their bytes go by this last rule.

The sweep takes the project's lock for each expired candidate and deletes it with its
conditions repeated (still pending, not deleted, still past the cutoff), and removes the bytes
only of a row that this delete removed: a message that named the upload since the sweep
chose it has bound it, the delete finds nothing, and the file stays. A stray blob is asked for
its age outside every transaction; only the look at its row is under the project's lock, the
lock under which an upload inserts its row; the removal follows after the lock is released.
Neither store call waits under the lock, since for `s3` both are network calls. That is safe
because an upload inserts its row only while its write is younger than `UPLOAD_FRESH`: a blob
older than `BLOB_GRACE` before the look, with no row at the look, can no longer get one. The
bound is not a reservation the database holds: it rests on the store's write time and the
hub's clock agreeing to within a few minutes (half the grace, less the write's own duration). A message cannot name an upload past its 24
hours either (`unknown`), so the two cannot disagree about the same row.
A folder no project row has is left alone, named once per process in the log, and checked
before its keys are read: the look at a blob's row needs that project's lock, which no row
can give, and before, the pass stopped there and never reached the blobs after it. Checking
the folder first also skips one the hub cannot read (`lost+found` on an ext4 volume, owned
by root), whose listing failed the pass under `local`, and costs one query a pass instead of
a lookup and a lock for each of its blobs.

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

## A download past one mebibyte streams and holds its last piece back until the digest matches

**Id:** 81f57cb5-f48a-43c7-9729-1d4e4de696b7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-11-03 (`docs/api.md` §8.7: bytes that do not match their digest are never served; the build plan for the `s3` store: downloads stream, checked while they stream); the threshold is the implementer's
**Revisit when:** a client is found that keeps a body shorter than its `Content-Length`, or attachments grow past what the threshold was chosen for
**See:** replicas.md#attachments-move-to-s3-compatible-object-storage — a70d7269-a0a9-45aa-94c5-54715f112c10 — as of 2026-11-03

`GET …/content` first compares the stored size with the row's and answers
`500 internal` when they differ. Up to 1 MiB (`routes/attachments.WHOLE`) the
bytes are then read whole and their SHA-256 checked before the answer starts,
so a mismatch is still a plain `500`. Past it they stream with the row's
`Content-Length`, hashed as they pass, and the last piece is held back until
the digest is known: when it does not match, the answer ends short of its
length and the hub logs it, so no client takes the bytes for the attachment.
Its status line is still `200`: a client that ignores a body shorter than its
`Content-Length` would keep a partial file. Uploads are not streamed: the body
is read whole within the upload limit, as before, and written in one piece.

**Reason:** the contract forbids serving bytes that do not match their
digest, and a whole file in memory per download does not hold for large files
or many downloads at once. The status line is gone by the time the last byte
is read, so a short body is the one way left to refuse; a small file, the
common case, keeps the plain `500`.

**Rejected alternatives:**
- **Reading every file whole, as before:** a 100 MiB download costs 100 MiB of
  the pod's memory for as long as it takes.
- **Streaming without the check, or checking only after the last byte went
  out:** the client would hold bytes the hub never vouched for.

## A plain-HTTP S3 endpoint needs its own switch and a host that stays inside the cluster

**Id:** 63204998-0aa3-48eb-bfc6-071612309cb4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16 (`MAITY_ATTACHMENT_S3_ENDPOINT`: plain HTTP only to a loopback or cluster-internal host, only with `MAITY_ATTACHMENT_S3_ALLOW_HTTP=1`), which leaves "cluster-internal" undefined; `config.cluster_internal`, implementation session 2026-11-03
**Revisit when:** a deployment's object store sits on a private address outside these ranges, or the contract defines the term itself

A host counts as cluster-internal when it is a loopback address, an address in
10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10 or fc00::/7,
`localhost`, a name of one label (a service in the same namespace, a compose
service), or a name ending in `.svc`, `.svc.cluster.local` or `.cluster.local`.
Any other name, which resolves through public DNS, needs `https`.

**Reason:** the credentials and the attachments travel in every request, so
plain HTTP is only for the MinIO in the same cluster or on the same machine,
which often has no certificate; the switch makes even that a choice the
operator wrote down.

**Rejected alternative:**
- **Python's `is_private`, as first written:** it also counts the
  documentation ranges (203.0.113.0/24 and others) as private.

## An upload's caller is checked from its headers before its body is read

**Id:** ea27e3d7-14b1-40ab-8158-b86ab575583e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the plan for card tsk-eejgfehwg4k0, approved by the team lead on 2026-11-04; `docs/api.md` §8.7 and §2; implementation session, 2026-11-04
**Revisit when:** another call takes a body larger than the 64 KiB cap without a pre-check, the signed scheme gains a part that covers no body, or uploads are streamed to the store instead of read whole

The middleware reads a body whole before any route runs, because the
credential filter of §2.2 scans it. For `POST …/attachments`, whose body may be
10 MiB, it first runs `caller.precheck`: the checks of `authenticate` that need
no body, in the same order and with the same refusals. That is a credential or
a session cookie at all; for a bearer credential the transport, the credential
and its secret; for a session cookie the transport, `Sec-Fetch-Site` and a live
session; for a signed call the headers' shape, the time window and that the
credential exists. A call that fails one gets that refusal and its body is
never read. A call that passes is authenticated in full by its route as
before, so a revoked credential, a signature that does not verify and every
later check keep their order and their answers; the pre-check renews nothing
and spends no nonce. When the database cannot answer the pre-check, the call
goes on and fails at its route as any call does.

**Reason:** the hub reads up to 10 MiB only for a caller who can authenticate,
and the refusal is the one the full check would give, so no client sees a new
answer.

**Rejected alternatives:**
- **A body cap at the ingress alone:** the hub's own cap for this call is
  10 MiB, so an ingress cap above it changes nothing for this call and one
  below it breaks uploads the contract allows.
- **Writing the body to disk while it is read:** it moves the bytes from memory
  to disk but still reads them for every caller, and it is more code than this
  change needs.
- **A limit on concurrent connections in the server (`limit_concurrency`):** it
  refuses every call above the limit, the events long-poll (§5) included, which
  every agent holds open, and the right number depends on the instance's size.
