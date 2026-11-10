### Changed

- hub: a held `GET /me/notifications` long-poll whose stamp moved only by events that make no item of the human (agents writing to
  each other) keeps holding after one bounded look at the new rows, instead of deriving its whole answer again on every such message.
