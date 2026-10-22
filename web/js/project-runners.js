// (9) Project → Runners (#/p/<slug>/runners, project:admin): the runners
// allowed to start agents for this project (docs/api.md §15.4). Allowing
// one is the grant; its own configuration still decides what it starts.
// Detaching closes the agents it runs here. Capabilities are shown in the
// words of the Runners page (M.runnerWords) and rendered as text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  const PRESENCE_MS = 30000;

  const agents = (n) => n + (n === 1 ? " agent" : " agents");

  M.views.projectRunners = async function (ctx, root) {
    const words = M.runnerWords;
    const status = M.statusLine();
    const list = h("div", { class: "runners" });
    const allow = h("div", { class: "allow-runner" });
    const projectName = ctx.project.name || ctx.slug;

    // A hub before attachments has no such endpoint: say so instead of failing.
    let attached;
    try {
      attached = await M.api.getAll(ctx.base + "/runners");
    } catch (err) {
      if (err.status !== 404) throw err;
      append(root, h("h2", null, "Runners"),
        h("p", null, "This hub cannot allow runners in projects yet. ",
          h("a", { href: "#/runners" }, "You can pair one on the Runners page already"), "."));
      return;
    }

    async function act(label, call) {
      status.busy(label + "…");
      try {
        await call();
        status.done();
      } catch (err) {
        if (err.code === "already_attached") {
          status.done();
          append(status.el, h("span", { class: "ok" }, "It was allowed here already."));
        } else {
          status.fail(label + " failed: ", err);
        }
      }
      await reload().catch((err) => status.fail("Could not refresh: ", err));
    }

    function card(a) {
      const r = a.runner;
      const c = r.capabilities;
      const n = a.active_placements || 0;
      // The runner checks its own configuration again; a project missing
      // there means it starts nothing here, whatever the hub allows.
      const notInConfig = c && !(c.projects || []).includes(ctx.slug);
      return h("article", { class: "runner", "aria-label": r.name },
        h("header", null,
          h("span", { class: "dot " + words.presenceClass(r) }),
          h("h3", null, r.name),
          h("span", { class: "presence " + words.presenceClass(r) }, words.presenceText(r)),
          h("span", { class: "muted" }, " · " + words.backendLabel(r) + (r.version ? " · " + r.version : ""))),
        h("p", { class: "muted" }, "Allowed here " + formatAgo(a.attached_at) + " · " + (n ? agents(n) + " running here" : "no agent running here")),
        r.credential_state !== "active"
          ? h("p", { class: "flag" }, "It cannot start anything until it is paired again, on the ", h("a", { href: "#/runners" }, "Runners page"), ".")
          : null,
        notInConfig
          ? h("p", { class: "flag" }, "Its own configuration does not allow " + ctx.slug
            + ", so it starts nothing here; add it to [limits] projects on that machine.")
          : null,
        words.capabilities(r),
        h("div", { class: "runner-actions" },
          h("button", {
            type: "button",
            class: "danger",
            onclick: () => {
              // The hub closes the placements; the runner, still connected, ends the agents.
              const what = n
                ? "The hub closes the placement" + (n === 1 ? "" : "s") + " of the " + agents(n) + " it runs here, and the runner stops "
                  + (n === 1 ? "it." : "them.")
                : "Nothing runs on it here.";
              if (!window.confirm("Detach " + r.name + " from " + projectName + "? " + what)) return;
              act("Detaching", () => M.api.del(ctx.base + "/runners/" + encodeURIComponent(r.id)));
            },
          }, "Detach")));
    }

    function drawAllow(mine, attachedIds) {
      clear(allow);
      const free = mine.filter((r) => !r.removed_at && r.owner_id === ctx.me.id && !attachedIds.has(r.id));
      append(allow, h("h3", null, "Allow a runner here"));
      if (!free.length) {
        append(allow, h("p", { class: "muted" },
          mine.some((r) => !r.removed_at && r.owner_id === ctx.me.id) ? "All your runners are allowed here. " : "You have no runner yet. ",
          h("a", { href: "#/runners" }, "Pair one on the Runners page"), "."));
        return;
      }
      const select = h("select", { id: "allow-runner" }, free.map((r) =>
        h("option", { value: r.id }, r.name + " · " + words.presenceText(r))));
      select.value = free[0].id;
      append(allow, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          act("Allowing", () => M.api.post(ctx.base + "/runners", { runner_id: select.value }));
        },
      }, h("label", { for: "allow-runner" }, "Runner"), select, h("button", { type: "submit" }, "Allow it here")));
    }

    function draw(items, mine) {
      clear(list);
      if (!items.length) append(list, h("div", { class: "empty-state" }, h("p", null, "No runner is allowed in this project yet.")));
      items.forEach((a) => append(list, card(a)));
      drawAllow(mine, new Set(items.map((a) => a.runner.id)));
    }

    async function reload() {
      const [a, mine] = await Promise.all([M.api.getAll(ctx.base + "/runners"), M.api.getAll("/runners")]);
      draw(a.items, mine.items);
    }

    append(root, h("h2", null, "Runners"),
      h("p", { class: "muted" }, "A runner allowed here can start agents for " + projectName
        + ", within what its own configuration allows. Detaching it closes the agents it runs here."),
      allow, status.el, list);
    draw(attached.items, (await M.api.getAll("/runners")).items);
    // Presence and capabilities emit no events: re-read them (docs/api.md §15.1).
    ctx.every(PRESENCE_MS, () => reload().catch((err) => status.fail("Could not refresh: ", err)));
  };
})(window.Maity);
