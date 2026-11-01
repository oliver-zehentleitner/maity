### Fixed

- hub: a proxy answers a request only by recording its owner's answer: `on_behalf_of` names a member with trust `owner`, without it the answer is `forbidden` (`proxy_relays_only`), and from anyone else it is `invalid` (§2.3, §7). A proxy's call held by an owner who leaves goes back to the owner, not to the admins.
