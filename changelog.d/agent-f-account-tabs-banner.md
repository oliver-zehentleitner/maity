### Fixed

- web: on a phone the current tab stays in sight in its row when the fonts arrive after the page
  is drawn, in the account's tabs and in the header's row of a project's views; before,
  Security could end 1 px outside the row at 390 px and a project's Settings 16 px, and the
  e2e step `account_tabs_layout` failed now and then (tsk-1cs7h9jhww36).
