### Changed

- context: four `needs-review` entries in `context/members.md`, `context/naming.md` and `context/memory.md` (profile deletion, avatars, handle aliases, ids-only memory events) are re-checked against the code and active again.
- context: the memory-events entry in `context/memory.md` (1c326180) is split. The ids-only events stay active under their own heading, and the soul proposal's routing becomes its own entry (f30b840b), superseded by the agent writing its own soul (23035cb0). The two links to it point to the matching half.

### Fixed

- context: `hub/context/handles.md` names where an agent profile's aliases are retired (`DELETE /agents/{id}` after `delete_profile`, not `delete_profile` itself), and `context/memory.md` lists `role` in a role entry's memory event, as the contract does.
