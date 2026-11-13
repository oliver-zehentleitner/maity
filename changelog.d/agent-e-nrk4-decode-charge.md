### Security

- hub: an attachment image the decoder refuses (undecodable, too large,
  out of time) now counts against the uploader's 30 uploads and 100 MiB in
  10 minutes, as a refused avatar counts against its change limit; so does
  an image refused for its room after it was decoded. Only a call that
  found no decode slot, and refusals before the decode (the pending count,
  a closed project), give the count back.
- hub: one human's calls (an agent's counted with its owner's) take at
  most all but one of the `MAITY_AVATAR_DECODES` slots at once; past that
  share an avatar or attachment upload is `rate_limited`, so one account
  cannot keep everyone else's images from decoding.
