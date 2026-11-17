// The head of a page with tabs, built once for the project's Agents page (js/agents-page.js) and
// its Team page (js/members.js), as the maintainer asked on 2026-11-12 (tsk-vkyp71qp95n9): the
// heading with the page's buttons at the right end, the tab bar under them, each the page's full
// width; and the Join an agent button both pages offer, which opens the one join form (js/join.js)
// with its part for a start on a runner (js/placements.js).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // items: [key, href, label] (a falsy item is left out); the one whose key is `chosen` is marked.
  M.tabBar = (cls, label, items, chosen) => h("nav", { class: "view-tabs " + cls, "aria-label": label },
    items.filter(Boolean).map(([key, href, text]) =>
      h("a", { href, class: "view-tab", "aria-current": key === chosen ? "page" : null }, text)));

  // spec: { title, titleId, note (a node beside the heading), actions: [nodes], tabs (M.tabBar) }.
  M.pageHead = (spec) => h("div", { class: "page-head" },
    h("div", { class: "toolbar page-head-bar" }, h("h2", { id: spec.titleId || null }, spec.title), spec.note || null,
      h("div", { class: "page-head-actions" }, (spec.actions || []).filter(Boolean))),
    spec.tabs || null);

  // Who may bring an agent here (§3.1, tsk-zd2ch05rk7s1): members:admin, or a human member
  // without it, who adds agents of their own while the project allows it, up to
  // member_agents_max. Both pages' Join an agent follow it.
  M.bringing = (ctx) => {
    const policy = ctx.project.policy || {};
    const memberAdds = !ctx.canAdmin && !M.trust.guest(ctx) && policy.member_agents !== "off";
    return { memberAdds, mayAdd: (ctx.canAdmin || memberAdds) && !!M.join, policy };
  };

  // Join an agent: one button that opens the one join form (js/join.js) in `slot`, under the head,
  // so on every tab of the page; its last part starts the agent on a runner instead
  // (js/placements.js, tsk-hdczmsq2r431; once a menu of two ways, tsk-vkyp71qp95n9). opts (all
  // optional):
  // - any(opener): opens the join panel itself, where the page has one wired to its own lists
  //   (the Agents tab: the seats, the count, the limit). Without it the button mounts a panel of
  //   its own on first use (the Team page, the other tabs).
  // - anyDisabled(): a reason the way is closed now (one's limit of agents reached), else null.
  // - member: the caller adds agents of their own only (§3.1), as the Agents page's panel.
  // - closeAny(): the page's other form (New agent profile), closed as the panel opens.
  // - started(placement): after a start on a runner, for a page that lists placements.
  // Returns { el (the button), button, slot, closeAll(refocus), openAny }.
  M.joinButton = function (ctx, opts) {
    opts = opts || {};
    const slot = h("div", { class: "join-slot" });
    const status = M.statusLine();
    let J = null;
    const button = h("button", { type: "button", class: "primary join-open" }, M.t("agents.join.open"));

    function closeAll(refocus) {
      if (J && !opts.any) J.close(false);
      if (refocus) button.focus();
    }

    async function openAny() {
      // Closed now (one's limit reached): said beside the button, nothing opens.
      const closed = opts.anyDisabled ? opts.anyDisabled() : null;
      if (closed) { status.fail("", { message: closed }); return; }
      status.done();
      if (opts.any) { opts.any(button); return; }
      // The page's other form (New agent profile) closes (review of #1706).
      if (opts.closeAny) opts.closeAny();
      if (!J) {
        try {
          J = await M.join.mount(ctx, {
            member: !!opts.member,
            full: () => false, // the hub refuses past one's limit (§3.1) and the panel says why
            changed: () => {},
            opened: (yes) => { if (!yes) button.focus(); },
            started: opts.started,
          });
        } catch (err) {
          status.fail(M.t("agents.project.joins_failed"), err);
          return;
        }
        append(slot, J.panel, J.listStatus.el);
      }
      J.open(button, null);
    }
    button.addEventListener("click", openAny);
    append(slot, status.el);
    return { el: button, button, slot, closeAll, openAny };
  };
})(window.Maity);
