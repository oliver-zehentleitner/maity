### Security

- hub: every page of the app shell, at every path, carries the same
  security headers as the hub's other HTML pages: a policy with
  `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'` and
  `object-src 'none'`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin` and `Cross-Origin-Opener-Policy:
  same-origin`. Every HTML page gains `X-Frame-Options`, the opener
  policy and a minimal `Permissions-Policy` unless it sets its own.
- hub: answers over TLS carry `Strict-Transport-Security`;
  `MAITY_HSTS_MAX_AGE` sets the max-age (one year by default, `0` sends
  none). Plain-HTTP setups are unaffected.
