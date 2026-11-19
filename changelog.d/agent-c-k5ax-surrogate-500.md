### Fixed

- hub: a text with a lone surrogate (JSON's `\ud800` without its pair) is refused
  with 400 `invalid`, no longer a 500: a request's `action.body` (`lone_surrogate`), a
  project's `public_about`, an invitation's `note` and the landing and legal pages'
  texts (`control_character`), the sign-in and sign-up pages' `title`, `subline`,
  `point_N` and `note` (`invalid`), a language key of the landing, legal, sign-in and
  sign-up pages (`invalid`, under the parent's path), and an abuse report's `text`
  (`not_text`); a report's `target.id` or `target.project` holding one is `not_found`;
  and an error answer now shows a key holding a lone surrogate as its `\uXXXX` escape
  instead of failing. A card note's `body` was already refused with 400.
