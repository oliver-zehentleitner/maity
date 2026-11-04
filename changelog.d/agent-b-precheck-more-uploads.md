### Changed

- Hub: every request whose body may be larger than the 64 KiB default (attachments, images, the
  landing, legal and sign-in pages' settings and their previews) has its query and its caller
  checked from the headers before the body is read; a call that fails gets the same refusal as
  before, with its body unread (docs/api.md §1.7, §8.7).
