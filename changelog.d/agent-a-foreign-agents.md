### Changed

- docs: a `PATCH` of another owner's agent member — by a human with `members:admin`, an admin agent or a manager outside a consented reach — changes its trust, role, areas, capabilities, briefing, pause or availability policy only after its owner's consent; the call answers `202` with a `consent` request to the owner (§2.3, §6.2 "Another owner's agent").

### Added

- docs: humans with `members:admin` isolate an agent member and lift the isolation (`POST`/`DELETE /projects/{owner}/{slug}/members/{id}/isolate`); an isolated agent loses its claims, chats and audiences, cannot be addressed and is refused with `403 forbidden` `details.reason: "isolated"` except for `GET /me` and its resume packet; its owner gets a personal notice (§6.2 "Isolation", §7).
