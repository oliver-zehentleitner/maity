// Abuse reports, the Reports section of /admin (docs/api.md §16.8;
// js/instance-admin.js shows it to the instance admin only): the reports,
// open ones first, filtered by status and type and paged by the hub's
// cursor; one opened shows what was reported (the snapshot, the one
// content an instance admin reads) and is resolved with dismiss, hide,
// remove or suspend and a note. A resolved report is resolved again to
// replace its action; dismiss lifts a hold. The reporter's text and the
// snapshot are untrusted: shown as text, never as markup or a link.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const PAGE = 50;
  const STATUSES = [["open", () => M.t("reports.status.open")], ["resolved", () => M.t("reports.status.resolved")], ["all", () => M.t("reports.status.all")]];
  const TYPES = [["", () => M.t("reports.type.all")], ["profile", () => M.t("reports.type.profile")], ["project", () => M.t("reports.type.project")],
    ["message", () => M.t("reports.type.message")], ["card", () => M.t("reports.type.card")]];
  const REASONS = { spam: () => M.t("reports.reason.spam"), abuse: () => M.t("reports.reason.abuse"), illegal: () => M.t("reports.reason.illegal"),
    prompt_injection: () => M.t("reports.reason.prompt_injection"), impersonation: () => M.t("reports.reason.impersonation"),
    other: () => M.t("reports.reason.other") };
  // What each action does, said before it is chosen (§16.8 "The actions").
  const ACTIONS = [
    ["dismiss", () => M.t("reports.action.dismiss"), () => M.t("reports.action.dismiss.hint")],
    ["hide", () => M.t("reports.action.hide"), () => M.t("reports.action.hide.hint")],
    ["remove", () => M.t("reports.action.remove"), () => M.t("reports.action.remove.hint")],
    ["suspend", () => M.t("reports.action.suspend"), () => M.t("reports.action.suspend.hint")],
  ];
  const words = (list, key) => { const found = list.find(([k]) => k === key); return found ? found[1]() : key; };
  const reasonOf = (r) => (Object.hasOwn(REASONS, r) ? REASONS[r]() : r);

  // The target in words: its type and what names it (a project's full name
  // as it is now, a message or a card with its project).
  function targetText(t) {
    if (!t) return "";
    const kind = words(TYPES, t.type);
    return t.project ? M.t("reports.target.in_project", { kind, id: t.id, project: t.project }) : M.t("reports.target", { kind, id: t.id });
  }
  function stateText(r) {
    if (r.status === "open") return M.t("reports.state.open");
    if (r.status === "expired") return M.t("reports.state.expired");
    return M.t("reports.state.resolved", { action: words(ACTIONS, r.action) });
  }

  // The snapshot as the reporter could read it (§16.8), every field as text.
  function snapshot(s) {
    if (!s) return h("p", { class: "muted" }, M.t("reports.snapshot.none"));
    const rows = [];
    const add = (label, value) => { if (value !== null && value !== undefined && value !== "") rows.push(h("dt", null, label), h("dd", null, String(value))); };
    add(M.t("reports.field.type"), words(TYPES, s.type));
    add(M.t("reports.field.project"), s.project || s.full_name);
    add(M.t("reports.field.name"), s.display_name || s.name);
    add(M.t("reports.field.handle"), s.handle ? "@" + s.handle : null);
    add(M.t("reports.field.repository"), s.repository_url);
    add(M.t("reports.field.title"), s.title);
    add(M.t("reports.field.author"), s.author && s.author.handle ? "@" + s.author.handle : null);
    add(M.t("reports.field.owner"), s.owner && s.owner.handle ? "@" + s.owner.handle : null);
    add(M.t("reports.field.at"), s.at ? formatTime(s.at) : null);
    const body = s.redacted ? M.t("reports.snapshot.redacted") : s.body;
    return [h("dl", { class: "facts report-snapshot" }, rows),
      body ? h("pre", { class: "report-body" }, body) : null];
  }

  // `openId0`: a report to open at once, from /admin/reports/<id> (a report_open notification).
  async function section(ctx, root, openId0) {
    const status = M.statusLine();
    const list = h("div", { class: "reports-box" });
    const detail = h("div", { class: "report-detail" });
    const more = h("div", { class: "actions" });
    const statusPick = h("select", { id: "reports-status" }, STATUSES.map(([v, l]) => h("option", { value: v }, l())));
    statusPick.value = "open";
    const typePick = h("select", { id: "reports-type" }, TYPES.map(([v, l]) => h("option", { value: v }, l())));
    typePick.value = "";
    let items = [];
    let next = null;
    let seq = 0;
    let shownFilter = null;
    let openId = null;

    const filterNow = () => ({ status: statusPick.value, type: typePick.value });
    const query = (filter, cursor) => {
      const p = new URLSearchParams();
      p.set("status", filter.status);
      if (filter.type) p.set("type", filter.type);
      p.set("limit", String(PAGE));
      if (cursor) p.set("cursor", cursor);
      return "/admin/reports?" + p.toString();
    };

    function draw() {
      clear(list);
      if (!items.length) { append(list, h("p", { class: "muted" }, M.t("reports.none"))); }
      else {
        append(list, h("ul", { class: "reports-list" }, items.map((r) => h("li", { class: "report-item report-" + r.status, "data-report": r.id },
          h("button", { type: "button", class: "small", "aria-expanded": openId === r.id ? "true" : "false", "aria-controls": "report-detail",
            onclick: () => open(r.id) }, M.t("reports.open_one", { reason: reasonOf(r.reason) })),
          " ", h("span", null, targetText(r.target)),
          h("span", { class: "muted" }, " · " + stateText(r) + " · " + formatTime(r.created_at)
            + (r.reporter && r.reporter.handle ? " · @" + r.reporter.handle : ""))))));
      }
      clear(more);
      if (next) append(more, h("button", { type: "button", onclick: () => load(shownFilter, next) }, M.t("reports.more")));
    }

    async function load(filter, cursor) {
      const mine = ++seq;
      status.busy(M.t("reports.reading"));
      try {
        const page = await M.api.get(query(filter, cursor));
        if (mine !== seq) return;
        items = cursor ? items.concat(page.items) : page.items;
        next = page.next_cursor;
        shownFilter = filter;
        draw();
        status.done();
      } catch (err) {
        if (mine !== seq) return;
        status.fail(M.t("reports.unread"), err);
      }
    }

    async function open(id) {
      openId = id;
      draw();
      clear(detail);
      const st = M.statusLine();
      append(detail, st.el);
      let r;
      try {
        r = await M.api.get("/admin/reports/" + encodeURIComponent(id));
      } catch (err) {
        st.fail(M.t("reports.unread_one"), err);
        return;
      }
      if (openId !== id) return;
      clear(detail);
      const pick = h("select", { id: "report-action" }, ACTIONS.map(([v, l]) => h("option", { value: v }, l())));
      pick.value = r.action || "dismiss";
      const hint = h("p", { class: "hint", id: "report-action-hint" });
      const showHint = () => { hint.textContent = words(ACTIONS.map(([k, , w]) => [k, w]), pick.value); };
      pick.setAttribute("aria-describedby", "report-action-hint");
      pick.addEventListener("change", showHint);
      showHint();
      const note = h("textarea", { id: "report-note", rows: "3", maxlength: "2048" }, r.note || "");
      const save = h("button", { type: "submit" }, r.status === "open" ? M.t("reports.resolve") : M.t("reports.resolve_again"));
      const done = M.statusLine();
      const form = r.status === "expired" ? h("p", { class: "muted" }, M.t("reports.expired_note")) : h("form", {
        class: "inline-form report-resolve",
        onsubmit: async (e) => {
          e.preventDefault();
          const action = pick.value;
          if (action === "suspend" && !window.confirm(M.t("reports.suspend_confirm", { target: targetText(r.target) }))) return;
          const body = { action };
          if (note.value.trim()) body.note = note.value.trim();
          save.disabled = true;
          done.busy(M.t("reports.resolving"));
          try {
            await M.api.post("/admin/reports/" + encodeURIComponent(r.id) + "/resolve", body);
          } catch (err) {
            done.fail(M.t("reports.not_resolved"), err);
            save.disabled = false;
            return;
          }
          await load(shownFilter || filterNow(), null);
          await open(r.id);
          append(detail, h("p", { class: "ok", role: "status" }, M.t("reports.resolved", { action: words(ACTIONS, action) })));
        },
      }, h("label", { for: "report-action" }, M.t("reports.action")), pick, hint,
      h("label", { for: "report-note" }, M.t("reports.note")), note, save, done.el);
      append(detail, h("section", { class: "panel report-open", id: "report-detail", "aria-labelledby": "report-detail-title" },
        h("h3", { id: "report-detail-title", tabindex: "-1" }, M.t("reports.detail_title", { reason: reasonOf(r.reason), target: targetText(r.target) })),
        h("p", { class: "muted" }, stateText(r) + " · " + formatTime(r.created_at)
          + (r.reporter && r.reporter.handle ? " · " + M.t("reports.by", { handle: r.reporter.handle }) : "")
          + (r.resolved_at ? " · " + M.t("reports.resolved_at", { at: formatTime(r.resolved_at) }) : "")),
        r.text ? [h("h4", null, M.t("reports.reporter_text")), h("pre", { class: "report-body" }, r.text)] : null,
        h("h4", null, M.t("reports.snapshot")), snapshot(r.snapshot),
        r.note && r.status !== "open" ? h("p", null, M.t("reports.note_shown", { note: r.note })) : null,
        form));
    }

    statusPick.addEventListener("change", () => { openId = null; clear(detail); load(filterNow(), null); });
    typePick.addEventListener("change", () => { openId = null; clear(detail); load(filterNow(), null); });

    append(root, h("h2", null, M.t("reports.title")),
      h("p", { class: "muted" }, M.t("reports.intro")),
      h("div", { class: "users-filter" },
        h("label", { for: "reports-status" }, M.t("reports.show")), statusPick,
        h("label", { for: "reports-type" }, M.t("reports.of_type")), typePick),
      status.el, list, more, detail);
    await load(filterNow(), null);
    if (openId0) await open(openId0);
  }

  M.adminReports = { section };
})(window.Maity);
