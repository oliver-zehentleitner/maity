// The instance admin's maintenance window (docs/api.md §16.12): announce one, change it,
// cancel it before it starts or end it early, and every change made, newest first.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const PATH = "/admin/maintenance";
  const TEXT_MAX = 500;
  const REASONS = {
    from_after_until: () => M.t("admin.maintenance.reason.from_after_until"),
    until_past: () => M.t("admin.maintenance.reason.until_past"),
    too_long: () => M.t("admin.maintenance.reason.too_long"),
    too_short: () => M.t("admin.maintenance.reason.too_short"),
    running: () => M.t("admin.maintenance.reason.running"),
    invalid: () => M.t("admin.maintenance.reason.invalid"),
  };
  const ACTIONS = {
    created: () => M.t("admin.maintenance.action.created"),
    changed: () => M.t("admin.maintenance.action.changed"),
    cancelled: () => M.t("admin.maintenance.action.cancelled"),
    ended: () => M.t("admin.maintenance.action.ended"),
  };
  const FIELDS = { from: () => M.t("admin.maintenance.from"), until: () => M.t("admin.maintenance.until"), text: () => M.t("admin.maintenance.text") };
  function fieldError(err) {
    const errors = err.details && err.details.fields;
    if (!errors) return err;
    return { message: Object.entries(errors).map(([field, reason]) => (Object.hasOwn(FIELDS, field) ? FIELDS[field]() : field) + ": "
      + (Object.hasOwn(REASONS, reason) ? REASONS[reason]() : reason)).join("; ") };
  }
  // A datetime-local field holds the time in the account's zone, the one the times are shown in
  // (docs/api.md §5.1); the hub keeps UTC.
  const toField = (iso) => M.fmt.toWall(iso);
  function fromField(value) {
    const d = M.fmt.fromWall(value);
    return d ? d.toISOString().replace(/\.\d{3}Z$/, "Z") : null;
  }
  const zone = () => M.i18n.zone();

  async function section(ctx, root) {
    const status = M.statusLine();
    append(root, h("h2", null, M.t("admin.maintenance.title")), h("p", { class: "hint" }, M.t("admin.maintenance.intro")), status.el);
    let current;
    try { current = (await M.api.get(PATH)).window; }
    catch (err) { status.fail(M.t("admin.maintenance.read_failed"), err); return; }
    const state = h("div", { class: "maintenance-state" });
    const formSlot = h("div");
    const changes = h("div", { class: "maintenance-changes" });
    append(root, state, formSlot, changes);

    // The window the hub answered: the banner and the rest of the page follow it.
    function took(found) {
      current = found;
      M.maintenance.know(found);
      draw();
      readChanges();
    }

    function draw() {
      clear(state);
      clear(formSlot);
      const running = !!current && current.state === "running";
      if (!current) append(state, h("p", { class: "muted" }, M.t("admin.maintenance.none")));
      else {
        const times = { from: M.fmt.dateTime(current.from), until: M.fmt.dateTime(current.until) };
        append(state, h("p", null, running ? M.t("admin.maintenance.running", times) : M.t("admin.maintenance.upcoming", times)),
        h("p", { class: "message-body" }, current.text),
        current.updated_at ? h("p", { class: "muted" }, M.t("admin.maintenance.changed_at", { at: formatTime(current.updated_at) })) : null);
        const act = h("button", { type: "button", class: running ? "primary" : null }, running ? M.t("maintenance.end") : M.t("admin.maintenance.cancel"));
        act.addEventListener("click", async () => {
          if (act.disabled) return;
          act.disabled = true;
          status.busy(running ? M.t("maintenance.ending") : M.t("admin.maintenance.cancelling"));
          try {
            const answer = running ? await M.api.post(PATH + "/end") : await M.api.del(PATH);
            status.done();
            took(answer.window);
          } catch (err) {
            act.disabled = false;
            status.fail(running ? M.t("maintenance.end_failed") : M.t("admin.maintenance.cancel_failed"), err);
            // A window that started or ended meanwhile (409): what the hub has now.
            if (err.status === 409) M.api.get(PATH).then((a) => took(a.window), () => {});
          }
        });
        append(state, h("div", { class: "maintenance-actions" }, act));
      }
      const from = h("input", { id: "maintenance-from", type: "datetime-local", required: true });
      from.disabled = running;
      const until = h("input", { id: "maintenance-until", type: "datetime-local", required: true });
      const text = h("textarea", { id: "maintenance-text", rows: "3", maxlength: String(TEXT_MAX), required: true });
      if (current) { from.value = toField(current.from); until.value = toField(current.until); text.value = current.text; }
      const save = h("button", { type: "submit" }, current ? M.t("admin.maintenance.save") : M.t("admin.maintenance.announce"));
      const form = h("form", { class: "inline-form admin-maintenance-form" },
        h("h3", null, current ? M.t("admin.maintenance.change") : M.t("admin.maintenance.new")),
        h("label", { for: from.id }, M.t("admin.maintenance.from")), from,
        h("label", { for: until.id }, M.t("admin.maintenance.until")), until,
        h("p", { class: "hint" }, zone() ? M.t("admin.maintenance.zone", { zone: zone() }) : M.t("admin.maintenance.zone_local")),
        running ? h("p", { class: "hint" }, M.t("admin.maintenance.from_kept")) : null,
        h("label", { for: text.id }, M.t("admin.maintenance.text")), text,
        h("p", { class: "hint" }, M.t("admin.maintenance.text_hint", { max: TEXT_MAX })),
        save);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (save.disabled) return;
        // A running window keeps its `from` as the hub has it, to the second.
        const body = { from: running ? current.from : fromField(from.value), until: fromField(until.value), text: text.value.trim() };
        if (!body.from || !body.until) { status.fail(M.t("admin.maintenance.not_saved"), { message: M.t("admin.maintenance.times_needed") }); return; }
        save.disabled = true;
        status.busy(M.t("admin.maintenance.saving"));
        try {
          const answer = await M.api.put(PATH, body);
          status.done();
          took(answer.window);
          append(status.el, h("span", { class: "ok" }, M.t("admin.maintenance.saved")));
        } catch (err) {
          status.fail(M.t("admin.maintenance.not_saved"), fieldError(err));
        } finally {
          save.disabled = false;
        }
      });
      append(formSlot, form);
    }

    // Every change, newest first, a page at a time (§1.4).
    let cursor = null;
    async function readChanges(more) {
      if (!more) cursor = null;
      let page;
      try {
        page = await M.api.get(PATH + "/changes?limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
      } catch (err) {
        const failed = M.statusLine();
        failed.fail(M.t("admin.maintenance.changes_failed"), err);
        append(clear(changes), failed.el);
        return;
      }
      if (!more) append(clear(changes), h("h3", null, M.t("admin.maintenance.changes")), h("ul", { class: "maintenance-change-list" }));
      const list = changes.querySelector("ul");
      const old = changes.querySelector("button.more");
      if (old) old.parentNode.removeChild(old);
      page.items.forEach((c) => append(list, h("li", null,
        h("strong", null, Object.hasOwn(ACTIONS, c.action) ? ACTIONS[c.action]() : c.action), " ",
        h("span", { class: "muted" }, formatTime(c.at)), " · ",
        M.t("admin.maintenance.change_line", { from: M.fmt.dateTime(c.window.from), until: M.fmt.dateTime(c.window.until), text: c.window.text }))));
      if (!page.items.length && !more) append(list, h("li", { class: "muted" }, M.t("admin.maintenance.no_changes")));
      cursor = page.next_cursor;
      if (cursor) append(changes, h("button", { type: "button", class: "small more", onclick: () => readChanges(true) }, M.t("admin.maintenance.more")));
    }

    draw();
    await readChanges();
  }

  M.adminMaintenance = { section };
})(window.Maity);
