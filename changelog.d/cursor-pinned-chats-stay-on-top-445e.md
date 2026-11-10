### Changed

- docs: the conversation lists (§9.3) keep every pinned chat above every unpinned one:
  pinned with unread messages, then quietly pinned, then unpinned with unread messages,
  then the rest, each band in its activity order. The cursor follows that order. A new
  message a human participant has not read stays visible through that conversation's
  unread count and the header's chat badge. An observer's unread is null and adds
  nothing to the badge.
