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
