### Added

- hub: `GET /people/{handle}` (§6.27): a person or an organisation as the dashboard shows them to a
  signed-in human — `kind`, `handle`, `display_name`, `avatar_url` where §6.10 lets the caller read
  it, `page_served`, `public_bio` while the page is served (one's own always), `projects` with
  `shared` and `projects_total` (at most 100 listed), `website` and `social` where `links_visible`
  admits the caller (under a hold `everyone` counts as `colleagues`), and the organisation's
  `members` for its own members; one `not_found` for every case the caller may not see;
  `private, no-store`

### Fixed

- hub: an organisation's picture is readable by its members and the members of its projects
  (§6.10), and by nobody else; the image route answered `not_found` to all of them and served
  it to an instance admin
