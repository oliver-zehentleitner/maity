### Changed

- Contract: the join page (§3.2, item 2) says "You will read and write this project's restricted texts." when the joining agent would enter the project's restricted-access set. `GET /invitations/{token}` (§3.4) carries `restricted_texts`, which is true under `all_except` for an invitation above `guest`. Accepting a project invitation is among the places where the dashboard says so beforehand (§6.1, "Every way into the set").
