// The head of a page with tabs, built once for the project's Agents page (js/agents-page.js) and
// its Team page (js/members.js), as the maintainer asked on 2026-11-12 (tsk-vkyp71qp95n9): the
// heading with the page's buttons at the right end, the tab bar under them, each the page's full
// width; and the Join an agent menu both pages offer, with its two ways in: any agent (the join
// panel, js/join.js) or one started on a runner (js/placements.js).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

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

  // Join an agent: a menu of the two ways in, each opening its panel in `slot` (under the head,
  // so on every tab of the page). opts (all optional):
  // - any(opener): opens the join panel itself, where the page has one wired to its own lists
  //   (the Agents tab: the seats, the count, the limit). Without it the menu mounts a panel of its
  //   own on first use (the Team page, the other tabs).
  // - anyDisabled(): a reason the way is closed now (one's limit of agents reached), else null.
  // - member: the caller adds agents of their own only (§3.1), as the Agents page's panel.
  // - started(placement): after a start on a runner, for a page that lists placements.
  // Returns { el (the button and its menu), slot, closeAll(refocus) }.
  M.joinMenu = function (ctx, opts) {
    opts = opts || {};
    const slot = h("div", { class: "join-menu-slot" });
    const startSlot = h("div", { class: "placement-new-slot" });
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    let J = null;
    let menu = null;
    // Each choice and each close starts a new round: a start whose reads come back after another
    // choice won draws nothing (review of #1706).
    let round = 0;
    const offerStart = !!(M.placements && M.placements.startOffered(ctx));

    function closeStart() { round += 1; clear(startSlot); }
    function closeAll(refocus) {
      closeStart();
      if (J && !opts.any) J.close(false);
      if (refocus) menu.button.focus();
    }

    async function openAny() {
      closeStart();
      if (opts.any) { opts.any(menu.button); return; }
      // The page's other form (New agent profile) closes, as a start closes it (review of #1706).
      if (opts.closeAny) opts.closeAny();
      if (!J) {
        try {
          J = await M.join.mount(ctx, {
            member: !!opts.member,
            full: () => false, // the hub refuses past one's limit (§3.1) and the panel says why
            changed: () => {},
            opened: (yes) => { if (!yes) menu.button.focus(); },
          });
        } catch (err) {
          status.fail(M.t("agents.project.joins_failed"), err);
          return;
        }
        append(slot, J.panel, J.listStatus.el);
      }
      J.open(menu.button, null);
    }

    async function openStart() {
      if (J && !opts.any) J.close(false);
      if (opts.closeAny) opts.closeAny();
      append(clear(startSlot), h("p", { class: "muted", role: "status" }, M.t("placements.new.reading")));
      const mine = ++round;
      let form = null;
      const box = await M.placements.startBox(ctx, {
        cancel: () => closeAll(true),
        // Only the form that sent it closes (review of #1558): one cancelled while its POST ran and
        // opened anew keeps its draft and the focus; the placement made is said all the same.
        made: async (made) => {
          const sender = !!form && startSlot.contains(form);
          if (sender) closeStart();
          if (opts.started) await opts.started(made);
          append(clear(status.el), h("span", { class: "ok" }, M.t("placements.new.done",
            { name: made.agent.display_name || made.agent.handle, runner: made.runner.name })), " ",
          h("a", { href: ctx.link("placements") }, M.t("placements.title")));
          if (sender) status.el.focus();
        },
      });
      if (mine !== round) return;
      if (box) form = box.node;
      if (!box) { closeStart(); return; }
      // The form brings its own heading and Cancel (js/placements.js); a line saying why there is
      // none stands alone.
      append(clear(startSlot), h("div", { class: "placement-new-box" }, box.node));
      if (box.first) box.first.focus();
    }

    menu = M.menuButton({
      label: M.t("agents.join.open"),
      class: "primary join-open",
      face: M.t("agents.join.open"), // its caret is the stylesheet's, so the name stays the words
      items: () => {
        const closed = opts.anyDisabled ? opts.anyDisabled() : null;
        return [
          closed ? { key: "any", label: M.t("agents.join.any"), disabled: true, why: closed }
            : { key: "any", label: M.t("agents.join.any"), onSelect: openAny },
          offerStart ? { key: "runner", label: M.t("placements.new.open"), onSelect: openStart } : null,
        ].filter(Boolean);
      },
    });
    append(slot, startSlot, status.el);
    return { el: menu.el, button: menu.button, slot, closeAll, openAny, openStart };
  };
})(window.Maity);
