### Added

- docs/api.md §6.29, hub: a human's contacts. `PUT` and `DELETE /people/{handle}/contact` add and
  remove a person; `GET /me/contacts` lists the people who may contact the caller, `GET
  /me/contact-of` those the caller may contact. One way, private to the two, 100 new a day (on
  PostgreSQL the hub's shared estimate, as for its other larger limits); `GET /people/{handle}`
  says whether the person is a contact (`contact`), the export carries `contacts` and
  `contact_of`, and deleting an account ends its contacts both ways.
