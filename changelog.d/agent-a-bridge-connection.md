### Changed

- docs/api.md §2.3 "The bridge": a bridge is a connection with a stated purpose instead of a role.
  Any agent keeps its own role and lends its hands through `POST …/members/{id}/bridges`
  `{bridge, purpose}` (several per agent, at most 5; `PATCH`/`DELETE …/bridges/{brg}`); across
  owners the bridge's owner answers a consent request carrying the purpose as the frame of the
  agreement. The member view and the resume packet carry `bridges` and `bridging_for`; acting with
  `Maity-For` is unchanged. The role `bridge` is removed.
