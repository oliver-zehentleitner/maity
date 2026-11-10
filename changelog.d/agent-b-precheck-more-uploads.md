### Changed

- Hub: every request to a route that takes a caller whose body may be larger than the 64 KiB
  default (attachments, images, the landing, legal and sign-in pages' settings and their
  previews) has its query and its caller
  checked from the headers before the body is read; a call that fails gets the same refusal as
  before, with its body unread (docs/api.md §1.7, §8.7). On the join host every body is held to
  64 KiB, and a larger one is refused with `payload_too_large` unread. The forge webhook keeps
  its own limit and signature check (docs/api.md §17.4).
