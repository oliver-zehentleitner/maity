### Security

- hub: a `review_result` adds the sender's or the author's `reports_to` only when that boss's
  owner and the owner of the agent it leads both resolve and are the same; an owner that cannot
  be resolved leaves the boss out, as docs/api.md §8.4 now says (tsk-9sjg106s9wdc).
