### Changed

- web: one organigram for Team and Agents. Both Organisation tabs draw the
  same row for a member from one renderer in `js/org.js`: each instance is
  `#abcd` after its status dot in the presence's colour, the lead ringed, a
  link to its sessions whose name says the address and the state. Team feeds
  in every member (Tree and Paths stay); Agents feeds in you and your own
  agents, with a stub for a boss of someone else's.

### Removed

- web: `drawFleet`, `fleetDots`, their `fleet-*` styles and the catalog key
  `org.fleet.dot`, replaced by the shared row.
