### Changed

- Contract §16.9, §6.1: a new project is public by default (`public_page: on`); `POST /projects` takes `public_page`, and a project whose repository the hub finds private or cannot read at creation starts private. The create form shows the choice as "Private". Projects created before keep their value.
