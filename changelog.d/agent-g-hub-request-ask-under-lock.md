### Fixed

- hub: `POST …/requests` checks the caller's membership as read under the project lock, as a
  claim does. A change that commits after the first membership read but before the request
  takes the lock now refuses the request instead of storing it: a role change to `expert`
  (`403`, `details.scope: requests:ask`), a trust change from `admin` to `member` for an
  `urgent` request (`priority: urgent_needs_requests_answer`) and a role change away from
  `proxy` for a request with `action` (`action: proxy_only`). A request that takes the lock
  first is stored, and the change waits for it.
