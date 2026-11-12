// The hub's maintenance window (docs/api.md §16.12): a banner above every page from the
// moment a window exists, the public and the sign-in pages included, in the viewer's time
// zone and language; while it runs, a full page instead of the view, with End maintenance
// now for the instance admin. The window is read from GET /maintenance (anyone, no
// sign-in), from /me (maintenance) and from every 503 `maintenance` (js/api.js).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  // How old a read may be before a drawing asks the hub again; while the full page stands,
  // how often it asks whether the window changed or ended early.
  const FRESH_MS = 60000;
  const FULL_POLL_MS = 30000;
  // A boundary further away than this is looked at again then, not waited for in one timer.
  const MAX_WAIT_MS = 3600000;

  let known = null;
  let readAt = 0;
  let boundary = null;
  let poll = null;
  // Whether the page drawn now was drawn for a running window (the full page, or the
  // admin's window alone): set by fullPage and aware(), cleared when a drawing starts.
  let showingFull = false;
  // js/app.js's render: called when the window starts or ends under an open page.
  let redraw = null;

  // The window as the hub's clock has it now: its state from `from` and `until`, null once over.
  function current() {
    if (!known) return null;
    const now = M.api.now();
    if (Date.parse(known.until) <= now) return null;
    return Object.assign({}, known, { state: Date.parse(known.from) <= now ? "running" : "upcoming" });
  }
  const running = () => { const w = current(); return !!w && w.state === "running"; };

  // A window learnt from the hub (or null): the banner follows, and the page redraws when
  // the window starts or ends under it, or runs under a page drawn without it. `quiet`: a
  // drawing that reads the window itself (/me) and decides on its own.
  function know(value, quiet) {
    const was = running();
    known = value && value.from && value.until ? { from: value.from, until: value.until, text: value.text || "" } : null;
    readAt = Date.now();
    drawBanner();
    schedule();
    if (!quiet && redraw && (running() !== was || (running() && !showingFull))) redraw();
  }

  // Before a drawing: GET /maintenance unless a read is recent. A failed read keeps what is known.
  async function fresh() {
    // A recent read answers from what is known; the banner is drawn again all the same, since a
    // drawing after a change of language must not keep it in the old one.
    if (readAt && Date.now() - readAt < FRESH_MS) { drawBanner(); return current(); }
    try {
      const answer = await M.api.get("/maintenance");
      known = answer.window ? { from: answer.window.from, until: answer.window.until, text: answer.window.text } : null;
      readAt = Date.now();
    } catch (err) {
      // A hub that does not answer says so on the page itself.
    }
    drawBanner();
    schedule();
    return current();
  }

  // One timer for the next boundary (the start or the end), so the page changes when the
  // window does, without asking the hub for it.
  function schedule() {
    if (boundary) window.clearTimeout(boundary);
    boundary = null;
    const w = current();
    if (!w) return;
    const at = Date.parse(w.state === "upcoming" ? w.from : w.until) - M.api.now();
    boundary = window.setTimeout(() => {
      boundary = null;
      drawBanner();
      if (at <= MAX_WAIT_MS && redraw) redraw();
      else schedule();
    }, Math.max(0, Math.min(at, MAX_WAIT_MS)) + 500);
  }

  // `from` with its date, `until` with its date only when it is another day.
  function span(w) {
    const sameDay = M.fmt.day(w.from) === M.fmt.day(w.until);
    return { from: M.fmt.dateTime(w.from), until: sameDay ? M.fmt.time(w.until) : M.fmt.dateTime(w.until) };
  }

  // Above the header, outside what a drawing replaces.
  function drawBanner() {
    const header = document.getElementById("header");
    if (!header || !header.parentNode) return;
    const parent = header.parentNode;
    const old = Array.from(parent.childNodes).find((n) => n.id === "maintenance-banner");
    const w = current();
    if (!w) { if (old) parent.removeChild(old); return; }
    const words = M.t("maintenance.banner", Object.assign(span(w), { text: w.text }));
    const banner = h("p", { id: "maintenance-banner", class: "maintenance-banner" + (w.state === "running" ? " running" : ""), role: "status" }, words);
    // The same words can change state: an upcoming window starts under an open page.
    if (old && old.textContent === words && old.className === banner.className) return;
    if (old) parent.replaceChild(banner, old);
    else parent.insertBefore(banner, header);
  }

  // The full page while a window runs. `me`: the signed-in caller (null without a session):
  // the instance admin gets End maintenance now and the way to change the window, a visitor
  // the way to sign in, since the sign-in stays open (§16.12).
  function fullPage(main, header, opts) {
    const w = current();
    if (!w) return false;
    const me = opts.me || null;
    showingFull = true;
    append(clear(header), h("div", { class: "bar" }, opts.brand, opts.tools || null));
    const status = M.statusLine();
    const admin = !!(me && me.instance_admin);
    const end = admin ? h("button", { type: "button", class: "primary" }, M.t("maintenance.end")) : null;
    if (end) {
      end.addEventListener("click", async () => {
        if (end.disabled) return;
        end.disabled = true;
        status.busy(M.t("maintenance.ending"));
        try {
          await M.api.post("/admin/maintenance/end");
          status.done();
          know(null);
        } catch (err) {
          end.disabled = false;
          status.fail(M.t("maintenance.end_failed"), err);
        }
      });
    }
    append(clear(main), h("section", { class: "view view-maintenance maintenance-page" },
      h("h2", null, M.t("maintenance.title")),
      h("p", null, M.t("maintenance.back_at", { until: M.fmt.dateTime(w.until) })),
      w.text ? h("p", { class: "message-body maintenance-text" }, w.text) : null,
      admin ? h("div", { class: "maintenance-actions" }, end, h("a", { href: "/admin/maintenance" }, M.t("maintenance.change"))) : null,
      admin ? status.el : null,
      !me && opts.signIn ? h("p", null, h("a", { href: "/login" }, M.t("maintenance.sign_in"))) : null,
      h("p", { class: "muted" }, M.t("maintenance.reloads"))));
    document.title = M.t("maintenance.title") + " · Maity";
    // Asks the hub now and then: a window ended early or moved shows at once.
    if (poll) window.clearInterval(poll);
    poll = window.setInterval(() => {
      if (!showingFull) { window.clearInterval(poll); poll = null; return; }
      readAt = 0;
      fresh().then(() => { if (!running() && redraw) redraw(); });
    }, FULL_POLL_MS);
    return true;
  }

  M.maintenance = {
    current,
    running,
    know,
    fresh,
    fullPage,
    drawBanner,
    // js/app.js: every drawing starts here; the full page is the drawing's to set again.
    drawing: () => { showingFull = false; },
    // A page drawn for the running window other than the full page (the admin's window alone).
    aware: () => { showingFull = true; },
    onChange: (fn) => { redraw = fn; },
  };
  // A 503 `maintenance` anywhere (js/api.js): the window from its details.
  M.onMaintenance = (details) => {
    if (details && details.from && details.until) know({ from: details.from, until: details.until, text: details.text });
  };
})(window.Maity);
