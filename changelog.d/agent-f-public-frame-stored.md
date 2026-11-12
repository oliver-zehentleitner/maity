### Changed

- hub: a stored public page opened on its own (`?as=public`: a person,
  an agent, an organisation, a project and its views, a card) stands in
  the landing page's header and footer, as `/explore` and the legal
  pages do. The frame is applied when the page is served, in the
  reader's language, around the page as it was stored, so a change to
  the start page shows at once without rendering the pages again. The
  answer's `ETag` covers the frame, and its policy also allows the
  frame's stylesheets and fonts.
