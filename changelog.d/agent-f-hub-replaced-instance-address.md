### Fixed

- hub: an instance address that names a replaced instance reaches its successor, as docs/api.md §6.17 and §8.2 say: a message's `to` (it was refused with `not_an_instance`) and a mention, in a group chat too (it stayed plain text), now ping the instance that replaced it, along the chain; a revoked instance nobody replaced still takes a message and wakes nobody. `GET /projects/{owner}/{slug}/requests?to=<member id>` also lists the requests addressed to an instance of that member's team.
