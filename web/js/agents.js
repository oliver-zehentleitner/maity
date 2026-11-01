// An agent's parts that Members shows in its row (tsk-7v2snhk002ak): its
// credentials as id, dates and a revoke button, never their value; its
// briefing; the words a pause says.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  // How a credential was last used (docs/api.md §10): what signing:
  // required would refuse is the bearer kind. A kind the hub adds later reads as its own word.
  function lastUsed(c) {
    const ago = formatAgo(c.last_used_at);
    if (!c.last_used_via) return M.t("agentparts.credential.last_used", { ago });
    if (c.last_used_via === "signed") return M.t("agentparts.credential.last_used_signed", { ago });
    if (c.last_used_via === "bearer") return M.t("agentparts.credential.last_used_bearer", { ago });
    return M.t("agentparts.credential.last_used_via", { ago, via: c.last_used_via });
  }

  // revoked(): what follows a revocation; the whole view drawn anew without one.
  function credentials(ctx, m, list, revoked) {
    const box = h("div", { class: "credentials" }, h("h4", { class: "credentials-title" }, M.t("agentparts.credentials")));
    if (!list.items.length) {
      append(box, h("p", { class: "muted" }, M.t("agentparts.credentials.none")));
      return box;
    }
    const status = M.statusLine();
    // Active ones first, as the hub lists them; revoked ones stay visible.
    // The text flows as one line that wraps; the button stays beside it.
    append(box, h("ul", null, list.items.map((c) => h("li", { class: c.revoked_at ? "revoked" : "" },
      h("span", { class: "credential-text" },
        h("code", null, c.id),
        " " + (c.client || "") + " · " + M.t("agentparts.credential.created", { time: formatTime(c.created_at) }),
        c.revoked_at
          ? h("span", { class: "muted" }, " · ", c.revoked_reason
            ? M.tn("agentparts.credential.revoked_reason", { time: formatTime(c.revoked_at), who: M.dom.memberRef(ctx, c.revoked_by), reason: c.revoked_reason })
            : M.tn("agentparts.credential.revoked", { time: formatTime(c.revoked_at), who: M.dom.memberRef(ctx, c.revoked_by) }))
          : (c.resumed_at
            ? h("span", null, " · " + lastUsed(c))
            : h("span", { class: "never" }, " · " + M.t("agentparts.credential.never_resumed")))),
      c.revoked_at
        ? null
        : [
          h("button", {
            type: "button",
            class: "danger",
            onclick: async (e) => {
              if (!window.confirm(M.t("agentparts.credential.revoke_confirm", { id: c.id, name: m.display_name }))) return;
              e.target.disabled = true;
              status.busy(M.t("agentparts.credential.revoking"));
              try {
                await M.api.post(ctx.base + "/credentials/" + encodeURIComponent(c.id) + "/revoke", {});
                if (revoked) revoked(); else ctx.refresh();
              } catch (err) {
                e.target.disabled = false;
                status.fail(M.t("agentparts.credential.not_revoked"), err);
              }
            },
          }, M.t("agentparts.credential.revoke")),
        ]))), status.el);
    return box;
  }

  // The briefing (docs/api.md §6.2): shown to members:admin, edited in
  // place. The view re-reads presence in place, so an open editor stays.
  const BRIEFING_CHARS = 16 * 1024;
  function briefingControl(ctx, m) {
    const box = h("div", { class: "briefing" });
    const status = M.statusLine();
    const show = () => {
      M.dom.clear(box);
      append(box, h("h4", null, M.t("agentparts.briefing")),
        m.briefing ? h("p", { class: "pre" }, m.briefing) : h("p", { class: "muted" }, M.t("agentparts.briefing.none")),
        // Who wrote the current text, where the hub says (docs/api.md §6.2).
        m.briefing && m.briefing_by ? h("p", { class: "muted" }, m.briefing_version
          ? M.t("agentparts.briefing.set_by_version", { handle: m.briefing_by.handle, version: String(m.briefing_version) })
          : M.t("agentparts.briefing.set_by", { handle: m.briefing_by.handle })) : null,
        h("button", { type: "button", class: "small", onclick: edit }, m.briefing ? M.t("agentparts.briefing.edit") : M.t("agentparts.briefing.write")),
        status.el);
    };
    box.edit = () => edit();
    box.hasText = () => !!m.briefing;
    const edit = () => {
      const id = "briefing-" + m.id;
      const text = M.dom.sendOnCtrlEnter(h("textarea", { id, rows: "6" }));
      text.value = m.briefing || "";
      const saveButton = h("button", { type: "submit" }, M.t("agentparts.briefing.save"));
      const save = async (e) => {
        e.preventDefault();
        if (saveButton.disabled) return;
        // Markdown keeps its spaces: only line ends are made the same; a
        // briefing of nothing but space is no briefing.
        const value = text.value.replace(/\r\n?/g, "\n");
        if ([...value].length > BRIEFING_CHARS) {
          status.fail(M.t("agentparts.briefing.not_saved"), { message: M.t("agentparts.briefing.too_long", { max: BRIEFING_CHARS }) });
          return;
        }
        status.busy(M.t("agentparts.briefing.saving"));
        // Held while it is saved: one PATCH per submission, by click or Ctrl+Enter.
        saveButton.disabled = true;
        try {
          const updated = await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { briefing: value.trim() ? value : null });
          m.briefing = updated && "briefing" in updated ? updated.briefing : (value.trim() ? value : null);
          ["briefing_by", "briefing_version", "briefing_updated_at"].forEach((k) => { if (updated && k in updated) m[k] = updated[k]; });
          status.done();
          show();
        } catch (err) {
          status.fail(M.t("agentparts.briefing.not_saved"), err);
        } finally {
          saveButton.disabled = false;
        }
      };
      M.dom.clear(box);
      append(box, h("form", { class: "briefing-form", onsubmit: save },
        h("label", { for: id }, M.t("agentparts.briefing.label", { max: BRIEFING_CHARS, keys: M.dom.SEND_KEYS })), text,
        h("p", { class: "hint" }, M.t("agentparts.briefing.hint")),
        h("div", { class: "row" },
          h("button", { type: "button", onclick: show }, M.t("agentparts.briefing.cancel")),
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
  // Getters: a language set after the page loads still applies.
  // What a pause by a human does (docs/api.md §5.3), in one line.
  M.pauseWords = {
    get effect() { return M.t("agentparts.pause.effect"); },
    get paused() { return M.t("agentparts.pause.paused"); },
  };
  M.agentParts = { credentials, briefingControl, loadCredentials };
})(window.Maity);
