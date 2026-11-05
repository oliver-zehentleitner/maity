### Changed

- Dashboard (§16.8, §7): the instance admin's request for a new abuse report shows in the inbox as
  Personal, with no answer field, no replies and no Withdraw, only Later and **Open report**, which
  opens that report in Admin → Reports; this works from the all-projects inbox. The bell's
  `report_open` item is no longer handled. `resolve_the_report` has its words in every language,
  and a personal request with neither project nor organisation is named "Personal" alone. The
  fixture hub lists such requests, refuses answering or withdrawing them and withdraws one when
  its report is resolved.
