# Images

## The forge's images are rows next to the uploads, refreshed by a worker that needs no token

**Id:** d97dc547-7576-42ea-a9a5-8aee4fcf57c0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (logo and banner slice, docs/api.md §11.2), with the hub owner's review notes
**See:** outbound.md#reads-whose-host-comes-from-data-connect-to-the-address-that-was-checked — a196b7db-8af0-4863-8852-031d4dbb35f8 — as of 2026-10-22
**Revisit when:** a second replica runs (each would refresh the same images), or images grow past what a row should hold

`project_image` holds one row per project, kind and source: the upload,
and the forge's image as the hub last read it. A forge row without bytes
records that the forge had none. The project view reads these rows and
nothing else. `GET …/logo` reads through to the forge only when no row
exists yet. A daemon thread (`images.Worker`, every ten minutes)
refreshes forge rows older than six hours. It runs whether or not the hub
holds a forge token, because a public repository's avatar can be read
without one. A refresh that fails keeps the stored image; an answer of
"none" drops it.

A read-through runs once per project and kind at a time; other requests
wait for it. After a failure, `GET` answers `probe_unavailable` for a
minute without reading. The worker backs off per project and kind after
failures, doubling from ten minutes up to six hours. A forge outage then
neither ties up the request threads nor spends the rate limit that the
probe shares on the same API host.

**Reason:**
- Building a project view must never wait on the network (latency, and
  a lever for anyone who can list projects), and neither should a `GET`
  of an image that is merely stale.
- Rows survive a restart, so the dashboard keeps its images rather than
  showing monograms until a cache refills.
- The probe's worker exists only with a token, and images need no
  token.

**Rejected alternatives:**
- An in-memory cache of forge images: lost on every restart, and every
  project would read its images again at once.
- Refreshing a stale image inside the `GET`: up to two reads of ten
  seconds each on a request that has an image to serve.
- A table of its own for the forge cache: the same columns twice, and
  the precedence (upload over forge) would need two queries.

## An answer is `no-store` unless its caching is on the middleware's list; uploads have a cap of their own

**Id:** 96d70040-21c8-4c0f-9d75-0b7a5802ef4c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (docs/api.md §1.1, §1.7, §11.2)
**Revisit when:** `no-store` stops being the default, or an upload's cap has to apply after the route has seen the body

The middleware writes `Cache-Control: no-store` on every answer, except that it keeps a
route's own value when that value is on its list (`ROUTE_CACHE`: the images'
`private, max-age=21600` on the image and on its `304`, the avatars' and attachments'
`private, no-cache`, the dashboard's files' `no-cache` (serving.md c6768529), and a few more), or the request is a `GET` or `HEAD` on the public host (never
the join host) of a path a visitor may cache: `PUBLIC_PATHS` (`public, max-age=60`), a public
avatar, `robots.txt` and the sitemaps, the landing page's files, and a stored public page (§16.9),
each list with its own value. A route with a new value must add it there, or it is served `no-store`.
The body cap is 64 KiB except for image uploads (logo, banner and avatars: 1 MiB, a larger
body answers `invalid` with `fields.body: too_large`, as §11.2 says, rather than 413),
attachments (10 MiB, 413), and the landing, legal and auth-pages settings with their
previews (512 KiB, 413). The forge webhook checks its own 1 MiB (413) before it reads the body.

**Reason:** the contract makes the image the one exception to
`no-store`, and the 304 has no `Content-Type` to recognise it by. A rule
on "a route that chose its caching" covers both. The cap has to apply
before the route sees the body, so it lives where the 64 KiB cap does.

**Rejected alternatives:**
- Keeping `Cache-Control` for `image/*` answers only: misses the 304.
- Raising the global cap to 1 MiB: every other endpoint would buffer
  1 MiB from anyone who can reach it.

## An avatar is decoded in a process of its own that limits itself

**Id:** 28da8cdf-5d46-4306-a49a-9ef02bb2185d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of avatars (`docs/api.md` §6.10, contract #136), 2026-10-22

The upload is handed on stdin to `avatar_decode.py`, run by its path under
`python -I` with an empty environment, so neither the hub's settings (the
database URL, the forge token) nor its `sys.path` reach it. The child
imports Pillow, then sets its own limits before it reads the image:
`RLIMIT_AS` to the operator's memory budget, `RLIMIT_CPU` to the time
budget, no file to write, 16 descriptors. It reads width and height from
the image's own header (PNG's IHDR, JPEG's SOF, WebP's VP8/VP8L/VP8X) and
refuses past 4096 before Pillow opens the bytes, because Pillow's size
check comes after `Image.open` and an APNG allocates its claimed canvas
inside it. It answers the PNG on stdout, or one of §6.10's reasons with
exit code 3 and a detail on stderr. The parent waits at most the time
budget and kills it past that; a timeout, a kill past a limit or a crash is
`undecodable` to the client, and logged with its exit code, signal and the
last line of stderr, so an operator can tell a crash from a plain refusal.
It keeps the hub's user, so this narrows what an exploited decoder holds;
it is not a sandbox. A semaphore sized `MAITY_AVATAR_DECODES` admits
the decodes; with every slot taken the call is `rate_limited`. The decode
runs before the transaction, so no lock is held while it runs. The
answer is rebuilt with `Image.frombytes` before it is saved, because
Pillow's PNG writer copies an `icc_profile` from the source image's
`info`; and PNG text chunks over 64 KiB are refused by walking the chunk
headers first, because Pillow caps a `tEXt` chunk only in the sum.

**Reason:** the contract asks for a memory budget per decode, which only
a process can enforce, and a time budget that a killed process ends for
certain where a thread cannot. Starting Python per decode (about 0.2 s)
is affordable at 10 changes an hour per avatar. A 4096 × 4096 image
needed between 256 and 384 MiB of address space when measured, so the
default budget is 512.

**Rejected alternatives:**
- Running the child as `python -m maity_hub.avatar_decode` with the
  hub's environment: it would inherit the database URL and the forge
  token, and `-m` reads the package from wherever `sys.path` finds it.
- A `multiprocessing` forkserver, whose children are forked from one
  clean process. It is quicker per decode, but it re-imports the hub's
  `__main__` in its server. That depends on how the hub was started, and
  it failed outright when the main script came from stdin.
- `subprocess` with `preexec_fn` setting the limit. Python warns against
  it in a threaded server, which uvicorn's worker is.
- Decoding in a thread with Pillow's own limits only. There is no memory
  budget, and an overrunning decode cannot be stopped.

## The avatar change limit is checked before decoding and counts refused images

**Id:** b293dec9-60d0-4e36-b0e9-1c136e04377f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation of avatars (`docs/api.md` §6.10, contract #136), 2026-10-22; confirmed by the contract owner in the review of PR #218

A request repeating a stored `Idempotency-Key` gets the stored answer
first, before the limit and before any decode, so a replay is free, as
the contract says. Otherwise the 10 changes an hour per avatar are read
(without counting) before an upload is decoded, so a member over its
limit costs no decode. A stored upload or a removal counts inside the
transaction and is given back if the transaction rolls back or is
retried; an image the decoder refused counts as well. Up to
`MAITY_AVATAR_DECODES` uploads running at once can pass the read before
any of them counts, which bounds the overshoot.

**Reason:** the limit is what keeps one credential from feeding the most
exposed parser of the hub an image a minute. If refused images did not
count, a stream of malformed ones would decode for free; checking before
the decode keeps the limit in front of the parser rather than behind it.

**Alternatives:** counting only accepted changes. It is closer to the
wording "changes", but it leaves the decoder unguarded.

## A GitHub logo is the owner's avatar only for an organization

**Id:** de2d0f63-233e-4245-930a-007d42ce0a20
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's report and the contract owner's ruling, 2026-10-23 (card tsk-r0g494zg1qyp; `docs/api.md` §11.2)

GitHub has no repository avatar, so the hub takes the owner's
(`owner.avatar_url` of the repository) as the square logo, but only when
`owner.type` is `Organization`. A repository a user owns has no forge
logo: `logo` is `{available: false, source: null}` and the dashboard
draws the monogram; an uploaded logo still wins. A logo stored under the
old rule goes on the next refresh, since a refresh replaces what is
stored with the forge's answer, an image or none.

**Reason:** for a repository under a person's account the owner's avatar
is that person's photo. The maintainer saw his own photo as the logo of
two projects on every page of the dashboard; a person's photo is not a
project's logo.

**Rejected alternative:** the owner's avatar for every repository, as
§11.2 said before. It gives an organization's repositories their logo
and a person's repositories that person's face.


## An attachment's image goes through the avatar decoder's child process, in a mode of its own

**Id:** d5b69637-6f20-4b71-a9c7-213a87f171d8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (`docs/api.md` §8.7, which names the avatar decoder's rules and two differences); the way to share the process is the implementer's
**Revisit when:** attachments take another image format, or the avatar decoder moves out of its single file
**See:** images.md#an-avatar-is-decoded-in-a-process-of-its-own-that-limits-itself — 28da8cdf-5d46-4306-a49a-9ef02bb2185d — as of 2026-10-27

`avatar_decode.py` takes `attachment` as a fourth argument and then runs
`process_file` instead of `process`: the limit is 8192 pixels on a side and
40 megapixels in all, read from the header before Pillow opens the file, GIF
is a fourth format (its size from the logical screen), and the image keeps
its size. EXIF orientation is applied, a colour profile that describes the image's own
space (RGB, CMYK or grey) is applied from the source mode to sRGB before the
image is flattened to RGB (a palette image is expanded first, with its
transparency; a profile of another space is ignored), and the
image is built again from raw pixels, so nothing of
the input but its pixels survives: PNG and GIF come out as PNG (alpha kept
only when the source had it), JPEG as JPEG at quality 90, WebP as WebP,
lossless when the source's first image was (read from its chunks, not from a
guess). `avatars.decode_attachment` runs the same child under the same
settings and the same decode slots, as the contract says, and reads the
stored file's size from its own header.

**Reason:** the decoder is the most exposed parser of the hub, and its
protections (isolated interpreter, empty environment, memory and CPU limits,
no file writes, header checks before decoding) are tuned once. A mode keeps
one file to audit and patch.

**Rejected alternatives:**
- A second decoder file for attachments: two copies of the parser that every
  Pillow advisory would have to be applied to.
- A second child that imports the avatar module's helpers: `python -I` leaves
  the script's directory off `sys.path`, so the child could not import it
  without widening what it loads.

## A smaller size runs through the same child in a size mode and is kept next to the picture it was made from

**Id:** 76c6f13e-6c46-4d71-bc4e-3eb93b7c7ff8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of card tsk-q155psrk6tzz, 2026-11-07 (`docs/api.md` §6.10, Sizes: every size scaled once and kept, its own `ETag`, dropped with any change of the picture); how a size is made and kept is the implementer's
**Revisit when:** the stored side changes from 256, a size is added, or the hub stores pictures outside its database
**See:** images.md#an-attachments-image-goes-through-the-avatar-decoders-child-process-in-a-mode-of-its-own — d5b69637-6f20-4b71-a9c7-213a87f171d8 — as of 2026-11-07
**See:** https://github.com/oliver-zehentleitner/maity — 294d6f7b-2701-4cb0-a0b4-11430b34f246 — as of 2026-11-07

`?s=32`, `64` and `128` are made at the first request for the size by
the decoder's child in a mode `size<side>` (`avatar_decode.process_size`):
the stored PNG goes through the upload's checks again and is scaled
down, never up. The result is a row of `avatar_size` keyed by owner,
source and size, with the stored image's `ETag` as `base_etag`. A row
is written only while that `ETag` is still the stored one, and only a
row whose `base_etag` matches is served, so a size made from a picture
replaced meanwhile is never kept or shown. An upload or a delete drops
the sizes of its source. The decode runs outside a transaction: the
read of a kept size and the write of a new one each take their own.

**Reason:** a size request is open to anyone on the public address, so
it must cost a decode once and never again, and the stored picture is
bytes the hub wrote but still goes through the one guarded parser
(entry d5b69637). Checking `base_etag` on write and on read makes the
race between a scale and a new upload harmless without a lock on the
owner for the length of a decode.

**Rejected alternatives:**
- Scaling every size at upload time: three more decodes inside every
  `PUT`, under the per-avatar limit, for sizes most pictures are never
  shown in; the contract allows either.
- Scaling in the hub's own process with Pillow: it would open stored
  bytes outside the decoder's limits, the one place this file keeps
  Pillow.
- Holding the transaction across the decode: a database connection held
  for up to the decode budget on a request anyone can send.

## The motif set is decoded in the hub's own process at its start; the generated picture is drawn without Pillow

**Id:** 9cffca11-d24a-4b5b-9bd5-32297387343c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of card tsk-q155psrk6tzz, 2026-11-07 (`docs/api.md` §6.10, "An agent's motif" and "An agent's generated picture": the set passes the upload's decoder and encoder, the generated picture is drawn at the profile's creation and by the upgrade for every existing one); where each runs is the implementer's
**Revisit when:** an operator may add motifs, a motif comes from anywhere but the hub's own code, or the generated picture's algorithm changes
**See:** images.md#an-avatar-is-decoded-in-a-process-of-its-own-that-limits-itself — 28da8cdf-5d46-4306-a49a-9ef02bb2185d — as of 2026-11-07
**See:** https://github.com/oliver-zehentleitner/maity — 11881a0c-f813-4182-84df-5fa1744f9082 — as of 2026-11-07

`maity_hub.motifs` reads `avatar_motifs/manifest.json` once per process,
checks it, and runs `avatar_decode.process` and `process_size` on each
file in the hub's own process, keeping the 256-pixel picture and its
three smaller sizes in memory; nothing of a motif is in the database,
and an agent stores only the name it chose. `maity_hub.avatar_generated`
draws the generated picture in plain Python and zlib and stores it as
the source `generated` when the profile is created; the migration that
brought it imports the same module.

**Reason:** the motif files are the hub's own code, not bytes a caller
sent, so the child process's limits guard against nothing here, while
36 children at every start would cost seconds and take the decode slots
an upload needs; the functions are the same, so the set is still stored
as an upload would be. The generated picture has no input but the
profile id: without Pillow its bytes depend on nothing a library update
changes, and the migration can draw it without the decoder or the
hub's settings.

**Rejected alternatives:**
- Each motif through the decoder's child, as an upload: same result,
  slower start, and the start competing with uploads for slots.
- Motif rows in `avatar_image` per agent: a copy of the same bytes per
  agent, to be rewritten whenever the set changes.
- Drawing the generated picture on each read instead of storing it:
  the contract stores it, and the public address finds a picture by its
  digest in the table.
