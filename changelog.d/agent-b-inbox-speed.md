### Fixed

- hub: `GET …/requests` and `GET /requests` build full views only for the page they
  answer, not for every filtered request, so a listing costs its page however many
  requests (history included) a human has
- hub: `GET /me/notifications` reads the personal requests behind its inbox items and
  their askers' names together, not three queries per item
