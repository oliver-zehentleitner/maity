// (4) Members (#/<owner>/<slug>/members): everyone in the project, humans and
// agents, with role, owner, presence, when they joined and whether they are
// paused (docs/api.md §6.2). With members:admin each row can be managed: the
// role, an agent's pause, and removal. Where the hub sends them (an admin,
// or an agent's owner on their own agents), an agent's owner and a
// credentials summary are shown: counts and times only.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRESENCE_LABELS = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };
  // Presence emits no event (docs/api.md §5.3): the view re-reads it and
  // updates the presence cells in place, so focus and forms stay.
  const PRESENCE_MS = 30000;
  // The hub's refusals, in words; anything else is shown as it comes.
  // The hub's refusals in words, by field and reason; a reason the page
  // does not know is shown as it comes.
  const REFUSALS = {
    "trust:last_owner": "The project's last owner cannot be demoted or removed.",
    "member:last_owner": "The project's last owner cannot be demoted or removed.",
    "trust:humans_only": "Only a human can be an owner.",
    "trust:unknown": "Not a trust of this hub.",
    "role:unknown": "Not a role of this hub.",
    "role:proxy_needs_admin": "A proxy holds trust admin, and only that.",
    "reports_to:guest": "A guest is never reported to.",
    "reports_to:cycle": "That would close a circle: they would end up reporting to themselves.",
    "reports_to:not_a_member": "Reports to someone who is not a member of this project.",
    "areas:invalid_path": "An area is a repository path like hub/ or docs/api.md, without ..",
    "areas:too_long": "At most 50 areas.",
    "capabilities:unknown": "A capability this hub does not know.",
    "capabilities:too_long": "At most 20 capabilities.",
    "paused.reason:string_too_long": "The pause's reason is too long.",
  };
  const CYCLE = REFUSALS["reports_to:cycle"];
  const BAD_AREA = REFUSALS["areas:invalid_path"];
  // The hub's rules for an area (hub/src/maity_hub/routes/members.py).
  const AREA = /^[A-Za-z0-9._/-]{1,255}$/;
  const areaOk = (a) => AREA.test(a) && !a.startsWith("..") && !("/" + a + "/").includes("/../");
  const CAPABILITIES = [["tag", "May tag a release (tag)"]];

  // The hub names each bad field (details.fields); said in words.
  function refusal(err) {
    if (err.code === "forbidden" && err.details && err.details.reason === "humans_only") {
      return { message: "only a human may make this change" };
    }
    // §2.3: granting owner, admin or proxy, and lowering or removing an owner.
    if (err.code === "forbidden" && err.details && err.details.reason === "owner_only") {
      return { message: "only an owner may grant trust owner or admin or the role proxy, or lower or remove an owner" };
    }
    // §6.25: the person whose namespace holds the project stays its owner.
    if (err.code === "namespace_owner") {
      return { message: "the project lives in this person's namespace, so they stay an owner; transfer it to someone else first (Project settings)" };
    }
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    const said = Object.entries(fields).map(([f, reason]) => REFUSALS[f + ":" + reason] || f.replace("_", " ") + ": " + reason);
    return { message: said.join(" ") };
  }

  // A change an agent's rule holds for a human's go answers 202 with the
  // consent request (docs/api.md §2.3), not with the member.
  const isConsent = (answer) => !!answer && answer.class === "consent" && /^req-/.test(answer.id || "");

  function credentialsText(c) {
    if (!c) return "—";
    const parts = [c.active + " active"];
    if (c.never_resumed) parts.push(c.never_resumed + " never used");
    if (c.revoked_recent) parts.push(c.revoked_recent + " revoked in the last 30 days");
    if (c.last_used_at) parts.push("last used " + formatAgo(c.last_used_at) + (c.last_used_via === "bearer" ? " (bearer token)" : ""));
    return parts.join(" · ");
  }

  // A presence the page knows gets its dot; anything else is said as it comes.
  function presenceNodes(m, warn) {
    const known = Object.prototype.hasOwnProperty.call(PRESENCE_LABELS, m.presence);
    return [known ? h("span", { class: "dot " + m.presence, "aria-hidden": "true" }) : null, known ? " " : null,
      known ? PRESENCE_LABELS[m.presence] : String(m.presence || "unknown"),
      M.dom.isSilentAgent(m) ? [" · ", M.dom.silentSince(m, warn)]
        : m.last_seen_at && m.presence !== "online" ? h("span", { class: "muted" }, " · seen " + formatAgo(m.last_seen_at)) : null];
  }

  // args[0]: a member to show (#/<owner>/<slug>/members/<id>, a mention's link):
  // its row is marked and takes the focus.
  M.views.members = async function (ctx, root, args) {
    // "join" asks for the join panel open (#/<owner>/<slug>/members/join).
    const joinAsked = !!(args && args[0] === "join");
    const wanted = joinAsked ? null : args && args[0];
    const status = M.statusLine();
    const box = h("div", { class: "members-box" });
    // Rows open for managing stay open across a redraw.
    const open = new Set();
    // #/<owner>/<slug>/members/<id>/rulebook (a join's quota refusal): that row open, at its rulebook.
    const rulebookAsked = !!(wanted && args[1] === "rulebook");
    // #/<owner>/<slug>/members/<id>/picture: the account's link to an agent's picture.
    const pictureAsked = !!(wanted && args[1] === "picture");
    if (rulebookAsked || pictureAsked) open.add(wanted);
    // member id -> its presence cell, updated in place by the refresh.
    const presenceCells = new Map();
    // focus key -> the element drawn for it, so focus survives a redraw.
    const focusables = new Map();
    const keyed = (key, el) => { focusables.set(key, el); el.setAttribute("data-focus", key); return el; };
    let items = ctx.members;
    const byId = () => Object.fromEntries(items.map((m) => [m.id, m]));
    const nameOf = (id) => { const m = byId()[id]; return m ? m.display_name : ctx.nameOf(id); };

    // Who paused it is a member like any other: a link to them.
    function pausedText(m) {
      const p = m.paused;
      if (!p) return "";
      const by = p.by === m.id ? "paused itself" : ["paused by ", M.dom.memberRef(ctx, p.by)];
      return [by, " " + formatAgo(p.since) + (p.reason ? ": " + p.reason : "")];
    }

    // The Keep the Why commitment (docs/api.md §6.23), per instance: when it
    // confirmed, or by when it is to; past that without a confirmation a
    // mark, not an error. Only where the hub sends it (policy required).
    function ktwCell(m) {
      if (!("keep_the_why_unconfirmed" in m)) return "—";
      const lines = (m.instances || []).map((i) => h("div", { class: "ktw-instance" }, (i.label || i.id) + ": ",
        i.keep_the_why_acknowledged_at ? "confirmed " + formatAgo(i.keep_the_why_acknowledged_at)
          : i.keep_the_why_acknowledge_by ? "to confirm by " + formatTime(i.keep_the_why_acknowledge_by) : "not confirmed yet"));
      return [m.keep_the_why_unconfirmed ? h("span", { class: "mark ktw-unconfirmed" }, "Keep the Why not confirmed in time") : null, lines];
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
    }

    // A write and the re-read after it are told apart: a write that went
    // through is said as done even when the list cannot be read afterwards.
    // `settled` runs once the hub has taken the call (a change or a consent
    // request), before the list is read again and drawn. The outcome is said
    // once the list is drawn again, so "Saved" means the rows show it and
    // nothing is replaced under the next click.
    async function act(label, done, call, focusKey, settled) {
      status.busy(label + "…");
      let answer;
      try {
        answer = await call();
      } catch (err) {
        status.fail(label + " failed: ", refusal(err));
        return false;
      }
      if (settled) settled();
      try {
        await reload();
        redraw(focusKey);
      } catch (err) {
        status.fail(done + " Could not refresh: ", err);
        return isConsent(answer) ? "consent" : true;
      }
      status.done();
      // Waiting for a human's go is no change yet: said as such.
      append(status.el, isConsent(answer)
        ? h("span", { class: "flag" }, "Not changed yet: waiting for " + (answer.to === "owner" ? "the owner" : ctx.nameOf(answer.to))
          + "'s consent (" + answer.id + (answer.title ? ", " + answer.title : "") + ").")
        : h("span", { class: "ok" }, done));
      return isConsent(answer) ? "consent" : true;
    }

    // A row opens for a member admin, and for a human on their own agents
    // (tsk-7v2snhk002ak): what the Agents page showed them, in one place.
    const ownAgent = (m) => m.kind === "agent" && ctx.me.kind === "human" && m.owner_id === ctx.me.id;
    const mayOpen = (m) => ctx.canAdmin || ownAgent(m);

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
      };
      const fill = (got, refocus) => {
        append(clear(slot), got.error
          ? h("div", { class: "credentials" }, h("h4", { class: "credentials-title" }, "Credentials"), M.errorBox(got.error))
          : P.credentials(ctx, m, got.list, revoked));
        const head = refocus && slot.querySelector(".credentials-title");
        if (head) { head.setAttribute("tabindex", "-1"); head.focus(); }
      };
      function load(refocus) {
        const known = credsOf.get(m.id);
        if (known && !known.then) { fill(known, refocus); return; }
        if (!refocus) append(slot, h("p", { class: "muted" }, "Reading the credentials…"));
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
        act("Changing the picture", words, () => Promise.resolve(answer), null);
      };
      const fill = (profile) => append(clear(slot), h("h4", { class: "member-picture-title" }, "Picture"),
        profile.error ? M.errorBox(profile.error)
          : M.pictureEditor(Object.assign({}, m, profile), "/agents/" + encodeURIComponent(m.id) + "/avatar", false, changed));
      const known = profileOf.get(m.id);
      if (known && !known.then) { fill(known); return slot; }
      append(slot, h("p", { class: "muted" }, "Reading the picture…"));
      const reading = known || ownProfile(m.id)
        .then((a) => ({ avatar_url: a.avatar_url, avatar_source: a.avatar_source }), (error) => ({ error }))
        .then((got) => { profileOf.set(m.id, got); return got; });
      profileOf.set(m.id, reading);
      reading.then((got) => { if (slot.isConnected !== false) fill(got); });
      return slot;
    }

    // The team's rulebook (docs/api.md §6.18, tsk-xzbk67raztm0): for the
    // human who owns the agent profile only, as the hub allows it; other
    // viewers see none of it. Only the fields that changed are sent.
    const DISTRIBUTION = [["free", "Free: any instance claims"], ["lead", "Lead: the lead hands cards out"], ["round_robin", "Round robin: in turn"]];
    const WAKE = [["all", "All listening instances"], ["lead", "Only the lead"], ["next_free", "The least busy instance"]];
    function teamForm(m, memberPath) {
      if (!ownAgent(m) || !("team" in m)) return null;
      const t = Object.assign({ max_instances: 1, distribution: "free", lead_instance: null, wake: "all", review_within_team: false }, m.team || {});
      const id = (what) => "team-" + what + "-" + m.id;
      const active = (m.instances || []).filter((i) => !i.revoked_at);
      const max = keyed("team-max:" + m.id, h("input", { id: id("max"), type: "number", min: "1", max: "16", step: "1", "aria-describedby": id("max") + "-hint" }));
      max.value = String(t.max_instances);
      const pick = (what, list, value) => {
        const s = h("select", { id: id(what) }, list.map(([v, l]) => h("option", { value: v }, l)));
        s.value = value;
        return s;
      };
      const distribution = pick("distribution", DISTRIBUTION, t.distribution);
      const wake = pick("wake", WAKE, t.wake);
      // A lead revoked since stays chosen, marked, so saving another field does not clear it.
      const gone = t.lead_instance && !active.some((i) => i.id === t.lead_instance) ? [[t.lead_instance, "#" + t.lead_instance + " (revoked)"]] : [];
      const lead = pick("lead", [["", "none"]].concat(active.map((i) => [i.id, i.label ? i.label + " (#" + i.id + ")" : "#" + i.id]), gone), t.lead_instance || "");
      const review = h("input", { id: id("review"), type: "checkbox" });
      review.checked = !!t.review_within_team;
      const error = h("p", { class: "field-error", id: id("error"), role: "alert" });
      const save = h("button", { type: "submit" }, "Save the rulebook");
      return h("form", {
        class: "member-team",
        "aria-labelledby": id("title"),
        onsubmit: async (e) => {
          e.preventDefault();
          error.textContent = "";
          const n = Number(max.value);
          if (!Number.isInteger(n) || n < 1 || n > 16) { error.textContent = "At most instances: a whole number from 1 to 16."; max.focus(); return; }
          if ((distribution.value === "lead" || wake.value === "lead") && !lead.value) {
            error.textContent = "A lead is needed while cards or wakes go to the lead."; lead.focus(); return;
          }
          const want = { max_instances: n, distribution: distribution.value, lead_instance: lead.value || null, wake: wake.value, review_within_team: review.checked };
          const team = {};
          Object.keys(want).forEach((k) => { if (want[k] !== t[k]) team[k] = want[k]; });
          if (!Object.keys(team).length) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
          save.disabled = true;
          await act("Saving the rulebook", "The rulebook of " + m.display_name + " is saved.", () => M.api.patch(memberPath, { team }), "team-max:" + m.id);
          save.disabled = false;
        },
      },
      h("h4", { id: id("title") }, "Team rulebook"),
      h("p", { class: "hint" }, "How many instances of your agent may run here and how they share the work. Only you, its owner, set this."),
      h("label", { for: id("max") }, "At most instances"), max,
      h("p", { class: "hint", id: id("max") + "-hint" }, active.length + (active.length === 1 ? " instance is" : " instances are") + " active now. Lowering the limit stops none; it refuses new ones."),
      h("label", { for: id("distribution") }, "Cards assigned to the team"), distribution,
      h("label", { for: id("lead") }, "Lead instance"), lead,
      h("label", { for: id("wake") }, "An event for the team wakes"), wake,
      h("label", { class: "check", for: id("review") }, review, " One instance may review another's work"),
      error,
      t.updated_by ? h("p", { class: "muted" }, "Last set by @" + (t.updated_by.handle || t.updated_by.id) + (t.updated_at ? " · " + formatTime(t.updated_at) : "")) : null,
      h("div", { class: "actions" }, save));
    }

    function manage(m, rowId) {
      const memberPath = ctx.base + "/members/" + encodeURIComponent(m.id);
      const self = m.id === ctx.me.id;
      // Their own agent's owner, without members:admin: its credentials and
      // whether it gets their preferences, nothing that changes the membership.
      if (!ctx.canAdmin) {
        return h("tr", { class: "member-manage", id: rowId, role: "row" }, h("td", { colspan: "99", role: "cell" },
          picturePart(m),
          teamForm(m, ctx.base + "/members/" + encodeURIComponent(m.id)),
          credentialsPart(m),
          M.preferences && "owner_preferences" in m ? M.preferences.ownerToggle(ctx, m) : null));
      }
      const parts = [editForm(m, memberPath, self)];
      if (m.kind === "agent") {
        // The briefing (§6.2), edited here; where the hub knows briefings.
        if ("briefing" in m && M.agentParts) parts.push(M.agentParts.briefingControl(ctx, m));
        if (ownAgent(m) && M.preferences && "owner_preferences" in m) parts.push(M.preferences.ownerToggle(ctx, m));
        parts.push(picturePart(m));
        parts.push(teamForm(m, memberPath));
        parts.push(credentialsPart(m));
      }
      if (m.kind === "agent") {
        const reasonId = "member-pause-" + m.id;
        const reason = keyed("reason:" + m.id, h("input", { id: reasonId, placeholder: "Why it stops, e.g. quota", autocomplete: "off" }));
        reason.value = (edits.get(m.id) || {}).reason || "";
        reason.addEventListener("input", () => { edits.set(m.id, Object.assign(edits.get(m.id) || {}, { reason: reason.value })); });
        const words = M.pauseWords || { effect: "", paused: "" };
        parts.push(m.paused
          ? h("div", { class: "member-pause" }, h("span", null, pausedText(m)),
            m.paused.by === m.id ? null : h("p", { class: "hint" }, words.paused),
            keyed("unpause:" + m.id, h("button", {
              type: "button",
              onclick: () => act("Clearing the pause", "The pause of " + m.display_name + " is cleared.",
                () => M.api.patch(memberPath, { paused: null }), "reason:" + m.id),
            }, "Clear pause")))
          : h("form", {
            class: "inline-form member-pause",
            onsubmit: (e) => {
              e.preventDefault();
              if (!reason.value.trim()) { reason.focus(); return; }
              act("Pausing", m.display_name + " is paused.", () => M.api.patch(memberPath, { paused: { reason: reason.value.trim() } }), "unpause:" + m.id,
                () => { const d = edits.get(m.id); if (d) delete d.reason; });
            },
          }, h("label", { for: reasonId }, "Pause with a reason"), reason,
          h("button", { type: "submit" }, "Pause"),
          h("p", { class: "hint" }, words.effect)));
      }
      parts.push(h("div", { class: "member-remove" }, h("button", {
        type: "button",
        class: "danger",
        onclick: async () => {
          const what = m.kind === "agent"
            ? "Its credentials are revoked and the cards it claimed are released."
            : self ? "You lose access to this project." : "They lose access to this project.";
          if (!window.confirm("Remove " + m.display_name + " from " + (ctx.project.name || ctx.slug) + "? " + what)) return;
          open.delete(m.id);
          const removed = await act("Removing", m.display_name + " was removed.", () => M.api.del(memberPath));
          if (removed && self) window.location.hash = "#/all";
        },
      }, "Remove from the project")));
      return h("tr", { class: "member-manage", id: rowId, role: "row" }, h("td", { colspan: "99", role: "cell" }, parts));
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
    // The rows' unsaved edits, by member id: a redraw (an action elsewhere,
    // the presence refresh) rebuilds the form from them, not from the member.
    const edits = new Map();

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
      const fillRoles = () => {
        const wanted = role.value || (draft.role !== undefined ? draft.role : m.role);
        const offered = M.trust.ROLES.filter((r) => r !== "proxy" || r === m.role || (ctx.isOwner && trust.value === "admin"));
        if (m.role && !offered.includes(m.role)) offered.push(m.role);
        append(clear(role), offered.map((r) => h("option", { value: r }, r)));
        role.value = offered.includes(wanted) ? wanted : m.role;
      };
      fillRoles();
      trust.addEventListener("change", () => { keep("trust", trust.value); fillRoles(); });
      // The current boss stays offered even if it is not in the list read.
      const others = items.filter((x) => x.id !== m.id);
      const listed = !m.reports_to || others.some((x) => x.id === m.reports_to);
      // A guest is never reported to (§2.3).
      const reports = keyed("reports:" + m.id, h("select", { id: id("reports") }, h("option", { value: "" }, "nobody"),
        others.filter((x) => !M.trust.guest(x) || x.id === m.reports_to).map((x) => h("option", { value: x.id }, x.display_name + " (@" + M.dom.handleOf(ctx, x) + ")")),
        listed ? null : h("option", { value: m.reports_to }, nameOf(m.reports_to) + " (not in this list)")));
      reports.value = m.reports_to || "";
      // A drafted boss who has left since is dropped, and said: a select that
      // fell back to "nobody" would clear the member's boss on the next save.
      let bossGone = null;
      if (draft.reports !== undefined) {
        if (!draft.reports || others.some((x) => x.id === draft.reports) || draft.reports === m.reports_to) reports.value = draft.reports;
        else { bossGone = nameOf(draft.reports); delete draft.reports; }
      }
      const areas = keyed("areas:" + m.id, h("input", { id: id("areas"), placeholder: "hub/, docs/", autocomplete: "off", spellcheck: "false" }));
      areas.value = draft.areas !== undefined ? draft.areas : (m.areas || []).join(", ");
      const caps = CAPABILITIES.map(([cap, label]) => {
        const box = h("input", { type: "checkbox", id: id("cap-" + cap) });
        box.checked = draft["cap:" + cap] !== undefined ? draft["cap:" + cap] : (m.capabilities || []).includes(cap);
        box.addEventListener("change", () => keep("cap:" + cap, box.checked));
        return { cap, box, label };
      });
      role.addEventListener("change", () => keep("role", role.value));
      reports.addEventListener("change", () => keep("reports", reports.value));
      areas.addEventListener("input", () => keep("areas", areas.value));
      // Each field says its own error, tied to it (as on the account view).
      const errorOf = (what) => h("p", { class: "field-error", id: id(what) + "-error", role: "alert" });
      const errors = { trust: errorOf("trust"), role: errorOf("role"), reports: errorOf("reports"), areas: errorOf("areas") };
      if (bossGone) errors.reports.textContent = bossGone + ", whom you picked, is no longer a member; reports to is back to what it is.";
      [[trust, "trust"], [role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => f.setAttribute("aria-describedby", id(k) + "-error"
        + (k === "areas" ? " " + id("areas") + "-hint" : "")));
      const clearErrors = () => [[trust, "trust"], [role, "role"], [reports, "reports"], [areas, "areas"]].forEach(([f, k]) => { errors[k].textContent = ""; f.removeAttribute("aria-invalid"); });
      const fieldFail = (f, k, text) => { errors[k].textContent = text; f.setAttribute("aria-invalid", "true"); status.fail("Not saved: ", { message: text }); f.focus(); };
      const save = h("button", { type: "submit" }, "Save changes");
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
            if (boss && closesCircle(m, boss)) { fieldFail(reports, "reports", CYCLE); return; }
            body.reports_to = boss;
          }
          const list = [...new Set(areas.value.split(",").map((a) => a.trim()).filter(Boolean))];
          if (list.some((a) => !areaOk(a))) { fieldFail(areas, "areas", BAD_AREA); return; }
          if (list.join("\n") !== (m.areas || []).join("\n")) body.areas = list;
          // Capabilities this page does not offer are kept as they are.
          const kept = (m.capabilities || []).filter((c) => !CAPABILITIES.some(([k]) => k === c));
          const capList = kept.concat(caps.filter((c) => c.box.checked).map((c) => c.cap));
          if ([...capList].sort().join() !== [...(m.capabilities || [])].sort().join()) body.capabilities = capList;
          if (!Object.keys(body).length) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
          const said = { trust: "trust", role: "role", reports_to: "reports to", areas: "areas", capabilities: "capabilities" };
          save.disabled = true;
          const saved = await act("Saving", "Saved for " + m.display_name + ": " + Object.keys(body).map((k) => said[k]).join(", ") + ".",
            () => M.api.patch(memberPath, body), "role:" + m.id, () => edits.delete(m.id));
          save.disabled = false;
          // Demoting oneself changes what this page may offer: re-render it.
          if (saved === true && self && (body.trust || body.role)) ctx.refresh();
        },
      },
      h("div", { class: "member-fields" },
        h("label", { for: id("trust") }, "Trust"), trust, errors.trust,
        h("label", { for: id("role") }, "Role"), role, errors.role,
        h("label", { for: id("reports") }, "Reports to"), reports, errors.reports,
        h("label", { for: id("areas") }, "Areas"), areas,
        h("p", { class: "hint", id: id("areas") + "-hint" }, "Repository paths this member owns, comma separated; cards in an area go to its narrowest owner."),
        errors.areas,
        h("fieldset", { class: "member-caps" }, h("legend", null, "Capabilities"),
          caps.map((c) => h("label", { class: "check", for: c.box.id }, c.box, " " + c.label)))),
      h("div", { class: "actions" }, save));
    }

    function nameCell(m) {
      // An agent's card is on the Agents view; one's own agent also has a chat.
      const mine = m.kind === "agent" && m.owner_id === ctx.me.id;
      return h("th", { scope: "row", role: "rowheader", "data-label": "Name", tabindex: m.id === wanted ? "-1" : null },
        h("span", { class: "member-name" }, M.dom.memberRef(ctx, m.id, { avatar: 20 })), h("span", { class: "muted" }, " @" + M.dom.handleOf(ctx, m)),
        m.kind === "human" && !m.removed_at && m.language
          ? h("p", { class: "muted member-language" }, "Language: " + (m.language === "de" ? "Deutsch" : "English")) : null,

        m.kind === "agent" && m.briefing != null && ctx.project.settings && "onboarding" in ctx.project.settings
          ? h("span", { class: "badge briefing-override", title: "This member uses its own briefing instead of the project default." }, "Own briefing") : null,
        mine ? h("span", { class: "member-links" }, " · ", h("a", { href: ctx.link("chat", m.id) }, "Chat")) : null);
    }

    // heading: false where the heading stands apart (the agents', with Add).
    function table(kind, list, columns, heading) {
      const label = kind === "human" ? "Humans" : "Agents";
      const withActions = ctx.canAdmin || list.some(ownAgent);
      const headingId = "members-" + kind;
      return [heading === false ? null : h("h3", { id: headingId }, label + " (" + list.length + ")"),
        h("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-labelledby": headingId },
          h("table", { class: "members", role: "table", "aria-labelledby": headingId },
            h("thead", { role: "rowgroup" }, h("tr", { role: "row" },
              h("th", { scope: "col", role: "columnheader" }, "Name"),
              columns.map((c) => h("th", { scope: "col", role: "columnheader" }, c.title)),
              withActions ? h("th", { scope: "col", role: "columnheader" }, "Actions") : null)),
            h("tbody", { role: "rowgroup" }, list.map((m) => {
              const expanded = open.has(m.id);
              const rowId = "member-manage-" + m.id;
              const row = h("tr", { class: "member" + (m.paused ? " paused" : "") + (m.id === wanted ? " wanted" : ""), role: "row", "data-member": m.id },
                nameCell(m),
                columns.map((c) => {
                  const td = h("td", { "data-label": c.title, role: "cell" }, c.cell(m));
                  if (c.presence) presenceCells.set(m.id, td);
                  return td;
                }),
                !withActions ? null : !mayOpen(m) ? h("td", { class: "member-actions", "data-label": "Actions", role: "cell" })
                  : h("td", { class: "member-actions", "data-label": "Actions", role: "cell" }, keyed("manage:" + m.id, h("button", {
                  type: "button",
                  class: "small",
                  "aria-expanded": expanded ? "true" : "false",
                  "aria-controls": expanded ? rowId : null,
                  "aria-label": (expanded ? (ctx.canAdmin ? "Done managing " : "Close the details of ") : (ctx.canAdmin ? "Manage " : "Details of ")) + m.display_name,
                  onclick: () => {
                    // Done closes the row and drops its unsaved edits.
                    if (open.has(m.id)) { open.delete(m.id); edits.delete(m.id); redraw("manage:" + m.id); } else { open.add(m.id); redraw(ctx.canAdmin ? "role:" + m.id : "manage:" + m.id); }
                  },
                }, expanded ? "Done" : ctx.canAdmin ? "Manage" : "Details"))));
              return expanded ? [row, manage(m, rowId)] : row;
            }))))];
    }

    function draw() {
      presenceCells.clear();
      focusables.clear();
      const humans = items.filter((m) => m.kind === "human");
      const agents = items.filter((m) => m.kind === "agent");
      // Owner and credentials only where the hub sends them.
      const hasCreds = agents.some((m) => "credentials" in m);
      const role = { title: "Trust and role", cell: (m) => M.trust.words(m) };
      const presence = { title: "Presence", presence: true, cell: (m) => presenceNodes(m, ctx.canAdmin) };
      const joined = { title: "Joined", cell: (m) => formatTime(m.joined_at) };
      const owner = { title: "Owner", cell: (m) => M.dom.memberRef(ctx, m.owner ? Object.assign({ member_id: m.owner_id }, m.owner) : m.owner_id) };
      const paused = { title: "Paused", cell: (m) => pausedText(m) || "—" };
      const creds = { title: "Credentials", cell: (m) => credentialsText(m.credentials) };
      const ktw = { title: "Keep the Why", cell: ktwCell };
      const hasKtw = agents.some((m) => "keep_the_why_unconfirmed" in m);
      append(clear(box), table("human", humans, [role, presence, joined]));
      agentsHeading.textContent = "Agents (" + agents.length + ")";
      append(clear(agentsBox), agents.length
        ? table("agent", agents, [role, owner, presence, joined, paused].concat(hasKtw ? [ktw] : [], hasCreds ? [creds] : []), false)
        : h("p", { class: "muted" }, "No agents yet.", (ctx.canAdmin || memberAdds) && M.join ? " Add one: its line is made here." : ""));
      drawJoins();
    }

    // Joining (docs/api.md §3.1, js/join.js), for whom may create joins:
    // Add at the head of the agents' table opens the panel under it; the
    // open joins stand as seats under the table, the others folded after
    // the placements. The panel, its form and a line shown once live
    // outside the redrawn table, so a redraw loses neither.
    const agentsHeading = h("h3", { id: "members-agent" }, "Agents");
    const addButton = h("button", { type: "button", class: "primary join-open" }, !ctx.canAdmin ? "+ Add my agent" : "+ Add an agent");
    const agentsBox = h("div", { class: "members-agents" });
    const seatsBox = h("div", { class: "profiles join-seats" });
    const earlierBox = h("div", { class: "earlier-box" });
    let J = null;
    // Bringing one's own agent (§3.1, tsk-zd2ch05rk7s1): a human member
    // without members:admin adds agents of their own while the project
    // allows it, up to member_agents_max. Only where the hub sends the
    // field: a hub without it refuses a member's join.
    const policy = ctx.project.policy || {};
    const memberAdds = !ctx.canAdmin && ctx.me.kind === "human" && !M.trust.guest(ctx)
      && "member_agents" in policy && policy.member_agents !== "off";
    const maxOwn = policy.member_agents_max === undefined ? 3 : policy.member_agents_max;
    // What §3.1 counts: one's distinct agents with an active membership or
    // an open join; an instance of one already counted adds nothing.
    const ownMembers = () => items.filter((m) => ownAgent(m) && !m.removed_at);
    const ownCount = () => new Set(ownMembers().map((m) => m.id).concat(J ? J.openAgents() : [])).size;
    const limitNote = h("span", { class: "muted member-agents-limit" });
    // How many agents, online, and joins open, under the agents' heading.
    const countLine = h("p", { class: "muted agents-count" });
    function drawCount() {
      const agents = items.filter((m) => m.kind === "agent");
      const open = J ? J.openCount() : 0;
      countLine.textContent = agents.length + (agents.length === 1 ? " agent" : " agents") + " · "
        + agents.filter((m) => m.presence === "online").length + " online"
        + (J ? " · " + open + (open === 1 ? (memberAdds ? " open join of yours" : " open join") : (memberAdds ? " open joins of yours" : " open joins")) : "");
      if (memberAdds) {
        const n = ownCount();
        const full = n >= maxOwn;
        // At the limit the panel still makes an instance of one of them.
        limitNote.textContent = n + " of " + maxOwn + " agents of yours"
          + (full ? (ownMembers().length ? " · no new one; another instance or a replacement still" : " · the project allows no more") : "");
        addButton.disabled = full && !ownMembers().length;
        addButton.setAttribute("aria-describedby", "member-agents-limit");
      }
    }
    function drawJoins() {
      drawCount();
      if (!J) return;
      append(clear(seatsBox), J.seats());
      append(clear(earlierBox), J.earlier());
    }

    append(root, h("h2", null, "Members"),
      h("p", { class: "muted" }, "Everyone in " + (ctx.project.name || ctx.slug) + ", humans first."
        + (ctx.canAdmin ? " Manage a row to change its role, see and revoke an agent's credentials, edit its briefing, pause it or remove a member."
          : ctx.members.some(ownAgent) ? " Your own agents' Details show their credentials and whether they get your preferences." : "")),
      status.el, box);
    // The join panel is read beside the list, not before it: the rows and
    // a member asked for by the URL never wait for the joins.
    const panelSlot = h("div", { class: "join-panel-slot" });
    addButton.hidden = true;
    limitNote.id = "member-agents-limit";
    append(root, h("div", { class: "toolbar agents-head" }, agentsHeading, memberAdds ? limitNote : null, addButton), countLine, panelSlot, agentsBox, seatsBox);
    if ((ctx.canAdmin || memberAdds) && M.join) {
      M.join.mount(ctx, {
        member: memberAdds,
        full: () => memberAdds && ownCount() >= maxOwn,
        changed: drawJoins,
        opened: (yes) => { addButton.hidden = yes; if (!yes) addButton.focus(); },
      }).then((mounted) => {
        J = mounted;
        addButton.hidden = false;
        addButton.addEventListener("click", () => { if (!addButton.disabled) J.open(addButton); });
        append(panelSlot, J.panel, J.listStatus.el);
        drawJoins();
        // Asked for, or no agent yet: the panel is the way in, open at once.
        if (joinAsked || (ctx.canAdmin && !items.some((m) => m.kind === "agent"))) J.open(addButton);
      }, (err) => append(panelSlot, h("p", { class: "send-status failed" }, "Could not read the joins: " + err.message)));
      // An agent running its line takes its seat: the list is read again,
      // unless the panel is open; then only the seats move.
      ctx.onEvents((events) => {
        if (!J || !events.some((e) => e.kind === "member_joined")) return;
        if (J.busy()) J.reread();
        else reload().then(() => redraw(), () => {});
      });
    }
    // Where the agents run (js/placements.js), where the hub has placements.
    const placementsSlot = h("div", { class: "placements-slot" });
    append(root, placementsSlot, earlierBox);
    if (M.placements) {
      const agentsNow = items.filter((m) => m.kind === "agent");
      Promise.all(agentsNow.map((m) => (M.agentParts ? M.agentParts.loadCredentials(ctx, m) : Promise.resolve({ list: { items: [] } }))))
        .then((creds) => M.placements.section(ctx, Object.fromEntries(agentsNow.map((m, i) => [m.id, (creds[i].list && creds[i].list.items) || []]))))
        .then((placed) => { if (placed) append(placementsSlot, placed); }, () => {});
    }
    draw();
    // Inviting a person (§3.4), below the members, for a human with members:admin.
    if (M.invite) {
      const slot = h("div", { class: "invitations-slot" });
      append(root, slot);
      M.invite.membersPanel(ctx).then((panel) => { if (panel) append(slot, panel); }, (err) => {
        append(slot, h("p", { class: "send-status failed" }, "Could not show the invitations: " + err.message));
      });
    }
    // A member asked for by the URL: its row takes the focus once the view is
    // in the page; an id that is no member here is said.
    if (wanted) {
      const row = Array.from(box.querySelectorAll("tr.member")).concat(Array.from(agentsBox.querySelectorAll("tr.member")))
        .find((tr) => tr.getAttribute("data-member") === wanted);
      const th = row && row.childNodes[0];
      const at = rulebookAsked ? focusables.get("team-max:" + wanted) : null;
      if (at) window.setTimeout(() => at.focus(), 0);
      else if (th) window.setTimeout(() => th.focus(), 0);
      else append(status.el, h("span", null, "No member with the id " + wanted + " in this project."));
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
          ctx.members = fresh;
          ctx.memberById = Object.fromEntries(fresh.map((m) => [m.id, m]));
          redraw();
          return;
        }
        fresh.forEach((m) => { const td = presenceCells.get(m.id); if (td) append(clear(td), presenceNodes(m, ctx.canAdmin)); });
        status.done();
      } catch (err) {
        status.fail("Could not refresh: ", err);
      }
    });
  };
})(window.Maity);
