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

## A person's chat verdicts: every one they gave is exported, and they stay with a deleted account

**Id:** 79c2a1d3-ed63-4550-ade1-2c1e186399c9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §2.9 (the export holds "what is about the caller or written by them"; the deletion keeps the projects' record), §9.7; the review lead's ruling on #1818 that verdicts belong in the export with no exception in the contract

`chat_verdicts` in the export lists each `chat_verdict` event the person
wrote: as a member, and as an owner reading a group chat along from outside
the project (found through the projects their agents are in). Each item has
its chat, the message's seq, the value and the sentence. A redacted one is
exported as redacted. The message is named by its seq and never by its text,
which is another person's. The `chat_verdict` table, the current verdict, is
not read for it. On account deletion the verdicts stay in the project, as the
chat messages they answer do.

**Reason:** a verdict and its sentence are written by the person, so §2.9
puts them in the export. Every change is written by them, not only the
current one, and the events hold every change, while the table holds only
the latest. A verdict is part of a chat's record, like a reply, so the
deletion keeps it like the person's messages. Someone who wants a sentence
gone redacts it first, which also clears the stored sentence.
That verdicts go into the export is the review lead's ruling. Exporting the
history, and keeping verdicts on deletion, are inferred from §2.9 and not
stated anywhere.

**Rejected alternatives:**
- Leaving verdicts out of the export, since §2.9's list did not name them:
  rejected in review, because the list is the rule's instances and not its
  limit.
- Exporting only the current verdicts from the table: it leaves out the
  sentences of earlier changes, which the person also wrote.
- Deleting a deleted account's verdicts: a chat's history would then lose
  answers that its messages keep.
