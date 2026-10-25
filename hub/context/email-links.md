# Mail sign-in

## A link and its browser-bound code spend one grant; guesses are serialised per human

**Id:** 24bacf7b-862a-4c2a-b702-a851c8cb386d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.3–§2.6.5 and the mail sign-in implementation, 2026-10-25
**Revisit when:** issuance, code redemption or link completion can run without the human row lock

The link's nonce hash and the requesting browser's pending-cookie hash name the
same `email_sign_in` row. A conditional update of its unused, unexpired state is
the final check before creating a session. Code guesses additionally lock the
human row and reread the flow, so a request that read before the fifth wrong
guess cannot use the stale proof afterwards. The per-human UTC-day wrong-code
counter uses that same lock, across every source address and every flow.

**Reason:** separate used markers for the link and code would need to be changed
atomically everywhere; one grant gives both paths the same last check. A lock on
one flow alone cannot enforce the twenty-guess limit across several flows. The
human row already exists before a flow or a daily counter does, so it also
serialises creating those rows without an insert race on the server engines.
SQLite takes its equivalent write lock at transaction start.

Five wrong guesses remove only that code's proof; twenty remove every code proof
of the human and suppress new codes until the UTC day changes. They do not spend
the grant: the unguessable signed link stays usable. The route must commit wrong
guesses before returning `code_invalid`, since raising inside the transaction
would roll back the budget.

**Rejected alternatives:** separate link/code used flags, or a counter per flow
alone: they leave a second redemption path or let distributed guesses multiply
the human's allowed guesses. The limits and continued validity of the links are
contract requirements, not new policy introduced by this implementation.
