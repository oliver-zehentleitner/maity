### Changed

- web, hub: signed out, a public project page and a card's page show at once in their final design.
  There is no empty moment while the dashboard reads the page, because the hub's copy is already
  in the dashboard's design and stylesheets, and the dashboard draws the same page over it. Each
  stylesheet is loaded once. A person's and an agent's page keep the short wait until they move
  to the same design.
