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
    namespace_owner: "a project in your namespace is still open: archive it, or transfer it to someone else (Project settings), first",
    last_instance_admin: "you are this hub's last instance admin: make someone else an instance admin first",
    mail_not_configured: "this hub sends no mail, and the deletion is confirmed by a mail",
    address_unverified: "your address is not verified, and the deletion is confirmed by a mail to it",
  };
  function said(err) {
    if (err.code === "invalid" && err.details && err.details.fields && err.details.fields.confirm) return { message: "that is not your handle" };
    if (err.code === "rate_limited") return { message: "an export at most every 10 minutes; try again later" };
    return REFUSALS[err.code] ? { message: REFUSALS[err.code] } : err;
  }

  // The file as the hub names it (§2.9), saved through a link the page clicks.
  function save(name, text) {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = h("a", { href: url, download: name });
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportPart(ctx, ask) {
    const status = M.statusLine();
    const go = h("button", { type: "button" }, "Export my data");
    go.addEventListener("click", async () => {
      go.disabled = true;
      status.busy("Preparing your export…");
      try {
        const doc = await M.stepUp.run(() => M.api.get("/me/export"), ask);
        const day = String(doc.exported_at || new Date().toISOString()).slice(0, 10);
        M.yourData.save("maity-export-" + ctx.me.handle + "-" + day + ".json", JSON.stringify(doc, null, 2));
        status.done();
        append(status.el, h("span", { class: "ok" }, "Your export was saved."));
      } catch (err) {
        if (err.code === "cancelled") status.done();
        else status.fail("Not exported: ", said(err));
      } finally {
        go.disabled = false;
      }
    });
    return h("div", { class: "data-export" },
      h("h4", null, "Export"),
      h("p", { class: "hint" }, "One JSON file with your account, your sessions and memberships, your agents and runners, and what you wrote in every project: "
        + "messages, requests and answers, cards, reports and notes. Another person's text appears only as the title of what yours belongs to. "
        + "At most once every 10 minutes."),
      go, status.el);
  }

  function deletionPart(ctx, ask, redraw) {
    const status = M.statusLine();
    const pending = ctx.me.deletion;
    if (pending) {
      const withdraw = h("button", { type: "button" }, "Withdraw the deletion");
      withdraw.addEventListener("click", async () => {
        withdraw.disabled = true;
        status.busy("Withdrawing…");
        try {
          await M.api.del("/me/deletion");
          ctx.me.deletion = null;
          redraw("The deletion was withdrawn; your account stays.");
        } catch (err) {
          withdraw.disabled = false;
          status.fail("Not withdrawn: ", err);
        }
      });
      return h("div", { class: "data-deletion pending" },
        h("h4", null, "Delete my account"),
        h("p", { class: "flag", role: "status" }, "You asked to delete your account on " + formatTime(pending.requested_at)
          + ". It is deleted only when you follow the link in the mail we sent to your verified address, before " + formatTime(pending.expires_at) + "."),
        withdraw, status.el);
    }
    const id = "delete-account-confirm";
    const typed = h("input", { id, autocomplete: "off", spellcheck: "false", placeholder: "@" + ctx.me.handle });
    const go = h("button", { type: "submit", class: "danger" }, "Delete my account");
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
        status.busy("Asking…");
        try {
          const answer = await M.stepUp.run(() => M.api.post("/me/deletion", { confirm: ctx.me.handle }), ask);
          ctx.me.deletion = (answer && answer.deletion) || null;
          redraw("We sent a mail to your verified address. Your account is deleted only when you follow its link.");
        } catch (err) {
          busy = false;
          typed.disabled = false;
          settle();
          if (err.code === "cancelled") status.done();
          else status.fail("Not asked: ", said(err));
        }
      },
    }, h("label", { for: id }, "Type @" + ctx.me.handle + " to delete your account"), typed, go, status.el);
    return h("div", { class: "data-deletion" },
      h("h4", null, "Delete my account"),
      h("p", { class: "hint" }, "Deleting ends every session and membership, deletes your agents and runners, and removes your name, addresses and picture. "
        + "What you wrote stays in its projects, shown as from \"Deleted account\": redact what you want gone first, and export your data. "
        + "Your handle is never given to anyone else. This cannot be undone."),
      h("p", { class: "hint" }, "It takes two steps: we send a mail to your verified address, and only its link (valid 24 hours) deletes the account."),
      form);
  }

  // The section for a human; null for an agent.
  function section(ctx) {
    if (ctx.me.kind !== "human") return null;
    const heading = h("h3", { id: "your-data-heading", tabindex: "-1" }, "Your data");
    const ask = h("div", { class: "step-up-slot" });
    ask.hidden = true;
    const note = h("div");
    const body = h("div");
    const draw = (words) => {
      append(clear(body), exportPart(ctx, ask), deletionPart(ctx, ask, draw));
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
    };
    draw();
    return { el: h("section", { class: "your-data", "aria-labelledby": "your-data-heading" }, heading, note, ask, body), heading };
  }

  M.yourData = { section, save };
})(window.Maity);
