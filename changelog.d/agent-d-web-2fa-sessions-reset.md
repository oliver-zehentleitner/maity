### Added

- web: **Sessions** says which sessions passed the second factor, and **Admin → Users** has
  **Reset two-factor sign-in**: a reason and a mail the person confirms (§2.8.3, §2.8.7).

### Changed

- web: at the top right **Talk to the lead** now stands left of the global chat.

### Fixed

- web: a tab that left the enrolment page, by signing out or because the hub let go of the
  requirement, drew nothing at the next `second_factor_enrolment_required` refusal.
