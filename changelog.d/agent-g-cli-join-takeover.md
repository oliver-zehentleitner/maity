### Added

- `maity join` and `maity resume` print `Takes over from @<handle>; the hand-over is in <card | message #seq>` with the command that reads it, in the `Check in` block (or where it would stand), while the packet carries `membership.takes_over` (docs/api.md §5.2).

### Changed

- `maity join` always ends with the `pipx ensurepath` sentence for later shells (§3.2); when `maity` is not on `PATH` already, the line names the directory instead.
- Without a briefing, a join that names a takeover points at the hand-over above instead of the general hint.
