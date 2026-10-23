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

## Responses choose their own caching only for images; uploads have a cap of their own

**Id:** 96d70040-21c8-4c0f-9d75-0b7a5802ef4c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (docs/api.md §1.1, §1.7, §11.2)
**Revisit when:** another route needs to be cached by the browser, or another upload is added

The middleware writes `Cache-Control: no-store` on every answer unless
the route set a `Cache-Control` itself. Only the image routes do, with
`private, max-age=21600` on the image and on its `304`. The body cap is
64 KiB everywhere except `PUT /projects/{slug}/logo` and `…/banner`, which
take 1 MiB and answer a larger body with `invalid` and
`fields.body: too_large`, as §11.2 says, rather than 413.

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

