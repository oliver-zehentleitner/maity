### Security

- cli: no credential from a remote's URL reaches the output or the hub any more. `maity report`
  on a branch whose upstream is a URL with an embedded token (`https://x-access-token:…@…`)
  printed that URL in its refusal and sent it as `upstream`; git's and gh's error lines, the
  runner's `workspace claim` and an unreachable hub URL are cleaned the same way.
