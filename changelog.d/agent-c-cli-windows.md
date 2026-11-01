### Added

- cli: `maity` starts on Windows. The state directory is protected by an access list of its own, and a credential or state directory others can reach is refused as on POSIX. The runner stays POSIX only: on Windows it refuses and points to WSL.
