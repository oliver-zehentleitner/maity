### Fixed

- hub: an outbound answer whose stream ends before its declared `Content-Length` is
  refused (`unavailable`, or `timeout` past the deadline) instead of returned as if it
  were the whole body; under load the deadline watchdog closing the socket could end a
  read that way, so a forge image or probe answer could be stored cut short
