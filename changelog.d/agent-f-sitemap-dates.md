### Fixed

- ci: the project site's `sitemap.xml` dates the rendered docs pages. `tools/site_docs.py` lists each page's Markdown source in `docs/_assets/sources.json`, and `tools/site_sitemap.py` takes the page's `<lastmod>` from that file's last commit (a section of the split API contract from `docs/api.md`); before, it looked for a source under `docs/` that does not exist, and only the home page had a date.

### Changed

- tools: `tools/site_docs.py` takes `--base` like `tools/site_sitemap.py`, with the same default (`https://maity.dev`) from one constant, so the docs pages' canonical links and the sitemap's URLs name the same address.
