### Changed

- `maity resume`: in the compact text another member's `member_updated` still counts as addressed to you when it changes `reports_to`, `owner_id` or `availability_policy`.
- `maity say --type review_result`: in a shallow clone, a cite without a line that isn't in the file is sent with a note instead of refused, as the history can't show its removal.

### Fixed

- `maity claim`: a card held by a sibling with no recorded instance no longer names only your own member id as the holder.
