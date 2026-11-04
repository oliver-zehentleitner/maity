### Changed

- context: four `needs-review` entries in `context/members.md`, `context/naming.md` and `context/memory.md` (profile deletion, avatars, handle aliases, ids-only memory events) are re-checked against the code and active again.

### Fixed

- context: `hub/context/handles.md` names where an agent profile's aliases are retired (`DELETE /agents/{id}` after `delete_profile`, not `delete_profile` itself), and `context/memory.md` lists `role` in a role entry's memory event, as the contract does.
