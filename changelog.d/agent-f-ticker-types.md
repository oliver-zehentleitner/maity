### Fixed

- hub: the ticker listing filters by every item type of §17.1: `GET …/ticker?type=jour_fixe` lists a round's report instead of answering `invalid`. A manual post of type `jour_fixe` answers `not_for_type`, as §17.1 says, instead of `invalid`.

### Changed

- hub: a ticker subscription takes the types of §17.8 only. Following or muting `rename` now answers `invalid` (it was accepted and changed nothing, since a rename goes to `all` alone), and so does `jour_fixe`; a `rename` already stored in a subscription can still be removed.
