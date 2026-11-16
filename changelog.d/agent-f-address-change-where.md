### Fixed

- hub: the notice to the old address after a verified address change names the browser,
  operating system and IP address the change was asked from, as docs/api.md §2.6.3 and §18.4
  promise; before, only a removal did. The hub keeps them with the pending address and clears
  them at its verification, replacement, removal or voiding, and once its link expired
  (migration `20261115000000_address_where`; tsk-y5hkg2ztvwq9).
