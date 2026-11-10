### Fixed

- hub: two first changes of the notification settings of one person at the same moment no longer
  answer 500 for the later one; it finds the row the first made and goes on.
- hub: a refused `email.kinds` setting is named by its kind (`email.kinds.<kind>`), so the
  dashboard can point at the switch that is wrong; a stored `browser.content` of another kind than
  `chat` and `mention` is no longer read.
