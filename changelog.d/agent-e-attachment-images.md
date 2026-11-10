### Added

- hub: the attachment image path (§8.7): the avatar decoder's child process has an `attachment`
  mode that decodes an image under the same budgets and slots and encodes it again at its own
  size (8192 px on a side, 40 megapixels), as PNG, JPEG or WebP, with EXIF orientation applied,
  the colour profile converted to sRGB and nothing but the pixels kept. The upload routes
  follow with the attachments core.
