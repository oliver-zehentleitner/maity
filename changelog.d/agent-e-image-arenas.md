### Fixed

- deploy: the hub image sets `MALLOC_ARENA_MAX=2`: the process drifts upward by a small amount with
  glibc's per-thread memory arenas (about 0.1 KiB a request) and stays flat with two; throughput and
  latency are unchanged. `hub/scripts/measure_arenas.py` measures it.
