### Added

- hub: a project's own links (§6.11). `links` holds issues, wiki, discussions and chat, set with `PATCH /projects/{owner}/{slug}` under `project:admin` and merged by key. Each is checked as a person's website is, with 500 characters; a change is `"links": true` in `project_updated`. A public page shows them with `rel="nofollow ugc"`, a link into the repository's own path only while the repository is public.
- web: the links beside the repository in the header and on the overview, and four fields in Project settings that send only what changed.

### Changed

- web: the header's repository button reads "Repository" for every forge; its mark and its screen-reader name still say which forge.
- docs: §6.11 states the change as `"links": true` in the `fields` object of `project_updated`, as every settings change is.
