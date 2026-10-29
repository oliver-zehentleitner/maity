### Changed

- web: the inbox is the requests alone: the block of unread activity under them (Request updates,
  Conversations, Mentions, Account) is gone; its history is the Show filter, the activity is on
  the bell, the Chat button and `/notifications` (tsk-430dnt8s25a8).
- web: `/notifications` shows an unread item in bold with a dot, as the bell does, and offers
  **Mark all read**.

### Fixed

- web: a project's inbox lists the open personal requests about that project too, so it shows what
  its tab counts; before, the tab could say 5 while the list said "No open requests".
