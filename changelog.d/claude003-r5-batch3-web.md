### Changed

- web: internal clean-up with no change in behaviour (audit round 5, batch 3): one
  attribute comparison in `js/dom.js` for `sameTree` and `keepImages`, `getAttributeNames`
  and `replaceChildren` called directly, an element told by its `nodeType`; the board asks
  `M.isMenuId` (js/menu.js) for a menu's made-up id instead of repeating its format; the
  runner part of the join form takes "a member bringing their own agent" as the form does.
