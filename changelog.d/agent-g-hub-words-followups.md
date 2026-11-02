### Changed

- hub: the words of a mail or a link page are matched to a language as on the public pages,
  so `zh-CN` reads `zh-Hans`, and the registration page asks for its own section's words.
- `make -C web release-check` also fails on hub words that lack a key or follow an older English
  text (`hub/words-meta/`).
