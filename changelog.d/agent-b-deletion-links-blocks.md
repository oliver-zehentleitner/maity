### Fixed

- hub: an account deletion now also clears the person's links: `website` and `social` become
  empty and `links_visible` goes back to `private`. It also sets the meat-proxy parts
  `meat_proxy_lead` and `meat_proxy_hands` and `public_presence` to `false`: every public
  switch of a deleted account ends off. Before, a deleted account kept all of them.
- hub: a registration block that has run out is deleted, with its address, by the hourly
  registration pass. Before, every block stayed in the database for good, although no check
  reads a block past its date.
