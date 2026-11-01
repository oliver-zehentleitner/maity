// (9) Project → Runners (/<owner>/<slug>/runners, project:admin): the runners
// allowed to start agents for this project (docs/api.md §15.4). Allowing
// one is the grant; its own configuration still decides what it starts.
// Detaching closes the agents it runs here. Capabilities are shown in the
// words of the Runners page (M.runnerWords) and rendered as text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  const PRESENCE_MS = 30000;

  M.views.projectRunners = async function (ctx, root) {
    const words = M.runnerWords;
    const status = M.statusLine();
    const list = h("div", { class: "runners" });
    const allow = h("div", { class: "allow-runner" });
    const projectName = ctx.project.name || ctx.slug;

    // The dashboard ships with its hub, which has attachments: any refusal
    // fails loud like every other view's.
    const attached = await M.api.getAll(ctx.base + "/runners");
    status.el.setAttribute("tabindex", "-1");

    // busy and failed: the status line's words while it runs and when it is
    // refused; done: what went through, for the status line that gets the focus.
    async function act(busy, failed, done, call) {
      status.busy(busy);
      try {
        await call();
        status.done();
        append(status.el, h("span", { class: "ok" }, done));
      } catch (err) {
        if (err.code === "already_attached") {
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("prunners.already")));
        } else {
          status.fail(failed, err);
        }
      }
      await reload().catch((err) => status.fail(M.t("prunners.refresh_failed"), err));
      // The control that acted may be gone: the line that says what happened has the focus.
      status.el.focus();
    }

    function card(a) {
      const r = a.runner;
      const c = r.capabilities;
      const shownN = a.active_placements || 0;
      // The runner checks its own configuration again; a project missing
      // there means it starts nothing here, whatever the hub allows.
      const notInConfig = c && !(c.projects || []).includes(ctx.slug);
      return h("article", { class: "runner", "aria-label": r.name },
        h("header", null,
          h("span", { class: "dot " + words.presenceClass(r) }),
          h("h3", null, r.name),
          h("span", { class: "presence " + words.presenceClass(r) }, words.presenceText(r)),
          h("span", { class: "muted" }, " · " + words.backendLabel(r) + (r.version ? " · " + r.version : ""))),
        h("p", { class: "muted" }, M.t("prunners.allowed_since", { ago: formatAgo(a.attached_at) }), " · ",
          shownN ? M.t("prunners.running", { count: shownN }) : M.t("prunners.running.none")),
        // §15.3: revoked, or none (attached through an enrollment, never paired).
        r.credential_state === "revoked"
          ? h("p", { class: "flag" }, M.tn("prunners.revoked", { page: h("a", { href: "/runners" }, M.t("prunners.runners_page")) }))
          : r.credential_state && r.credential_state !== "active"
            ? h("p", { class: "flag" }, M.tn("prunners.unpaired", { page: h("a", { href: "/runners" }, M.t("prunners.runners_page")) }))
            : null,
        notInConfig
          ? h("p", { class: "flag" }, M.t("prunners.not_in_config", { project: ctx.slug }))
          : null,
        words.capabilities(r),
        h("div", { class: "runner-actions" },
          h("button", {
            type: "button",
            class: "danger",
            "data-focus": "detach:" + r.id,
            onclick: async () => {
              // The count the confirmation names is read now, not from the last refresh.
              let n = a.active_placements || 0;
              try {
                const now = (await M.api.getAll(ctx.base + "/runners")).items.find((x) => x.runner.id === r.id);
                if (now) n = now.active_placements || 0;
              } catch (ignored) {
                // The last refresh's count, then: the hub still decides.
              }
              // The hub closes the placements; the runner, still connected, ends the agents.
              const ask = n
                ? M.t("prunners.detach.confirm", { runner: r.name, project: projectName, count: n })
                : M.t("prunners.detach.confirm.none", { runner: r.name, project: projectName });
              if (!window.confirm(ask)) return;
              act(M.t("prunners.detaching"), M.t("prunners.detach.failed"), M.t("prunners.detached", { runner: r.name, project: projectName }),
                () => M.api.del(ctx.base + "/runners/" + encodeURIComponent(r.id)));
            },
          }, M.t("prunners.detach"))));
    }

    // The free runners last drawn: the Allow form is rebuilt only when they change.
    let freeKey = null;
    function drawAllow(mine, attachedIds) {
      const free = mine.filter((r) => !r.removed_at && r.owner_id === ctx.me.id && !attachedIds.has(r.id));
      const key = free.map((r) => r.id).join(" ") + "|" + mine.some((r) => !r.removed_at && r.owner_id === ctx.me.id);
      if (key === freeKey) return;
      freeKey = key;
      const chosen = allow.querySelector("select") ? allow.querySelector("select").value : null;
      // A focus inside the form comes back to the same control after the rebuild.
      const had = document.activeElement && allow.contains(document.activeElement) ? document.activeElement.getAttribute("data-focus") : null;
      clear(allow);
      append(allow, h("h3", null, M.t("prunners.allow.title")));
      if (!free.length) {
        const pair = h("a", { href: "/runners" }, M.t("prunners.pair_link"));
        append(allow, h("p", { class: "muted" }, mine.some((r) => !r.removed_at && r.owner_id === ctx.me.id)
          ? M.tn("prunners.all_allowed", { pair }) : M.tn("prunners.none_yet", { pair })));
        return;
      }
      const select = h("select", { id: "allow-runner", "data-focus": "allow" }, free.map((r) => h("option", { value: r.id }, r.name)));
      select.value = free.some((r) => r.id === chosen) ? chosen : free[0].id;
      append(allow, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          const name = (free.find((r) => r.id === select.value) || {}).name;
          act(M.t("prunners.allowing"), M.t("prunners.allow.failed"), name ? M.t("prunners.allowed", { runner: name }) : M.t("prunners.allowed.unnamed"),
            () => M.api.post(ctx.base + "/runners", { runner_id: select.value }));
        },
      }, h("label", { for: "allow-runner" }, M.t("prunners.runner")), select, h("button", { type: "submit", "data-focus": "allow-submit" }, M.t("prunners.allow"))));
      const again = had && Array.from(allow.querySelectorAll("select, button")).find((e) => e.getAttribute("data-focus") === had);
      if (again) again.focus();
    }

    // Drawn again only when what it shows changed, and then with the focus
    // back on the same control (its data-focus key).
    let shownKey = null;
    function draw(items, mine) {
      drawAllow(mine, new Set(items.map((a) => a.runner.id)));
      const key = JSON.stringify(items);
      if (key === shownKey) return;
      shownKey = key;
      const had = document.activeElement && list.contains(document.activeElement) ? document.activeElement.getAttribute("data-focus") : null;
      clear(list);
      if (!items.length) append(list, h("div", { class: "empty-state" }, h("p", null, M.t("prunners.empty"))));
      items.forEach((a) => append(list, card(a)));
      const again = had && Array.from(list.querySelectorAll("button")).find((b) => b.getAttribute("data-focus") === had);
      if (again) again.focus();
    }

    async function reload() {
      const [a, mine] = await Promise.all([M.api.getAll(ctx.base + "/runners"), M.api.getAll("/runners")]);
      draw(a.items, mine.items);
    }

    append(root, h("h2", null, M.t("prunners.title")),
      h("p", { class: "muted" }, M.t("prunners.hint", { project: projectName })),
      allow, status.el, list);
    draw(attached.items, (await M.api.getAll("/runners")).items);
    // Presence and capabilities emit no events: re-read them (docs/api.md §15.1).
    ctx.every(PRESENCE_MS, () => reload().catch((err) => status.fail(M.t("prunners.refresh_failed"), err)));
  };
})(window.Maity);
