### Changed

- hub: the memory listing and the resume packet's memory block build their
  entries in batches: a fixed number of queries per page or store instead of
  four to six per entry.
- hub: a background Keep the Why refresh that fails unexpectedly is logged with
  its trace instead of passing silently.
