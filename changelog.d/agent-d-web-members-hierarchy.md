### Changed
- web: Members is one list in the project's hierarchy instead of a table
  of humans and one of agents: owners at the top, then admins, members
  and guests, each a level deeper (a level nobody holds is left out). The
  Organisation tree places a member without `reports_to` or area the same
  way, under the owners rather than beside them.
- web: smoke's check for labels that run inline reads layout rules in
  their context (a descendant selector needs its ancestor; rules inside
  `@media` and CSS comments do not count).
