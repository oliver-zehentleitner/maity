### Changed

- Hub: a bridge's `Maity-For` is not taken on the project's memory routes or on the connection routes; without the header the bridge calls them as itself (docs/api.md §2.3).
- Hub: a connection's `purpose` is one plain line (`details.fields.purpose: "plain_line"`), quoted in the consent request as the asker wrote it.
- Hub: at the last `go` across owners, the hub checks again that an asker whose own action stood for the project's consent still holds `members:admin` (`details.fields.asker: "members_admin"`).
- Hub: a change of `policy.outside_roles` ends the connections across owners the limits would now refuse, as a role change does.
- Hub: a write through a connection that ended meanwhile is refused (`not_your_bridge`).
