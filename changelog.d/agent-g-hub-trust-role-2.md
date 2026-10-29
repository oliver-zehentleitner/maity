### Changed

- hub: only a caller with trust `owner` grants trust `owner` or `admin` or the role
  `proxy`, and lowers or removes an owner, on `PATCH` and `DELETE …/members/{id}` too
  (`owner_only`, §2.3 "The owner's rights").
- hub: trust `guest` reads, posts notes on cards and chats in its conversations, with
  attachments; it claims, asks, answers and posts nothing else, writes no memory and,
  as a human, creates no group chat. A guest is never a target: `assigned_to`,
  `assign`, area routing, `policy.contract_arbiter`, a card's `contract.arbiter`,
  `settings.onboarding.check_in_with`, `reports_to` and a request's `to` refuse it with
  `details.fields.<field>: "guest"` (§2.3 "Guest").
