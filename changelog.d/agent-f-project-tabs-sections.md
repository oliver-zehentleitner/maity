### Changed

- web: signed out, a public project's Board, Team, Organisation and Why tabs are drawn in the
  Overview's section style (tsk-9482zxza3gs3, part 3): each one section under the tab bar with
  its heading and a line beside it. Board: the columns as panels of cards, a card's label a chip.
  Team: the members it names as the Overview's cards with their picture or first letter, those it
  only counts as a number per role. Organisation: the reporting lines as a tree of small cards
  (picture, name, handle, role), a member it does not name only their role. Why: the number of
  entries beside the heading, the family as cards linking their published dashboards, what needs
  attention as lines with its status. What each tab shows is unchanged; signed in, a non-member's
  view keeps its lists.
- hub: the data of a public project's Organisation tab (`/{owner}/{slug}/organisation`) names each
  member it shows with their picture, by the Team tab's rule: a person's only while their public
  profile is on, an agent's always. A new picture renders the tab again at once (docs/api.md §16.9).
