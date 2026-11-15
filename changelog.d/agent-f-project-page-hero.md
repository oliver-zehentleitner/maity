### Changed

- web: signed out, a public project's page has the approved mockup's top (tsk-9482zxza3gs3, part 1):
  a dark hero with the crumb `owner / slug`, the project's tile (its first letter in the accent
  colour), the title and a state chip; on the Overview the about text, "Try it — create your
  account" (to where the header's call to action leads, only where it has one), a GitHub or
  Repository button and the project's links as one row of short words, and "Right now" with who
  is online. Under it a band of figures (members, cards done, reviews given, pull requests
  merged, handovers; a figure that is 0 or empty is left out), then the views Overview, Board,
  Team, Organisation and Why as a bar across the page. On a phone the hero stacks, the figures
  stand three in a row and the bar scrolls sideways. The rules are `web/css/public-sections.css`,
  one set for the signed-out project, person and agent pages, on only in the landing's frame.
  Signed in, a non-member's view is unchanged.
