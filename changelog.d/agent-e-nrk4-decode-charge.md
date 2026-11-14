### Security

- hub: an attachment image the decoder refuses (undecodable, too large,
  out of time) now counts against the uploader's 30 uploads and 100 MiB in
  10 minutes, as a refused avatar counts against its change limit; so does
  an image refused for its room after it was decoded. A call that found
  no decode slot and a refusal for the pending count before the decode
  give the count back; an upload into a closed project is not counted.
- hub: one human's calls (an agent's counted with its owner's) take at
  most all but one of a serving process's `MAITY_AVATAR_DECODES` slots at
  once (one when there is only one); past that
  share an avatar or attachment upload is `rate_limited`, so one account
  cannot keep everyone else's images from decoding.
