### Changed

- hub, web: a chat's meat-proxy choice now decides the lead part only and the hands part always comes from the profile, so a profile with only the hands part no longer shows the mode as active in a chat. `true` over a profile that is off gives the lead part alone (before: both), and `false` keeps the hands part (before: none). Participant entries carry `meat_proxy_lead` and `meat_proxy_hands`.
