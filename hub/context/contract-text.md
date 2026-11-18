# Contract text

## A contract text read keeps the default branch's head for 30 s, per token, repository and branch

**Id:** 90903003-d5d0-4299-a2f5-e0e660a20436
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-ybc2ma72dzvq (reads stay cheap at scale), the lead's split of 2026-11-14 naming a 30 s head cache per repository and branch; docs/api.md §6.8
**Revisit when:** the contract routes resolve the head another way (a webhook that pushes it, the probe's observation), or several pods read so often that a shared cache would pay

`contract_text._head` keeps `Forge.branch` for `HEAD_AGE` (30 s), keyed by a digest of the reader's token, the repository and the branch, the newest 1024 kept per process (`bounded.put`). An answer of the forge is kept, a forge that did not answer is not. Within the 30 s a read whose text is kept too (`MAX_AGE`, 60 s, keyed by the commit) asks the forge nothing.

**Reason:** every call of the card's section and of the whole contract asked the forge for the branch first, so the forge reads grew with the viewers; with the head kept, a read the hub holds needs none. A new commit showing up to 30 s late is the price, below the text's own 60 s. Each pod keeps its own heads, which for 30 s is acceptable.

**Rejected alternatives:**
- A key of repository and branch alone: a reader whose token cannot see a repository would get its head from another reader's read and so reach the text kept for that commit, skipping the visibility check the forge read makes. The token's digest in the key keeps every answer one that its reader's own read made; an installation token minted anew each hour costs one read more.
- Keeping the head as long as the text (60 s): a new commit would show a minute late on the card.
- A shared cache in the database for several pods: a write per read for a 30 s answer.
- Checking the budget before a kept head: it would refuse a read that needs nothing from the forge.
