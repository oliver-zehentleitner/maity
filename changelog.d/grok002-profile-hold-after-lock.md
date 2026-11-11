### Fixed

- hub: a profile's display name and a person's public profile read a moderation
  hold after the owner's row lock, and a hide of a profile takes that lock
  before it writes the hold.
