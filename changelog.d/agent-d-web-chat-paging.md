### Changed

- web: a chat opens on its newest 50 messages, read in two requests whatever its length, instead
  of reading its whole history; older pages come on scroll-up or with **Show earlier messages**,
  the reader's place kept, and a long tail is let go at the newest. Measured on a chat of 2000
  messages: 2 requests and 50 messages drawn, where it was 10 and 2000. Reading a group chat along
  from outside re-reads the newest page every 30 seconds, no longer the whole history
- web: **Message the project** starts in the Chat tab (and the Messages view), no longer in the
  inbox
