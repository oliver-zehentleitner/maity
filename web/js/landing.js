// The instance's landing page (docs/api.md §16.7): what a visitor without
// a session sees at the root when the operator has written one — the
// lockup, the title, the operator's Markdown, the button and a way to sign
// in. Disabled, or when the call fails, the login page as before: the
// landing page never stands between a person and sign-in. And the admin
// area's editor for it, with a preview drawn by the same renderer.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, safeUrl } = M.dom;
  const SETTINGS = "/admin/settings/landing";
  const ROUTE = M.markdown.ROUTE;
  const TITLE_MAX = 120, LABEL_MAX = 40;
  const MARKDOWN_MAX = 64 * 1024; // bytes of UTF-8, as the hub counts
  const utf8Length = (s) => [...s].reduce((n, ch) => { const c = ch.codePointAt(0); return n + (c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4); }, 0);

  // The page as the hub serves it, or null: disabled, absent or failed.
  // Asked only where the hub's machine form lists it: an older hub would
  // answer 404 on every visit to the root.
  async function read() {
    try {
      if (!await M.api.hubHas("GET", "/landing")) return null;
      const page = await M.api.get("/landing");
      return page && page.enabled && page.markdown ? page : null;
    } catch (err) {
      return null;
    }
  }

  // A cta's target as a link: a dashboard route stays in the page, an
  // https URL opens apart; anything else is no button.
  function ctaLink(cta, cls) {
    if (!cta || !cta.label) return null;
    if (ROUTE.test(cta.href || "")) return h("a", { class: cls, href: cta.href.slice(1) }, cta.label);
    const url = safeUrl(cta.href);
    return url ? h("a", { class: cls, href: url, rel: "noopener noreferrer", target: "_blank" }, cta.label) : null;
  }

  // The page itself, for the visitor and as the editor's preview.
  function page(p) {
    return h("article", { class: "landing" },
      h("div", { class: "landing-lockup" },
        h("img", { class: "brand-light", src: "brand/maity-lockup-large.svg", alt: "", width: "320", height: "96" }),
        h("img", { class: "brand-dark", src: "brand/maity-lockup-large-dark.svg", alt: "", width: "320", height: "96" })),
      p.title ? h("h2", { class: "landing-title" }, p.title) : null,
      h("div", { class: "md landing-body" }, M.markdown.withRoutes(p.markdown || "")),
      h("p", { class: "landing-actions" },
        ctaLink(p.cta, "button primary landing-cta"),
        p.cta && p.cta.href === "/#/login" ? null : h("a", { class: "landing-sign-in", href: "#/login" }, "Sign in")));
  }

  function show(main, p, header) {
    if (p.title) document.title = p.title;
    append(clear(header), h("div", { class: "bar" }, M.brandTitle()));
    append(clear(main), page(p));
  }

  // ---- the admin area's editor ----------------------------------------------

  const REASONS = {
    required: "required while the page is on",
    invalid: "not allowed here",
    extra_forbidden: "not supported by this hub",
  };
  const MARKDOWN_RULE = "Headings, paragraphs, emphasis, lists, quotes, fenced code and links (https, or a dashboard route like /#/login); "
    + "no images and no HTML outside fenced code.";

  async function section(ctx, root) {
    const status = M.statusLine();
    const enabled = h("input", { id: "landing-enabled", type: "checkbox" });
    const title = h("input", { id: "landing-title", maxlength: String(TITLE_MAX), autocomplete: "off" });
    const markdown = h("textarea", { id: "landing-markdown", rows: "14", spellcheck: "true", "aria-describedby": "landing-markdown-rule landing-markdown-error" });
    const label = h("input", { id: "landing-cta-label", maxlength: String(LABEL_MAX), autocomplete: "off", placeholder: "Sign in" });
    const href = h("input", { id: "landing-cta-href", autocomplete: "off", spellcheck: "false", placeholder: "/#/login or https://…" });
    const errors = {
      title: h("p", { class: "field-error", id: "landing-title-error", role: "alert" }),
      markdown: h("p", { class: "field-error", id: "landing-markdown-error", role: "alert" }),
      cta: h("p", { class: "field-error", id: "landing-cta-error", role: "alert" }),
      enabled: h("p", { class: "field-error", id: "landing-enabled-error", role: "alert" }),
    };
    const preview = h("div", { class: "landing-preview", "aria-label": "Preview" });
    const changed = h("p", { class: "muted landing-changed" });
    let current = null;

    const value = () => ({
      enabled: enabled.checked,
      title: title.value.trim() || null,
      markdown: markdown.value.trim() ? markdown.value : null,
      cta: label.value.trim() || href.value.trim() ? { label: label.value.trim(), href: href.value.trim() } : null,
    });
    // The preview's links are text: a click would leave the editor and
    // its unsaved text.
    const inert = (node) => {
      Array.from(node.querySelectorAll("a")).forEach((a) => {
        a.parentNode.insertBefore(h("span", { class: "inert-link " + (a.className || "") }, a.textContent), a);
        a.remove();
      });
      return node;
    };
    const drawPreview = () => {
      const v = value();
      append(clear(preview), v.markdown ? inert(page(v)) : h("p", { class: "muted" }, "Write the page's text to see it here."));
    };
    [title, markdown, label, href].forEach((el) => el.addEventListener("input", drawPreview));

    function fill(v) {
      current = v;
      enabled.checked = !!v.enabled;
      title.value = v.title || "";
      markdown.value = v.markdown || "";
      label.value = v.cta ? v.cta.label : "";
      href.value = v.cta ? v.cta.href : "";
      changed.textContent = v.updated_at
        ? "Last changed " + formatTime(v.updated_at) + " by " + (v.updated_by === ctx.me.id ? "you" : (ctx.nameOf ? ctx.nameOf(v.updated_by) : v.updated_by)) + "."
        : "Never changed: visitors see the login page.";
      drawPreview();
    }

    // The hub's refusal at its field; a Markdown line it names is selected.
    function refused(fields) {
      Object.values(errors).forEach((e) => { e.textContent = ""; });
      Object.entries(fields).forEach(([key, reason]) => {
        const at = key.startsWith("cta") ? "cta" : key;
        const line = /^line (\d+)$/.exec(reason);
        if (key === "markdown" && line) {
          const n = Number(line[1]);
          const lines = markdown.value.replace(/\r\n?/g, "\n").split("\n");
          const text = lines[n - 1] || "";
          errors.markdown.textContent = "Line " + n + " breaks the rules: “" + text.trim().slice(0, 80) + "”. " + MARKDOWN_RULE;
          const start = lines.slice(0, n - 1).reduce((a, l) => a + l.length + 1, 0);
          markdown.focus();
          if (markdown.setSelectionRange) markdown.setSelectionRange(start, start + text.length);
          return;
        }
        if (errors[at]) errors[at].textContent = (key === "cta.href" ? "The link: " : "") + (REASONS[reason] || reason);
      });
    }

    const form = h("form", {
      class: "inline-form landing-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const v = value();
        const local = {};
        if (v.markdown && utf8Length(v.markdown) > MARKDOWN_MAX) local.markdown = "longer than 64 KiB";
        if (v.enabled && !v.markdown) local.markdown = "required";
        if (v.cta && !v.cta.label) local.cta = "a button needs a label as well as a link";
        else if (v.cta && !(ROUTE.test(v.cta.href) || safeUrl(v.cta.href))) local["cta.href"] = "invalid";
        if (Object.keys(local).length) { refused(local); status.done(); return; }
        refused({});
        status.busy("Saving…");
        try {
          fill(await M.api.patch(SETTINGS, v));
          status.done();
          append(status.el, h("span", { class: "ok" }, v.enabled ? "Saved. Visitors see it within a minute." : "Saved. Visitors see the login page."));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          // The hub's body cap can be met before the Markdown's own limit.
          if (err.status === 413) { refused({ markdown: "larger than the hub accepts in one save; shorten the text" }); status.done(); }
          else if (fields) { refused(fields); status.done(); } else status.fail("Not saved: ", err);
        }
      },
    },
    h("label", { class: "check", for: "landing-enabled" }, enabled, " Show the landing page to visitors who are not signed in"), errors.enabled,
    h("label", { for: "landing-title" }, "Title"), title, errors.title,
    h("label", { for: "landing-markdown" }, "Text (Markdown)"), markdown,
    h("p", { class: "hint", id: "landing-markdown-rule" }, MARKDOWN_RULE + " At most 64 KiB."), errors.markdown,
    h("label", { for: "landing-cta-label" }, "Button label"), label,
    h("label", { for: "landing-cta-href" }, "Button link"), href, errors.cta,
    h("button", { type: "submit" }, "Save landing page"),
    status.el);

    append(root, h("h2", null, "Landing page"),
      h("p", { class: "hint" }, "What visitors who are not signed in see at the root. Off, they see the login page; a sign-in link is always on the page."),
      changed, form, h("h3", null, "Preview"), preview);
    fill(await M.api.get(SETTINGS));
  }

  M.landing = { read, show, section, page };
})(window.Maity);
