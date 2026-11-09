### Fixed

- hub: a request filed while its member's role changes to `expert` is refused with `403`
  (`details.scope: requests:ask`) instead of stored: `POST …/requests` checks the scope again
  on the membership read under the project lock, as a claim does.
