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
  // The hub's reasons a section is not shown, in words from the catalog;
  // any other code as it comes.
  const WHY = {
    unset: () => M.t("contract.why.unset"),
    not_found_on_forge: () => M.t("contract.why.not_found_on_forge"),
    not_found_in_file: () => M.t("contract.why.not_found_in_file"),
    ambiguous_in_file: () => M.t("contract.why.ambiguous_in_file"),
    too_large: () => M.t("contract.why.too_large"),
    not_text: () => M.t("contract.why.not_text"),
    probe_not_configured: () => M.t("contract.why.probe_not_configured"),
    probe_unavailable: () => M.t("contract.why.probe_unavailable"),
  };

  // Cards whose panel was open when their place was saved: the board draws
  // them anew from the hub's answer, and the panel opens again with them.
  const reopen = new Set();

  const mayEdit = (ctx, c) => M.trust.governs(ctx) || c.created_by === ctx.me.id
    || !!(c.claim && c.claim.holder === ctx.me.id);

  // onSaved(updated, focusId): the board redraws the card from the hub's answer.
  function panel(ctx, c, onSaved) {
    const k = c.contract;
    const where = (k.path || DEFAULT_PATH) + (k.section ? " § " + k.section : "");
    const body = h("div", { class: "contract-body", "aria-live": "polite" });
    const status = M.statusLine();
    let loaded = false;
    // Refresh is a small text button in the line that says what was read
    // (the designer's pass part 3), not a row of its own.
    const refresh = () => h("button", { type: "button", class: "link-button contract-refresh", onclick: () => read() }, M.t("contract.refresh"));

    async function read() {
      loaded = true;
      append(clear(body), h("p", { class: "muted" }, M.t("contract.reading")));
      let s;
      try {
        s = await M.api.get(ctx.base + "/tasks/" + encodeURIComponent(c.id) + "/contract");
      } catch (err) {
        const fields = (err.details && err.details.fields) || {};
        const code = fields["contract.section"] || fields["contract.path"] || err.code || "error";
        append(clear(body), h("p", { class: "flag contract-unresolved" },
          M.tn("contract.unresolved", { where: h("code", null, where), why: Object.hasOwn(WHY, code) ? WHY[code]() : err.message || code, code: h("code", null, code) }),
          " ", refresh()));
        return;
      }
      const url = safeUrl(s.url);
      append(clear(body),
        h("p", { class: "muted contract-meta" }, M.tn("contract.meta.at", { path: s.path, ref: h("code", null, String(s.ref || "").slice(0, 7)) }),
          " · ", M.t("contract.meta.read", { ago: formatAgo(s.fetched_at, M.api.now()) }),
          url ? [" · ", h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, M.t("contract.meta.file"))] : null,
          " · ", refresh()),
        h("div", { class: "md contract-text" }, M.markdown(s.text)),
        s.truncated ? h("p", { class: "flag" }, url
          ? M.tn("contract.truncated.link", { link: h("a", { href: url, rel: "noopener noreferrer", target: "_blank" }, M.t("contract.truncated.open")) })
          : M.t("contract.truncated")) : null);
    }

    // Where the section is read from changes rarely: its form waits behind
    // Change source, so the card shows the text, not an editor.
    const place = mayEdit(ctx, c) ? placeForm(ctx, c, onSaved, status) : null;
    const change = place ? h("button", { type: "button", class: "link-button contract-change", "aria-expanded": "false",
      onclick: () => {
        place.hidden = !place.hidden;
        change.setAttribute("aria-expanded", String(!place.hidden));
        if (!place.hidden) place.querySelector("input").focus();
      } }, M.t("contract.change")) : null;
    if (place) place.hidden = true;
    const box = h("details", { class: "contract-section" },
      h("summary", null, M.tn("contract.summary", { where: h("code", null, where) })),
      body,
      change ? h("p", { class: "contract-change-row" }, change) : null,
      place,
      status.el);
    box.addEventListener("toggle", () => { if (box.open && !loaded && k.section) read(); });
    if (!k.section) append(body, h("p", { class: "muted" }, M.t("contract.none")));
    // Without a section the form is what there is to do: open at once.
    if (place && !k.section) { place.hidden = false; change.setAttribute("aria-expanded", "true"); }
    if (reopen.delete(c.id)) {
      box.open = true;
      if (k.section) read();
    }
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
        status.busy(M.t("contract.saving"));
        try {
          const updated = await M.api.patch(ctx.base + "/tasks/" + encodeURIComponent(c.id), { contract: next });
          status.done();
          reopen.add(c.id);
          onSaved(updated, idOf("contract-section"));
        } catch (err) {
          status.fail(M.t("contract.not_saved"), M.boardEdit ? M.boardEdit.said(err) : err);
        }
      },
    },
    h("label", { for: idOf("contract-path") }, M.t("contract.file")), path,
    h("label", { for: idOf("contract-section") }, M.t("contract.section")), section,
    h("button", { type: "submit" }, M.t("contract.save")));
  }

  M.contractPanel = { panel };
})(window.Maity);
