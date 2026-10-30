### Added

- hub: the repository of a project with a public page (§16.9, step 4b): the probe stores whether the forge reports it public, whatever grant reads it (`project.repository_public`, migration `20261030155716_repo_public`), and the page shows the URL only while it does; an answer the hub could not read counts as private, and a page that loses the URL is rendered again at once (tsk-w89mspg3gwx1).
