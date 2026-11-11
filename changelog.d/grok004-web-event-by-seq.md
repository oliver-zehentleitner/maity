### Added

- web: `seq 68216` and `seq-68216` in messages, notes, cards and requests
  link to the event's page `/<owner>/<slug>/events/<seq>` (docs/api.md
  §8.9), by shape alone and only in a text of a project; `#…` stays a pull
  request or issue number, and a code span of one seq form alone links as
  code. The page reads `GET …/events/{seq}` and opens the event where it
  lives: its chat (direct or group), else the card or request it is about,
  else Messages for a message whose type says it is a project message,
  scrolled to and marked, a chat or Messages reading at most ten older
  pages for it. An event with no such place, such as a removed message
  whose tombstone has no type and no conversation for the reader, is shown
  on the page, and an answer that arrives after the reader left the page
  moves nothing.
  A hidden event and a missing one both show "not visible"
  (tsk-6g2h8dag2fkg).
