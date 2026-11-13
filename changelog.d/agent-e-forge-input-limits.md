### Security

- hub: a project's repository URL takes an owner and a name only of the
  letters, digits, `.`, `_` and `-` the contract allows (§6.1), never `.`
  or `..`, and not ending in `.git` or `.atom` after the clone suffix; a
  percent-encoded part, a query or a fragment is refused too, so the
  probe's API paths name the repository and nothing else
  (tsk-qtr9myhtysbs).
- hub: an answer from the forge's API is read for at most 30 seconds in
  all and refused past 16 MiB, for the probe's reads and the GitHub App's
  alike; a forge that trickles its answer no longer holds the read open
  (tsk-qtr9myhtysbs).
- cli: an error message shows the token of a `/join/`, `/r/` or `/i/` link
  as `<token>`, so a pasted error no longer carries a working link
  (tsk-qtr9myhtysbs).
