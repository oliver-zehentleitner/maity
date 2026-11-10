### Fixed

- docs/install: the k3s step that reads the SMTP password is marked as `bash`; under `dash` its `read -s` fails and leaves an empty password.
