### Changed

- cli: internal clean-up with the same output: the resume's unread chats and
  cross-project chats are listed by one loop, the "an int that is not a bool"
  checks in the resume text go through `_count` and `_is_seq`, and the review
  text check builds its path pattern once. Only a negative number from the hub
  reads differently: another instance's claims count is left out, a ticker
  count reads 0, and a hand-over message number names no message.
