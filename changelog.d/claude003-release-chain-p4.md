### Changed

- deploy: the Helm chart (0.2.0) pulls the hub image by digest by default:
  `image.digest` is required, and the chart's `appVersion` is no longer a
  default image tag. Pulling by tag is an explicit opt-in,
  `image.allowTag: true` with `image.tag`. The docs no longer call a tag
  immutable. Upgrade note: an install that sets only `image.tag`, or neither,
  sets `image.digest` (or the opt-in) before its next upgrade; an install that
  already pins a digest is unchanged (tsk-6zh891gy6cvz, point 4).
