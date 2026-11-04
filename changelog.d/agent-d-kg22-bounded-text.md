### Changed

- The hub renders Markdown in time bounded by the text's length (docs/api.md §16.7): a link's
  target and title are at most 2048 characters each, stay on their line and hold no `[`; quotes
  nest at most 8 deep, as on the dashboard, and a ninth quote's lines are a paragraph in the
  eighth. Choosing a language from `Accept-Language` reads the parts wholly within its first
  1024 characters, at most 20, and a tag longer than 35 characters matches nothing.
