### Changed

- hub: a device code is 12 characters of Crockford's base32, shown in three groups of four
  (`K7QM-4XPR-9D2F`); the hub reads exactly 12, so an 8-character code of before is no longer
  taken (docs/api.md §2.6.2)
- web: the device-code field, its hint and the code shown on Sign in another device take the 12
  characters in three groups
