### Fixed

- hub: removing a card link follows the contract's access rule: the holding
  instance, the link's adder or the card's creator with the right to write
  cards, or `tasks:admin`; a link removed already answers the same way, and
  only to a caller whose card history shows the removal.
