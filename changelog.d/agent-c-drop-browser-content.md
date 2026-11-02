### Removed

- The setting `browser.content` and the `content` field of notification items (`docs/api.md` §18). The hub
  never filled the field, so the dashboard's "Text in the notification" switches did nothing. A `PATCH` that
  names it is now `invalid`. The mail's `content` switches stay.
