### Changed

- Hub: the password login and the registration refuse a `Sec-Fetch-Site` of `same-site` as well as `cross-site`, like the device and mail sign-in calls; every anonymous sign-in and sign-up call now keeps one shared rule, and the login answers an `Authorization` header with `details.reason: humans_only` (docs/api.md §2.1, §2.6.5).
