// Ids in text become links (the maintainer's ask, tsk-dcj6qwjxc9cq):
// wherever the dashboard renders what someone wrote, a well-formed card,
// request or member id links to its page, and #123 to the project
// repository's pull request or issue. Linked by shape only: no id is
// looked up, the page it opens says when there is no such thing. The
// link's text is the id as written; nothing else of the text changes, and
// no mention is made (docs/api.md §8.6 is the hub's). Code stays plain:
// the callers never pass code spans or fenced blocks here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;

  // hub/src/maity_hub/ids.py: a prefix and 12 Crockford base32 characters
  // (no i, l, o, u). #n is a forge number (docs/api.md §6.13), not part of
  // a word, a path or a URL's fragment.
  const ID = /(?<![\w\-/#&?=.])(?:(tsk|req|agt|hum)-([0-9a-hjkmnp-tv-z]{12})|#([1-9][0-9]{0,6}))(?![\w\-])/g;

  // The forge numbers resolve on: GitHub only (§6.13, the one forge of V1),
  // an https URL with owner and repository and nothing after them.
  function forgeBase(url) {
    const m = /^https:\/\/github\.com\/([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?\/?$/.exec(String(url || ""));
    return m ? "https://github.com/" + m[1] + "/" + m[2] : null;
  }

  // Where a text belongs: the project it is part of, from a view's context.
  function where(ctx) {
    const p = ctx && ctx.project;
    return { slug: (ctx && ctx.slug) || null, repository: (p && p.repository && p.repository.url) || null };
  }

  // A text as strings and links. `at`: {slug, repository}; without a slug
  // ids stay text (there is no page to open), without a GitHub repository
  // numbers do.
  function link(text, at) {
    const s = String(text == null ? "" : text);
    const slug = at && at.slug;
    const forge = at && forgeBase(at.repository);
    if (!slug && !forge) return [s];
    const out = [];
    let from = 0;
    for (const m of s.matchAll(ID)) {
      const href = m[1]
        ? (slug ? "#/p/" + encodeURIComponent(slug) + "/" + { tsk: "tasks", req: "inbox", agt: "members", hum: "members" }[m[1]] + "/" + m[0] : null)
        : (forge ? forge + "/issues/" + m[3] : null);
      if (!href) continue;
      if (m.index > from) out.push(s.slice(from, m.index));
      out.push(m[1]
        ? h("a", { class: "id-ref", href }, m[0])
        : h("a", { class: "id-ref", href, rel: "noopener noreferrer", target: "_blank" }, m[0]));
      from = m.index + m[0].length;
    }
    if (from < s.length || !out.length) out.push(s.slice(from));
    return out;
  }

  // Only the links of a text, for a place that cannot hold links itself
  // (an entry's title inside its button).
  const refs = (text, at) => link(text, at).filter((x) => typeof x !== "string");

  M.ids = { link, refs, where, forgeBase };
})(window.Maity);
