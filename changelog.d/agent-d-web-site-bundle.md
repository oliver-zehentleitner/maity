### Added

- web: **Import or export everything** in the instance admin, at `/admin/site`: the landing page,
  the legal pages and registration as one `maity-site/1` file; an unknown key anywhere refuses
  the file, named by its path; a check lists each part as changes, the same, not in the file or
  refused, and one Save writes the changed parts in turn, asking for the second factor once and
  saying what is saved and what is not if a step fails; Export reads the settings again first;
  the template `web/tools/maity-site.json`, with placeholders in square brackets for the imprint,
  replaces `web/tools/landing-v3-complete.json`
