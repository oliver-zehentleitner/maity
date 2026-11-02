### Added

- cli: `maity say --type review_result` reads each cite at the review's `head` in the local clone
  and refuses the send, naming the cite, when a quote is not on its line or not in the file;
  without a clone or the commit it sends and says the cites were not checked.
