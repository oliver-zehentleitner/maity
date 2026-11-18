### Changed

- hub: a person's public page takes its links from `person_links.public`, the
  anonymous reader's case of `person_links.admitted`, instead of testing
  `links_visible == "everyone"` itself; what the page and the visitors' route
  show is unchanged.
