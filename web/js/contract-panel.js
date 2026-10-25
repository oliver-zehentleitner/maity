// The contract's section on a contract card (docs/api.md §6.8): the text
// stays in the repository, the hub reads it on request and the card shows
// it — the heading's section as Markdown, the commit it was read at, when,
// and the forge's page for the file. Folded until opened, so the board
// reads nothing for a card nobody looks at; Refresh reads again. The text
// is the repository's and untrusted (§6.14): no mentions, no ids made into
// links, its links as the Markdown renderer allows them. When the hub
// cannot resolve it, the card's path and section are shown with the hub's
// code — never an older text. Whoever may edit the card (holder, creator,
// tasks:admin) changes the path and the section here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, safeUrl } = M.dom;

  const DEFAULT_PATH = "docs/api.md";
  const TASKS_ADMIN = new Set(["owner", "admin"]);
  // The hub's reasons a section is not shown, in words; any other code as
  // it comes.
  const WHY = {
    unset: "the card names no section yet",
    not_found_on_forge: "the file is not in the repository's default branch",
    not_found_in_file: "the file has no heading with this number",
    ambiguous_in_file: "the file has two headings with this number; the hub shows neither",
    too_large: "the file is larger than 1 MiB",
    not_text: "the file is not UTF-8 text",
    probe_not_configured: "the hub has no forge token for this repository",
    probe_unavailable: "the forge did not answer",
  };

  const mayEdit = (ctx, c) => TASKS_ADMIN.has(ctx.role) || c.created_by === ctx.me.id
    || !!(c.claim && c.claim.holder === ctx.me.id);

  // onSaved(updated, focusId): the board redraws the card from the hub's answer.
  function panel(ctx, c, onSaved) {
    const k = c.contract;
    const where = (k.path || DEFAULT_PATH) + (k.section ? " § " + k.section : "");
    const body = h("div", { class: "contract-body", "aria-live": "polite" });
    const status = M.statusLine();
    let loaded = false;

    async function read() {
      loaded = true;
      append(clear(body), h("p", { class: "muted" }, "Reading the section from the repository…"));
      let s;
      try {
        s = await M.api.get(ctx.base + "/tasks/" + encodeURIComponent(c.id) + "/contract");
      } catch (err) {
        const fields = (err.details && err.details.fields) || {};
        const code = fields["contract.section"] || fields["contract.path"] || err.code || "error";
        append(clear(body), h("p", { class: "flag contract-unresolved" },
          h("code", null, (k.path || DEFAULT_PATH) + (k.section ? " § " + k.section : "")), " is not shown: ",
          WHY[code] || err.message || code, " (", h("code", null, code), ")."));
        return;
      }
      const url = safeUrl(s.url);
      append(clear(body),
        h("p", { class: "muted contract-meta" }, s.path + " at ", h("code", null, String(s.ref || "").slice(0, 7)),
          " · read " + formatAgo(s.fetched_at, M.api.now()),
          url ? [" · ", h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, "the file on the forge")] : null),
        h("div", { class: "md contract-text" }, M.markdown(s.text)),
        s.truncated ? h("p", { class: "flag" }, "Cut at 64 KiB; the whole section is in the file",
          url ? [" (", h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, "open it"), ")"] : null, ".") : null);
    }

    const refresh = h("button", { type: "button", class: "small", onclick: () => read() }, "Refresh");
    const box = h("details", { class: "contract-section" },
      h("summary", null, "Contract section: ", h("code", null, where)),
      h("div", { class: "contract-bar" }, refresh),
      body,
      mayEdit(ctx, c) ? placeForm(ctx, c, onSaved, status) : null,
      status.el);
    box.addEventListener("toggle", () => { if (box.open && !loaded && k.section) read(); });
    if (!k.section) append(body, h("p", { class: "muted" }, "The card names no section yet."));
    return box;
  }

  // Path and section, as whoever may edit the card sets them (§6.8).
  function placeForm(ctx, c, onSaved, status) {
    const k = c.contract;
    const idOf = (name) => name + "-" + c.id;
    const path = h("input", { id: idOf("contract-path"), autocomplete: "off", spellcheck: "false", placeholder: DEFAULT_PATH });
    path.value = k.path || DEFAULT_PATH;
    const section = h("input", { id: idOf("contract-section"), autocomplete: "off", spellcheck: "false", placeholder: "6.20" });
    section.value = k.section || "";
    return h("form", {
      class: "inline-form contract-place",
      onsubmit: async (e) => {
        e.preventDefault();
        const next = { path: path.value.trim() || DEFAULT_PATH, section: section.value.trim() || null };
        if (next.path === (k.path || DEFAULT_PATH) && next.section === (k.section || null)) return;
        status.busy("Saving…");
        try {
          const updated = await M.api.patch(ctx.base + "/tasks/" + encodeURIComponent(c.id), { contract: next });
          status.done();
          onSaved(updated, idOf("contract-section"));
        } catch (err) {
          status.fail("Not saved: ", M.boardEdit ? M.boardEdit.said(err) : err);
        }
      },
    },
    h("label", { for: idOf("contract-path") }, "File"), path,
    h("label", { for: idOf("contract-section") }, "Section (the heading's number)"), section,
    h("button", { type: "submit" }, "Save"));
  }

  M.contractPanel = { panel };
})(window.Maity);
