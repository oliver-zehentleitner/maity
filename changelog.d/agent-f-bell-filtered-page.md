### Changed

- docs/api.md §18.2: a `GET /me/notifications` page filtered by `kind` or `project` (the link to a
  project's mentions beside its tabs) reads only the sources that can give an item of them. Before,
  it read every other source to the end of the 30-day window and dropped what it read, so such a page
  could take about a minute on a busy account. The answer is the same.
