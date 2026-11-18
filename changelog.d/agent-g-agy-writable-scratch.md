### Added

- cli: an antigravity placement gets a scratch, so an agy reviewer can write
  its `review_result` file and name it with
  `maity say --review-file "$MAITY_SCRATCH/review.json"`. Its sandbox makes the
  beside-clone `.scratch` read-only, so the scratch goes under the host's
  shared temporary directory instead, in a per-user parent owned only by the
  user the agents run as; the session reaches it as `MAITY_SCRATCH`, with
  `TMPDIR` inside it, and the file is read through the existing recorded-scratch
  path (`tsk-bbhcekjk2mgm`). An agy placement on an ssh host still gets none.
