### Fixed

- hub: a text with a lone surrogate (JSON's `\ud800` without its pair) is refused
  with 400 `invalid`, no longer a 500: a request's `action.body` (`lone_surrogate`), a
  project's `public_about` and the landing and legal pages' texts (`control_character`),
  an invitation's `note` and the sign-in and sign-up pages' `note` (`invalid`), and an
  abuse report's `text` (`not_text`). A card note's `body` was already refused with 400.
