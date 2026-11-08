### Fixed

- web: a second-factor answer that arrives after its question was cancelled
  no longer closes the next question in the same place (`js/step-up.js`).
- web: without a session, a public page whose read fails other than with
  404 (a 503, a dropped connection) keeps the sign-in instead of "not found".
- web: the fixture's member role change checks a role beyond the member
  rule before an unknown one, in the hub's order.
- web: `tools/vendor_ktw.py` has a hard deadline for a run's network time:
  each fetch runs in a worker thread and is refused once the run's 120 s
  are spent, whatever it is doing then (the DNS lookup, connect, TLS,
  headers, redirects, chunk framing or the body); each socket wait inside
  it is capped at 15 s; a network failure ends in one `refused:` line
  instead of a traceback.

### Changed

- web: smoke pins a `/site/chrome` answer that arrives after the frame was
  left, the frame left once a session read succeeds, every line separator of
  the contract view, the mention line following a counts read, and a
  consent case with data the hub produces; `/site/chrome` joins the shape
  requests; a comment in `tools/check.py` on the unchecked Chinese address
  is corrected (tsk-gsk31zvpfv02, batch 1).
