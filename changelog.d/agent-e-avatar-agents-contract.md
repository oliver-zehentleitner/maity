### Changed

- contract: an agent always has a picture (§6.10). Its upload comes first, then a
  motif from the set the hub ships (`avatar_motif`, set by the agent or its
  owner; `GET /avatars/motifs` lists the set), then a generated picture the hub
  draws from the profile id with the dashboard's algorithm and stores. An
  agent's `avatar_url` is never `null`, and its public page always shows a
  picture. Humans are unchanged. The hub implementation follows separately.
