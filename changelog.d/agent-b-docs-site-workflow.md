### Changed

- Docs site (`pages.yml`): the site is built in a job with read access only, from
  `tools/requirements/site.txt` alone (the Keep the Why dashboard, Markdown and PyYAML, pinned with
  hashes, as wheels only, in a fresh environment); a second job that installs nothing publishes it
  and alone holds `pages: write` and `id-token: write`. `make -C tools lock` and
  `make -C tools lock-check` keep the lock current; CI checks it and runs the docs renderer's tests
  with it, and the audit workflow checks it against known advisories.
