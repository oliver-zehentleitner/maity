// Two pages of All projects (/all/jour-fixe, /all/why): a project's Jour fixe
// and Why side by side, read per project from the endpoints the project's own
// pages use, so each project's rules on who sees what stay as they are. The
// hub has no read across projects (context/views.md).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // One section per project, in the header's order, each filled when its own
  // answer comes: a slow or failing project holds up and hides no other.
  function perProject(ctx, root, title, intro, path, draw) {
    append(root, h("h2", null, title), h("p", { class: "muted" }, intro));
    if (!ctx.projects.length) { append(root, h("p", { class: "muted" }, M.t("all.page.no_projects"))); return; }
    // Not awaited: the page is drawn once the view returns, so it must not wait for an answer.
    ctx.projects.forEach((p) => {
      const box = h("div", null, h("p", { class: "muted" }, M.t("all.page.reading")));
      append(root, h("section", { class: "all-project", "data-project": p.full_name, "aria-label": p.name || p.full_name },
        h("h3", null, h("a", { href: "/" + p.full_name + "/" + draw.view }, p.name || p.full_name)), box));
      M.api.get("/projects/" + M.api.projectPath(p.full_name) + path).then(
        (answer) => append(clear(box), draw.answer(p, answer)),
        (err) => append(clear(box), draw.refused(p, err)));
    });
  }

  const unread = (err) => h("p", { class: "send-status failed" }, M.t("all.page.unread", { reason: err.message }));

  const jourFixe = {
    view: "jour-fixe",
    answer: (p, state) => ((state.series || []).length
      ? h("ul", { class: "all-jf-series" }, state.series.map((s) => h("li", { "data-series": s.id },
        h("strong", null, s.topic || s.id),
        h("span", { class: "muted" }, " · " + (s.enabled
          ? M.t("jf.next", { at: s.next_at ? formatTime(s.next_at) : M.t("jf.next.none") }) : M.t("jf.not_scheduled"))),
        s.current_round
          ? h("p", { class: "jf-current" }, M.t("jf.current"), " ",
            h("a", { href: "/" + p.full_name + "/jour-fixe/" + encodeURIComponent(s.current_round.id) }, M.jourFixe.statusWord(s.current_round.status)))
          : null)))
      : h("p", { class: "muted" }, M.t("all.jf.none"))),
    refused: (p, err) => unread(err),
  };

  const whyDrawn = (answer, note) => [note || null, M.why.summaryBox(answer),
    answer.summary.attention
      ? h("details", null, h("summary", null, M.t("why.attention.title")), M.why.attentionList(answer)) : null];

  const why = {
    view: "why",
    answer: (p, answer) => whyDrawn(answer),
    refused: (p, err) => {
      if (err.code === "ktw_not_configured") return h("p", { class: "muted" }, M.t("all.why.none"));
      if (err.code === "ktw_unavailable") {
        const { last, note } = M.why.unavailable(err);
        return last ? whyDrawn(last, note) : note;
      }
      return unread(err);
    },
  };

  M.views.allJourFixe = (ctx, root) => perProject(ctx, root, M.t("all.page.jour_fixe"), M.t("all.jf.intro"), "/jour-fixe", jourFixe);
  M.views.allWhy = (ctx, root) => perProject(ctx, root, M.t("all.page.why"), M.t("all.why.intro"), "/keep-the-why", why);
})(window.Maity);
