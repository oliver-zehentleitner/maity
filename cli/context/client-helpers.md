# One helper for what `cli.py` repeated

## The paging loop, the `more:` line, the linked pull requests, JSON input and project paths each have one helper

**Id:** 9dd8c66a-b225-4198-be62-b552a293914d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-sgaz43qazfzx (the lead's order); the clean-up audit, card tsk-hgnbapyw7hnh, area 13
**Revisit when:** `cli.py` is split into modules (the structure card), or the hub's paging contract changes

`cli.py` had the same few lines in several places. Each is now one function: `_all_pages` (fetch
every page of a list, used by the conversations, memory, takeover, card, note and jour fixe
reads), `_printable_cursor` and `_more_line` (the next cursor and the `more:` line of
`messages` and `ticker`), `_linked_prs` (the pull requests a card links, for the probe, the
belongs-to-the-card guess and the mismatch refusal), `_json_file` (JSON from a file or stdin,
for statements, answers and `--review-file`), `Session.path_in` (a project path from the full
name a resume packet gives), `_round_path` (every jour fixe rounds path) and `_members` (also for
the handle map). `hub.USER_AGENT` and `MESSAGE_TYPES` were aliases of `CLIENT` and `SAY_TYPES`
with one meaning each, and are gone.

**Reason:** a fix to one copy (a cursor that comes back, a link whose forge URL names no pull
request) had to be made in every copy, and the copies had begun to differ in small ways: the
page query put `limit` first in one place and last in another, and one of the three JSON
readers named the parse error with its position and the others did not. The change also makes
the coming split of `cli.py` smaller, which is why it lands before it.

**Rejected alternatives:**
- Leaving the copies until the split: each module would carry its own copy, and the split would
  have to be reviewed for behaviour changes at the same time as for moves.
- One `_all_pages` that takes the whole query with its own `limit`: the three callers that set a
  page size would each still spell the `("limit", …)` pair and its position.

**Known differences from the old code:** the page query now always puts `limit` after the
caller's own parameters (its position never mattered to the hub); a JSON file that is not JSON
says so with the parser's full message in all three readers, and a file for `jourfixe answer`
that is not a JSON object says "the body is one JSON object" before the keys are checked;
a card whose pull request link has a forge URL that names no pull request, checked against a
pull request whose own URL names none either, no longer counts as the card's by that
coincidence: the card id in the title, body or branch decides, and `--yes` confirms it.

## The dict helpers `get` and `obj` live in `onboarding`, and `cli.py` calls them there

**Id:** 515f27a7-79fa-4946-90a5-8747fa14aee1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-sgaz43qazfzx; the clean-up audit, card tsk-hgnbapyw7hnh, finding 3
**Revisit when:** the structure card moves them into a leaf module

`cli._field` was `onboarding.get` and `cli._obj` was `onboarding._dict`. Both pairs are gone
from `cli.py`: it calls `onboarding.get` and `onboarding.obj` (the second renamed from `_dict`
so that another module may call it). The card asked to keep one pair and left its place to the
structure card, to be decided there if that card went first. It had not landed, so the place
is the module that already was the lower one. The choice of `onboarding` is this change's own;
the card names no place.

**Rejected alternatives:**
- Keeping `_field` and `_obj` in `cli.py` and having `onboarding` use them: `cli` imports
  `onboarding`, so that would be a cycle.
- A `_field = onboarding.get` alias in `cli.py`: two spellings of one function stay, which was
  the finding.
- A new leaf module now: that is the structure card's decision and would pre-empt it.
