// Which of one's agents the hub tells about a maintenance window (docs/api.md §16.12,
// GET/PATCH /me/broadcasts): all, none, only those ticked, or all but those ticked. It
// governs the notice alone: during a window every agent gets the 503, whatever is chosen.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear } = M.dom;
  const PATH = "/me/broadcasts";
  const MODES = [
    ["accept_all", () => M.t("broadcasts.mode.accept_all")],
    ["refuse_all", () => M.t("broadcasts.mode.refuse_all")],
    ["accept_only", () => M.t("broadcasts.mode.accept_only")],
    ["refuse_for", () => M.t("broadcasts.mode.refuse_for")],
  ];
  const listed = (mode) => mode === "accept_only" || mode === "refuse_for";

  // The part under the list of one's agents on /agents. `profiles`: one's own agents.
  function part(ctx, profiles) {
    const box = h("section", { class: "broadcasts", "aria-labelledby": "broadcasts-heading" },
      h("h3", { id: "broadcasts-heading" }, M.t("broadcasts.title")),
      h("p", { class: "hint" }, M.t("broadcasts.hint")));
    const status = M.statusLine();
    const body = h("div");
    append(box, body, status.el);
    M.api.get(PATH).then((choice) => draw(choice), (err) => status.fail(M.t("broadcasts.read_failed"), err));

    function draw(choice) {
      clear(body);
      const mode = h("select", { id: "broadcasts-mode" }, MODES.map(([value, label]) => h("option", { value }, label())));
      mode.value = choice.mode;
      const ticks = profiles.map((a) => {
        const box = h("input", { type: "checkbox", id: "broadcasts-agent-" + a.id });
        box.checked = choice.agents.includes(a.id);
        return box;
      });
      const agents = h("fieldset", { class: "broadcasts-agents" }, h("legend", null, M.t("broadcasts.agents")),
        profiles.length ? profiles.map((a, i) => h("label", { class: "check", for: ticks[i].id }, ticks[i], " ", a.display_name,
          h("span", { class: "muted" }, " @" + (a.name || a.handle)))) : h("p", { class: "muted" }, M.t("agents.none")));
      const show = () => { agents.hidden = !listed(mode.value); };
      mode.addEventListener("change", show);
      show();
      const save = h("button", { type: "submit" }, M.t("broadcasts.save"));
      const form = h("form", { class: "inline-form broadcasts-form" },
        h("label", { for: mode.id }, M.t("broadcasts.mode")), mode, agents, save);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (save.disabled) return;
        const wanted = { mode: mode.value, agents: listed(mode.value) ? profiles.filter((a, i) => ticks[i].checked).map((a) => a.id) : [] };
        save.disabled = true;
        status.busy(M.t("broadcasts.saving"));
        try {
          const answer = await M.api.patch(PATH, wanted);
          status.done();
          draw(answer);
          append(status.el, h("span", { class: "ok" }, M.t("broadcasts.saved")));
        } catch (err) {
          status.fail(M.t("broadcasts.save_failed"), err);
        } finally {
          save.disabled = false;
        }
      });
      append(body, form);
    }
    return box;
  }

  M.broadcasts = { part };
})(window.Maity);
