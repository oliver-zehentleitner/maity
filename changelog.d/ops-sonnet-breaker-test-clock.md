### Fixed

- ci: the two device-code breaker tests read a frozen monotonic clock. Sixty requests on a
  slow runner could outlast the 60 s wrong-code window, so the breaker never tripped and
  the test failed with `200 == 429`.
