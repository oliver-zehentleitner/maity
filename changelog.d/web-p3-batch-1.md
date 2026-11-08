### Fixed

- web: a second-factor answer that arrives after its question was cancelled
  no longer closes the next question in the same place (`js/step-up.js`).
- web: without a session, a public page whose read fails other than with
  404 (a 503, a dropped connection) keeps the sign-in instead of "not found".
- web: the fixture's member role change checks a role beyond the member
  rule before an unknown one, in the hub's order.
- web: `tools/vendor_ktw.py` bounds a run's network time (one deadline in
  all, a cap per attempt) and ends a network failure in one `refused:` line
  instead of a traceback.

### Changed

- web: smoke pins a `/site/chrome` answer that arrives after the frame was
  left, the frame left once a session read succeeds, every line separator of
  the contract view, the mention line following a counts read, and a
  consent case with data the hub produces; `/site/chrome` joins the shape
  requests; a comment in `tools/check.py` on the unchecked Chinese address
  is corrected (tsk-gsk31zvpfv02, batch 1).
