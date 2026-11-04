### Changed

- hub: the sign-in link page (`/mail/sign-in/{token}`) and its dead-link page stand in the frame
  of the pages without a session (§16.7.5): the landing page's header and footer, between them the
  door of `public-pages.css`, as the dashboard draws `/login`. The link page is in the person's
  language, the dead-link page in the browser's. The frame's footer stands in the product line's
  place, as on the framed `/login`. The `GET` still changes nothing but the form cookie, and one
  button signs in. The policy allows the hub's own stylesheets and fonts and, newly, posts the form
  only to itself (`form-action 'self'`).
