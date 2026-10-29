### Removed

- web: the fixture hub's boolean `keep_the_why` alias of `memory.provider`, as the hub's: `POST` and
  `PATCH /projects` refuse it (`extra_forbidden`), the project view and the fixtures no longer carry
  it, and the machine form no longer names it.
