### Fixed

- hub: deleting an account (§2.9) now also deletes its forge links with their pending
  state and token, forgetting the installations' cached tokens, and its pending sign-in
  links with the day's count of wrong codes; both features landed after the deletion.
