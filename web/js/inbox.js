// (1) The inbox: what each agent wants from the human, one entry after the
// other. The first open entry in the chosen order is expanded; answering
// it expands the next. Runs in one project (/<owner>/<slug>/inbox) or across
// all of them (/all), where every entry is labelled with its project.
// Requests carry everything an entry shows (docs/api.md §7): asker, card
// and context are inline, so no other call is made.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRIORITY_RANK = { urgent: 0, high: 1, normal: 2, low: 3 };

  // Getters: the words are the catalog's when shown.
  const CLASS_LABELS = {
    get decision() { return M.t("inbox.class.decision"); },
    get consent() { return M.t("inbox.class.consent"); },
    get contract() { return M.t("inbox.class.contract"); },
    get info() { return M.t("inbox.class.info"); },
  };
  const SORT_LABELS = {
    get priority() { return M.t("inbox.sort.priority"); },
    get date() { return M.t("inbox.sort.date"); },
    get agent() { return M.t("inbox.sort.agent"); },
    get project() { return M.t("inbox.sort.project"); },
  };

  // Per tab only: which order and filter the human picked, which entry is
  // open, and which were put off with "Later". Not persisted, never sent:
  // there is no deferred state in the hub, a request stays open until it
  // is answered.
  // project: the cross-project view's filter ("" for every project);
  // group: whether it shows one section per project.
  const ui = { sort: "priority", show: "open", current: null, later: new Set(), project: "", group: false };

  // An entry is addressed by project and id: ids are unique per project
  // only. req.slug is set on load to the project's full name (§6.25); the
  // API gives a cross-project item its project as {slug, full_name, name,
  // state} and a per-project item none.
  const keyOf = (req) => req.slug + "/" + req.id;

  // Who asked, from the request itself: asked_by and, where the request was
  // filed for someone else, on_behalf_of.
  // A request the hub files itself (asked_by null, filed_by "hub": an
  // outage, an unconfirmed commitment, the not-listening digest, §5.3, §7).
  const byHub = (req) => !req.asked_by && req.filed_by === "hub";
  // The not-listening digest (§5.3): the hub's, personal, about no project
  // and no organisation; it leads to one's agents.
  // A report's request (§16.8) is the hub's too, without project or organisation, but no digest.
  const digest = (req) => byHub(req) && req.personal && !req.project && !req.org && !req.report;

  function asker(req) {
    const by = req.asked_by ? req.asked_by.display_name : byHub(req) ? "Maity" : "—";
    return req.on_behalf_of ? M.t("inbox.asker_for", { by, name: req.on_behalf_of.display_name }) : by;
  }

  function comparator(names) {
    const priority = (a, b) => (PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority])
      || a.created_at.localeCompare(b.created_at);
    let cmp = priority;
    if (ui.sort === "date") cmp = (a, b) => b.created_at.localeCompare(a.created_at);
    if (ui.sort === "agent") cmp = (a, b) => asker(a).localeCompare(asker(b)) || priority(a, b);
    if (ui.sort === "project") cmp = (a, b) => names.project(a).localeCompare(names.project(b)) || priority(a, b);
    // Entries put off with "Later" go to the end, in the same order.
    return (a, b) => (ui.later.has(keyOf(a)) - ui.later.has(keyOf(b))) || cmp(a, b);
  }

  function answerLabel(req) {
    const a = req.answer;
    if (!a) return req.status;
    if (a.talk) return M.t("inbox.talk");
    if (a.reply_id) {
      const reply = (req.replies || []).find((r) => r.id === a.reply_id);
      return reply ? reply.label : a.reply_id;
    }
    return M.t("inbox.free_text");
  }

  function addressee(ctx, req) {
    const to = req.to;
    if (!to) return null;
    if (to === "owner") return M.t("inbox.to.owner");
    if (to.startsWith("role:")) return M.t("inbox.to.role", { role: to.slice(5) });
    if (to.startsWith("trust:")) return M.t("inbox.to.trust", { trust: to.slice(6) });
    if (to === ctx.me.id) return M.t("inbox.to.you");
    if (to.startsWith("profile_owner:")) return M.t("inbox.to.profile_owner");
    // A human in person (`human:<id>`) and one instance of an agent
    // (`<member>#<instance>`, §6.17) name their member apart from the form.
    const human = to.startsWith("human:") ? to.slice(6) : null;
    if (human && human === ctx.me.id) return M.t("inbox.to.you");
    const [id, instance] = human ? [human, null] : to.split("#");
    return ref(ctx, req, { member_id: id, display_name: ctx.nameOf ? ctx.nameOf(id) : id, instance: instance || null });
  }

  // In the cross-project view: the project's logo or monogram, its name
  // and state, a link to the project, before the entry it belongs to.
  function projectBadge(ctx, req, names) {
    const p = req.project || { full_name: req.slug, name: names.project(req) };
    // A personal request (§7) is the human's, not the project's: no link to
    // a project inbox that never lists it, and maybe one is not a member of.
    // One with a project (a transfer into an organisation, §6.26) names the
    // project; one without (an organisation's invitation) the organisation
    // where the request carries it, otherwise nothing more.
    if (req.personal) {
      const of = p.name || (req.org ? "@" + req.org.handle : "");
      return h("span", { class: "project-label personal" }, M.t("inbox.personal"), of ? h("span", { class: "muted" }, " · " + of) : null);
    }
    return h("a", { class: "project-label", href: ctx.projectLink(p.full_name, "inbox") },
      M.projectMark(p.full_name, p.name, (ctx.projectViews || {})[p.full_name], "small"),
      p.name,
      p.state ? h("span", { class: "state state-" + p.state }, ctx.stateLabel(p.state)) : null);
  }

  // What the entry's button starts with where its badge is not seen: whose
  // request it is, one whole label per case.
  function hiddenLabel(req, names) {
    const name = names.project(req) || (req.org ? "@" + req.org.handle : "");
    if (!req.personal) return M.t("inbox.label.project", { name });
    // Neither project nor organisation (a report's request, §16.8): Personal alone.
    if (!name) return M.t("inbox.label.personal_alone");
    return req.project && req.org ? M.t("inbox.label.personal_into", { name, org: req.org.handle }) : M.t("inbox.label.personal", { name });
  }

  function entrySummary(ctx, req, names, expanded, onToggle) {
    return h("button", {
      class: "entry-head",
      type: "button",
      "aria-expanded": expanded ? "true" : "false",
      onclick: onToggle,
    },
    // The project's badge stands before the entry, as a link; its name is
    // also the start of this button's name, for whom the badge is not seen.
    ctx.scope === "all" || req.personal ? h("span", { class: "visually-hidden" }, hiddenLabel(req, names)) : null,
    h("span", { class: "prio prio-" + req.priority }, req.priority),
    h("span", { class: "kind" }, Object.hasOwn(CLASS_LABELS, req.class) ? CLASS_LABELS[req.class] : req.class),
    h("span", { class: "title" }, req.title),
    ui.later.has(keyOf(req)) ? h("span", { class: "muted" }, M.t("inbox.later_mark")) : null,
    h("span", { class: "meta" }, asker(req) + " · " + formatAgo(req.created_at)));
  }

  // A reply id is chosen by the asking agent, so it never becomes a class:
  // only the hub's own "go" of a consent without options is styled as the
  // primary answer.
  function replyClass(req, reply) {
    const computedGo = req.class === "consent" && !(req.options && req.options.length) && reply.id === "go";
    return computedGo ? "reply primary" : "reply";
  }

  // A member named in an entry (who asked, on whose behalf, to whom), as a
  // link to them and their instance in the request's own project (§7): their
  // page there, Sessions with the instance chosen. Only one that project's
  // member list names is linked: inside a project from its list, across
  // projects from the list of each request's project (`membersOf`). One it
  // does not list stays text, the way the project's inbox shows them: a
  // member removed since, a human who asks without a membership (§6.26), a
  // project the reader is not in, a list that could not be read.
  function ref(ctx, req, person) {
    const id = person && (person.member_id || person.id);
    const list = ctx.scope === "project" ? ctx.memberById : membersOf[req.slug];
    const m = id && list ? list[id] : null;
    const link = (view, ...rest) => ctx.projectLink(req.slug, view, ...rest);
    const view = { memberById: m ? { [id]: m } : {}, link, nameOf: ctx.nameOf };
    return M.dom.memberRef(view, person, { instance: person && person.instance });
  }

  function who(ctx, req, person) {
    return [ref(ctx, req, person), " · " + M.trust.words(person) + (person.session_id ? " · " + M.t("inbox.session", { id: person.session_id }) : "")];
  }

  // The project a request's text belongs to, for its ids as links
  // (js/ids.js): none for a personal request from a project the human is
  // not in, whose pages would not open.
  function textAt(ctx, req) {
    const p = ctx.projects.find((x) => x.full_name === req.slug);
    const slug = req.personal && !p ? null : req.slug;
    return { slug, repository: (p && p.repository && p.repository.url) || (ctx.slug === req.slug ? M.ids.where(ctx).repository : null),
      // Across projects (/all) a card or request reads with its project (§6.25).
      outside: ctx.scope !== "project" };
  }

  // A card as an entry names it: its reference, title and status (the hub's word).
  const cardLine = (cardRef, task) => M.t("inbox.card", { ref: cardRef, title: task.title, status: task.status.replace("_", " ") });

  // The member ids of the reader's own agent profiles (GET /agents), read once
  // per view: who Talk may go to across projects and for personal requests.
  let ownAgents = new Set();

  // Across projects, the members of each request's project by id (GET
  // …/members), read once per view for the reader's projects the list shows:
  // whom `ref` links there. A project whose list fails is left out.
  let membersOf = {};

  // Talk ("neither, let's talk") is the human's who owns the asking agent
  // (§7), and the agent must read the answer. The request does not say so, so
  // it is worked out: never for a request the hub filed itself (no asking
  // agent reads it) or one that cannot be read in full; inside a project the
  // member list names the asker's owner; across projects and for a personal
  // request the reader's own profiles do. A human asker is nobody's agent.
  function canTalk(ctx, req) {
    if (!req.asked_by || req.filed_by === "hub" || (req.personal && req.status === "open" && req.unreadable)) return false;
    const id = req.asked_by.member_id;
    if (ctx.scope !== "project" || req.personal) return ownAgents.has(id);
    const agent = (ctx.memberById || {})[id];
    return !!agent && agent.kind === "agent" && agent.owner_id === ctx.me.id;
  }

  // A proxy's request for the owner's go on one call (§2.3): the whole call, as
  // the go binds it. The body is shown pretty-printed, and also as sent: a parsed
  // body can hide a repeated key or a rounded number, and the hub compares the bytes.
  // Characters a reader cannot see, cannot tell from a space, or that reorder what is seen: control,
  // format and separator characters, the default-ignorable ones and the blank braille cell. The
  // plain space, a line break and a tab stay as they are, they show.
  const HIDDEN_CHAR = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Zs}\p{Default_Ignorable_Code_Point}\u2800]/u;
  const isHidden = (c) => c !== " " && c !== "\n" && c !== "\t" && HIDDEN_CHAR.test(c);
  const hasHidden = (s) => typeof s === "string" && Array.from(s).some(isHidden);
  // The text with each such character as a visible [U+XXXX]: the proxy writes this text. Not \uXXXX,
  // which a JSON body can hold as six plain characters, with another SHA-256.
  function revealed(s) {
    const out = [];
    let run = "";
    Array.from(String(s)).forEach((c) => {
      if (!isHidden(c)) { run += c; return; }
      if (run) { out.push(run); run = ""; }
      out.push(h("mark", { class: "hidden-char" }, "[U+" + c.codePointAt(0).toString(16).toUpperCase().padStart(4, "0") + "]"));
    });
    if (run) out.push(run);
    return out;
  }
  // Whether parsing kept the text: the text without the white space between tokens against the
  // parsed form written back. A rounded number, a repeated key, an escape or a moved key differ.
  function parsedDiffers(raw, pretty) {
    let bare = "";
    let inString = false;
    for (let k = 0; k < raw.length; k++) {
      const c = raw[k];
      if (inString) {
        bare += c;
        if (c === "\\") { k += 1; bare += raw[k] || ""; } else if (c === '"') inString = false;
      } else if (!/\s/.test(c)) {
        bare += c;
        if (c === '"') inString = true;
      }
    }
    return bare !== JSON.stringify(JSON.parse(pretty));
  }
  function actionCall(req) {
    const a = req.action;
    let pretty = null;
    if (a.body !== null && a.body !== undefined) {
      try { pretty = JSON.stringify(JSON.parse(a.body), null, 2); } catch (err) { pretty = null; }
    }
    const fact = (label, value) => [h("dt", null, label), h("dd", null, h("code", null, revealed(value)))];
    const hasBody = a.body !== null && a.body !== undefined;
    const differs = pretty !== null && parsedDiffers(a.body, pretty);
    const hidden = [a.method, a.path, a.query, a.body, pretty].some(hasHidden);
    const warning = (text) => h("p", { class: "field-error request-action-warning" }, text);
    const answeredGo = req.status === "answered" && req.answer && req.answer.reply_id === "go";
    return h("div", { class: "request-action" },
      h("h3", { class: "sub" }, M.t("inbox.action.title")),
      h("dl", { class: "facts" },
        fact(M.t("inbox.action.method"), a.method),
        fact(M.t("inbox.action.path"), a.path),
        a.query === null || a.query === undefined ? null
          : a.query === "" ? [h("dt", null, M.t("inbox.action.query")), h("dd", { class: "muted" }, M.t("inbox.action.query_empty"))]
            : fact(M.t("inbox.action.query"), a.query)),
      hidden ? warning(M.t("inbox.action.hidden_chars")) : null,
      differs ? warning(M.t("inbox.action.differs")) : null,
      !hasBody ? h("p", { class: "muted" }, M.t("inbox.action.no_body"))
        : [h("h4", null, M.t("inbox.action.body")), h("pre", { class: "request-action-body", tabindex: "0" }, revealed(pretty === null ? a.body : pretty)),
          h("details", differs ? { open: "open" } : null, h("summary", null, M.t("inbox.action.as_sent")),
            h("pre", { class: "request-action-body", tabindex: "0" }, revealed(a.body)),
            a.body_sha256 ? h("p", { class: "muted" }, "SHA-256 ", h("code", null, a.body_sha256)) : null)],
      a.used_at ? h("p", { class: "ok" }, M.t("inbox.action.used", { at: formatTime(a.used_at) }))
        : answeredGo && req.answered_at ? h("p", { class: "muted" }, M.t("inbox.action.valid", { at: formatTime(new Date(Date.parse(req.answered_at) + 86400000).toISOString()) }))
          : req.status === "open" ? h("p", { class: "hint" }, M.t("inbox.action.hint")) : null);
  }

  function entryBody(ctx, req, names, onAnswer, onLater) {
    const body = h("div", { class: "entry-body" });
    const at = textAt(ctx, req);
    // The title is inside the entry's button, where a link cannot be: its
    // ids are offered here.
    const titleRefs = M.ids.refs(req.title, at);

    append(body, h("dl", { class: "facts" },
      req.personal && req.org && !req.project
        ? [h("dt", null, M.t("inbox.fact.organisation")), h("dd", null, M.t("inbox.fact.org_personal", { org: req.org.handle }))]
        : null,
      // A transfer into an organisation: the project, and the organisation it would move into.
      req.personal && req.org && req.project
        ? [h("dt", null, M.t("inbox.fact.project")), h("dd", null, M.t("inbox.fact.project_org", { name: names.project(req), org: req.org.handle })),
          h("dt", null, M.t("inbox.fact.into")), h("dd", null, "@" + req.org.handle)]
        : null,
      req.personal && !req.org && names.project(req)
        ? [h("dt", null, M.t("inbox.fact.project")), h("dd", null, M.t("inbox.fact.project_owner", { name: names.project(req) }))]
        : null,
      ctx.scope === "all" && !req.personal
        ? [h("dt", null, M.t("inbox.fact.project")), h("dd", null, h("a", { href: ctx.projectLink(req.slug, "inbox") }, names.project(req)))]
        : null,
      titleRefs.length ? [h("dt", null, M.t("inbox.fact.title_refs")), h("dd", { class: "title-refs" }, titleRefs.map((a, i) => [i ? ", " : null, a]))] : null,
      h("dt", null, M.t("inbox.fact.asked_by")), h("dd", null, req.asked_by ? who(ctx, req, req.asked_by) : byHub(req) ? M.t("inbox.fact.by_hub") : "—"),
      req.on_behalf_of ? [h("dt", null, M.t("inbox.fact.on_behalf_of")), h("dd", null, who(ctx, req, req.on_behalf_of))] : null,
      req.to ? [h("dt", null, M.t("inbox.fact.to")), h("dd", null, addressee(ctx, req))] : null,
      h("dt", null, M.t("inbox.fact.asked")), h("dd", null, formatTime(req.created_at)),
      req.task
        ? [h("dt", null, M.t("inbox.fact.card")), h("dd", null, req.personal
          ? cardLine(M.ids.ref(req.project && req.project.full_name, req.task.id, true), req.task)
          : h("a", { href: ctx.projectLink(req.slug, "tasks", req.task.id) }, cardLine(M.ids.ref(req.slug, req.task.id, ctx.scope !== "project"), req.task)))]
        : null,
      digest(req) ? [h("dt", null, M.t("inbox.fact.your_agents")), h("dd", null, h("a", { class: "digest-agents", href: "/agents" }, M.t("inbox.fact.see_agents")))] : null,
      // Nobody waits on one the hub filed itself.
      byHub(req) ? null : [h("dt", null, M.t("inbox.fact.meanwhile")), h("dd", null, req.while_open === "proceed_provisionally"
        ? M.t("inbox.fact.proceeds")
        : M.t("inbox.fact.waits"))],
      req.ktw_ref ? [h("dt", null, M.t("inbox.fact.reasoning")), h("dd", null, h("code", null, req.ktw_ref))] : null));

    // Mentions link to the member in the request's own project (docs/api.md §8.6).
    // A personal request's project may be one the human is not in: no links there.
    const memberHref = (id) => (req.personal ? null : ctx.projectLink(req.slug, "members", id));
    // Drawn by the one renderer of chats, cards and messages (js/markdown.js): code with its Copy, links, mentions.
    const said = (field, text, mentions) => M.markdown(text, at, { mentions, field, hrefOf: memberHref, ctx });
    if (req.summary) append(body, h("div", { class: "md summary" }, said("summary", req.summary, req.mentions)));
    // An organisation's invitation, or a transfer into one: its go can make the human an
    // owner in projects whose restricted-access settings this page does not read; one
    // general sentence says so before (§6.1 "Every way into the set", §6.26).
    if (M.restricted && req.personal && req.org && req.status === "open") {
      append(body, h("p", { class: "restricted-ahead" }, req.project
        ? M.t("restricted.ahead.org_transfer_you", { project: names.project(req), org: "@" + req.org.handle })
        : M.restricted.aheadOrg("@" + req.org.handle, null)));
    }
    if (req.tried) append(body, h("h3", { class: "sub" }, M.t("inbox.tried")), h("div", { class: "md" }, said("tried", req.tried, req.mentions)));
    if (req.options && req.options.length) {
      append(body, h("h3", { class: "sub" }, M.t("inbox.options")),
        h("ul", { class: "options" }, req.options.map((o) =>
          h("li", null, h("strong", null, M.ids.link(o.label, at)), o.detail ? h("div", { class: "md option-detail" }, M.markdown(o.detail, at)) : null))));
    }
    const nis = req.needs_in_session;
    if (nis) {
      append(body, h("p", { class: "flag", role: "note" },
        h("strong", null, M.t("inbox.needs_session")), " ",
        ref(ctx, req, nis), (nis.session_id ? " · " + M.t("inbox.session", { id: nis.session_id }) : "") + (nis.harness ? " · " + nis.harness : "") + ". ",
        nis.reason));
    }

    if (req.action) append(body, actionCall(req));

    const preference = M.preferences && M.preferences.isProposal(req);
    // Not read in full: no reply that could apply a proposal unseen.
    const unread = req.personal && req.status === "open" && req.unreadable;
    if (req.status !== "open") {
      const a = req.answer;
      if (preference) append(body, M.preferences.outcome(req));
      append(body, h("p", { class: "answered" },
        (req.status === "withdrawn" ? M.t("inbox.withdrawn") : M.t("inbox.answered", { answer: answerLabel(req) })),
        a ? [" · ", a.on_behalf_of
          // Who answered, and for whom: one sentence, both members in it.
          ? M.tn("inbox.answered_by_for", { by: ref(ctx, req, { member_id: a.by, display_name: names.member(a.by) }),
            who: ref(ctx, req, { member_id: a.on_behalf_of, display_name: names.member(a.on_behalf_of) }) })
          : ref(ctx, req, { member_id: a.by, display_name: names.member(a.by) }),
          " · " + formatTime(a.at)] : null),
        a && a.text ? h("div", { class: "md answer-text" }, said("text", a.text, a.mentions)) : null);
      return body;
    }

    const status = M.statusLine();
    // What stays disabled once a refused answer gives the controls back (Talk, Send without words).
    let settle = null;
    const send = (payload, verb) => {
      body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = true; });
      status.busy(M.t("inbox.sending"));
      onAnswer(req, payload, verb).catch((err) => {
        body.querySelectorAll("button, textarea").forEach((el) => { el.disabled = false; });
        if (settle) settle();
        status.fail(M.t("inbox.not_sent"), err);
      });
    };

    if (unread) {
      const again = h("button", { type: "button", onclick: async () => {
        again.disabled = true;
        await readInFull(req);
        const fresh = entryBody(ctx, req, names, onAnswer, onLater);
        append(clear(body), Array.from(fresh.childNodes));
      } }, M.t("inbox.retry"));
      append(body, h("div", { class: "error", role: "alert" },
        h("p", null, M.t("inbox.unreadable", { reason: req.unreadable.message || req.unreadable.code || "" })),
        again));
    }
    // A preference proposal (§19.4) is answered in its review: accept,
    // accept an edit, decline; Later, talk and Withdraw stay below.
    if (preference) append(body, M.preferences.review(ctx, req, (payload) => onAnswer(req, payload)));

    const textId = "reply-" + String(req.slug).replace("/", "-") + "-" + req.id;
    const text = h("textarea", { id: textId, rows: "3", placeholder: M.t("inbox.reply_placeholder") });
    // The one field above the buttons is always writable: a reply or Talk
    // takes its text along when it holds any (§7); Send is the answer in
    // words alone, beside the replies too (below). A preference proposal's
    // words go with its Decline, in the review.
    // Inside a project the trust is known: only the owner answers an action (§2.3).
    const notOwner = !!req.action && ctx.scope === "project" && !ctx.isOwner;
    if (notOwner) append(body, h("p", { class: "muted" }, M.t("inbox.action.owner_only")));
    // The instance admin's request about a new abuse report (§16.8) has no answer: it closes
    // when the report is resolved, under Admin → Reports, after its snapshot was read.
    const reportReq = !!req.report;
    const noField = preference || unread || notOwner || reportReq;
    const replies = noField ? [] : req.replies || [];
    const withText = (payload) => {
      const value = text.value.trim();
      return value ? Object.assign({}, payload, { text: value }) : payload;
    };
    // Send is on every request with a field: the words alone are an answer (§7), Ctrl+Enter
    // the same. Not where the hub refuses them (a takeover's reply is required) or reads them as
    // No (a consent's proposal or placement, §15.6): the request view does not say which consent
    // carries one, so no consent, action or takeover gets the words alone; it stays, disabled,
    // and says why (web/context/views.md).
    const wordsAlone = req.class !== "consent" && !req.action && !req.placement && !req.takeover_id;
    const sendWords = () => {
      const value = text.value.trim();
      if (!wordsAlone) return;
      if (!value) { text.focus(); return; }
      send({ text: value });
    };
    const hintId = textId + "-hint";
    // A takeover's request needs one of its replies (§6.19): the hub refuses `talk` as it refuses the words alone.
    const talkable = canTalk(ctx, req) && !notOwner && !req.takeover_id;
    // Not where no answer is possible yet: a call for the owner alone, a request not read in full;
    // nor on a report's request, which has no answer at all (§16.8).
    const showTalk = !notOwner && !unread && !reportReq;
    const talkWhy = talkable || !showTalk ? null : req.takeover_id ? M.t("inbox.talk_takeover")
      : req.filed_by === "hub" ? M.t("inbox.talk_hub") : M.t("inbox.talk_not_yours");
    // No reason for a Send that is not there (no field: a preference review, an unread or a call for the owner alone).
    const sendWhy = wordsAlone || noField ? null : M.t("inbox.send_needs_reply");
    const why = [sendWhy, talkWhy].filter(Boolean);
    const sendText = noField ? null : h("button", { type: "button", class: "reply send", onclick: sendWords,
      "aria-describedby": sendWhy ? hintId : null }, M.t("inbox.send"));
    const empty = () => { if (sendText) sendText.disabled = !wordsAlone || !text.value.trim(); };
    if (sendText) {
      empty();
      text.addEventListener("input", empty);
      // Ctrl+Enter only where Send can ever send: a Send disabled for good announces no shortcut.
      if (wordsAlone) M.dom.sendOnCtrlEnter(text, sendWords, sendText);
    }
    const talk = h("button", { type: "button", class: "reply talk", "aria-describedby": talkWhy ? hintId : null,
      onclick: () => { if (talkable) send(withText({ talk: true })); } }, M.t("inbox.talk"));
    talk.disabled = !talkable;
    settle = () => { empty(); talk.disabled = !talkable; };
    append(body,
      noField ? null : h("div", { class: "free-text" },
        h("label", { for: textId }, replies.length ? M.t("inbox.note_label") : M.t("inbox.free_text_label", { keys: M.dom.SEND_KEYS })),
        text,
        // @ offers this project's members; the hub links them, it pings nobody (§8.6).
        // Not for a personal request: its project may be one the human is not in.
        req.personal ? null : M.mentionPicker(text, () => M.api.getAll("/projects/" + M.api.projectPath(req.slug) + "/members").then((r) => r.items), ctx.me.id)),
      // Right-aligned, the secondary ones first: Later, Talk, then the replies.
      h("div", { class: "replies" },
        h("button", {
          type: "button",
          class: "reply later",
          title: M.t("inbox.later_title"),
          onclick: () => onLater(req),
        }, M.t("inbox.later")),
        // Talk on every request one can answer; where the hub takes `talk` from nobody here it stays,
        // disabled, and says why (§7).
        showTalk ? talk : null,
        // Its human may withdraw a personal request, as nobody else can (§7); a report
        // request only closes with its report (§16.8).
        reportReq ? h("a", {
          // a.button: a link drawn as the buttons beside it are.
          class: "button primary reply open-report",
          href: "/admin/reports/" + encodeURIComponent(req.report.id),
        }, M.t("inbox.open_report")) : null,
        req.personal && !reportReq ? h("button", {
          type: "button",
          class: "reply withdraw",
          onclick: () => {
            if (!window.confirm(M.t("inbox.withdraw_confirm"))) return;
            const reason = text.value.trim();
            send(reason ? { reason } : {}, "withdraw");
          },
        }, M.t("inbox.withdraw")) : null,
        // The primary reply last, the others in the hub's order before it.
        [...replies.filter((r) => replyClass(req, r) !== "reply primary"),
          ...replies.filter((r) => replyClass(req, r) === "reply primary")].map((r) =>
          h("button", { type: "button", class: replyClass(req, r), onclick: () => send(withText({ reply_id: r.id })) }, r.label)),
        sendText),
      why.length ? h("p", { class: "muted reply-hint", id: hintId }, why.join(" ")) : null,
      status.el);

    // Ownership is known inside a project only; across projects the link to
    // the project's inbox leads there.
    const agent = ctx.scope === "project" && req.asked_by ? ctx.memberById[req.asked_by.member_id] : null;
    if (agent && agent.kind === "agent" && agent.owner_id === ctx.me.id) {
      append(body, h("p", { class: "chat-link" },
        h("a", { href: ctx.link("chat", agent.id) }, M.t("inbox.chat_with", { name: agent.display_name }))));
    }
    return body;
  }

  // A personal request as GET /requests/{id} has it: a proposal with its
  // texts (§19.4), or the error that kept it from being read.
  function readInFull(r) {
    return M.api.get("/requests/" + encodeURIComponent(r.id)).then((full) => {
      delete r.unreadable;
      if (full.memory_proposal) r.memory_proposal = full.memory_proposal;
    }, (err) => { r.unreadable = err; });
  }

  async function load(ctx) {
    if (ctx.scope === "project") {
      // The project's own requests, and the open personal requests about it
      // (§7: a project's list never holds them, the tab's count does, §18.2):
      // the list shows what the tab counts.
      // A failed read of them is said in the list's status line (load's
      // personalError), never an empty list short of the tab.
      let personalError = null;
      const [requests, personal] = await Promise.all([M.api.getAll(ctx.base + "/requests?status=all"),
        M.api.getAll("/requests").then((r) => r.items.filter((x) => x.personal && x.status === "open" && x.project && x.project.full_name === ctx.slug),
          (err) => { personalError = err; return []; })]);
      requests.items.forEach((r) => { r.slug = ctx.slug; });
      personal.forEach((r) => { r.slug = ctx.slug; });
      await Promise.all(personal.map(readInFull));
      const all = requests.items.concat(personal);
      all.personalError = personalError;
      return all;
    }
    const requests = await M.api.getAll("/requests");
    // A personal request may have no project (an organisation's invitation, §6.26).
    requests.items.forEach((r) => { r.slug = r.project ? r.project.full_name : null; });
    // A list shows no proposal (§7): an open personal request is read on its
    // own, so a preference proposal (§19.4) comes with its review's texts.
    // One that cannot be read is offered no reply until it is: it may be a
    // proposal whose texts the human has to see first.
    await Promise.all(requests.items.filter((r) => r.personal && r.status === "open").map(readInFull));
    return requests.items;
  }

  // args[0]: a request to show (/<owner>/<slug>/inbox/<id>, an id's link,
  // js/ids.js): opened, and listed among the answered when it is one; an id
  // the project's inbox does not hold is said.
  M.views.inbox = async function (ctx, root, args) {
    const items = await load(ctx);
    ownAgents = new Set();
    membersOf = {};
    if (ctx.scope !== "project") {
      const slugs = [...new Set(items.map((r) => r.slug))].filter((s) => s && ctx.projects.some((p) => p.full_name === s));
      await Promise.all(slugs.map((s) => M.api.getAll("/projects/" + M.api.projectPath(s) + "/members")
        .then((r) => { membersOf[s] = Object.fromEntries(r.items.map((x) => [x.id, x])); }, () => null)));
    }
    // Inside a project the member list says whose an agent is; the profiles are needed across projects
    // and for a personal request only.
    if (ctx.scope !== "project" || items.some((r) => r.personal)) {
      try {
        ownAgents = new Set((await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at).map((a) => a.id));
      } catch (ignored) { /* no Talk where the reader's agents are unknown */ }
    }
    const wanted = ctx.scope === "project" && args && args[0] ? args[0] : null;
    const wantedReq = wanted ? items.find((r) => r.id === wanted) : null;
    let showAll = false;
    if (wantedReq) {
      ui.current = keyOf(wantedReq);
      // An answered one is shown among the answered for this view only;
      // the inbox's own choice stays as it was.
      if (wantedReq.status !== "open") showAll = true;
    }
    const names = {
      member: (id) => (ctx.nameOf ? ctx.nameOf(id) : id || "—"),
      project: (req) => (req.project && req.project.name)
        || (req.slug ? (ctx.projects.find((x) => x.full_name === req.slug) || { name: req.slug }).name : ""),
    };
    const sorts = ctx.scope === "all" ? ["priority", "date", "agent", "project"] : ["priority", "date", "agent"];
    if (!sorts.includes(ui.sort)) ui.sort = "priority";
    // The cross-project view lists what is waiting, nothing else.
    const show = () => (ctx.scope === "all" ? "open" : showAll ? "all" : ui.show);

    // The project filter is the cross-project view's only; a project no
    // longer in the switcher is no filter (it would empty the list for good).
    if (ui.project && !ctx.projects.some((p) => p.full_name === ui.project)) ui.project = "";
    const projectFilter = () => (ctx.scope === "all" ? ui.project : "");
    const grouped = () => ctx.scope === "all" && ui.group;
    const list = h("div", { class: "entries-box" });
    const listStatus = M.statusLine();
    if (items.personalError) listStatus.fail(M.t("inbox.personal_failed"), items.personalError);

    // With no open entry on screen there is nothing being read or typed, so
    // a change of the counts reloads the list on its own (app.js, watch).
    ctx.quietReload = () => !ordered().some((r) => r.status === "open");

    // The entries in the order they are on screen: shown, filtered, sorted,
    // and grouped by project in the switcher's order. draw(), the next
    // entry after an answer, and the quiet reload all use this one order.
    function ordered() {
      const sorted = items
        .filter((r) => show() === "all" || r.status === "open")
        .filter((r) => !projectFilter() || r.slug === projectFilter())
        .sort(comparator(names));
      if (!grouped()) return sorted;
      // Personal requests first, in a group of their own; then by project.
      const at = (r) => { if (r.personal) return -1; const i = ctx.projects.findIndex((p) => p.full_name === r.slug); return i < 0 ? ctx.projects.length : i; };
      return sorted.map((r, i) => [r, i]).sort((a, b) => at(a[0]) - at(b[0]) || a[1] - b[1]).map(([r]) => r);
    }

    function draw() {
      const shown = ordered();
      const open = shown.filter((r) => r.status === "open");
      if (!shown.some((r) => keyOf(r) === ui.current)) ui.current = open.length ? keyOf(open[0]) : null;
      M.dom.clear(list);
      // A filter outlives a reload: what it hides is said, or a new request elsewhere looks like no reload at all.
      const hiddenByFilter = projectFilter() ? items.filter((r) => r.status === "open" && r.slug !== projectFilter()).length : 0;
      if (hiddenByFilter) {
        append(list, h("p", { class: "flag inbox-filter-hidden" }, M.t("inbox.filter.hidden", { count: hiddenByFilter }), " ",
          h("button", { type: "button", class: "small", onclick: () => {
            ui.project = "";
            if (projectSelect) projectSelect.value = "";
            draw();
          } }, M.t("inbox.filter.show_all"))));
      }
      if (!shown.length) {
        append(list, h("ol", { class: "entries" }, h("li", { class: "empty" }, M.t("inbox.empty"),
          h("p", { class: "first-hint" }, ctx.scope === "all" ? M.t("inbox.empty.all") : M.t("inbox.empty.project")))));
        return;
      }
      const entry = (req) => {
        const expanded = keyOf(req) === ui.current;
        return h("li", { class: "entry" + (expanded ? " current" : "") + (req.status !== "open" ? " done" : ""), "data-request": req.id },
          // A personal request carries its label in a project's inbox too (§18.2).
          ctx.scope === "all" || req.personal
            ? h("div", { class: "entry-row" }, projectBadge(ctx, req, names), entrySummary(ctx, req, names, expanded, () => {
              ui.current = expanded ? null : keyOf(req);
              draw();
            }))
            : entrySummary(ctx, req, names, expanded, () => {
              ui.current = expanded ? null : keyOf(req);
              draw();
            }),
          expanded ? entryBody(ctx, req, names, answer, later) : null);
      };
      if (grouped()) {
        // One section per project, its heading and its own list, so that a
        // list's items are its entries only.
        const groupOf = (r) => (r.personal ? "" : r.slug);
        const slugs = [...new Set(shown.map(groupOf))];
        slugs.forEach((slug) => {
          const own = shown.filter((r) => groupOf(r) === slug);
          const id = "inbox-group-" + (slug ? slug.replace("/", "-") : "personal");
          append(list, h("section", { class: "entry-group", "aria-labelledby": id },
            h("h3", { id }, slug ? names.project(own[0]) : M.t("inbox.personal"), h("span", { class: "count" }, String(own.length))),
            h("ol", { class: "entries" }, own.map(entry))));
        });
      } else {
        append(list, h("ol", { class: "entries" }, shown.map(entry)));
      }
    }

    // The open entry after `after` in the current order, wrapping round to
    // the first; the order is taken before the answer changed anything.
    function next(order, after) {
      const i = order.findIndex((r) => keyOf(r) === keyOf(after));
      const rest = order.slice(i + 1).concat(order.slice(0, i));
      const pick = rest.find((r) => r.status === "open" && keyOf(r) !== keyOf(after));
      ui.current = pick ? keyOf(pick) : null;
    }

    function later(req) {
      const order = ordered();
      ui.later.add(keyOf(req));
      next(order, req);
      draw();
    }

    // A personal request is answered and withdrawn on /requests/{id} (§7):
    // the project's routes answer not_found for it.
    async function answer(req, payload, verb) {
      const order = ordered();
      const path = (req.personal ? "" : "/projects/" + M.api.projectPath(req.slug))
        + "/requests/" + encodeURIComponent(req.id) + "/" + (verb || "answer");
      const updated = await M.api.post(path, payload);
      updated.slug = req.slug;
      if (req.project) updated.project = req.project;
      items[items.indexOf(req)] = updated;
      ui.later.delete(keyOf(req));
      // Move on to the open entry after this one in the current order.
      next(order, req);
      draw();
      // The counts come from the hub (docs/api.md §5.1).
      try {
        await ctx.refreshCounts();
        ctx.markSeen();
        listStatus.done();
      } catch (err) {
        listStatus.fail(M.t("inbox.counts_failed"), err);
      }
    }

    const sortSelect = h("select", {
      id: "inbox-sort",
      onchange: (e) => { ui.sort = e.target.value; ui.current = null; draw(); },
    },
    sorts.map((s) => h("option", { value: s, selected: s === ui.sort }, SORT_LABELS[s])));
    const showSelect = ctx.scope === "all" ? null : h("select", {
      id: "inbox-show",
      onchange: (e) => { ui.show = e.target.value; showAll = false; draw(); },
    },
    [["open", M.t("inbox.show.open")], ["all", M.t("inbox.show.all")]].map(([v, l]) => h("option", { value: v, selected: v === show() }, l)));

    // The cross-project view: a project filter and grouping by project.
    const projectSelect = ctx.scope === "all" ? h("select", {
      id: "inbox-project",
      onchange: (e) => { ui.project = e.target.value; ui.current = null; draw(); },
    }, h("option", { value: "" }, M.t("inbox.every_project")),
    // No counts in the options: the switcher beside it has them, kept current.
    ctx.projects.map((p) => h("option", { value: p.full_name }, p.name))) : null;
    if (projectSelect) projectSelect.value = ui.project;
    const groupBox = ctx.scope === "all" ? h("input", { type: "checkbox", id: "inbox-group", onchange: (e) => { ui.group = e.target.checked; draw(); } }) : null;
    if (groupBox) groupBox.checked = ui.group;

    // The project's banner (docs/api.md §11.2) heads its landing page.
    const banner = ctx.scope === "project" && M.api.imageUrl(ctx.slug, "banner", ctx.project.banner);
    if (banner) append(root, h("img", { class: "project-banner", src: banner, alt: "" }));
    append(root,
      h("div", { class: "toolbar" },
        h("h2", null, ctx.scope === "all" ? M.t("inbox.title.all") : M.t("inbox.title")),
        h("label", { for: "inbox-sort" }, M.t("inbox.sort_by")), sortSelect,
        showSelect ? [h("label", { for: "inbox-show" }, M.t("inbox.show")), showSelect] : null,
        projectSelect ? [h("label", { for: "inbox-project" }, M.t("inbox.filter.project")), projectSelect,
          h("label", { class: "check", for: "inbox-group" }, groupBox, " " + M.t("inbox.group"))] : null),
      listStatus.el,
      wanted && !wantedReq ? h("p", { class: "muted wanted-note", role: "status" }, M.t("inbox.not_here", { id: wanted })) : null,
      list);
    draw();
    if (wantedReq) {
      const head = Array.from(list.querySelectorAll("li.entry")).filter((li) => li.getAttribute("data-request") === wanted)
        .map((li) => li.querySelector("button.entry-head"))[0];
      if (head) window.setTimeout(() => head.focus(), 0);
    }
  };
})(window.Maity);
