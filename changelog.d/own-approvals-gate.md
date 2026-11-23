### Security

- hub: outsiders' work (a card an outside agent holds, or whose current report one filed) reaches `done` only with `policy.own_approvals` own approvals on its reported head, as docs/api.md §2.3 "Own approvals" contracts: every move to `done` is refused before that with `forbidden`, `details.reason: own_approvals`, `needed` and `counted`; a report with `"done": true` goes to `review`; and under `merged_closes: auto` a merge closes it once it has them (tsk-3ggnhdmgmkf3).
