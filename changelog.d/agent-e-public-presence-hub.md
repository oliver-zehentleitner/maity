### Added

- hub: `public_presence` on `PATCH /me` and `GET /me` (default `true`, migration `20261102120000_public_presence`). While it is `false`, a project page's Online counts the person and leaves the name out of the page and `online.named`; switching it off renders the person's project pages at once, also under `interval`. Their agents are named as before (§16.9, tsk-my5gvj4warte).
