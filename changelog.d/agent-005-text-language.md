### Changed

- hub: the language of the hub's own texts for a human is read by
  `maity_hub/text_language.py` instead of `notifications/preferences.py`.
  The modules that write mails and pages in a human's language no longer
  import the notification settings for it, and the bell drops a
  function-local import. The language chosen is unchanged.
