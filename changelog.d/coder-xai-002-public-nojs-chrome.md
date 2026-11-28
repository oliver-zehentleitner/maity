### Fixed

- hub, web: a public page now has its header and footer without JavaScript. A visitor's stored page (project,
  its Board/Team/Organisation/Why views, a card, a person, an agent, an organisation) comes inside the app
  shell, whose header and footer only `js/site-chrome.js` drew: with script off it was an empty bar and no
  footer. The hub now puts the landing page's header and footer into the served HTML in the visitor's language
  (`?lang`, else `Accept-Language`, so the answer also varies by it), with Sign in coming back to the page and the
  footer's languages on the page's own path; the app's bar is hidden, and the dashboard's script takes the same
  markup over. The theme switch is in that served header too, visible without script so the layout matches
  (it only changes the theme once a script runs; the shell does not load landing.js). The header's section
  links and the footer's extra columns follow the landing page and the legal pages as configured, the same as
  with script. No stored page is rendered again for this. Without script the organisation page shows at once
  instead of after three seconds.

### Changed

- hub, web: the crumb `owner / project` above a project page's title (and a card's) is two links, to the owner's
  public page and to the project's page, in the served HTML and in the dashboard's drawing. `public_pages.FORMAT`
  is 4, so the stored project pages are rendered again once.
