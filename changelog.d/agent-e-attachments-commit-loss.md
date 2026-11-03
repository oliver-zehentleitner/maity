### Fixed

- hub: an upload whose database COMMIT went through but whose answer was lost no longer removes
  its bytes. After an error, the hub first checks, under the project's lock, whether the
  attachment's row exists, so a COMMIT the database is still running is waited for. It removes
  the bytes only when no row names them, and leaves them to the sweep when it cannot tell.

### Changed

- hub: an image upload past the limit of pending uploads is refused before the image is decoded.
  A database error in that check gives the upload back to the rate, as any refusal before the
  write does.
- hub: the attachment sweep logs one line per pass with what it removed, also when nothing went.
