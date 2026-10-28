// An agent's parts that Members shows in its row (tsk-7v2snhk002ak): its
// credentials as id, dates and a revoke button, never their value; its
// briefing; the words a pause says. #/<owner>/<slug>/agents leads to Members.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  // How a credential was last used (docs/api.md §10): what signing:
  // required would refuse is the bearer kind.
  const VIA = { signed: "(signed)", bearer: "(bearer token)" };

  // revoked(): what follows a revocation; the whole view drawn anew without one.
  function credentials(ctx, m, list, revoked) {
    const box = h("div", { class: "credentials" }, h("h4", { class: "credentials-title" }, "Credentials"));
    if (!list.items.length) {
      append(box, h("p", { class: "muted" }, "None."));
      return box;
    }
    const status = M.statusLine();
    // Active ones first, as the hub lists them; revoked ones stay visible.
    // The text flows as one line that wraps; the button stays beside it.
    append(box, h("ul", null, list.items.map((c) => h("li", { class: c.revoked_at ? "revoked" : "" },
      h("span", { class: "credential-text" },
        h("code", null, c.id),
        " " + (c.client || "") + " · created " + formatTime(c.created_at),
        c.revoked_at
          ? h("span", { class: "muted" }, " · revoked " + formatTime(c.revoked_at) + " by ", M.dom.memberRef(ctx, c.revoked_by),
            c.revoked_reason ? " (" + c.revoked_reason + ")" : "")
          : (c.resumed_at
            ? h("span", null, " · last used " + formatAgo(c.last_used_at)
              + (c.last_used_via ? " " + (VIA[c.last_used_via] || "(" + c.last_used_via + ")") : ""))
            : h("span", { class: "never" }, " · never resumed"))),
      c.revoked_at
        ? null
        : [
          h("button", {
            type: "button",
            class: "danger",
            onclick: async (e) => {
              if (!window.confirm("Revoke " + c.id + " of " + m.display_name + "? Its session loses access at once.")) return;
              e.target.disabled = true;
              status.busy("Revoking…");
              try {
                await M.api.post(ctx.base + "/credentials/" + encodeURIComponent(c.id) + "/revoke", {});
                if (revoked) revoked(); else ctx.refresh();
              } catch (err) {
                e.target.disabled = false;
                status.fail("Not revoked: ", err);
              }
            },
          }, "Revoke"),
        ]))), status.el);
    return box;
  }

  // What a pause by a human does (docs/api.md §5.3), in one line.
  const PAUSE_EFFECT = "A pause tells the agent at once and refuses it new work (claims, new cards); "
    + "it can still checkpoint, report, give a card back and talk to you.";
  const PAUSED_EFFECT = "The agent was told at once and gets no new work (claims, new cards); "
    + "it can still checkpoint, report, give a card back and talk to you.";

  // The briefing (docs/api.md §6.2): shown to members:admin, edited in
  // place. The view re-reads presence in place, so an open editor stays.
  const BRIEFING_CHARS = 16 * 1024;
  function briefingControl(ctx, m) {
    const box = h("div", { class: "briefing" });
    const status = M.statusLine();
    const show = () => {
      M.dom.clear(box);
      append(box, h("h4", null, "Briefing"),
        m.briefing ? h("p", { class: "pre" }, m.briefing) : h("p", { class: "muted" }, "No briefing yet."),
        // Who wrote the current text, where the hub says (docs/api.md §6.2).
        m.briefing && m.briefing_by ? h("p", { class: "muted" }, "Set by @" + m.briefing_by.handle
          + (m.briefing_version ? " · version " + m.briefing_version : "")) : null,
        h("button", { type: "button", class: "small", onclick: edit }, m.briefing ? "Edit briefing" : "Write a briefing"),
        status.el);
    };
    box.edit = () => edit();
    box.hasText = () => !!m.briefing;
    const edit = () => {
      const id = "briefing-" + m.id;
      const text = M.dom.sendOnCtrlEnter(h("textarea", { id, rows: "6" }));
      text.value = m.briefing || "";
      const saveButton = h("button", { type: "submit" }, "Save briefing");
      const save = async (e) => {
        e.preventDefault();
        if (saveButton.disabled) return;
        // Markdown keeps its spaces: only line ends are made the same; a
        // briefing of nothing but space is no briefing.
        const value = text.value.replace(/\r\n?/g, "\n");
        if ([...value].length > BRIEFING_CHARS) {
          status.fail("Not saved: ", { message: "the briefing is longer than 16,384 characters" });
          return;
        }
        status.busy("Saving…");
        // Held while it is saved: one PATCH per submission, by click or Ctrl+Enter.
        saveButton.disabled = true;
        try {
          const updated = await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { briefing: value.trim() ? value : null });
          m.briefing = updated && "briefing" in updated ? updated.briefing : (value.trim() ? value : null);
          ["briefing_by", "briefing_version", "briefing_updated_at"].forEach((k) => { if (updated && k in updated) m[k] = updated[k]; });
          status.done();
          show();
        } catch (err) {
          status.fail("Not saved: ", err);
        } finally {
          saveButton.disabled = false;
        }
      };
      M.dom.clear(box);
      append(box, h("form", { class: "briefing-form", onsubmit: save },
        h("label", { for: id }, "Briefing (Markdown, at most 16,384 characters; " + M.dom.SEND_KEYS + " saves)"), text,
        h("p", { class: "hint" }, "The agent reads it at its next resume."),
        h("div", { class: "row" },
          h("button", { type: "button", onclick: show }, "Cancel"),
          saveButton),
        status.el));
      text.focus();
    };
    show();
    return box;
  }

  // One failing credentials call costs that card its credentials section,
  // not the view.
  function loadCredentials(ctx, m) {
    return M.api.getAll(ctx.base + "/members/" + encodeURIComponent(m.id) + "/credentials")
      .then((list) => ({ list }), (error) => ({ error }));
  }

  // Shared with the Members view, whose manage row holds an agent's
  // credentials and briefing too (tsk-7v2snhk002ak).
  M.pauseWords = { effect: PAUSE_EFFECT, paused: PAUSED_EFFECT };
  M.agentParts = { credentials, briefingControl, loadCredentials };

  // #/<owner>/<slug>/agents, from before the agents moved into Members
  // (tsk-7v2snhk002ak): Members, with the join panel open where it was asked.
  M.views.agents = async function (ctx, root, args) {
    const join = !!(args && args[0] === "join");
    if (window.history && window.history.replaceState) window.history.replaceState(null, "", join ? ctx.link("members", "join") : ctx.link("members"));
    await M.views.members(ctx, root, join ? ["join"] : []);
  };
})(window.Maity);
