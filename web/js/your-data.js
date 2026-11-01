// Your data (docs/api.md §2.9) on the account: the export of what is about
// the human or written by them, and the deletion of the account in two
// steps (a request here, the confirming link in the mail). Both are
// sensitive calls: js/step-up.js asks for the password or a code first.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // The hub's refusals of a deletion request, in words.
  const REFUSALS = {
    namespace_owner: () => M.t("data.refused.namespace_owner"),
    last_instance_admin: () => M.t("data.refused.last_instance_admin"),
    mail_not_configured: () => M.t("data.refused.mail_not_configured"),
    address_unverified: () => M.t("data.refused.address_unverified"),
  };
  function said(err) {
    if (err.code === "invalid" && err.details && err.details.fields && err.details.fields.confirm) return { message: M.t("data.refused.not_handle") };
    if (err.code === "rate_limited") return { message: M.t("data.refused.rate_limited") };
    // §6.26: an organisation always has an owner.
    if (err.code === "org_last_owner") {
      const orgs = ((err.details && err.details.orgs) || []).map((o) => "@" + o);
      return { message: orgs.length
        ? M.t("data.refused.org_last_owner", { orgs: M.fmt.list(orgs) })
        : M.t("data.refused.org_last_owner.unnamed") };
    }
    return Object.hasOwn(REFUSALS, err.code) ? { message: REFUSALS[err.code]() } : err;
  }

  // The file as the hub names it (§2.9), saved through a link the page clicks.
  function save(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    // A blob: address is this page's own and made just above; h() rightly takes no such href.
    const a = h("a", { download: name });
    a.setAttribute("href", url);
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportPart(ctx, ask) {
    const status = M.statusLine();
    const go = h("button", { type: "button" }, M.t("data.export.button"));
    go.addEventListener("click", async () => {
      go.disabled = true;
      status.busy(M.t("data.export.busy"));
      try {
        const doc = await M.stepUp.run(() => M.api.get("/me/export"), ask, M.t("data.export.step_up"));
        const day = String(doc.exported_at || new Date().toISOString()).slice(0, 10);
        M.yourData.save("maity-export-" + ctx.me.handle + "-" + day + ".json", JSON.stringify(doc, null, 2));
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("data.export.saved")));
      } catch (err) {
        if (err.code === "cancelled") status.done();
        else status.fail(M.t("data.export.failed"), said(err));
      } finally {
        go.disabled = false;
      }
    });
    return h("div", { class: "data-export" },
      h("h4", null, M.t("data.export.title")),
      h("p", { class: "hint" }, M.t("data.export.hint")),
      go, status.el);
  }

  function deletionPart(ctx, ask, redraw) {
    const status = M.statusLine();
    const pending = ctx.me.deletion;
    if (pending) {
      const withdraw = h("button", { type: "button" }, M.t("data.delete.withdraw"));
      withdraw.addEventListener("click", async () => {
        withdraw.disabled = true;
        status.busy(M.t("data.delete.withdrawing"));
        try {
          await M.api.del("/me/deletion");
          ctx.me.deletion = null;
          redraw(M.t("data.delete.withdrawn"));
        } catch (err) {
          withdraw.disabled = false;
          status.fail(M.t("data.delete.not_withdrawn"), err);
        }
      });
      return h("div", { class: "data-deletion pending" },
        h("h4", null, M.t("data.delete.title")),
        h("p", { class: "flag", role: "status" }, M.t("data.delete.pending", { requested: formatTime(pending.requested_at), expires: formatTime(pending.expires_at) })),
        withdraw, status.el);
    }
    const id = "delete-account-confirm";
    const typed = h("input", { id, autocomplete: "off", spellcheck: "false", placeholder: "@" + ctx.me.handle });
    const go = h("button", { type: "submit", class: "danger" }, M.t("data.delete.button"));
    // One request at a time, for the handle as typed now: the field is locked
    // while it runs (a password or code asked meanwhile included).
    let busy = false;
    const confirmed = () => typed.value.trim().replace(/^@/, "") === ctx.me.handle;
    const settle = () => { go.disabled = busy || !confirmed(); };
    settle();
    typed.addEventListener("input", settle);
    const form = h("form", {
      class: "account-delete inline-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (busy || !confirmed()) return;
        busy = true;
        typed.disabled = true;
        settle();
        status.busy(M.t("data.delete.asking"));
        try {
          const answer = await M.stepUp.run(() => M.api.post("/me/deletion", { confirm: ctx.me.handle }), ask, M.t("data.delete.step_up"));
          ctx.me.deletion = (answer && answer.deletion) || null;
          redraw(M.t("data.delete.mailed"));
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          if (err.code === "cancelled") status.done();
          else status.fail(M.t("data.delete.not_asked"), said(err));
        }
      },
    }, h("label", { for: id }, M.t("data.delete.confirm", { handle: "@" + ctx.me.handle })), typed, go, status.el);
    return h("div", { class: "data-deletion" },
      h("h4", null, M.t("data.delete.title")),
      h("p", { class: "hint" }, M.t("data.delete.hint")),
      h("p", { class: "hint" }, M.t("data.delete.steps")),
      form);
  }

  // The section for a human; null for an agent.
  async function section(ctx) {
    if (ctx.me.kind !== "human") return null;
    const heading = h("h3", { id: "your-data-heading", tabindex: "-1" }, M.t("data.title"));
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const note = h("div");
    const body = h("div");
    const draw = (words) => {
      append(clear(body),
        exportPart(ctx, ask),
        deletionPart(ctx, ask, draw));
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
    };
    draw();
    return { el: h("section", { class: "your-data", "aria-labelledby": "your-data-heading" }, heading, note, ask, body), heading };
  }

  M.yourData = { section, save };
})(window.Maity);
