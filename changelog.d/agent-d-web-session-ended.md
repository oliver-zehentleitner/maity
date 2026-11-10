### Fixed

- web: when the session ends under the page (expired, revoked, ended elsewhere), the first 401 stops
  the background work and shows the sign-in page with a note instead of polling on into 401s;
  signing in again returns to the same route
