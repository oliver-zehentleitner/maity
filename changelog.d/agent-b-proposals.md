### Added

- hub: proposals — a `consent` request to the owner can carry what it applies on its go
  (`request.proposal`, `{"kind": …}`), settled by the kind registered in
  `maity_hub.proposals` with the proposer, the approver and the outcome (`go`, `no`,
  `withdrawn`) on every close, the proposer's removal included; each kind names who may
  answer it (a scope, humans only or not), checked on the answer and in what is offered
  to answer, for every answer, and may add its own fields to `GET …/requests/{id}`, never
  to its events, lists or resume packets; a kind the hub does not
  know is never filed and fails only its own request (`proposal_kind_unknown`) (migration
  `0014_request_proposal`)
