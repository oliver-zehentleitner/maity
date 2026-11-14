### Security

- hub: exchanging a join checks its creator again, as accepting an invitation
  checks its issuer: still an active member with `members:admin`, and an owner
  for trust `admin` or the role `proxy`; otherwise the join answers as an
  unknown one.
