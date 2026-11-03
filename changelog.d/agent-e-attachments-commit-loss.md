### Fixed

- hub: an upload whose database COMMIT went through but whose answer was lost no longer removes
  its bytes. After an error, the hub first checks whether the attachment's row exists. It removes
  the bytes only when no row names them, and leaves them to the sweep when it cannot tell.

### Changed

- hub: an image upload past the limit of pending uploads is refused before the image is decoded.
- hub: the attachment sweep logs one line per pass with what it removed, also when nothing went.
