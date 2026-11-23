### Fixed

- hub: a GitHub App installation can be linked in the browser. The forge sends the browser
  back to `GET /forge/github/setup` from another site, and the hub refused every such cookie
  request as `csrf_mismatch` before the route ran. A `Sec-Fetch-Site` of `cross-site` is now
  let through on that one call, and only as the browser's top-level navigation
  (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`); there the `state`, bound to the
  session and used once, protects the link, and a missing, expired, used or foreign one is a
  `303` to `/settings/forge?error=link_state`. A link another site opens to the setup changes
  nothing before its `state` is checked: no presence, no lease renewed, no read counted. A
  call with an `Authorization` or `Maity-For` header is `403 forbidden` (`humans_only`) before
  its credential is read, so it leaves no trace either. A
  cross-site `fetch` or frame to the setup, and every other cross-site cookie call, stay
  `csrf_mismatch` (docs/api.md §2.1, §11.4; tsk-2vtm39ykr7k4).
