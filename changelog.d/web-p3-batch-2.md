### Fixed

- web: `tools/vendor_ktw.py` ends a body cut short (`IncompleteRead`) or a
  body that is not JSON in one `refused:` line instead of a traceback.
- web: the person hint under the organisation invite is a whole sentence,
  and the note editor's hint says what the edited note shows (who and when,
  the reason only when one was given).

### Changed

- web: `web/README.md` describes the frame of the sign-in and registration
  pages, the `/site/chrome` fixture, the unread-mention line beside a
  project's tabs, the address filter on All notifications, and the stub for
  a boss of someone else's; Keep the Why records the fixed-word handle
  hints, the seq's `#` drawn by the stylesheet and three parts of the
  frame's design; `docs/api.md` §16.7 says the frame read keeps the last
  `?lang=` a page saw across its routes (tsk-gsk31zvpfv02, batch 2).
