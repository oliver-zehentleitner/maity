### Added

- hub: the instance's landing page (`docs/api.md` §16.7) — `GET`/`PATCH
  /admin/settings/landing` for the instance admin (`enabled`, `title`, `markdown`, `cta`;
  text-only Markdown up to 64 KiB, raw HTML outside fenced code and images refused with the
  line named, links only `https` URLs without credentials or dashboard routes `/#/…`,
  bare `https://` links checked the same way; `markdown` required when enabled;
  `updated_at` and `updated_by` recorded) and the public `GET /landing` on the public
  host: the same body for every visitor, `{enabled: false}` when off, `Cache-Control:
  public, max-age=60` and an ETag over the body (migration `0040_instance_landing`)
