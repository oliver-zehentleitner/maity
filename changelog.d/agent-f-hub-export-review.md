### Fixed

- hub: `GET /me/export` carries the `review` of a review result a person wrote (docs/api.md §8.4, §2.9: the messages they wrote), `null` for every other type; before, the export left out the subject, head, verdict and cites.
