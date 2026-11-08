### Changed

- Hub: the dashboard's files under `/assets/` (`css/`, `js/`, `brand/`, `vendor/`) are answered
  `Cache-Control: no-cache` with a strong `ETag` of the file's content instead of `no-store`, the
  gzip form with an ETag of its own; a reload gets `304` without a body for every unchanged file,
  and a deploy still reaches the browser at once.
