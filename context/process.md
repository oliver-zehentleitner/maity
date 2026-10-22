# Process

How Maity itself is built: the rules its own agents and maintainer work
by, where they differ from what the product prescribes.

## Pull requests get an independent first review on a different vendor's model; the coordinator decides, disagreements go to the maintainer

**Id:** 0b12c29d-1539-4737-9bc3-e5e5815238ec
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's card, 2026-10-22
**Revisit when:** the first-pass reviewer and the coordinator disagree often enough that the maintainer becomes the bottleneck, or the review cost becomes binding again
**See:** incidents.md#multi-agent-review-runs-exhausted-the-maintainers-monthly-budget — 1a5e729f-816a-4682-ab8c-a2029aa1ea0a — as of 2026-10-22

A reviewer running on ChatGPT does the first pass on a pull request,
independently of the agents that wrote it. The coordinator (the admin
agent) decides on the findings. Where the two disagree, the question goes
to the maintainer with both positions written out, and the maintainer
decides.

**Reason:** not recorded. The inferred part: a reviewer on another
vendor's model does not share the blind spots of the agents that wrote
the code, and a disagreement put to the maintainer with both positions
lets the maintainer decide without redoing the review.

**Alternatives:** unknown. The process it follows on is the one in the
incident above — one reviewer per pull request on the same model, plus a
targeted re-check by the coordinator; whether that was replaced or
extended is not recorded.

