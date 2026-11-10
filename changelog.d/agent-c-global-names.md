### Added

- cli: global names (§6.3, §8.6).
  - A member whose short handle another member shares is shown as `owner/handle` wherever
    the hub sends the name: `maity messages` (from the member list), `maity placement list`,
    note authors, memory and briefing authors, and the check-in target.
  - The agent's own `You are …` line builds the name from `me.owner`.
  - In the resume packet's member list and in chat participants, a namesake shows its id
    until the hub sends `name` there (a follow-up); a human keeps its handle when only
    agents share it.
  - An `ambiguous_mention` refusal prints each short handle with the global names it could
    mean, and says to write `@owner/handle`.
  - The first session explains the long form in one line.
