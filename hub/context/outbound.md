# Outbound reads

## Reads whose host comes from data connect to the address that was checked

**Id:** a196b7db-8af0-4863-8852-031d4dbb35f8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (logo and banner slice, docs/api.md §11.1)
**Revisit when:** the hub reads from a host the operator configures on a private network (a self-hosted forge), or a second HTTP client library enters the hub

`maity_hub.outbound.read` is the one way the hub reads from a host that
comes from data: a forge's image host today, the Keep the Why export's
host next. It resolves the host once, refuses the read when any resolved
address is not globally routable, and opens the TCP connection to the
address it checked, with TLS verified against the host name (SNI).
Redirects stay on the same host and reuse that address. The probe's reads
to the fixed forge API host stay on `forge._opener`, which satisfies the
rule as it is (§11.1).

**Reason:** checking the name and then letting `urllib` resolve it again
leaves a window in which the name can point at a private address (DNS
rebinding), which is exactly what the address rule exists to stop.
`http.client` with a socket the hub opened itself closes that window
without a new dependency. The ten seconds are a total deadline: a timer
closes the socket when they are up, because a per-`recv` timeout lets a
server that drips its headers one byte at a time hold the read open for
far longer. Python's `ipaddress.is_global` alone is not
the test: it counts multicast and the NAT64 prefix as global, so
`routable()` unwraps IPv4-mapped, 6to4, Teredo and NAT64 addresses and
refuses multicast explicitly.

**Rejected alternatives:**
- `urllib` with a check of `getaddrinfo` beforehand: resolves twice.
- Moving the probe onto the new helper: its host is fixed by the
  operator, its tests and rate-limit handling are tied to `urllib`, and
  §11.1 says it already complies. Its owner preferred to leave it.
- A real TLS server in the tests: it needs a certificate generated per
  run. The connection is a module-level seam (`outbound.connector`) that
  the tests replace with a fake socket, and `conftest.py` makes both seams
  refuse by default, so no test reaches the network.
