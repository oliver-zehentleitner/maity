### Security

- hub: a project's repository URL takes an owner and a name only of the
  letters, digits, `.`, `_` and `-` the contract allows (§6.1), never `.`
  or `..`, and not ending in `.git` or `.atom` after the clone suffix; a
  percent-encoded part, a query, a fragment or a second trailing slash is
  refused too, so the
  probe's API paths name the repository and nothing else
  (tsk-qtr9myhtysbs).
- hub: a request to the forge's API ends 10 seconds after it starts (§11.1), from
  the connection to the last byte of the answer, and a JSON answer past
  16 MiB is refused, for the probe's reads and the GitHub App's alike; a
  forge that trickles its headers or its answer no longer holds the read
  open (tsk-qtr9myhtysbs).
- cli: an error message shows a link's token as `<token>`: after `/join/`,
  `/j/`, `/r/`, `/i/`, `/invite/` and `/runners/pair/` in any case or
  %-encoding, under `/mail/<page>/`, and a join host's link that is the
  token alone, so a pasted error no longer carries a working link
  (tsk-qtr9myhtysbs).
