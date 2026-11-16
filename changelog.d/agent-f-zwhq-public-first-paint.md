### Fixed

- web, hub: a public page no longer shows its older plain layout for a moment before the page
  in its frame. Signed out, the hub's own copy of the page stays invisible until the dashboard
  has drawn it, and shows after 3 seconds where no script does; search engines read it as
  before.
