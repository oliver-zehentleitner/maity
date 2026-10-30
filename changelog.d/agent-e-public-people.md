### Added

- hub: a person's public page (§16.9, step 3): `GET /{handle}` while `public_profile` is on, with the display name, the handle and the bio; `PATCH /me` sets `public_profile` and `public_bio` (plain text of at most 280 characters, `control_character` and `too_long`; an agent is `humans_only`), `GET /me` returns them; the page is taken off in the same transaction when the person turns it off, edits the bio, is suspended, hidden, deleted or lifted again (migration `0105`, tsk-xr6fqx8e0vw5).
