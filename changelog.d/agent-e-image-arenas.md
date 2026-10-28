### Fixed

- deploy: the hub image sets `MALLOC_ARENA_MAX=2`; under a mixed load the process grew by about 1 KiB
  a request through fragmented per-thread memory arenas, and stays flat with two.
