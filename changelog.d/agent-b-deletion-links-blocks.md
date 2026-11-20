### Fixed

- hub: an account deletion now also clears the person's links: `website` and `social` become
  empty and `links_visible` goes back to `private`. Before, a deleted account kept them.
- hub: a registration block that has run out is deleted, with its address, by the hourly
  registration pass. Before, every block stayed in the database for good, although no check
  reads a block past its date.
