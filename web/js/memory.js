// Memory (docs/api.md §19; /<owner>/<slug>/memory): what the agents and
// members have written down, team, role and community, filtered by the hub and
// paged by its cursor, and below it the souls of one's own agents. The hub
// decides who reads what; the page offers only the writes it would allow and
// says its refusals in words. A deleted entry keeps its row without the text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const PAGE = 50;
  const SEARCH_MS = 300;
  const STORES = ["team", "role", "community"];
  const storeLabel = (s) => (s === "team" ? M.t("memory.store.team") : s === "role" ? M.t("memory.store.role") : M.t("memory.store.community"));

  function said(err) {
    // One bad tag comes back as tags.0, too many as tags (hub errors.py).
    const fields = Object.keys((err.details && err.details.fields) || {});
    if (err.code === "memory_full") return { message: M.t("memory.refused.full") };
    if (fields.includes("text")) return { message: M.t("memory.refused.text") };
    if (fields.includes("markdown")) return { message: M.t("memory.refused.soul") };
    if (fields.some((k) => k === "tags" || k.startsWith("tags."))) return { message: M.t("memory.refused.tags") };
    return err;
  }
  const tagsOf = (value) => value.trim().toLowerCase().split(/[\s,]+/).filter(Boolean);
  const authorOf = (by) => (by ? (by.handle || by.member_id || by.id || "") + (by.instance ? "#" + by.instance : "") : "");

  // What may be deleted, as the hub rules it (§19.2).
  function mayDelete(ctx, e) {
    if (e.deleted || M.trust.guest(ctx) || ctx.me.kind !== "human") return false;
    if (e.store === "community") return ctx.canAdmin;
    if (e.store === "role") return true;
    const team = ctx.members.find((m) => m.id === e.member_id);
    return ctx.canAdmin || !!(team && team.owner_id === ctx.me.id);
  }

  function entriesPart(ctx) {
    const box = h("section", { class: "memory-entries", "aria-labelledby": "memory-entries-title" });
    const list = h("div");
    const more = h("div");
    const status = M.statusLine();
    const governs = M.trust.governs(ctx);
    const roles = [...new Set(M.trust.ROLES.concat(ctx.members.map((m) => m.role).filter(Boolean)))];
    const field = (id, label, control) => h("div", { class: "field" }, h("label", { for: id }, label), control);

    const store = h("select", { id: "memory-store" }, h("option", { value: "" }, M.t("memory.store.all")),
      STORES.map((s) => h("option", { value: s }, storeLabel(s))));
    const agents = ctx.members.filter((m) => m.kind === "agent" && (ctx.canAdmin || m.owner_id === ctx.me.id));
    const team = h("select", { id: "memory-team" }, h("option", { value: "" }, M.t("memory.team.all")),
      agents.map((m) => h("option", { value: m.id }, m.display_name)));
    const role = h("select", { id: "memory-role" }, roles.map((r) => h("option", { value: r }, M.trust.roleLabel(r))));
    role.value = ctx.role && roles.includes(ctx.role) ? ctx.role : roles[0];
    const q = h("input", { id: "memory-q", type: "search", maxlength: "200", autocomplete: "off" });
    const deleted = h("input", { id: "memory-deleted", type: "checkbox" });
    const teamField = field("memory-team", M.t("memory.team"), team);
    const roleField = field("memory-role", M.t("memory.role"), role);

    let rows = [];
    let next = null;
    let seq = 0;

    const query = (cursor) => {
      const p = new URLSearchParams({ limit: String(PAGE) });
      if (store.value) p.set("store", store.value);
      if (store.value === "team" && team.value) p.set("member_id", team.value);
      if (store.value === "role" && governs) p.set("role", role.value);
      if (q.value.trim()) p.set("q", q.value.trim());
      if (deleted.checked) p.set("deleted", "true");
      if (cursor) p.set("cursor", cursor);
      return ctx.base + "/memory?" + p.toString();
    };

    const whereOf = (e) => (e.store === "team" ? M.t("memory.where.team", { name: ctx.nameOf(e.member_id) })
      : e.store === "role" ? M.t("memory.where.role", { role: M.trust.roleLabel(e.role) }) : M.t("memory.where.community"));

    function row(e) {
      const li = h("li", { class: e.deleted ? "muted" : null, "data-entry": e.id });
      const actions = h("div", { class: "memory-entry-actions" });
      function deleteForm() {
        const id = "memory-reason-" + e.id;
        const reason = h("input", { id, maxlength: "500", autocomplete: "off" });
        append(clear(actions), h("form", { class: "memory-delete", onsubmit: async (ev) => {
          ev.preventDefault();
          status.busy(M.t("memory.deleting"));
          try {
            await M.api.del(ctx.base + "/memory/" + encodeURIComponent(e.id), reason.value.trim() ? { reason: reason.value.trim() } : {});
          } catch (err) {
            status.fail(M.t("memory.not_done"), said(err));
            return;
          }
          await load(null);
        } },
        field(id, M.t("memory.delete.reason"), reason),
        h("p", { class: "hint" }, M.t("memory.delete.hint")),
        h("div", { class: "actions" }, h("button", { type: "submit", class: "small" }, M.t("memory.delete.confirm")),
          h("button", { type: "button", class: "small", onclick: () => { clear(actions); offer(); } }, M.t("memory.delete.cancel")))));
        reason.focus();
      }
      function offer() {
        if (mayDelete(ctx, e)) append(actions, h("button", { type: "button", class: "small", "aria-label": M.t("memory.delete.label", { text: e.text.slice(0, 40) }), onclick: deleteForm }, M.t("memory.delete")));
      }
      offer();
      append(li,
        e.deleted
          ? h("p", null, e.deleted.reason ? M.t("memory.deleted.because", { who: authorOf(e.deleted.by), when: formatTime(e.deleted.at), reason: e.deleted.reason })
            : M.t("memory.deleted", { who: authorOf(e.deleted.by), when: formatTime(e.deleted.at) }))
          : h("p", { class: "memory-text" }, e.text),
        h("p", { class: "hint" }, M.t("memory.by", { where: whereOf(e), who: authorOf(e.by), when: formatTime(e.created_at) }),
          (e.tags || []).map((t) => [" ", h("button", { type: "button", class: "small memory-tag", "aria-label": M.t("memory.tag.label", { tag: t }),
            onclick: () => { q.value = t; load(null); } }, t)])),
        actions);
      return li;
    }

    function draw() {
      append(clear(list), rows.length ? h("ul", { class: "memory-list" }, rows.map(row)) : h("p", { class: "muted" }, M.t("memory.empty")));
      clear(more);
      if (next) append(more, h("button", { type: "button", onclick: () => load(next) }, M.t("memory.more")));
    }

    // A newer filter wins over an older answer still on its way.
    async function load(cursor) {
      const mine = ++seq;
      status.busy(M.t("memory.loading"));
      try {
        const page = await M.api.get(query(cursor));
        if (mine !== seq) return;
        rows = cursor ? rows.concat(page.items) : page.items;
        next = page.next_cursor || null;
        draw();
        status.done();
      } catch (err) {
        if (mine !== seq) return;
        rows = []; next = null; clear(list); clear(more);
        status.fail(M.t("memory.not_read"), err);
      }
    }

    function showFilters() {
      teamField.hidden = store.value !== "team";
      roleField.hidden = store.value !== "role" || !governs;
    }
    const changed = () => { showFilters(); load(null); };
    [store, team, role, deleted].forEach((el) => el.addEventListener("change", changed));
    let timer = null;
    q.addEventListener("input", () => { window.clearTimeout(timer); timer = window.setTimeout(() => load(null), SEARCH_MS); });
    showFilters();

    // A human writes to a role's memory and, with project:admin, the community's; a team's only its agents.
    function addForm() {
      if (M.trust.guest(ctx) || ctx.me.kind !== "human") return null;
      const targets = (ctx.role || governs ? ["role"] : []).concat(ctx.canAdmin ? ["community"] : []);
      if (!targets.length) return null;
      const where = h("select", { id: "memory-add-store" }, targets.map((s) => h("option", { value: s }, storeLabel(s))));
      const addRole = h("select", { id: "memory-add-role" }, roles.map((r) => h("option", { value: r }, M.trust.roleLabel(r))));
      addRole.value = role.value;
      const roleBox = field("memory-add-role", M.t("memory.role"), addRole);
      const show = () => { roleBox.hidden = where.value !== "role" || !governs; };
      where.addEventListener("change", show);
      show();
      const text = h("textarea", { id: "memory-add-text", rows: "3", required: true });
      const tags = h("input", { id: "memory-add-tags", autocomplete: "off" });
      const add = h("button", { type: "submit", class: "primary" }, M.t("memory.add"));
      return h("form", { class: "memory-add", onsubmit: async (e) => {
        e.preventDefault();
        const said0 = text.value.trim();
        if (!said0) { status.fail(M.t("memory.not_done"), { message: M.t("memory.text_needed") }); return; }
        status.busy(M.t("memory.adding"));
        add.disabled = true;
        try {
          const body = { store: where.value, text: said0, tags: tagsOf(tags.value) };
          if (where.value === "role" && governs) body.role = addRole.value;
          await M.api.post(ctx.base + "/memory", body);
        } catch (err) {
          status.fail(M.t("memory.not_done"), said(err));
          return;
        } finally {
          add.disabled = false;
        }
        text.value = "";
        tags.value = "";
        await load(null);
      } },
      h("h4", null, M.t("memory.add.title")),
      field("memory-add-store", M.t("memory.add.store"), where), roleBox,
      field("memory-add-text", M.t("memory.text"), text),
      h("div", { class: "field" }, h("label", { for: "memory-add-tags" }, M.t("memory.tags")), tags, h("p", { class: "hint" }, M.t("memory.tags.hint"))),
      h("div", { class: "actions" }, add));
    }

    append(box, h("h3", { id: "memory-entries-title" }, M.t("memory.entries")),
      h("p", { class: "muted" }, M.t("memory.entries.hint")),
      h("form", { class: "memory-filter", role: "search", onsubmit: (e) => { e.preventDefault(); load(null); } },
        field("memory-store", M.t("memory.store"), store), teamField, roleField,
        field("memory-q", M.t("memory.search"), q)),
      h("label", { class: "check" }, deleted, " ", M.t("memory.show_deleted")),
      status.el, list, more, addForm());
    return { box, load };
  }

  // A soul belongs to the agent's owner (§19.1): read and written here, one agent at a time.
  function soulRow(member) {
    const id = "soul-" + member.id;
    const path = "/agents/" + encodeURIComponent(member.id) + "/soul";
    const status = M.statusLine();
    const text = h("textarea", { id, rows: "8" });
    const facts = h("p", { class: "hint" });
    const versions = h("ul", { class: "soul-versions" });
    const show = (soul) => {
      text.value = soul.markdown;
      append(clear(facts), soul.version
        ? M.t("memory.soul.version", { version: soul.version, who: authorOf(soul.by), when: formatTime(soul.updated_at) })
        : M.t("memory.soul.none"));
    };
    const save = h("button", { type: "submit", class: "primary" }, M.t("memory.soul.save"));
    const form = h("form", { class: "soul-form", onsubmit: async (e) => {
      e.preventDefault();
      save.disabled = true;
      status.busy(M.t("memory.soul.saving"));
      try {
        show(await M.api.put(path, { markdown: text.value }));
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("memory.soul.saved")));
      } catch (err) {
        status.fail(M.t("memory.not_done"), said(err));
      } finally {
        save.disabled = false;
      }
    } },
    h("div", { class: "field" }, h("label", { for: id }, M.t("memory.soul.text", { name: member.display_name })), text),
    facts, h("div", { class: "actions" }, save), status.el);
    const earlier = h("details", { class: "soul-earlier" }, h("summary", null, M.t("memory.soul.versions")), versions);
    earlier.addEventListener("toggle", async () => {
      if (!earlier.open) return;
      try {
        const page = await M.api.get(path + "/versions");
        append(clear(versions), page.items.map((v) => h("li", null,
          h("p", { class: "hint" }, M.t("memory.soul.version", { version: v.version, who: authorOf(v.by), when: formatTime(v.at) })),
          h("pre", { class: "memory-text" }, v.markdown))));
      } catch (err) {
        append(clear(versions), h("li", { class: "send-status failed" }, M.t("memory.not_read"), err.message));
      }
    });
    // Read when opened: every agent's text at once is a cost nobody asked for.
    let read = false;
    const box = h("details", { class: "soul", "data-soul": member.id }, h("summary", null, member.display_name), form, earlier);
    box.addEventListener("toggle", async () => {
      if (!box.open || read) return;
      read = true;
      status.busy(M.t("memory.loading"));
      try {
        show(await M.api.get(path));
        status.done();
      } catch (err) {
        read = false;
        status.fail(M.t("memory.not_read"), err);
      }
    });
    return box;
  }

  M.views.memory = async function (ctx, root) {
    const entries = entriesPart(ctx);
    const own = ctx.me.kind === "human" ? ctx.members.filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id && !m.removed_at) : [];
    append(root, h("h2", null, M.t("memory.title")), entries.box,
      own.length ? h("section", { class: "memory-souls", "aria-labelledby": "memory-souls-title" },
        h("h3", { id: "memory-souls-title" }, M.t("memory.souls")),
        h("p", { class: "muted" }, M.t("memory.souls.hint")),
        own.map(soulRow)) : null);
    await entries.load(null);
  };
})(window.Maity);
