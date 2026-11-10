### Added

- web: **the instance's landing page** (docs/api.md §16.7): at the root, a visitor without a session
  sees the operator's page from `GET /landing` — the large lockup, the title, the Markdown (dashboard
  routes as in-page links on this page only), the button and a **Sign in** link; off or failing,
  the login page as before, and `#/login` always reaches it. The admin area's **Landing page** edits
  it with a preview, who changed it last, and the hub's refused line named at the text
