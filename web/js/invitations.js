// The person invitations of one's projects in one place (/invite, docs/api.md
// §16.11, §3.4): the projects where the human holds members:admin, the form
// for the one chosen (?project=<owner>/<slug>, as Members' Invite user
// links it), and every chosen project's invitations as the list gives them.
// An organisation's invitations (§6.26) are not here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  M.views.invitations = async function (ctx, root) {
    append(root, h("h2", null, M.t("invitations.title")), h("p", { class: "muted" }, M.t("invitations.hint")));
    // members:admin goes with trust owner or admin (§2.3); the hub decides each call.
    const mine = ctx.me.kind === "human" ? ctx.projects.filter((p) => M.trust.governs(p)) : [];
    if (!mine.length) { append(root, h("p", { class: "muted" }, M.t("invitations.none"))); return; }
    const asked = new URLSearchParams(M.route.current().query || "").get("project");
    let chosen = mine.some((p) => p.full_name === asked) ? asked : mine[0].full_name;
    const pick = h("select", { id: "invitations-project" }, mine.map((p) => h("option", { value: p.full_name }, p.name || p.full_name)));
    pick.value = chosen;
    const formSlot = h("div");
    const others = h("div", { class: "invitations-others" });
    // The chosen project with its form; the others' lists below it. A choice
    // made while a draw still reads starts a new one; the older one stops.
    let drawSeq = 0;
    async function draw() {
      const seq = ++drawSeq;
      append(clear(formSlot), h("p", { class: "muted" }, M.t("invitations.reading")));
      clear(others);
      for (const p of mine) {
        if (seq !== drawSeq) return;
        let pctx;
        try {
          pctx = await M.projectContext(ctx, p.full_name, (slug, id) => "/chats/" + M.api.projectPath(slug) + (id ? "/" + encodeURIComponent(id) : ""));
        } catch (err) {
          if (seq !== drawSeq) return;
          append(p.full_name === chosen ? clear(formSlot) : others, h("p", { class: "send-status failed" }, M.t("invitations.project_failed", { project: p.name || p.full_name, reason: err.message })));
          continue;
        }
        const panel = p.full_name === chosen
          ? await M.invite.membersPanel(pctx, { heading: M.t("invitations.for_project", { project: p.name || p.full_name }) })
          : await M.invite.membersPanel(pctx, { heading: p.name || p.full_name, listOnly: true });
        if (seq !== drawSeq) return;
        if (p.full_name === chosen) append(clear(formSlot), panel);
        else append(others, panel);
      }
    }
    pick.addEventListener("change", () => { chosen = pick.value; draw(); });
    append(root, mine.length > 1 ? h("div", { class: "inline-form" }, h("label", { for: "invitations-project" }, M.t("invitations.project")), pick) : null,
      formSlot, mine.length > 1 ? [h("h3", null, M.t("invitations.others")), others] : null);
    await draw();
  };
})(window.Maity);
