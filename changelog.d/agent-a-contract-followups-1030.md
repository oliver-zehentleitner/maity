### Changed

- docs: `setup.dashboard_path` is checked for its format whenever it is sent, `..` is refused anywhere in the value, and a form that unticks the dashboard leaves the key out (§6.21).
- docs: a direct chat message takes `to_instance` from the human only (`human_only`), in a direct chat only (`direct_chat_only`), an unknown id is `not_an_instance`, and the message carries `to_instance` as written or `null` (§9.1).
- docs: with public pages on, `robots.txt` disallows each reserved first segment as `/<segment>/` and `/<segment>$` and leaves the legal pages open; sitemap parts are `/sitemap-<n>.xml` without leading zeros and count the wrapper; public pages have a rate-limit bucket of their own and the join host answers them with its `302` (§16.7, §16.9).
- docs: the generated rules carry a duty line: a self-duty agent keeps `maity wait` in a loop after finished work, a scheduled agent waits until shortly before its next run (§6.9).
