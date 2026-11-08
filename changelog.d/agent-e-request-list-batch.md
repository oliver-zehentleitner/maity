### Changed

- hub: a page of requests (`GET …/requests`, `GET /requests`, the resume packet) builds its
  views in one batch, so it costs a fixed number of statements instead of about six per
  request: 24 instead of 1,219 for a page of 200 on a local fixture. A single read of a
  request goes through the same batch.
