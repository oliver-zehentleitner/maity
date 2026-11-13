// The experiment notice (docs/api.md §5.1, "Experiment notice"): Maity is an early public
// experiment, and a person's agents act with the rights the person gives them. One text in
// every interface language; the hub shows the same on the registration's completion page.
//
// M.experimentNotice.box({ understood }) — the notice. With `understood`, an async function,
//   it carries an "Understood" button that runs it and then takes the notice away; a failure
//   stays under the button. Without it, the notice alone (for other places, such as the chat
//   firewall's first stranger, which decide for themselves what follows).
// M.experimentNotice.forConnecting(ctx) — the notice for a panel that connects an agent (the
//   join panel, the runner's start), while the person has not confirmed it; null after that,
//   and for an agent. "Understood" confirms it with PATCH /me and takes it away from every
//   panel that shows it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;
  const CONNECTING = "experiment-notice-connecting";
  // The connecting panels' notices still drawn: one confirmation takes every one away.
  let shown = [];

  function box(options) {
    const understood = options && options.understood;
    const classes = ["experiment-notice"].concat(options && options.className ? [options.className] : []);
    const el = h("div", { class: classes.join(" "), role: "note" }, h("p", null, M.t("experiment.notice")));
    if (!understood) return el;
    // The status line only once a confirmation failed: an empty one would be the panel's first.
    let status = null;
    const button = h("button", {
      type: "button",
      class: "btn",
      onclick: async () => {
        button.disabled = true;
        if (status) status.done();
        try {
          await understood();
        } catch (err) {
          button.disabled = false;
          if (!status) { status = M.statusLine(); append(el, status.el); }
          status.fail(M.t("experiment.not_saved"), err);
          return;
        }
        el.remove();
      },
    }, M.t("experiment.understood"));
    append(el, h("div", { class: "actions" }, button));
    return el;
  }

  function forConnecting(ctx) {
    const me = ctx && ctx.me;
    if (!me || me.kind !== "human" || me.experiment_notice_understood_at) return null;
    const el = box({
      className: CONNECTING,
      understood: async () => {
        const answer = await M.api.patch("/me", { experiment_notice_understood: true });
        me.experiment_notice_understood_at = (answer && answer.member && answer.member.experiment_notice_understood_at) || new Date(M.api.now()).toISOString();
        // The other panel open beside this one (the join and the runner's start) loses it too.
        shown.forEach((other) => { if (other !== el) other.remove(); });
        shown = [];
      },
    });
    shown = shown.filter((other) => other.parentNode).concat(el);
    return el;
  }

  M.experimentNotice = { box, forConnecting };
})(window.Maity);
