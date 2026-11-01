// Role memory (docs/api.md §19.2), a part of Settings → Mine: what the members
// holding a role keep for each other. A member reads and writes their own
// role's; trust owner and admin choose any role; a guest only reads. An entry
// belongs to the role, not its author, and a deleted one keeps its row
// without the text. The hub decides each of these; the page offers only what
// it would allow and says its refusals in words.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const PAGE = 50;

  function said(err) {
    if (err.code === "memory_full") return { message: M.t("rolememory.refused.full") };
    if (err.details && err.details.fields && err.details.fields.text) return { message: M.t("rolememory.refused.text") };
    if (err.details && err.details.fields && err.details.fields.tags) return { message: M.t("rolememory.refused.tags") };
    return err;
  }
  const tagsOf = (value) => value.trim().split(/[\s,]+/).filter(Boolean);
  const authorOf = (by) => (by ? (by.handle || by.member_id || "") + (by.instance ? "#" + by.instance : "") : "");

  async function section(ctx, root) {
    const governs = M.trust.governs(ctx);
    const writes = !M.trust.guest(ctx);
    const heading = h("h3", { id: "role-memory-heading" }, M.t("rolememory.title"));
    const list = h("div");
    const more = h("div");
    const status = M.statusLine();
    let role = ctx.role;
    let rows = [];
    let next = null;
    let seq = 0;

    const shownDeleted = h("input", { id: "role-memory-deleted", type: "checkbox" });
    const query = (cursor) => {
      const p = new URLSearchParams({ store: "role", limit: String(PAGE) });
      if (role) p.set("role", role);
      if (shownDeleted.checked) p.set("deleted", "true");
      if (cursor) p.set("cursor", cursor);
      return ctx.base + "/memory?" + p.toString();
    };

    function draw() {
      append(clear(list), rows.length
        ? h("ul", { class: "role-memory-list" }, rows.map((e) => h("li", { class: e.deleted ? "muted" : null, "data-entry": e.id },
          e.deleted
            ? h("p", null, M.t("rolememory.deleted", { who: authorOf(e.deleted.by), when: formatTime(e.deleted.at) }))
            : h("p", { class: "role-memory-text" }, e.text),
          h("p", { class: "hint" }, M.t("rolememory.by", { who: authorOf(e.by), when: formatTime(e.created_at) }),
            (e.tags || []).length ? " · " + e.tags.join(", ") : ""),
          !e.deleted && writes ? h("button", { type: "button", class: "small", "aria-label": M.t("rolememory.delete.label", { text: e.text.slice(0, 40) }),
            onclick: () => remove(e) }, M.t("rolememory.delete")) : null)))
        : h("p", { class: "muted" }, M.t("rolememory.empty")));
      clear(more);
      if (next) append(more, h("button", { type: "button", onclick: () => load(next) }, M.t("rolememory.more")));
    }

    async function load(cursor) {
      const mine = ++seq;
      status.busy(M.t("rolememory.loading"));
      try {
        const page = await M.api.get(query(cursor));
        if (mine !== seq) return;
        rows = cursor ? rows.concat(page.items) : page.items;
        next = page.next_cursor || null;
        draw();
        status.done();
      } catch (err) {
        if (mine === seq) status.fail(M.t("rolememory.not_read"), err);
      }
    }

    async function remove(entry) {
      if (!window.confirm(M.t("rolememory.delete.confirm"))) return;
      status.busy(M.t("rolememory.deleting"));
      try {
        await M.api.del(ctx.base + "/memory/" + encodeURIComponent(entry.id), {});
      } catch (err) {
        status.fail(M.t("rolememory.not_done"), said(err));
        return;
      }
      await load(null);
    }

    const parts = [heading, h("p", { class: "muted" }, governs ? M.t("rolememory.hint.admin") : M.t("rolememory.hint"))];
    if (governs) {
      const offered = [...new Set(M.trust.ROLES.concat(ctx.members.map((m) => m.role).filter(Boolean)))];
      role = role && offered.includes(role) ? role : offered[0];
      const pick = h("select", { id: "role-memory-role" }, offered.map((r) => h("option", { value: r }, M.trust.roleLabel(r))));
      pick.value = role;
      pick.addEventListener("change", () => { role = pick.value; load(null); });
      parts.push(h("div", { class: "field" }, h("label", { for: "role-memory-role" }, M.t("rolememory.role")), pick));
    }
    if (writes && role) {
      const text = h("textarea", { id: "role-memory-text", rows: "3", required: true });
      const tags = h("input", { id: "role-memory-tags", autocomplete: "off" });
      const form = h("form", { class: "role-memory-add", onsubmit: async (e) => {
        e.preventDefault();
        const said0 = text.value.trim();
        if (!said0) { status.fail(M.t("rolememory.not_done"), { message: M.t("rolememory.text_needed") }); return; }
        status.busy(M.t("rolememory.adding"));
        try {
          const body = { store: "role", text: said0, tags: tagsOf(tags.value) };
          if (governs) body.role = role;
          await M.api.post(ctx.base + "/memory", body);
        } catch (err) {
          status.fail(M.t("rolememory.not_done"), said(err));
          return;
        }
        text.value = "";
        tags.value = "";
        await load(null);
      } },
      h("div", { class: "field" }, h("label", { for: "role-memory-text" }, M.t("rolememory.text")), text),
      h("div", { class: "field" }, h("label", { for: "role-memory-tags" }, M.t("rolememory.tags")), tags,
        h("p", { class: "hint" }, M.t("rolememory.tags.hint"))),
      h("div", { class: "actions" }, h("button", { type: "submit", class: "primary" }, M.t("rolememory.add"))));
      parts.push(form);
    } else if (!writes) {
      parts.push(h("p", { class: "hint" }, M.t("rolememory.guest")));
    }
    shownDeleted.addEventListener("change", () => load(null));
    parts.push(h("label", { class: "check" }, shownDeleted, " ", M.t("rolememory.show_deleted")), status.el, list, more);
    append(root, h("section", { class: "role-memory", "aria-labelledby": "role-memory-heading" }, parts));
    if (role) await load(null); else append(list, h("p", { class: "muted" }, M.t("rolememory.no_role")));
  }

  M.roleMemory = { section };
})(window.Maity);
