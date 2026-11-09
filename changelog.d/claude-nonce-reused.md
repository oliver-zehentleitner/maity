### Fixed

- cli: a `GET` the hub answers with `nonce_reused` is signed again with a new nonce and sent
  once more, within what is left of its timeout, so `maity wait` no longer ends when a proxy
  delivered its long-poll twice (for instance during a hub restart). Writes are never sent
  again on `nonce_reused`. The deploy README notes how a proxy can cause it.
