### Security

- hub: a project's repository URL takes an owner and a name only of the
  letters, digits, `.`, `_` and `-` the contract allows (§6.1), never `.`
  or `..`, and not ending in `.git` or `.atom` after the clone suffix; a
  percent-encoded part, a query, a fragment or a second trailing slash is
  refused too, so the
  probe's API paths name the repository and nothing else; a URL stored
  before this check is checked again before the forge is asked, a REST
  path and a GraphQL read's variables alike, and an invalid one, or one
  short of two segments, asks nothing (tsk-qtr9myhtysbs).
- hub: a request to the forge's API ends 10 seconds after it starts (§11.1), from
  the connection attempts and the TLS handshake to the last byte of the answer
  (the name's resolution comes before and is not part of it), and a JSON answer past
  16 MiB is refused, for the probe's reads and the GitHub App's alike; a
  forge that trickles its headers or its answer no longer holds the read
  open (tsk-qtr9myhtysbs).
- cli: an error message shows a link's token as `<token>`: after `/join/`,
  `/j/`, `/r/`, `/i/`, `/invite/`, `/invitations/` and `/runners/pair/` in any case or
  %-encoding (decoded until it no longer changes), under `/mail/<page>/`, and a join host's link that is the
  token alone (also one with capitals), so a pasted error no longer carries a working link
  (tsk-qtr9myhtysbs).
