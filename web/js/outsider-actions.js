// "Add your agent" for an outsider of a public project (docs/api.md §6.1 "What the project allows"
// and "The outsiders' opt-in", §3.1 "An outsider's agent"; tsk-pgcm6wvyxxj4): drawn by
// M.outsiderActions into the slot js/app.js leaves in the dashed tab's head, on every drawing of
// the head (web/context/views.md f461c919). GET …/contribution decides: where `can_join`, a button
// that opens the one join form (js/join.js) as an outsider's join, under the head's row; for
// `limit` and `blocked` the reason in words; for `members_only` (no opt-in, the hub's default) and
// `member` nothing, and nothing when the read fails, a hub without the route (404) included.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // Why the button is missing, where the dashboard says it (§6.1); every other reason says nothing.
  const REASONS = {
    limit: (a) => M.t("outsider.reason.limit", { max: a.agents_max }),
    blocked: () => M.t("outsider.reason.blocked"),
  };

  M.outsiderActions = async (ctx, slot) => {
    let answer;
    try {
      answer = await M.api.get(ctx.base + "/contribution", { quiet: true });
    } catch (err) {
      return; // no button and no error: the hub may not have the route yet
    }
    // A newer drawing of the head has a slot of its own: this answer is not for it.
    const header = document.getElementById("header");
    if (!answer || !header || !header.contains(slot)) return;
    const roles = Array.isArray(answer.outside_roles) ? answer.outside_roles.filter((r) => typeof r === "string") : [];
    if (answer.can_join !== true || !roles.length) {
      if (Object.hasOwn(REASONS, answer.reason || "")) append(slot, h("span", { class: "outsider-reason", role: "note" }, REASONS[answer.reason](answer)));
      return;
    }
    // The join panel under the head's row, so it stays in view on every tab of the project; a
    // drawing of the head (another view) replaces it, as leaving the Agents view does a member's.
    const box = h("div", { class: "outsider-join" });
    const row = slot.parentNode && slot.parentNode.parentNode;
    if (row && row.parentNode) row.parentNode.insertBefore(box, row.nextSibling);
    const button = h("button", { type: "button", class: "primary outsider-add-agent", "aria-expanded": "false" }, M.t("outsider.add_agent"));
    let J = null;
    let mounting = null; // one mount for every click while it is read (as js/page-head.js)
    button.addEventListener("click", async () => {
      if (!J) {
        if (!mounting) {
          mounting = M.join.mount(ctx, {
            outsider: { roles },
            full: () => false, // the hub refuses past the quota (§3.1) and the panel says why
            changed: () => {},
            opened: (yes) => { button.setAttribute("aria-expanded", yes ? "true" : "false"); },
          }).then((made) => { J = made; append(box, J.panel, J.listStatus.el); }).finally(() => { mounting = null; });
        }
        try { await mounting; } catch (err) { return; }
        if (!J) return;
      }
      J.open(button, null);
    });
    append(slot, button);
  };
})(window.Maity);
