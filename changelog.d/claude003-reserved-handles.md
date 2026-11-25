### Changed

- hub: a new person or organisation can no longer take a handle of three characters or fewer,
  nor one of about 200 words the hub keeps free for pages of its own (`about`, `blog`, `docs`,
  `pricing`, `support` and the others listed in docs/api.md §16.11), so `/<word>` stays free
  for the product. Registration, a rename, a new organisation and `maity-hub owner create`
  answer `reserved`. An agent's handle is no address and may still be short or such a word.
  Whoever already holds one keeps it, its page and its alias; `maity-hub migrate` and the
  hub's start name those holders and go on. `owner` and `owners` stay free, since
  `maity-hub quickstart` falls back to `owner` (tsk-3ykgt3t9jd57).
