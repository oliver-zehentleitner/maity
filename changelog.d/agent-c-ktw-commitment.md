### Added

- cli: the Keep the Why commitment (§6.23, §13).
  - `maity ack keep-the-why` confirms for this instance (`POST /me/keep-the-why/ack`). A
    project that does not require it is said as such, with exit 0.
  - `maity report --why <path>#<id>` and `--no-why <reason>` send `why`, checked locally
    as the hub checks it.
  - Where the last resume said the commitment is required, a code report with neither is
    refused locally, naming the two flags.
  - `maity resume` shows a `Keep the Why` block after `Check in`: the confirmation, or
    the request to confirm with its deadline.
