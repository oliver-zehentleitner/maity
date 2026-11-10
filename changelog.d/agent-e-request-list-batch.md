### Changed

- hub: a page of requests (`GET …/requests`, `GET /requests`, the resume packet) builds its
  views in one batch, so it costs a fixed number of statements instead of about six per
  request: 24 instead of 1,219 for a page of 200 on a local fixture. A placement's request
  is the exception: its placement summary is still read per request. A single read of a
  request goes through the same batch.
