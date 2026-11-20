### Security

- runner: under a placement, `maity runner loop` and `maity runner logcap` take only a file the
  runner wrote in its own directory; a spec or log path inside a placed clone, a placement
  scratch or a temporary directory is refused (security round 5, S201/S202).
