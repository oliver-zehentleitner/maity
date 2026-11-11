### Changed

- hub: both conversation lists (§9.3) keep every pinned chat above every unpinned one:
  pinned with unread messages, then quietly pinned, then unpinned with unread messages,
  then the rest, each band in its activity order. The cursor follows that order; one from
  the earlier band order is refused. An observer's null unread counts as none.
