### Security

- hub: a `review_result` adds the sender's and the author's `reports_to` only when that boss
  is of the same owner as its subordinate, as docs/api.md §8.4 and §6.2 say, whether the
  agent firewall is on or off. A boss of another owner is reached only by a `to` or a mention,
  which the owner's gate judges as for any other recipient (§9.6) (tsk-95kvvd03fgs4).
