### Fixed

- cli: `maity --version` includes the code build revision and dirty state,
  distinguishing source installs that share a release version. Wheels
  carry their build stamp, source distributions preserve it, and editable
  checkouts show their current Git identity; unavailable provenance is
  shown as `unknown`.
