### Removed

- hub: the boolean `keep_the_why` alias of `memory.provider`: `POST` and `PATCH
  /projects` no longer take it (an unknown field, `invalid`), and project views and
  the resume packet's `project` no longer carry it; `conflicts_with_memory` is gone
  (§6.1, §6.21, §8.2)
