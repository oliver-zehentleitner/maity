### Changed

- Contract §16.9, §6.1: a new project is public by default (`public_page: on`); `POST /projects` takes `public_page`, and a project whose repository the hub finds private or cannot read at creation starts private whatever the call sent. The create form shows "Private" and sends the field only when it is checked. Projects created before keep their value.
