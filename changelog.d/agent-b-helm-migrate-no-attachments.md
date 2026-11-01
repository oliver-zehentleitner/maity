### Fixed

- helm: the migrate Job no longer mounts the attachment claim or gets `MAITY_ATTACHMENT_DIR`, so a `ReadWriteOnce` claim no longer blocks an upgrade on a second node.
