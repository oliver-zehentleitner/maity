// The whole contract (docs/api.md §6.8, "The whole contract"; the route
// /<owner>/<slug>/contract, §16.11): the file `settings.contract_path`
// names, read whole from the repository, its table of contents beside the
// rendered text. Read when the view opens and again only on Refresh, never
// on a poll: a file can be a megabyte. The browser's cache keeps the answer
// (`Cache-Control: private, no-cache`) and sends `If-None-Match` on every
// re-read, so an unchanged file comes back as a 304 without its bytes. The
// text is the repository's and untrusted (§6.14): drawn by the chat's
// renderer without a project, so neither mentions nor ids become links.
// Every heading of the table carries the hub's `anchor` as its `id`, so
// contract#s-6.8 opens that section. On an error: the path and the hub's
// reason, nothing else — never an older text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, safeUrl } = M.dom;

  const DEFAULT_PATH = "docs/api.md";
  const pathOf = (project) => ((project && project.settings) || {}).contract_path || DEFAULT_PATH;

  // The hub's reasons the file is not shown (§6.8 "The setting"), in words
  // from the catalog; any other code as it comes.
  const WHY = {
    not_found_on_forge: () => M.t("contract.whole.why.not_found_on_forge"),
    not_markdown: () => M.t("contract.whole.why.not_markdown"),
    too_large: () => M.t("contract.whole.why.too_large"),
    not_text: () => M.t("contract.whole.why.not_text"),
    probe_not_configured: () => M.t("contract.why.probe_not_configured"),
    probe_unavailable: () => M.t("contract.why.probe_unavailable"),
  };

  // The line separators the hub's reader splits on (Python's
  // `str.splitlines`), each one line break here, so that a heading's `line`
  // in `toc` is the line the renderer counts.
  const BREAKS = /\r\n|[\n\v\f\r\x1c\x1d\x1e\x85\u2028\u2029]/g;

  function reason(err) {
    const fields = (err.details && err.details.fields) || {};
    return fields["settings.contract_path"] || err.code || "error";
  }

  // The table of contents: one link per heading, indented by its level.
  // A plain click scrolls on this page; the href is the place's own
  // address, for a new tab or a copied link.
  // An anchor the route's check refuses (none the hub writes today) is a
  // line of the table without a link, never a page that fails to draw.
  function tocList(ctx, toc) {
    return h("nav", { class: "contract-toc", "aria-label": M.t("contract.whole.toc") },
      h("ol", null, toc.map((e) => {
        const words = e.number ? [h("span", { class: "contract-toc-number" }, e.number), " ", e.title] : e.title;
        const href = ctx.link("contract") + "#" + e.anchor;
        return h("li", { class: "contract-toc-" + e.level }, M.route.isAnchored(href) ? h("a", {
          href,
          onclick: (ev) => {
            if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
            if (M.route.jump(e.anchor)) ev.preventDefault();
          },
        }, words) : h("span", null, words));
      })));
  }

  function draw(ctx, body, s, refresh) {
    const url = safeUrl(s.url);
    const anchors = new Map((s.toc || []).map((e) => [e.line, { level: e.level, anchor: e.anchor }]));
    append(clear(body),
      h("p", { class: "muted contract-meta" },
        M.tn("contract.meta.at", { path: s.path, ref: h("code", null, String(s.ref || "").slice(0, 7)) }),
        " · ", M.t("contract.meta.read", { ago: formatAgo(s.fetched_at, M.api.now()) }),
        url ? [" · ", h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, M.t("contract.meta.file"))] : null,
        " · ", refresh()),
      h("div", { class: "contract-whole" },
        (s.toc || []).length ? tocList(ctx, s.toc) : null,
        h("div", { class: "md contract-text" }, M.markdown(String(s.text || "").replace(BREAKS, "\n"), null, { anchors }))));
  }

  M.views.contract = async function (ctx, root) {
    const path = pathOf(ctx.project);
    const body = h("div", { class: "contract-page", "aria-live": "polite" });
    append(root, h("h2", null, M.t("contract.whole.title")), body);
    const refresh = () => h("button", { type: "button", class: "link-button contract-refresh", onclick: () => read(false) }, M.t("contract.refresh"));

    async function read(first) {
      append(clear(body), h("p", { class: "muted" }, M.t("contract.whole.reading")));
      let s;
      try {
        s = await M.api.get(ctx.base + "/contract");
      } catch (err) {
        const code = reason(err);
        append(clear(body), h("p", { class: "flag contract-unresolved" },
          M.tn("contract.unresolved", { where: h("code", null, path), why: Object.hasOwn(WHY, code) ? WHY[code]() : err.message || code, code: h("code", null, code) }),
          " ", refresh()));
        return;
      }
      draw(ctx, body, s, refresh);
      // A place named in the address (contract#s-6.8) is opened once the text is there.
      const at = M.route.current().fragment;
      if (first && at) M.route.jump(at);
    }

    await read(true);
  };

  M.contractView = { pathOf, DEFAULT_PATH };
})(window.Maity);
