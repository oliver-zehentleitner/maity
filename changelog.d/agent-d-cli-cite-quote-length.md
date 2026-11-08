### Changed

- cli: `maity say --type review_result` refuses the send, exit 1, when a cite's quote is longer
  than the hub takes (300 characters), naming the cite and the quote's length, also without a
  clone; before, the limit showed only in the hub's refusal.
