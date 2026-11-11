// Report something to the instance's admins (docs/api.md §16.8, tsk-7ze5w6ymf7bw): one form for
// every place that offers it. A person or an agent, a project, a card or a message, named the way
// the reader can name it: a member by the member id the project's read gives, a stranger by the
// public name the page shows (§16.8, "The id a stranger sends"). The form asks a reason (§16.8's
// six) and an optional text of at most 2 KiB, and is one POST /reports. Sent, it says so and links
// Your account → Reports (GET /me/reports), the only place the reporter learns what became of it.
// Signed out, the button is a link to the sign-in that comes back with the form open (`?report`).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const REASONS = ["spam", "abuse", "illegal", "prompt_injection", "impersonation", "other"];
  const REASON_WORDS = {
    spam: () => M.t("reports.reason.spam"),
    abuse: () => M.t("reports.reason.abuse"),
    illegal: () => M.t("reports.reason.illegal"),
    prompt_injection: () => M.t("reports.reason.prompt_injection"),
    impersonation: () => M.t("reports.reason.impersonation"),
    other: () => M.t("reports.reason.other"),
  };
  // §16.8: `text` at most 2 KiB, counted as the hub counts it, in UTF-8 bytes.
  const TEXT_MAX = 2048;
  const bytes = (s) => {
    let n = 0;
    for (const ch of s) { const c = ch.codePointAt(0); n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; }
    return n;
  };
  // The button's accessible name says what is reported.
  const LABELS = {
    person: () => M.t("report.label.person"),
    agent: () => M.t("report.label.agent"),
    project: () => M.t("report.label.project"),
    card: () => M.t("report.label.card"),
    message: () => M.t("report.label.message"),
  };
  let forms = 0;

  // What a page asked for with `?report` (a public page's link through the sign-in): its form opens.
  const asked = () => M.route.current().query.has("report");

  // target: {type, id, project?} as POST /reports takes it; what: person, agent, project, card or
  // message (the button's name). opts.signedOut: the page's path, for a link to the sign-in instead.
  // Returns {button, slot}: the caller puts the button where its view keeps its actions and the slot
  // where the form may open.
  function control(target, what, opts) {
    const o = opts || {};
    const slot = h("div", { class: "report-slot" });
    const label = (LABELS[what] || LABELS.person)();
    if (o.signedOut) {
      const back = o.signedOut + (o.signedOut.includes("?") ? "&" : "?") + "report";
      return { button: h("a", { class: "button small report-open", href: M.withNext("/login", back), "aria-label": label }, M.t("report.sign_in")), slot };
    }
    const n = ++forms;
    const button = h("button", { type: "button", class: "small report-open", "aria-expanded": "false", "aria-label": label }, M.t("report.open"));
    const close = (refocus) => {
      clear(slot);
      button.hidden = false;
      button.setAttribute("aria-expanded", "false");
      button.removeAttribute("aria-controls");
      if (refocus) button.focus();
    };
    const open = () => {
      const f = form(n, target, label, { cancel: () => close(true), sent: (said) => { close(false); append(slot, said); said.focus(); } });
      append(clear(slot), f.el);
      button.hidden = true;
      button.setAttribute("aria-expanded", "true");
      button.setAttribute("aria-controls", f.el.id);
      f.first.focus();
    };
    button.addEventListener("click", open);
    return { button, slot, open };
  }

  function form(n, target, label, hooks) {
    const id = (x) => "report-" + n + "-" + x;
    const reason = h("select", { id: id("reason"), required: true },
      h("option", { value: "" }, M.t("report.reason.choose")),
      REASONS.map((r) => h("option", { value: r }, REASON_WORDS[r]())));
    const text = h("textarea", { id: id("text"), rows: "4", "aria-describedby": id("text-hint") + " " + id("text-error") });
    const textError = h("p", { class: "field-error", id: id("text-error"), role: "alert" });
    const reasonError = h("p", { class: "field-error", id: id("reason-error"), role: "alert" });
    reason.setAttribute("aria-describedby", id("reason-error"));
    const status = M.statusLine();
    const send = h("button", { type: "submit", class: "primary" }, M.t("report.send"));
    const cancel = h("button", { type: "button", onclick: () => hooks.cancel() }, M.t("report.cancel"));
    const el = h("form", { class: "report-form inline-form", id: id("form"), "aria-labelledby": id("title"), novalidate: true },
      h("h3", { id: id("title") }, label),
      h("p", { class: "hint" }, M.t("report.hint")),
      h("label", { for: id("reason") }, M.t("report.reason")), reason, reasonError,
      h("label", { for: id("text") }, M.t("report.text")), text,
      h("p", { class: "hint", id: id("text-hint") }, M.t("report.text.hint")), textError,
      h("div", { class: "actions" }, send, " ", cancel), status.el);
    let busy = false;
    el.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (busy) return;
      reasonError.textContent = ""; textError.textContent = "";
      const said = text.value.trim();
      if (!reason.value) { reasonError.textContent = M.t("report.reason.needed"); reason.focus(); return; }
      if (bytes(said) > TEXT_MAX) { textError.textContent = M.t("report.text.too_long"); text.focus(); return; }
      busy = true;
      send.disabled = true;
      status.busy(M.t("report.sending"));
      const body = { target, reason: reason.value };
      if (said) body.text = said;
      try {
        await M.api.post("/reports", body);
      } catch (err) {
        busy = false;
        send.disabled = false;
        status.fail(M.t("report.failed"), err.code ? { message: M.t("report.refusal", { reason: err.message, code: err.code }) } : err);
        return;
      }
      hooks.sent(h("p", { class: "ok report-sent", role: "status", tabindex: "-1" },
        M.tn("report.sent", { link: h("a", { href: "/account/reports" }, M.t("report.sent.link")) })));
    });
    return { el, first: reason };
  }

  // Your account → Reports (/account/reports, GET /me/reports): one's own reports, newest first,
  // with what became of each: open, resolved with its action, or expired. The target as the hub
  // names it now, or its neutral word once its page is gone (§16.8).
  const STATUS_WORDS = {
    open: () => M.t("report.mine.status.open"),
    resolved: () => M.t("report.mine.status.resolved"),
    expired: () => M.t("report.mine.status.expired"),
  };
  const ACTION_WORDS = {
    dismiss: () => M.t("report.mine.action.dismiss"),
    hide: () => M.t("report.mine.action.hide"),
    remove: () => M.t("report.mine.action.remove"),
    suspend: () => M.t("report.mine.action.suspend"),
  };
  const NEUTRAL = {
    person: () => M.t("report.mine.target.person"),
    agent: () => M.t("report.mine.target.agent"),
    project: () => M.t("report.mine.target.project"),
    card: () => M.t("report.mine.target.card"),
  };
  const targetWords = (t) => {
    if (!t) return "";
    if (t.id === null || t.id === undefined) return Object.hasOwn(NEUTRAL, t.label) ? NEUTRAL[t.label]() : String(t.label || "");
    if (t.type === "message") return M.t("report.mine.target.message", { seq: String(t.id), project: t.project || "" });
    return t.project ? t.project + " · " + t.id : String(t.id);
  };

  async function mine(root) {
    const list = h("ul", { class: "report-list" });
    const status = M.statusLine();
    const more = h("div", { class: "report-more" });
    append(root, h("h3", null, M.t("report.mine.title")), h("p", { class: "hint" }, M.t("report.mine.hint")), status.el, list, more);
    let cursor = null;
    const row = (r) => h("li", { class: "report-item", "data-report": r.id },
      h("span", { class: "report-target" }, targetWords(r.target)),
      h("span", { class: "muted" }, " · ", Object.hasOwn(REASON_WORDS, r.reason) ? REASON_WORDS[r.reason]() : r.reason, " · ", M.dom.formatTime(r.created_at)),
      h("span", { class: "report-state" }, " · ",
        Object.hasOwn(STATUS_WORDS, r.status) ? STATUS_WORDS[r.status]() : r.status,
        r.action ? [": ", Object.hasOwn(ACTION_WORDS, r.action) ? ACTION_WORDS[r.action]() : r.action] : null));
    async function load() {
      status.busy(M.t("report.mine.reading"));
      let page;
      try {
        page = await M.api.get("/me/reports?limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
      } catch (err) {
        status.fail(M.t("report.mine.failed"), err);
        return;
      }
      status.done();
      if (!cursor && !page.items.length) append(list, h("li", { class: "muted empty" }, M.t("report.mine.none")));
      append(list, page.items.map(row));
      cursor = page.next_cursor;
      clear(more);
      if (cursor) append(more, h("button", { type: "button", class: "small", onclick: () => load() }, M.t("report.mine.older")));
    }
    await load();
  }

  M.report = { control, asked, mine, REASONS };
})(window.Maity);
