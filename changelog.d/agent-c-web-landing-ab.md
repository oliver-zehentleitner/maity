### Added

- web: landing variants and campaigns (§16.7.2). The landing editor edits the main page or a variant at `/for/<slug>` (up to 5), previews and opens each one, and keeps a campaign list (code and label, up to 200) beside the privacy hint; both are part of the JSON import and export. Statistics gets the campaign table per day, page and campaign (views marked approximate) with the hub's CSV, and the registration page sends the link's `v` and `c` as `origin`.
