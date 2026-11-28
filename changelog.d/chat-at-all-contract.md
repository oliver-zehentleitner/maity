### Added

- docs: contract for `@all` in group chats (docs/api.md §8.6, §9.2, not built yet). In a
  group chat `@all` mentions every current participant other than the writer once, humans
  and agents, and is shown highlighted as a mention; it counts toward none of the 10 members
  a text may name. It spends one ping per participant it reaches from the writer's 30 per
  10 minutes, the write checked whole (`rate_limited`, nothing stored, when it does not fit).
  An agent waiting under §9.6 gets nothing. Each occurrence is stored as a `mentions` entry
  with `group: "all"` and no member, and every member entry gains `group: null`. In direct
  chats, project messages, cards, notes, reports, requests, jour fixe threads and
  cross-project group chats `@all` stays text; `@here` and `@everyone` stay text everywhere
  (tsk-n0x226d34y7f).
