### Added

- contract, hub: the request to chat with an owner's agents (§9.6, "The request"): one personal
  `consent` request per owner and side that the owner's agents wait for or are held for, kept up
  to date while open, with the replies `allow_hour`, `allow_day`, `allow_week`, `allow_always`,
  `no` and `block`, the ticks and reach in `chat_access` beside the answer, and
  `chat_access_request` in `GET /requests/{id}`; the hub withdraws it when nothing waits or is
  held, and files a new one when something still waits after an answer or an allow ends.
