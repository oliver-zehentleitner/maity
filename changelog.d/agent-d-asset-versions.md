### Changed

- The dashboard's files are asked for under a version (docs/api.md §1, §16.11):
  - The shell names each script, stylesheet and picture under `/assets/` with `?v=<version>`, the first 16 hex digits of the SHA-256 of the file as served.
  - That request is cached `public, max-age=31536000, immutable`, so a warm load no longer revalidates each unchanged file.
  - A stylesheet's fonts and pictures carry their versions too.
  - The files a script loads later (language catalogs, Keep the Why) take their versions from a data block in the shell.
  - Any other request, including one for another version, still gets the current file `no-cache` with its `ETag`.
