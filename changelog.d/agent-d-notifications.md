### Added

- web: notifications, stage 1 (docs/api.md §18): the switcher's pills count open requests plus
  unread chats and mentions, the inbox and chat tabs their own, and the tab title starts with the
  total; a **bell** lists the latest items, each linking to where it happened, with **Mark all read**;
  a sign-in or address alert is never marked read by opening it or by Mark all read
- web: browser notifications, opt-in on the account (`#/account/notifications`): the browser is
  asked only when they are turned on, per kind, a chat's or mention's text only where allowed,
  never for one's own actions, shown once across tabs
