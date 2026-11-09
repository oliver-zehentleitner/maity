// "Not found" (docs/api.md §16.11, tsk-h1e5zmq1wnhj): what the dashboard draws at an address that
// shows nothing. The hub answers every such address with the shell, 200 and `noindex`, and never
// says whether a name exists (context/routing.md e34ae588); so the words here never say it either.
// A visitor reads "does not exist, or it is not public" in the frame of the pages without a session,
// with the sign-in one link away: a private profile and a missing one look the same. A signed-in
// reader gets the same view inside the app. Dashboard routes that need a session keep the login
// (app.js decides which is which).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // /explore is the hub's page (§16.11): js/route.js leaves a click on it to the browser.
  const explore = () => h("a", { href: "/explore" }, M.t("not_found.explore"));

  // The ways on: the sign-in back to this address (a visitor), the start, the public projects.
  function ways(signedIn, path) {
    const items = signedIn
      ? [h("a", { href: "/all" }, M.t("not_found.all")), explore()]
      : [h("a", { href: M.withNext("/login", path) }, M.t("not_found.sign_in")), h("a", { href: "/" }, M.t("not_found.start")), explore()];
    return h("ul", { class: "not-found-ways" }, items.map((a) => h("li", null, a)));
  }

  // Without a session: the page in the frame (§16.7.5), as the sign-in stands in it. `bar` is the
  // app's header row for where the frame cannot be read.
  function page(main, header, path, bar) {
    document.title = M.t("not_found.title") + " · Maity";
    append(clear(header), bar);
    append(clear(main), M.authPages.door(null, h("section", { class: "view-not-found" },
      h("h1", { class: "door-title" }, M.t("not_found.title")),
      h("p", null, M.t("not_found.visitor")),
      ways(false, path))));
    M.siteChrome.enter(path);
  }

  // Signed in: the same view inside the app, under the reader's own header.
  function view(root) {
    append(root, h("h1", null, M.t("not_found.title")), h("p", null, M.t("not_found.member")), ways(true, null));
  }

  M.notFound = { page, view };
})(window.Maity);
