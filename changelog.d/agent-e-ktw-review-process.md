### Changed

- context: `context/process.md` records the review rules of 2026-11-03 as entries of their own: all three reviewer vendors (Antigravity, Grok, ChatGPT) approve the exact head, superseding one Grok and one Antigravity (297a0ea7); the review lead's team hands out every review; and an absent reviewer vendor gets no substitute from another vendor. The handback rule for a returning reviewer (8ba32bfa) is superseded: the maintainer accepted the lead's recommendation.
- context: the Keep the Why team rule in `context/process.md` (e534e9f3) stays beside the hub's required why on code reports, by the maintainer's decision. The hub accepts a why as a reference, of which it checks only the shape, or as `none` with a stated reason; the review checks that the entry exists and the linter is clean, or that the reason holds.
- docs: the README and maity.dev say that every pull request needs three approvals from reviewers of three vendors, no longer two.
