### Fixed

- hub: `/explore` has the landing page's light/dark switch in its header, like a stored
  public page in its frame: it loads the landing page's script and is served under the
  stored framed pages' policy, which lets that script run.
