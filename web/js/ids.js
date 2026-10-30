// Ids in text become links (the maintainer's ask, tsk-dcj6qwjxc9cq):
// wherever the dashboard renders what someone wrote, a well-formed card,
// request or member id links to its page, and #123 to the project
// repository's pull request or issue. Linked by shape only: no id is
// looked up, the page it opens says when there is no such thing. The
// link's text is the id as written, and outside the id's project a card's
// or request's carries the project's full name before it (docs/api.md
// §6.25: oliver/maity/tsk-…, display only, never parsed); nothing else of
// the text changes, and no mention is made (§8.6 is the hub's). Code stays
// plain, except a code span that is one id alone (only()); fenced blocks
// are never passed here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;

  // hub/src/maity_hub/ids.py: a prefix and 12 Crockford base32 characters
  // (no i, l, o, u). #n is a forge number (docs/api.md §6.13), not part of
  // a word, a path or a URL's fragment.
  // A card or request may carry its project's full name before it
  // (§6.25, models.py's handle and slug shapes): it links into that project.
  const ID = /(?<![\w\-/#&?=.])(?:(?:([a-z0-9][a-z0-9-]{1,30})\/([a-z0-9][a-z0-9-]{1,62})\/)?(tsk|req)-([0-9a-hjkmnp-tv-z]{12})|(agt|hum)-([0-9a-hjkmnp-tv-z]{12})|#([1-9][0-9]{0,6}))(?![\w\-])/g;
  const PAGE = { tsk: "tasks", req: "inbox", agt: "members", hum: "members" };

  // The forge numbers resolve on: GitHub only (§6.13, the one forge of V1),
  // read as the hub reads a repository (hub/src/maity_hub/forge.py): the
  // host github.com in any case, owner and name the first two segments.
  function forgeBase(url) {
    const m = /^https:\/\/([^/?#\s]+)\/([A-Za-z0-9-]+)\/([A-Za-z0-9._-]+?)(?:\.git)?(?:[/?#].*)?$/.exec(String(url || ""));
    return m && m[1].toLowerCase() === "github.com" ? "https://github.com/" + m[2] + "/" + m[3] : null;
  }

  // Where a text belongs: the project it is part of, from a view's context,
  // and whether it is shown outside that project (the global chat, the
  // views across projects). Read along from outside (/observe,
  // ctx.outsider) nothing of the project opens, so nothing links, as for a
  // member's name (M.dom.memberRef).
  function where(ctx) {
    if (!ctx || ctx.outsider) return { slug: null, repository: null };
    const p = ctx && ctx.project;
    return { slug: (ctx && ctx.slug) || null, repository: (p && p.repository && p.repository.url) || null,
      outside: !!(ctx.scope && ctx.scope !== "project") };
  }

  // A card's or a request's reference as it reads: the id alone inside its
  // project, `<full name>/<id>` outside it (§6.25). The one place that
  // writes the prefix.
  const ref = (full, id, outside) => (outside && full ? full + "/" + id : id);

  // A text as strings and links. `at`: {slug, repository, outside}; without
  // a slug ids stay text (there is no page to open), without a GitHub
  // repository numbers do.
  function link(text, at) {
    const s = String(text == null ? "" : text);
    const slug = at && at.slug;
    const forge = at && forgeBase(at.repository);
    if (!slug && !forge) return [s];
    const out = [];
    let from = 0;
    for (const m of s.matchAll(ID)) {
      const kind = m[3] || m[5];
      const id = kind && kind + "-" + (m[4] || m[6]);
      // The project the id names, else the text's own.
      const project = m[1] ? m[1] + "/" + m[2] : slug;
      const href = kind
        ? (slug ? "/" + M.api.projectPath(project) + "/" + PAGE[kind] + "/" + id : null)
        : (forge ? forge + "/issues/" + m[7] : null);
      if (!href && !kind) continue;
      if (m.index > from) out.push(s.slice(from, m.index));
      // An id with nowhere to open still reads as one, never broken.
      if (!href) out.push(h("span", { class: "id-ref" }, m[0]));
      else out.push(kind
        ? h("a", { class: "id-ref", href }, m[1] ? m[0] : kind === "tsk" || kind === "req" ? ref(slug, id, at.outside) : id)
        : h("a", { class: "id-ref", href, rel: "noopener noreferrer", target: "_blank" }, m[0]));
      from = m.index + m[0].length;
    }
    if (from < s.length || !out.length) out.push(s.slice(from));
    return out;
  }

  // Only the links of a text, for a place that cannot hold links itself
  // (an entry's title inside its button).
  const refs = (text, at) => link(text, at).filter((x) => typeof x !== "string");

  // A code span that is one id and nothing else, as a link drawn as code:
  // agents write ids in backticks, and the reader wants the card, not a
  // copy of its id. Anything more in the span, or an id with nowhere to
  // open, is null: the span stays code that copies itself.
  function only(text, at) {
    const parts = link(String(text).trim(), at);
    const a = parts.length === 1 && typeof parts[0] !== "string" && parts[0].tagName === "A" ? parts[0] : null;
    if (a) { const said = a.textContent; a.textContent = ""; a.appendChild(h("code", null, said)); }
    return a;
  }

  M.ids = { link, refs, only, where, ref, forgeBase };
})(window.Maity);
