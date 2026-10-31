# Bridges

## A connection waiting for consent is only its requests; the `bridge` table holds what exists

**Id:** a4dd5557-7978-4dcf-b847-ca2773b24565
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("The bridge") as #927 and #930 set it; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-31
**Revisit when:** a pending connection has to show somewhere the open requests do not reach, or the consent flow gains a third party

A row in `bridge` is a connection that exists: served and bridge as memberships, the purpose,
`cross_owner`. With one owner behind both agents `POST` writes it at once (201). Across owners it
files the pair of `consent` requests (`bridges.file`, kinds `bridge_owner` and `bridge_project`),
the proposal carrying served, bridge, purpose and, for a change of purpose, the connection's id;
`settle` writes or changes the row at the `go` that leaves none open, after `check` again with the
project as it is then. A change of purpose leaves the old purpose in the row until that `go`.

The limit of five counts held connections and the open requests of new pairs together, read from
the requests, so a pending pair takes its place without a row. A further `POST` for the same pair
or `PATCH` of the same connection withdraws the open requests (`superseded`) before filing anew;
ending a connection withdraws an open change (`bridge_ended`); a member removed, made a `proxy` or
moved into a role the limits across owners exclude ends its connections and requests.

Rejected: a `state` column (`pending` / `active`) on `bridge`. The purpose and the two answers
would then live in the row and in the requests at once, and every reader of the table (member
views, resume, chat observers, later `Maity-For`) would have to leave the pending rows out. The
cross-owner `reports_to` already keeps its pending edge in the request pair alone; bridges follow it.

## A chat shows the bridge as an observer without making it one

**Id:** e59c0bc0-fa15-487e-ad15-3b36d989e185
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.3 ("Seen in the chat") and the `bridge_observer` refusal of #930; implementation session for card tsk-emy3a9vtqxym, 2026-10-31
**Revisit when:** a bridge gets a chat route of its own beyond acting for the served agent

`group_chats.observers()`, which `access` reads, stays the owners of agent participants. The list a
chat view and the conversation list show is `shown_observers`: those owners, then every agent that
serves a participant across owners (`carriers`, one query for all chats of a list). A bridge reads a
chat only through the served agent, with `Maity-For` (the second pull request of the card); adding
it to `observers()` would have given it a reading route of its own, which the contract refuses with
`bridge_observer`. A bridge of the same owner is not shown: the owner already reads along.

## A proxy neither lists nor answers the project's consent to a bridge

**Id:** cbe0230b-8261-4451-80af-d62920aef2d4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on card tsk-emy3a9vtqxym, 2026-10-31, written into docs/api.md §2.3 by #930
**Revisit when:** a proxy is allowed to relay consents that grant access

The project's consent is a `consent` to `owner` that a human with `members:admin` answers. A proxy
answers requests to its owner on the owner's behalf elsewhere; here the answer grants another
owner's agent read access to the project, so the answerer is `humans_only` and `GET …/requests`
leaves `bridge_project` out for a proxy, which then does not see a request it may not relay.
