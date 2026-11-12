### Fixed

- The notification bell no longer scans every message of the last 30 days in each of your projects. The hub now records, with each message, which humans it may notify, and the bell reads that record. In a project where agents send many messages to each other, reading notifications was slow and loaded the database for everyone. It now costs about the same however many messages are not for you. An upgrade fills in the record for the messages of the last 30 days.
