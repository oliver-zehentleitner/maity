// (4) Members (/<owner>/<slug>/members): everyone in the project, humans and
// agents, as a neutral list: role, owner, presence, when they joined and
// whether they are paused (docs/api.md §6.2), a link to each profile and a
// Chat button. With members:admin each row can be managed: the role, an
// agent's briefing, credentials and pause, and removal. One's own agents are
// managed on Agents (js/agents-page.js), with the parts shared from here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRESENCE_LABELS = {
    online: () => M.t("members.presence.online"), away: () => M.t("members.presence.away"),
    offline: () => M.t("members.presence.offline"), paused: () => M.t("members.presence.paused"),
  };
  // Presence emits no event (docs/api.md §5.3): the view re-reads it and
  // updates the presence cells in place, so focus and forms stay.
  const PRESENCE_MS = 30000;
  // The hub's refusals, in words; anything else is shown as it comes.
  // The hub's refusals in words, by field and reason; a reason the page
  // does not know is shown as it comes.
  const REFUSALS = {
    "trust:last_owner": () => M.t("members.refused.last_owner"),
    "member:last_owner": () => M.t("members.refused.last_owner"),
    "trust:humans_only": () => M.t("members.refused.humans_only"),
    "trust:unknown": () => M.t("members.refused.trust_unknown"),
    "role:unknown": () => M.t("members.refused.role_unknown"),
    "role:proxy_needs_admin": () => M.t("members.refused.proxy_needs_admin"),
    "reports_to:guest": () => M.t("members.refused.reports_to_guest"),
    "reports_to:cycle": () => M.t("members.refused.reports_to_cycle"),
    "reports_to:not_a_member": () => M.t("members.refused.reports_to_not_a_member"),
    "areas:invalid_path": () => M.t("members.refused.areas_invalid_path"),
    "areas:too_long": () => M.t("members.refused.areas_too_long"),
    "capabilities:unknown": () => M.t("members.refused.capabilities_unknown"),
    "capabilities:too_long": () => M.t("members.refused.capabilities_too_long"),
    "paused.reason:string_too_long": () => M.t("members.refused.pause_reason_too_long"),
    // §6.2 "An agent whose owner is no member".
    "member:owner_not_member": () => M.t("members.refused.owner_not_member"),
    "member:outside_owner": () => M.t("members.refused.outside_owner_lift"),
    "trust:outside_owner": () => M.t("members.refused.outside_owner_trust"),
    "role:outside_owner": () => M.t("members.refused.outside_owner_role"),
    // §2.3 "The bridge": the connection's checks, on the served side and the bridge's.
    "member:too_many": () => M.t("bridges.refused.too_many"),
    "member:security_team": () => M.t("bridges.refused.security_team"),
    "member:outside_role": () => M.t("bridges.refused.outside_role"),
    "member:role": () => M.t("bridges.refused.proxy"),
    "bridge:role": () => M.t("bridges.refused.proxy"),
    "bridge:already": () => M.t("bridges.refused.already"),
    "purpose:invalid": () => M.t("bridges.refused.purpose"),
  };
  const CYCLE = () => M.t("members.refused.reports_to_cycle");
  const BAD_AREA = () => M.t("members.refused.areas_invalid_path");
  // The hub's rules for an area (hub/src/maity_hub/routes/members.py).
  const AREA = /^[A-Za-z0-9._/-]{1,255}$/;
  const areaOk = (a) => AREA.test(a) && !a.startsWith("..") && !("/" + a + "/").includes("/../");
  const CAPABILITIES = [["tag", () => M.t("members.capability.tag")]];

  // An agent whose owner holds no active membership here (§6.2). A reader who is
  // shown no owner_id gets no mark rather than a wrong one.
  function ownerOutside(ctx, m) {
    if (m.kind !== "agent" || !m.owner_id || m.removed_at) return false;
    const owner = (ctx.memberById || {})[m.owner_id];
    return !owner || !!owner.removed_at;
  }

  // The hub names each bad field (details.fields); said in words.
  function refusal(err) {
    if (err.code === "forbidden" && err.details && err.details.reason === "humans_only") {
      return { message: M.t("members.refused.humans_only_change") };
    }
    // §2.3: granting owner, admin or proxy, and lowering or removing an owner.
    if (err.code === "forbidden" && err.details && err.details.reason === "owner_only") {
      return { message: M.t("members.refused.owner_only") };
    }
    // §6.25, §6.26: the person whose namespace holds the project, and every
    // owner of the organisation that holds it, stays an owner here.
    if (err.code === "namespace_owner") {
      return { message: M.t("members.refused.namespace_owner") };
    }
    // §2.3: only the served agent's owner connects a bridge.
    if (err.code === "forbidden" && err.details && err.details.reason === "agent_owner") {
      return { message: M.t("bridges.refused.agent_owner") };
    }
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    const said = Object.entries(fields).map(([f, reason]) => (Object.hasOwn(REFUSALS, f + ":" + reason) ? REFUSALS[f + ":" + reason]()
      : M.t("members.refused.unknown", { field: f.replace(/_/g, " "), reason })));
    return { message: said.join(" ") };
  }

  // A change an agent's rule holds for a human's go answers 202 with the
  // consent request (docs/api.md §2.3), not with the member.
  const isConsent = (answer) => !!answer && answer.class === "consent" && /^req-/.test(answer.id || "");

  // A presence the page knows gets its dot; anything else is said as it comes.
  // Outage and cover (§6.12): a limit with its end and reason, who covers this member and
  // whom it covers. Nothing for a member who is simply available, offline or paused.
  function availabilityNodes(ctx, m) {
    const a = m.availability || {};
    const parts = [];
    if (a.state === "limited") {
      const away = a.source === "dormant" ? M.t("availability.dormant")
        : a.until ? M.t("availability.limited_until", { until: formatTime(a.until) }) : M.t("availability.limited");
      parts.push(h("span", { class: "availability-limited" }, away, a.reason ? " (" + a.reason + ")" : ""));
    }
    if (m.covered_by) parts.push(h("span", null, M.tn("availability.covered_by", { who: M.dom.memberRef(ctx, m.covered_by.member_id), ago: formatAgo(m.covered_by.since) })));
    (m.covering || []).forEach((c) => parts.push(h("span", null, M.tn("availability.covering", { who: M.dom.memberRef(ctx, c.member_id), ago: formatAgo(c.since) }))));
    return parts.length ? h("span", { class: "availability-note" }, parts) : null;
  }
  M.availabilityNodes = availabilityNodes;

  function presenceNodes(m, warn, ctx) {
    const known = Object.prototype.hasOwnProperty.call(PRESENCE_LABELS, m.presence);
    return [known ? h("span", { class: "dot " + m.presence, "aria-hidden": "true" }) : null, known ? " " : null,
      known ? PRESENCE_LABELS[m.presence]() : String(m.presence || M.t("members.presence.unknown")),
      M.dom.isSilentAgent(m) ? [" · ", M.dom.silentSince(m, warn)]
        : m.last_seen_at && m.presence !== "online" ? h("span", { class: "muted" }, " · ", M.t("members.seen", { ago: formatAgo(m.last_seen_at) })) : null,
      ctx ? availabilityNodes(ctx, m) : null];
  }

  // What a member's row and an own agent's card on Agents share (js/agents-page.js):
  // the rulebook, the credentials, the picture, the pause and the removal, each
  // written through act. view: {status, keyed, edits, open, reload, redraw}.
  function memberParts(ctx, view) {
    const { status, keyed, edits, open } = view;
    const reload = () => view.reload();
    const redraw = (focusKey) => view.redraw(focusKey);

    // Who paused it is a member like any other: a link to them.
    function pausedText(m) {
      const p = m.paused;
      if (!p) return "";
      const o = { ago: formatAgo(p.since), reason: p.reason || "" };
      if (p.by === m.id) return p.reason ? M.t("members.paused.self_reason", o) : M.t("members.paused.self", o);
      const by = M.dom.memberRef(ctx, p.by);
      return p.reason ? M.tn("members.paused.by_reason", Object.assign(o, { by })) : M.tn("members.paused.by", Object.assign(o, { by }));
    }

    // A write and the re-read after it are told apart: a write that went
    // through is said as done even when the list cannot be read afterwards.
    // `settled` runs once the hub has taken the call (a change or a consent
    // request), before the list is read again and drawn. The outcome is said
    // once the list is drawn again, so "Saved" means the rows show it and
    // nothing is replaced under the next click.
    async function act(label, done, call, focusKey, settled) {
      status.busy(M.t("members.act.busy", { action: label }));
      let answer;
      try {
        answer = await call();
      } catch (err) {
        status.fail(M.t("members.act.failed", { action: label }), refusal(err));
        return false;
      }
      if (settled) settled();
      try {
        await reload();
        redraw(focusKey);
      } catch (err) {
        status.fail(M.t("members.act.refresh_failed", { done }), err);
        return isConsent(answer) ? "consent" : true;
      }
      status.done();
      // Waiting for a human's go is no change yet: said as such.
      append(status.el, isConsent(answer)
        ? h("span", { class: "flag" }, consentWords(answer))
        : h("span", { class: "ok" }, done));
      return isConsent(answer) ? "consent" : true;
    }

    // Waiting for a human's go: whose, and the request it waits on, in one sentence.
    function consentWords(answer) {
      const o = { who: answer.to === "owner" ? M.t("members.consent.owner") : ctx.nameOf(answer.to), id: answer.id, title: answer.title || "" };
      return answer.title ? M.t("members.consent.waiting_titled", o) : M.t("members.consent.waiting", o);
    }

    // One's own agent, as a human: its rulebook, credentials and picture are theirs (§6.18, §6.10).
    const ownAgent = (m) => m.kind === "agent" && ctx.me.kind === "human" && m.owner_id === ctx.me.id;

    // An agent's credentials, read when its row first opens and kept across
    // redraws; a failed read costs that row its list, not the view.
    const credsOf = new Map();
    function credentialsPart(m) {
      const P = M.agentParts;
      if (!P) return null;
      const slot = h("div", { class: "member-credentials" });
      // A revocation reads this row's list again, in place: the row stays
      // open and the focus goes to the list's heading.
      const revoked = () => {
        credsOf.delete(m.id);
        load(true);
        // Whoever shows a count of this member's instances (Your agents) reads it again.
        if (view.revoked) view.revoked(m);
      };
      const fill = (got, refocus) => {
        append(clear(slot), got.error
          ? h("div", { class: "credentials" }, h("h4", { class: "credentials-title" }, M.t("members.credentials")), M.errorBox(got.error))
          : P.credentials(ctx, m, got.list, revoked));
        const head = refocus && slot.querySelector(".credentials-title");
        if (head) { head.setAttribute("tabindex", "-1"); head.focus(); }
      };
      function load(refocus) {
        const known = credsOf.get(m.id);
        if (known && !known.then) { fill(known, refocus); return; }
        if (!refocus) append(slot, h("p", { class: "muted" }, M.t("members.credentials.reading")));
        const reading = known || P.loadCredentials(ctx, m).then((got) => { credsOf.set(m.id, got); return got; });
        credsOf.set(m.id, reading);
        reading.then((got) => { if (slot.isConnected !== false) fill(got, refocus); });
      }
      load(false);
      return slot;
    }

    // One's own agent's picture (§6.10: the profile's owner sets it). The
    // member list has no avatar_source, one's agent profiles have: read once
    // when the first such row opens, kept across redraws.
    const profileOf = new Map();
    let profiles = null;
    const ownProfile = (id) => {
      profiles = profiles || M.api.getAll("/agents").then((r) => r.items);
      return profiles.then((items) => items.find((a) => a.id === id) || {});
    };
    function picturePart(m) {
      if (!ownAgent(m) || !M.pictureEditor) return null;
      const slot = h("div", { class: "member-picture" });
      const changed = (answer, words) => {
        profileOf.set(m.id, Object.assign({}, profileOf.get(m.id), answer));
        act(M.t("members.picture.changing"), words, () => Promise.resolve(answer), null);
      };
      const fill = (profile) => append(clear(slot), h("h4", { class: "member-picture-title" }, M.t("members.picture")),
        profile.error ? M.errorBox(profile.error)
          : M.pictureEditor(Object.assign({}, m, profile), "/agents/" + encodeURIComponent(m.id) + "/avatar", false, changed),
        // Deleting the profile (§6.3): its owner only, as the picture.
        !profile.error && M.profileDelete ? M.profileDelete(Object.assign({}, m, profile), (answer, words) => {
          open.delete(m.id);
          profileOf.delete(m.id);
          act(M.t("members.deleting"), words, () => Promise.resolve(answer), null);
        }) : null);
      const known = profileOf.get(m.id);
      if (known && !known.then) { fill(known); return slot; }
      append(slot, h("p", { class: "muted" }, M.t("members.picture.reading")));
      const reading = known || ownProfile(m.id)
        .then((a) => ({ avatar_url: a.avatar_url, avatar_source: a.avatar_source, handle: a.handle || m.handle, memberships: a.memberships || [] }), (error) => ({ error }))
        .then((got) => { profileOf.set(m.id, got); return got; });
      profileOf.set(m.id, reading);
      reading.then((got) => { if (slot.isConnected !== false) fill(got); });
      return slot;
    }

    // The team's rulebook (docs/api.md §6.18, tsk-xzbk67raztm0): for the
    // human who owns the agent profile only, as the hub allows it; other
    // viewers see none of it. Only the fields that changed are sent.
    const DISTRIBUTION = [["free", () => M.t("team.distribution.free")], ["lead", () => M.t("team.distribution.lead")], ["round_robin", () => M.t("team.distribution.round_robin")]];
    const WAKE = [["all", () => M.t("team.wake.all")], ["lead", () => M.t("team.wake.lead")], ["next_free", () => M.t("team.wake.next_free")]];
    function teamForm(m, memberPath) {
      if (!ownAgent(m)) return null;
      const t = Object.assign({ max_instances: 1, distribution: "free", lead_instance: null, wake: "all", review_within_team: false }, m.team || {});
      const id = (what) => "team-" + what + "-" + m.id;
      const active = (m.instances || []).filter((i) => !i.revoked_at);
      const max = keyed("team-max:" + m.id, h("input", { id: id("max"), type: "number", min: "1", max: "16", step: "1", "aria-describedby": id("max") + "-hint" }));
      max.value = String(t.max_instances);
      const pick = (what, list, value) => {
        const s = h("select", { id: id(what) }, list.map(([v, l]) => h("option", { value: v }, typeof l === "function" ? l() : l)));
        s.value = value;
        return s;
      };
      const distribution = pick("distribution", DISTRIBUTION, t.distribution);
      const wake = pick("wake", WAKE, t.wake);
      // A lead revoked since stays chosen, marked, so saving another field does not clear it.
      const gone = t.lead_instance && !active.some((i) => i.id === t.lead_instance) ? [[t.lead_instance, M.t("team.lead.revoked", { id: t.lead_instance })]] : [];
      const lead = pick("lead", [["", M.t("team.lead.none")]].concat(active.map((i) => [i.id, i.label ? M.t("team.lead.labelled", { label: i.label, id: i.id }) : "#" + i.id]), gone), t.lead_instance || "");
      const review = h("input", { id: id("review"), type: "checkbox" });
      review.checked = !!t.review_within_team;
      const error = h("p", { class: "field-error", id: id("error"), role: "alert" });
      const save = h("button", { type: "submit" }, M.t("team.save"));
      return h("form", {
        class: "member-team",
        "aria-labelledby": id("title"),
        onsubmit: async (e) => {
          e.preventDefault();
          error.textContent = "";
          const n = Number(max.value);
          if (!Number.isInteger(n) || n < 1 || n > 16) { error.textContent = M.t("team.max.invalid"); max.focus(); return; }
          if ((distribution.value === "lead" || wake.value === "lead") && !lead.value) {
            error.textContent = M.t("team.lead.needed"); lead.focus(); return;
          }
          const want = { max_instances: n, distribution: distribution.value, lead_instance: lead.value || null, wake: wake.value, review_within_team: review.checked };
          const team = {};
          Object.keys(want).forEach((k) => { if (want[k] !== t[k]) team[k] = want[k]; });
          if (!Object.keys(team).length) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("members.unchanged"))); return; }
          save.disabled = true;
          await act(M.t("team.saving"), M.t("team.saved", { name: m.display_name }), () => M.api.patch(memberPath, { team }), "team-max:" + m.id);
          save.disabled = false;
        },
      },
      h("h4", { id: id("title") }, M.t("team.title")),
      h("p", { class: "hint" }, M.t("team.hint")),
      h("label", { for: id("max") }, M.t("team.max")), max,
      h("p", { class: "hint", id: id("max") + "-hint" }, M.t("team.max.hint", { count: active.length })),
      h("label", { for: id("distribution") }, M.t("team.distribution")), distribution,
      h("label", { for: id("lead") }, M.t("team.lead")), lead,
      h("label", { for: id("wake") }, M.t("team.wake")), wake,
      h("label", { class: "check", for: id("review") }, review, " ", M.t("team.review")),
      error,
      t.updated_by ? h("p", { class: "muted" }, M.t("team.last_set", { handle: t.updated_by.handle || t.updated_by.id }), t.updated_at ? " · " + formatTime(t.updated_at) : "") : null,
      h("div", { class: "actions" }, save));
    }

    // The pause (§6.2), with members:admin or line:lead: a form with a reason, or Clear pause.
    function pausePart(m, memberPath) {
      const reasonId = "member-pause-" + m.id;
      const reason = keyed("reason:" + m.id, h("input", { id: reasonId, placeholder: M.t("members.pause.placeholder"), autocomplete: "off" }));
      reason.value = (edits.get(m.id) || {}).reason || "";
      reason.addEventListener("input", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { reason: reason.value })); });
      const words = M.pauseWords || { effect: "", paused: "" };
      return m.paused
        ? h("div", { class: "member-pause" }, h("span", null, pausedText(m)),
          m.paused.by === m.id ? null : h("p", { class: "hint" }, words.paused),
          keyed("unpause:" + m.id, h("button", {
            type: "button",
            onclick: () => act(M.t("members.pause.clearing"), M.t("members.pause.cleared", { name: m.display_name }),
              () => M.api.patch(memberPath, { paused: null }), "reason:" + m.id),
          }, M.t("members.pause.clear"))))
        : h("form", {
          class: "inline-form member-pause",
          onsubmit: (e) => {
            e.preventDefault();
            if (!reason.value.trim()) { reason.focus(); return; }
            act(M.t("members.pause.pausing"), M.t("members.pause.done", { name: m.display_name }), () => M.api.patch(memberPath, { paused: { reason: reason.value.trim() } }), "unpause:" + m.id,
              () => { const d = edits.get(m.id); if (d) delete d.reason; });
          },
        }, h("label", { for: reasonId }, M.t("members.pause.label")), reason,
        h("button", { type: "submit" }, M.t("members.pause.submit")),
        h("p", { class: "hint" }, words.effect));
    }

    // Lifting (§6.2): the events of the isolation stay readable unless the
    // box is ticked; then they stay hidden from the agent for good. Unticked
    // by default (the maintainer, tsk-zwxtdfmdscf7).
    function liftForm(m, isoPath) {
      const hideId = "member-lift-hide-" + m.id;
      const hide = keyed("lift-hide:" + m.id, h("input", { type: "checkbox", id: hideId }));
      // The choice survives a redraw (another action, the presence refresh) as the isolation's reason does.
      hide.checked = !!(edits.get(m.id) || {}).liftHide;
      hide.addEventListener("change", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { liftHide: hide.checked })); });
      return h("form", {
        class: "inline-form member-lift",
        onsubmit: (e) => {
          e.preventDefault();
          const done = hide.checked ? M.t("members.isolate.lifted_hidden", { name: m.display_name }) : M.t("members.isolate.lifted", { name: m.display_name });
          act(M.t("members.isolate.lifting"), done,
            () => (hide.checked ? M.api.del(isoPath, { hide_isolation_events: true }) : M.api.del(isoPath)), "isolate-reason:" + m.id,
            () => { const d = edits.get(m.id); if (d) delete d.liftHide; });
        },
      },
      h("label", { class: "check", for: hideId }, hide, " ", M.t("members.isolate.hide")),
      h("p", { class: "hint" }, M.t("members.isolate.hide.hint")),
      keyed("lift:" + m.id, h("button", { type: "submit" }, M.t("members.isolate.lift"))));
    }

    // Isolation (§6.2): a human with members:admin stops any agent member at
    // once, whoever owns it, with a reason; lifted again by Lift isolation.
    function isolatePart(m, memberPath) {
      if (m.kind !== "agent" || ctx.me.kind !== "human" || !ctx.canAdmin) return null;
      const isoPath = memberPath + "/isolate";
      if (m.isolated) {
        return h("div", { class: "member-isolate" },
          h("p", null, h("span", { class: "badge member-isolated" }, M.t("members.isolated.badge")), " ",
            // The hub's own isolation has no member to name (§6.2, isolated.by: "hub").
            m.isolated.by === "hub"
              ? M.t("members.isolated.by_hub", { ago: formatAgo(m.isolated.since) })
              : M.tn("members.isolated.since", { by: M.dom.memberRef(ctx, m.isolated.by), ago: formatAgo(m.isolated.since), reason: m.isolated.reason })),
          liftForm(m, isoPath));
      }
      const reasonId = "member-isolate-" + m.id;
      const reason = keyed("isolate-reason:" + m.id, h("input", { id: reasonId, maxlength: "500", autocomplete: "off" }));
      reason.value = (edits.get(m.id) || {}).isolate || "";
      reason.addEventListener("input", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { isolate: reason.value })); });
      return h("form", {
        class: "inline-form member-isolate",
        onsubmit: (e) => {
          e.preventDefault();
          const why = reason.value.trim();
          if (!why) { reason.focus(); return; }
          if (!window.confirm(M.t("members.isolate.confirm", { name: m.display_name }))) return;
          act(M.t("members.isolate.isolating"), M.t("members.isolate.done", { name: m.display_name }),
            () => M.api.post(isoPath, { reason: why }), "lift:" + m.id,
            () => { const d = edits.get(m.id); if (d) delete d.isolate; });
        },
      }, h("label", { for: reasonId }, M.t("members.isolate.label")), reason,
      h("button", { type: "submit", class: "danger" }, M.t("members.isolate.submit")),
      h("p", { class: "hint" }, M.t("members.isolate.hint")));
    }

    // after(removed): what follows a removal that went through.
    function removePart(m, memberPath, self, after) {
      // A member with trust owner is removed only by an owner (owner_only, §2.3).
      if (M.trust.owner(m) && !ctx.isOwner) return null;
      return h("div", { class: "member-remove" }, h("button", {
        type: "button",
        class: "danger",
        onclick: async () => {
          const o = { name: m.display_name, project: ctx.project.name || ctx.slug };
          const ask = m.kind === "agent" ? M.t("members.remove.confirm_agent", o) : self ? M.t("members.remove.confirm_self", o) : M.t("members.remove.confirm_human", o);
          if (!window.confirm(ask)) return;
          open.delete(m.id);
          const removed = await act(M.t("members.removing"), M.t("members.removed", { name: m.display_name }), () => M.api.del(memberPath));
          if (removed && after) after(removed);
        },
      }, M.t("members.remove")));
    }

    // Whom one's own agent reports to, for its human owner whatever their
    // trust and role (§2.3): nobody, the owner (where a member here), or
    // another of the owner's agents in the project; only reports_to is
    // sent. A boss of another owner is not offered (that edge needs both
    // owners' consent, §6.2), and one set already stays chosen, marked,
    // so that saving does not end it unasked.
    function reportsToPart(m, memberPath) {
      if (!ownAgent(m) || m.removed_at) return null;
      const id = "owner-reports-" + m.id;
      const members = ctx.members || [];
      const circle = (boss) => {
        const byIdNow = Object.fromEntries(members.map((x) => [x.id, x]));
        const seen = new Set();
        for (let at = boss; at; at = byIdNow[at] && byIdNow[at].reports_to) {
          if (at === m.id) return true;
          if (seen.has(at)) return false;
          seen.add(at);
        }
        return false;
      };
      // Never a guest (§2.3), never one that would close a circle.
      const mine = members.filter((x) => !x.removed_at && x.id !== m.id && (x.id === ctx.me.id || ownAgent(x)) && !M.trust.guest(x) && !circle(x.id));
      const options = [["", M.t("members.reports.nobody")]].concat(mine.map((x) => [x.id, x.id === ctx.me.id
        ? M.t("members.reports.you", { name: x.display_name })
        : M.t("members.reports.agent", { name: x.display_name, handle: M.dom.handleOf(ctx, x) })]));
      if (m.reports_to && !options.some(([v]) => v === m.reports_to)) {
        options.push([m.reports_to, M.t("members.reports.other_owner", { name: ctx.nameOf(m.reports_to) })]);
      }
      const pick = keyed("owner-reports:" + m.id, h("select", { id }, options.map(([v, l]) => h("option", { value: v }, l))));
      pick.value = m.reports_to || "";
      const save = h("button", { type: "submit", class: "small" }, M.t("members.reports.save"));
      return h("form", {
        class: "inline-form owner-reports",
        onsubmit: async (e) => {
          e.preventDefault();
          const to = pick.value || null;
          if (to === (m.reports_to || null)) { status.done(); append(status.el, h("span", null, M.t("members.reports.unchanged"))); return; }
          save.disabled = true;
          await act(M.t("members.reports.saving"), to ? M.t("members.reports.saved", { name: m.display_name, boss: ctx.nameOf(to) })
            : M.t("members.reports.saved_nobody", { name: m.display_name }),
            () => M.api.patch(memberPath, { reports_to: to }), "owner-reports:" + m.id);
          save.disabled = false;
        },
      }, h("label", { for: id }, M.t("members.reports.label")), pick, save,
      h("p", { class: "hint" }, M.t("members.reports.hint")));
    }

    // Bridges (§2.3 "The bridge"): the connections that serve this agent and those it
    // serves, each with its purpose; End for either agent's owner or members:admin.
    // Its owner connects a new one: an agent of the project and what for (1–200
    // characters). Across owners the hub files the bridge owner's and the project's
    // consent and answers 202 with the first; nothing is connected until both said go.
    function bridgesPart(m, memberPath) {
      if (m.kind !== "agent" || !Array.isArray(m.bridges)) return null;
      const mine = ownAgent(m);
      const byId = ctx.memberById || {};
      const owns = (id) => !!byId[id] && byId[id].owner_id === ctx.me.id;
      const serving = m.bridging_for || [];
      if (!mine && !ctx.canAdmin && !m.bridges.some((c) => owns(c.member_id)) && !serving.some((c) => owns(c.member_id))) return null;
      // servedId: whose membership holds the connection (its bridges list).
      const line = (c, words, servedId) => h("li", { class: "bridge", "data-bridge": c.id }, words,
        c.cross_owner ? [" ", h("span", { class: "badge bridge-cross" }, M.t("bridges.cross_owner"))] : null,
        mine || ctx.canAdmin || owns(c.member_id) ? [" ", keyed("bridge-end:" + c.id, h("button", {
          type: "button", class: "small bridge-end", "aria-label": M.t("bridges.end_label", { purpose: c.purpose }),
          onclick: () => act(M.t("bridges.ending"), M.t("bridges.ended", { purpose: c.purpose }),
            () => M.api.del(ctx.base + "/members/" + encodeURIComponent(servedId) + "/bridges/" + encodeURIComponent(c.id)), "bridge-pick:" + m.id),
        }, M.t("bridges.end")))] : null);
      const lists = [
        m.bridges.length ? h("ul", { class: "bridges-list bridges-serving-this" }, m.bridges.map((c) =>
          line(c, M.tn("bridges.serves_this", { member: M.dom.memberRef(ctx, c.member_id), purpose: c.purpose }), m.id))) : null,
        serving.length ? h("ul", { class: "bridges-list bridges-serving-other" }, serving.map((c) =>
          line(c, M.tn("bridges.serves_other", { member: M.dom.memberRef(ctx, c.member_id), purpose: c.purpose }), c.member_id))) : null,
        !m.bridges.length && !serving.length ? h("p", { class: "muted" }, M.t("bridges.none")) : null,
      ];
      return h("div", { class: "member-bridges" }, h("h5", null, M.t("bridges.title")), lists, mine ? connectForm(m, memberPath) : null);
    }

    function connectForm(m, memberPath) {
      const choices = (ctx.members || []).filter((x) => x.kind === "agent" && x.id !== m.id && !x.removed_at && x.role !== "proxy"
        && !m.bridges.some((c) => c.member_id === x.id));
      if (!choices.length) return h("p", { class: "hint" }, M.t("bridges.no_choice"));
      const pickId = "bridge-pick-" + m.id, purposeId = "bridge-purpose-" + m.id;
      const pick = keyed("bridge-pick:" + m.id, h("select", { id: pickId }, choices.map((x) => h("option", { value: x.id }, x.display_name + " (@" + x.handle + ")"))));
      const purpose = keyed("bridge-purpose:" + m.id, h("input", { id: purposeId, maxlength: "200", autocomplete: "off", placeholder: M.t("bridges.purpose_placeholder") }));
      const draft = edits.get(m.id) || {};
      if (draft.bridgePick && choices.some((x) => x.id === draft.bridgePick)) pick.value = draft.bridgePick;
      purpose.value = draft.bridgePurpose || "";
      pick.addEventListener("change", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { bridgePick: pick.value })); });
      purpose.addEventListener("input", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { bridgePurpose: purpose.value })); });
      return h("form", {
        class: "member-bridge-connect field-stack",
        onsubmit: (e) => {
          e.preventDefault();
          if (!purpose.value.trim()) { purpose.focus(); return; }
          connect(m, memberPath, pick.value, purpose.value.trim());
        },
      }, h("label", { for: pickId }, M.t("bridges.pick")), pick,
      h("label", { for: purposeId }, M.t("bridges.purpose")), purpose,
      h("p", { class: "hint" }, M.t("bridges.hint")),
      h("button", { type: "submit" }, M.t("bridges.connect")));
    }

    // Said here rather than through act(): across owners two humans decide, the
    // bridge's owner and the project, and the 202 names only the first.
    async function connect(m, memberPath, bridgeId, purpose) {
      const label = M.t("bridges.connecting");
      const bridge = (ctx.memberById || {})[bridgeId];
      status.busy(M.t("members.act.busy", { action: label }));
      let answer;
      try {
        answer = await M.api.post(memberPath + "/bridges", { bridge: bridgeId, purpose });
      } catch (err) {
        status.fail(M.t("members.act.failed", { action: label }), refusal(err));
        return;
      }
      const draft = edits.get(m.id);
      if (draft) { delete draft.bridgePurpose; delete draft.bridgePick; }
      const done = bridge ? M.t("bridges.connected", { name: bridge.display_name }) : M.t("bridges.connected_plain");
      try {
        await reload();
        redraw("bridge-pick:" + m.id);
      } catch (err) {
        status.fail(M.t("members.act.refresh_failed", { done }), err);
        return;
      }
      status.done();
      append(status.el, isConsent(answer)
        ? h("span", { class: "flag" }, M.tn("bridges.waiting", { owner: bridge && bridge.owner_id ? M.dom.memberRef(ctx, bridge.owner_id) : M.t("members.consent.owner") }))
        : h("span", { class: "ok" }, done));
    }

    return { pausedText, act, ownAgent, credentialsPart, picturePart, teamForm, pausePart, isolatePart, removePart, reportsToPart, bridgesPart };
  }
  M.memberParts = memberParts;
  M.presenceNodes = presenceNodes;

  // args[0]: a member (/<owner>/<slug>/members/<id>[/<tab>], a mention's link):
  // that member's page (js/member-page.js). ?manage=<id> (its Actions menu):
  // the list with that member's Manage row open, for an admin.
  // The Team page's tabs (context/members.md f0ca2279): Members, this
  // list, and Organisation (js/org.js), each at its own project view.
  M.teamTabs = (ctx, chosen) => h("nav", { class: "view-tabs team-tabs", "aria-label": M.t("team.tabs.label") },
    [["members", M.t("team.tab.members")], ["organisation", M.t("team.tab.organisation")]].map(([k, label]) =>
      h("a", { href: ctx.link(k), class: "view-tab", "aria-current": k === chosen ? "page" : null }, label)));

  M.views.members = async function (ctx, root, args) {
    if (args && args[0] && M.memberPage) { await M.memberPage.page(ctx, root, args[0], args[1], args[2]); return; }
    const wanted = ctx.canAdmin ? M.route.current().query.get("manage") : null;
    const status = M.statusLine();
    const box = h("div", { class: "members-box" });
    // Rows open for managing stay open across a redraw; the one asked for opens at once.
    const open = new Set(wanted ? [wanted] : []);
    // member id -> its presence cell, updated in place by the refresh.
    const presenceCells = new Map();
    // focus key -> the element drawn for it, so focus survives a redraw.
    const focusables = new Map();
    const keyed = (key, el) => { focusables.set(key, el); el.setAttribute("data-focus", key); return el; };
    let items = ctx.members;
    const byId = () => Object.fromEntries(items.map((m) => [m.id, m]));
    const nameOf = (id) => { const m = byId()[id]; return m ? m.display_name : ctx.nameOf(id); };

    // The rows' unsaved edits, by member id: a redraw (an action elsewhere,
    // the presence refresh) rebuilds the form from them, not from the member.
    const edits = new Map();
    const P = memberParts(ctx, { status, keyed, edits, open, reload, redraw });
    const { act, pausedText, ownAgent } = P;

    // The Keep the Why commitment (docs/api.md §6.23), per instance: when it
    // confirmed, or by when it is to; past that without a confirmation a
    // mark, not an error. Only where the hub sends it (policy required).
    function ktwCell(m) {
      if (!("keep_the_why_unconfirmed" in m)) return "—";
      const lines = (m.instances || []).map((i) => h("div", { class: "ktw-instance" }, (i.label || i.id) + ": ",
        i.keep_the_why_acknowledged_at ? M.t("members.ktw.confirmed", { ago: formatAgo(i.keep_the_why_acknowledged_at) })
          : i.keep_the_why_acknowledge_by ? M.t("members.ktw.by", { when: formatTime(i.keep_the_why_acknowledge_by) }) : M.t("members.ktw.not_yet")));
      return [m.keep_the_why_unconfirmed ? h("span", { class: "mark ktw-unconfirmed" }, M.t("members.ktw.late")) : null, lines];
    }

    // Focus survives a redraw by key: the element drawn for the same key.
    function redraw(focusKey) {
      const active = document.activeElement;
      const key = focusKey || (active && active.getAttribute ? active.getAttribute("data-focus") : null);
      draw();
      const again = key && focusables.get(key);
      if (again) again.focus();
    }

    async function reload() {
      items = (await M.api.getAll(ctx.base + "/members")).items;
      M.withMembers(ctx, items);
    }

    // level: the member's row's, so the open card keeps its indent on a phone.
    function manage(m, rowId, level) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const self = m.id === ctx.me.id;
      // Without members:admin, one's own agent's row holds what its owner
      // sets (§2.3, §6.18, §19.4): whom it reports to, its rulebook, its
      // preferences switch.
      if (!ctx.canAdmin) {
        return h("tr", { class: "member-manage member-level-" + level, id: rowId, role: "row" }, h("td", { colspan: "99", role: "cell" },
          P.reportsToPart(m, memberPath),
          M.preferences && "owner_preferences" in m ? M.preferences.ownerToggle(ctx, m) : null,
          P.teamForm(m, memberPath), P.bridgesPart(m, memberPath)));
      }
      const parts = [editForm(m, memberPath, self)];
      if (m.kind === "agent") {
        // The briefing (§6.2), edited here; an admin is sent every member's.
        if (M.agentParts) parts.push(M.agentParts.briefingControl(ctx, m));
        if (ownAgent(m) && M.preferences && "owner_preferences" in m) parts.push(M.preferences.ownerToggle(ctx, m));
        parts.push(P.picturePart(m), P.teamForm(m, memberPath), P.credentialsPart(m), P.bridgesPart(m, memberPath), P.pausePart(m, memberPath), P.isolatePart(m, memberPath));
      }
      parts.push(P.removePart(m, memberPath, self, () => { if (self) M.route.go("/all"); }));
      return h("tr", { class: "member-manage member-level-" + level, id: rowId, role: "row" }, h("td", { colspan: "99", role: "cell" }, parts));
    }

    // Would m reporting to boss close a circle? Follow boss's chain upwards.
    function closesCircle(m, boss) {
      const all = byId();
      const seen = new Set();
      for (let at = boss; at; at = all[at] && all[at].reports_to) {
        if (at === m.id) return true;
        if (seen.has(at)) return false;
        seen.add(at);
      }
      return false;
    }

    // The membership as §6.2 lets an admin change it, in one form; only the
    // fields that changed are sent, in one PATCH.

    function editForm(m, memberPath, self) {
      const id = (what) => "member-" + what + "-" + m.id;
      const draft = edits.get(m.id) || {};
      const keep = (k, v) => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { [k]: v })); };
      // Trust and role (§2.3). Owner only for a human; granting owner or admin
      // or the role proxy, and lowering an owner, only from an owner (owner_only):
      // a non-owner is not offered them. The member's own trust and role stay
      // offered (a project role included), so saving other fields never changes them.
      const trustOffered = (ctx.isOwner ? M.trust.TRUSTS : M.trust.owner(m) ? ["owner"] : ["member", "guest"])
        .filter((t) => t !== "owner" || m.kind === "human");
      if (m.trust && !trustOffered.includes(m.trust)) trustOffered.push(m.trust);
      const trust = keyed("trust:" + m.id, h("select", { id: id("trust") }, trustOffered.map((t) => h("option", { value: t }, t))));
      trust.value = draft.trust !== undefined ? draft.trust : m.trust;
      const role = keyed("role:" + m.id, h("select", { id: id("role") }));
      // The role proxy goes with trust admin only (proxy_needs_admin): with any
      // other trust it is not offered, and a proxy whose trust changes becomes a coder.
      const fillRoles = () => {
        const wanted = role.value || (draft.role !== undefined ? draft.role : m.role);
        const proxyOk = trust.value === "admin" && (ctx.isOwner || m.role === "proxy");
        const offered = M.trust.ROLES.filter((r) => r !== "proxy" || proxyOk);
        if (m.role && m.role !== "proxy" && !offered.includes(m.role)) offered.push(m.role);
        M.trust.fillRoles(role, offered, wanted, offered.includes(m.role) ? m.role : "coder");
      };
      const roleHelp = M.trust.roleHint(role);
      fillRoles();
      trust.addEventListener("change", () => { keep("trust", trust.value); fillRoles(); });
      // The current boss stays offered even if it is not in the list read.
      const others = items.filter((x) => x.id !== m.id);
      const listed = !m.reports_to || others.some((x) => x.id === m.reports_to);
      // A guest is never reported to (§2.3).
      const reports = keyed("reports:" + m.id, h("select", { id: id("reports") }, h("option", { value: "" }, M.t("members.reports.nobody")),
        others.filter((x) => !M.trust.guest(x) || x.id === m.reports_to).map((x) => h("option", { value: x.id }, M.t("members.reports.member", { name: x.display_name, handle: M.dom.handleOf(ctx, x) }))),
        listed ? null : h("option", { value: m.reports_to }, M.t("members.reports.unlisted", { name: nameOf(m.reports_to) }))));
      reports.value = m.reports_to || "";
      // A drafted boss who has left since is dropped, and said: a select that
      // fell back to "nobody" would clear the member's boss on the next save.
      let bossGone = null;
      if (draft.reports !== undefined) {
        if (!draft.reports || others.some((x) => x.id === draft.reports) || draft.reports === m.reports_to) reports.value = draft.reports;
        else { bossGone = nameOf(draft.reports); delete draft.reports; }
      }
      const areas = keyed("areas:" + m.id, h("input", { id: id("areas"), placeholder: M.t("members.edit.areas.placeholder"), autocomplete: "off", spellcheck: "false" }));
      areas.value = draft.areas !== undefined ? draft.areas : (m.areas || []).join(", ");
      const caps = CAPABILITIES.map(([cap, label]) => {
        const box = h("input", { type: "checkbox", id: id("cap-" + cap) });
        box.checked = draft["cap:" + cap] !== undefined ? draft["cap:" + cap] : (m.capabilities || []).includes(cap);
        box.addEventListener("change", () => keep("cap:" + cap, box.checked));
        return { cap, box, label: label() };
      });
      role.addEventListener("change", () => keep("role", role.value));
      reports.addEventListener("change", () => keep("reports", reports.value));
      areas.addEventListener("input", () => keep("areas", areas.value));
      // Each field says its own error, tied to it (as on the account view).
      const errorOf = (what) => h("p", { class: "field-error", id: id(what) + "-error", role: "alert" });
      const errors = { trust: errorOf("trust"), role: errorOf("role"), reports: errorOf("reports"), areas: errorOf("areas") };
      if (bossGone) errors.reports.textContent = M.t("members.edit.boss_gone", { name: bossGone });
      [[trust, "trust"], [role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => f.setAttribute("aria-describedby", id(k) + "-error"
        + (k === "areas" ? " " + id("areas") + "-hint" : k === "role" ? " " + roleHelp.id : "")));
      const clearErrors = () => [[trust, "trust"], [role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => { errors[k].textContent = ""; f.removeAttribute("aria-invalid"); });
      const fieldFail = (f, k, text) => { errors[k].textContent = text; f.setAttribute("aria-invalid", "true"); status.fail(M.t("members.edit.not_saved"), { message: text }); f.focus(); };
      const save = h("button", { type: "submit" }, M.t("members.edit.save"));
      return h("form", {
        class: "member-edit",
        onsubmit: async (e) => {
          e.preventDefault();
          if (save.disabled) return;
          clearErrors();
          const body = {};
          if (trust.value !== m.trust) body.trust = trust.value;
          if (role.value !== m.role) body.role = role.value;
          const boss = reports.value || null;
          if (boss !== (m.reports_to || null)) {
            if (boss && closesCircle(m, boss)) { fieldFail(reports, "reports", CYCLE()); return; }
            body.reports_to = boss;
          }
          const list = [...new Set(areas.value.split(",").map((a) => a.trim()).filter(Boolean))];
          if (list.some((a) => !areaOk(a))) { fieldFail(areas, "areas", BAD_AREA()); return; }
          if (list.join("\n") !== (m.areas || []).join("\n")) body.areas = list;
          // Capabilities this page does not offer are kept as they are.
          const kept = (m.capabilities || []).filter((c) => !CAPABILITIES.some(([k]) => k === c));
          const capList = kept.concat(caps.filter((c) => c.box.checked).map((c) => c.cap));
          if ([...capList].sort().join() !== [...(m.capabilities || [])].sort().join()) body.capabilities = capList;
          if (!Object.keys(body).length) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("members.unchanged"))); return; }
          const said = { trust: () => M.t("members.edit.said.trust"), role: () => M.t("members.edit.said.role"), reports_to: () => M.t("members.edit.said.reports_to"),
            areas: () => M.t("members.edit.said.areas"), capabilities: () => M.t("members.edit.said.capabilities") };
          save.disabled = true;
          const saved = await act(M.t("members.edit.saving"), M.t("members.edit.saved", { name: m.display_name, fields: M.fmt.list(Object.keys(body).map((k) => said[k]())) }),
            () => M.api.patch(memberPath, body), "role:" + m.id, () => edits.delete(m.id));
          save.disabled = false;
          // Demoting oneself changes what this page may offer: re-render it.
          if (saved === true && self && (body.trust || body.role)) ctx.refresh();
        },
      },
      h("div", { class: "member-fields" },
        h("label", { for: id("trust") }, M.t("members.edit.trust")), trust, errors.trust,
        h("label", { for: id("role") }, M.t("members.edit.role")), role, roleHelp, errors.role,
        h("label", { for: id("reports") }, M.t("members.edit.reports")), reports, errors.reports,
        h("label", { for: id("areas") }, M.t("members.edit.areas")), areas,
        h("p", { class: "hint", id: id("areas") + "-hint" }, M.t("members.edit.areas.hint")),
        errors.areas,
        h("fieldset", { class: "member-caps" }, h("legend", null, M.t("members.edit.capabilities")),
          caps.map((c) => h("label", { class: "check", for: c.box.id }, c.box, " " + c.label)))),
      h("div", { class: "actions" }, save));
    }

    // A chat per entry: one's own agent's direct chat, anyone else a group
    // chat with them chosen (§9.2).
    function chatLink(m) {
      if (m.id === ctx.me.id || m.removed_at || ctx.me.kind !== "human") return null;
      // A group chat as the Chat list offers one (js/chat.js): not in a closed
      // project, not for a human guest (§2.3, §9.2).
      const groupOk = groupsServed && !M.trust.guest(ctx) && ctx.project.state !== "archived";
      const href = ownAgent(m) ? ctx.link("chat", m.id) : groupOk ? ctx.link("chat", "new") + "?with=" + encodeURIComponent(m.id) : null;
      return href ? h("a", { class: "button-link member-chat", href, "aria-label": M.t("members.chat.label", { name: m.display_name }) }, M.t("members.chat")) : null;
    }

    function nameCell(m) {
      return h("th", { scope: "row", role: "rowheader", "data-label": M.t("members.col.name"), tabindex: m.id === wanted ? "-1" : null },
        h("span", { class: "member-name" }, M.dom.memberRef(ctx, m.id, { avatar: 20 })), h("span", { class: "muted" }, " @" + M.dom.handleOf(ctx, m)),
        m.kind === "human" && !m.removed_at && m.language
          ? h("p", { class: "muted member-language" }, M.t("members.language", { language: m.language === "de" ? "Deutsch" : "English" })) : null,
        ownerOutside(ctx, m) ? h("span", { class: "badge member-owner-outside", title: M.t("members.owner_outside.title") }, M.t("members.owner_outside.badge")) : null,
        m.kind === "agent" && m.isolated
          ? h("span", { class: "badge member-isolated", title: M.t("members.isolated.title", { reason: m.isolated.reason }) }, M.t("members.isolated.badge")) : null,
        // What a lifted isolation hid from it (§6.2 isolation_windows), read by whoever reads isolated.
        m.kind === "agent" && (m.isolation_windows || []).length
          ? h("p", { class: "muted member-hidden-windows" }, M.t("members.isolation_windows", {
            count: m.isolation_windows.length,
            // A seq is an id, not a quantity: written as the hub gives it, not formatted.
            ranges: m.isolation_windows.map((w) => M.t("members.isolation_window", { from: String(w.from_seq), to: String(w.to_seq) })).join(", "),
          })) : null,
        // Whose work it continues and where the hand-over is (§6.2), for every reader.
        m.kind === "agent" && (m.takes_over || m.handover)
          ? h("p", { class: "muted member-takes-over" }, M.join.takeOverWords(ctx, m)) : null,
        m.kind === "agent" && m.briefing != null
          ? h("span", { class: "badge briefing-override", title: M.t("members.own_briefing.title") }, M.t("members.own_briefing")) : null);
    }

    // The project's hierarchy follows trust (the maintainer, 2026-10-31): owner,
    // admin, member, guest, each a level deeper; a level nobody holds leaves no
    // empty step, the next moves up. `tiers`: the levels the list shows now.
    // A trust the dashboard does not know counts as member.
    const trustOf = (m) => (M.trust.TRUSTS.includes(m.trust) ? m.trust : "member");
    let tiers = M.trust.TRUSTS;
    const levelOf = (m) => Math.max(0, tiers.indexOf(trustOf(m)));

    function table(kind, list, columns) {
      const headingId = "members-" + kind;
      return [h("h3", { id: headingId }, M.t("members.all", { count: list.length })),
        h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-labelledby": headingId },
          h("table", { class: "members", role: "table", "aria-labelledby": headingId },
            h("thead", { role: "rowgroup" }, h("tr", { role: "row" },
              h("th", { scope: "col", role: "columnheader" }, M.t("members.col.name")),
              columns.map((c) => h("th", { scope: "col", role: "columnheader" }, c.title)),
              h("th", { scope: "col", role: "columnheader" }, M.t("members.col.actions")))),
            h("tbody", { role: "rowgroup" }, list.map((m) => {
              const expanded = open.has(m.id);
              const rowId = "member-manage-" + m.id;
              const row = h("tr", { class: "member member-" + m.kind + " member-level-" + levelOf(m) + (m.paused ? " paused" : "") + (m.id === wanted ? " wanted" : ""),
                role: "row", "data-member": m.id, "data-level": String(levelOf(m)) },
                nameCell(m),
                columns.map((c) => {
                  const td = h("td", { "data-label": c.title, role: "cell" }, c.cell(m));
                  if (c.presence) presenceCells.set(m.id, td);
                  return td;
                }),
                h("td", { class: "member-actions", "data-label": M.t("members.col.actions"), role: "cell" }, chatLink(m),
                  !ctx.canAdmin && !P.ownAgent(m) ? null : keyed("manage:" + m.id, h("button", {
                    type: "button",
                    class: "small",
                    "aria-expanded": expanded ? "true" : "false",
                    "aria-controls": expanded ? rowId : null,
                    "aria-label": expanded ? M.t("members.manage.done_label", { name: m.display_name }) : M.t("members.manage.label", { name: m.display_name }),
                    onclick: () => {
                      // Done closes the row and drops its unsaved edits.
                      if (open.has(m.id)) { open.delete(m.id); edits.delete(m.id); redraw("manage:" + m.id); } else { open.add(m.id); redraw((ctx.canAdmin ? "role:" : "owner-reports:") + m.id); }
                    },
                  }, expanded ? M.t("members.manage.done") : M.t("members.manage")))));
              return expanded ? [row, manage(m, rowId, levelOf(m))] : row;
            }))))];
    }

    // Only my agents (the maintainer, 2026-10-30): the agents the viewer
    // owns, without the humans; remembered per viewer in this browser.
    const mineKey = "maity.members.mine." + ctx.me.id;
    let mineOnly = false;
    if (ctx.me.kind === "human") {
      try { mineOnly = window.localStorage.getItem(mineKey) === "1"; } catch (err) { mineOnly = false; }
    }
    function mineFilter() {
      if (ctx.me.kind !== "human") return null;
      const box = keyed("mine", h("input", { type: "checkbox", id: "members-mine" }));
      box.checked = mineOnly;
      box.addEventListener("change", () => {
        mineOnly = box.checked;
        try { if (mineOnly) window.localStorage.setItem(mineKey, "1"); else window.localStorage.removeItem(mineKey); } catch (err) { /* this browser keeps nothing */ }
        redraw("mine");
      });
      return h("div", { class: "members-filter" }, h("label", { class: "check", for: "members-mine" }, box, " " + M.t("members.filter.mine")));
    }

    function draw() {
      presenceCells.clear();
      focusables.clear();
      // One list, the project's hierarchy (the maintainer, 2026-10-31): by trust,
      // owners at the top, then admins, members and guests, each a level deeper;
      // within a level the hub's order. Only my agents keeps one's own agents.
      const shown = items.filter((m) => (mineOnly ? m.kind === "agent" && ownAgent(m) : true));
      tiers = M.trust.TRUSTS.filter((t) => shown.some((m) => trustOf(m) === t));
      const list = shown.map((m, i) => ({ m, i })).sort((a, b) => levelOf(a.m) - levelOf(b.m) || a.i - b.i).map((x) => x.m);
      const agents = shown.filter((m) => m.kind === "agent");
      const role = { title: M.t("members.col.role"), cell: (m) => M.trust.words(m) };
      const presence = { title: M.t("members.col.presence"), presence: true, cell: (m) => presenceNodes(m, ctx.canAdmin, ctx) };
      const joined = { title: M.t("members.col.joined"), cell: (m) => formatTime(m.joined_at) };
      // An agent's own columns; a human's read "—".
      const agentOnly = (cell) => (m) => (m.kind === "agent" ? cell(m) : "—");
      const owner = { title: M.t("members.col.owner"), cell: agentOnly((m) => M.dom.memberRef(ctx, m.owner ? Object.assign({ member_id: m.owner_id }, m.owner) : m.owner_id)) };
      const paused = { title: M.t("members.col.paused"), cell: agentOnly((m) => pausedText(m) || "—") };
      const ktw = { title: M.t("members.col.ktw"), cell: agentOnly(ktwCell) };
      const hasKtw = agents.some((m) => "keep_the_why_unconfirmed" in m);
      append(clear(box), mineFilter(), h("div", { class: "members-list" }, list.length
        ? table("all", list, [role, owner, presence, joined, paused].concat(hasKtw ? [ktw] : []))
        : [h("h3", { id: "members-all" }, M.t("members.all", { count: 0 })), h("p", { class: "muted" }, mineOnly ? M.t("members.filter.mine_none") : M.t("members.agents.none"))]));
    }

    // The Chat button may start a group chat with anyone (§9.2).
    const groupsServed = !!M.groupChat;
    const ownHere = ctx.me.kind === "human" && items.some(ownAgent);
    // Bringing someone in (the maintainer, 2026-10-31): a person on the invitations
    // page, an agent on Your agents' Join an agent, each with this project chosen. A guest brings no agent (§3.1).
    const inviteUser = ctx.canAdmin && ctx.me.kind === "human"
      ? h("a", { class: "button primary members-invite-user", href: "/invite?project=" + encodeURIComponent(ctx.slug) }, M.t("members.invite_user")) : null;
    const joinAgent = ctx.me.kind === "human" && !M.trust.guest(ctx)
      ? h("a", { class: "button primary members-join-agent", href: "/agents?project=" + encodeURIComponent(ctx.slug) }, M.t("members.join_agent")) : null;
    append(root, M.teamTabs(ctx, "members"), h("h2", null, M.t("members.title")),
      inviteUser || joinAgent ? h("div", { class: "actions members-add" }, inviteUser, joinAgent) : null,
      h("p", { class: "muted" }, M.t("members.hint", { project: ctx.project.name || ctx.slug }),
        ctx.canAdmin ? [" ", M.t("members.hint.admin")] : null,
      // A guest brings no agent (§3.1): no way there said to them.
      ownHere || (ctx.me.kind === "human" && !M.trust.guest(ctx))
        ? [" ", h("a", { href: ctx.link("agents") }, ownHere ? M.t("members.agents_link.own") : M.t("members.agents_link.add"))] : null),
      status.el, box);
    draw();
    // A member marked by the URL keeps the focus across this redraw.
    const wantedHead = () => { const tr = Array.from(box.querySelectorAll("tr.member")).find((x) => x.getAttribute("data-member") === wanted); return tr && tr.childNodes[0]; };
    // The member asked for (?manage=<id>): its row open, the focus on its
    // first field; an id that is no member here is said.
    if (wanted) {
      const first = () => focusables.get("role:" + wanted) || wantedHead();
      // Looked up when focused: the Chat redraw may have drawn the row again.
      if (wantedHead()) window.setTimeout(() => { if (first()) first().focus(); }, 0);
      else append(status.el, h("span", null, M.t("members.no_such", { id: wanted })));
    }
    ctx.every(PRESENCE_MS, async () => {
      try {
        const fresh = (await M.api.getAll(ctx.base + "/members")).items;
        const ids = (list) => list.map((m) => m.id).sort().join(" ");
        const same = ids(fresh) === ids(items);
        items = fresh;
        // Someone joined or left: redraw (focus kept); else presence in place.
        // The page's member list follows, so every name on it — a global
        // name where a handle is now shared (§6.3) — agrees with the rows.
        if (!same) {
          M.withMembers(ctx, fresh);
          redraw();
          return;
        }
        fresh.forEach((m) => { const td = presenceCells.get(m.id); if (td) append(clear(td), presenceNodes(m, ctx.canAdmin, ctx)); });
        status.done();
      } catch (err) {
        status.fail(M.t("members.refresh_failed"), err);
      }
    });
  };
})(window.Maity);
