### Fixed

- ci: `install-python.sh` and `install-services.sh` change to `/` first: they ran uv and `config.sh` as the runner
  user in whatever directory root stood in, and uv failed on `/root/uv.toml` ("Permission denied") or on a
  directory the script had deleted.
