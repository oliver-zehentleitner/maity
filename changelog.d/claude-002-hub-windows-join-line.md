### Fixed

- hub: `paste_lines.windows` sets PowerShell to UTF-8 without a byte order
  mark before anything runs, so non-ASCII text piped into `maity` under
  Windows PowerShell 5.1 no longer arrives as `?`, and on a machine without
  pipx it installs pipx with `python -m pip install --user` and runs it as a
  module instead of failing at `pipx`.
