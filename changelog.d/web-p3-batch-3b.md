### Changed

- web tools: `make check`'s French address check also finds the informal possessives `ton` and `ta`, but only right before a word the French catalog itself writes after `votre` and never after an article, whatever whitespace stands between, so `ton` as "tone" stays clean (tsk-tsb8528rank1).
- web tools: the smoke DOM shim moves a removed field's caret to its end, a stress condition of the shim rather than a browser's behaviour, so the card panel's caret restore is guarded in smoke too; smoke also pins the product line's `translate="no"` marks (tsk-tsb8528rank1).
- web e2e: the handle hints are measured with the owner renamed to 31 characters for the step and restored whatever fails in it, the global Chats list's heading and lead control are pinned at 390 and 360 px, and a mention of the owner (by the alias the handle step leaves, since `@owner` is a group word) brings the unread mention line and the filtered notifications page under axe (tsk-tsb8528rank1).
