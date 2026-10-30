### Added

- Dashboard, chat with an agent: **Send to** beside the heading, where the agent has more than one
  live instance: the whole team by default (its wake rule), or one instance, sent as `to_instance`
  (§9.1); kept per chat in the tab, and a message sent to one instance says "to <handle>#<id>". The
  fixture hub takes `to_instance` as §9.1 says and returns it on the message.
