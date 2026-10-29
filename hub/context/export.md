# The account export

Why `GET /me/export` (`docs/api.md` §2.9, `maity_hub/export.py`) is built
the way it is.

## A created card shows the text as its creator wrote it

**Id:** 679e3238-26d0-47a2-979d-1e4807ba67b3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §2.9 ("what is about the caller or written by them, and nothing that is only another person's"); implementation of the export

`cards_created` takes the title and body from the card's `created` history
entry (§6.15), redacted when that entry is redacted, and the card's current
title only as the title of the thing, while the caller may read the project.

**Rejected alternative:** the card's current `title` and `body`. Rejected
because another member may have edited them since, and their text would then
leave the hub in the creator's export as if it were the creator's.

**Consequence:** a card made before the history existed has no `created`
entry; its `as_created` is `null` rather than a guess.
