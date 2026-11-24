### Changed

- hub: a request refused because it holds a string in the credential format no longer reads
  the database when that string names an id the hub never makes; the refusal is the same. A
  real credential in it is still revoked, also among many such strings.
