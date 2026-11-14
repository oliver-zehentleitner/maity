### Security

- hub: the credential filter (§2.2) finds a credential whatever character stands right
  before it, and also reads a JSON body as the strings (keys and values) it decodes to, so
  a JSON escape such as `\n` or `m` hides none, nor does an encoding the JSON parser
  also reads (a UTF-8 byte order mark, UTF-16, UTF-32). Such a body is refused with
  `credential_in_payload`, and a real credential in it is revoked.
- cli: the check before sending refuses the same cases: the pattern has no boundary in
  front, and a JSON body's decoded strings are checked as well, in any encoding the hub
  reads as JSON.
