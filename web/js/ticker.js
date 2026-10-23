// (12) Ticker (#/p/<slug>/ticker, docs/api.md §17): the project's change
// feed — merges, decisions, deploys, releases and notes — newest first,
// "For me" and "Everything" as two tabs, filtered by type and area, paged
// with the hub's cursor. An item is its text (plain, never Markdown), its
// link when it is https, and for the viewer why it is theirs, in words.
// The viewer's own follow and mute are edited here (§17.8); an owner or
// admin posts a note, a deploy or a release (§17.6). New items come with
// the project's feed. A hub without the ticker says so, asked once per
// page load.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatTime } = M.dom;

  const TYPES = [["merge", "Merges"], ["contract", "Contract changes"], ["decision", "Decisions"], ["deploy", "Deploys"], ["release", "Releases"], ["note", "Notes"]];
  const TYPE_WORD = { merge: "Merge", decision: "Decision", deploy: "Deploy", release: "Release", note: "Note" };
  const PAGE = 50;
  let hubWithout = false;

  // A reason token (§17.3, §17.6, §17.8) as the viewer reads it.
  function whyWords(token) {
    const [kind, ...rest] = token.split(":");
    const arg = rest.join(":");
    switch (kind) {
      case "area_owner": return "you own " + arg;
      case "card_holder": return "you hold " + arg;
      case "card_assignee": return "you are assigned " + arg;
      case "contract_implementer": return "you implement §" + arg;
      case "role": return "you are " + (arg === "admin" ? "an admin" : "a " + arg);
      case "decision_asker": return "you asked";
      case "decision_on_behalf_of": return "it was asked for you";
      case "contract_watcher": return "you watch the contract";
      case "all_members": return "it is for everyone";
      case "posted_to_all": return "it was posted to everyone";
      case "addressed": return "it was addressed to you";
      case "follow": return rest[0] === "type" ? "you follow " + rest.slice(1).join(":") + "s" : "you follow " + arg;
      default: return token;
    }
  }

  // The hub's refusals of a post or a subscription change, in words.
  const FIELD_WORDS = {
    not_for_type: "does not go with this type", required: "is required", not_done: "names a release card that is not done",
    too_many: "may hold at most 20", invalid: "is not valid", unknown: "is not known", too_long: "is longer than 280 characters",
  };
  function said(err) {
    if (err.code === "ticker_duplicate") return { message: "this was posted already (item " + (err.details && err.details.seq) + ")" };
    if (err.code === "rate_limited") return { message: "too many posts in the last hour; try again later" };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) return { message: Object.entries(fields).map(([f, why]) => f + " " + (FIELD_WORDS[why] || why)).join("; ") };
    return err;
  }

  M.views.ticker = async function (ctx, root) {
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const toolbar = h("div", { class: "toolbar" }, h("h2", null, "Ticker"));
    if (hubWithout) {
      append(root, toolbar, h("p", { class: "muted" }, "This hub has no ticker yet."));
      return;
    }
    let forMe = true;
    let type = "";
    let area = "";
    let cursor = null;
    const list = h("ol", { class: "ticker-list" });
    const more = h("div", { class: "actions" });
    const query = (extra) => ctx.base + "/ticker?" + [forMe ? "for=me" : "for=all", type ? "type=" + encodeURIComponent(type) : null,
      area ? "area=" + encodeURIComponent(area) : null, "limit=" + PAGE, extra || null].filter(Boolean).join("&");

    function item(x) {
      const link = safeUrl(x.url);
      const words = x.type === "decision" && x.detail ? x.detail.reply_label + " — " + x.detail.request_title : null;
      return h("li", { class: "ticker-item type-" + x.type + (x.for_me ? " for-me" : ""), "data-seq": String(x.seq) },
        h("div", { class: "ticker-head" },
          h("span", { class: "badge" }, x.type === "merge" && x.contract ? "Contract change" : TYPE_WORD[x.type] || x.type),
          " ", h("span", { class: "muted" }, formatTime(x.at) + (x.actor && x.actor.member_id ? " · " + ctx.nameOf(x.actor.member_id) : ""))),
        x.redacted ? h("p", { class: "muted msg-redacted" }, "This item was removed.")
          : h("p", { class: "ticker-text" }, x.text, link ? [" ", h("a", { href: link, rel: "noopener noreferrer", target: "_blank" }, "link")] : null),
        words ? h("p", { class: "muted" }, "Decided: " + words) : null,
        x.for_me ? h("p", { class: "ticker-why" }, "For you: " + x.why.map(whyWords).join(", ") + (x.muted ? " (muted: it woke no one here)" : "") + ".") : null);
    }

    // given: a page already read (the first one, below).
    async function load(reset, given) {
      if (reset) { clear(list); cursor = null; }
      let page = given;
      try {
        if (!page) page = await M.api.get(query(cursor ? "cursor=" + encodeURIComponent(cursor) : null));
      } catch (err) {
        status.fail("Could not read the ticker: ", err);
        return false;
      }
      page.items.forEach((x) => append(list, item(x)));
      if (!list.querySelector("li")) append(list, h("li", { class: "empty muted" }, forMe ? "Nothing for you yet." : "Nothing in the ticker yet."));
      cursor = page.next_cursor;
      clear(more);
      if (cursor) append(more, h("button", { type: "button", class: "small", onclick: () => load(false) }, "Older"));
      return true;
    }

    // The first read decides whether the hub has a ticker at all.
    let first;
    try {
      first = await M.api.get(query());
    } catch (err) {
      if (err.status === 404) {
        hubWithout = true;
        append(root, toolbar, h("p", { class: "muted" }, "This hub has no ticker yet."));
        return;
      }
      throw err;
    }

    const tab = (mine, label) => h("button", { type: "button", class: "small", "aria-pressed": String(forMe === mine),
      onclick: async (e) => { forMe = mine; Array.from(tabs.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b === e.target))); await load(true); } }, label);
    const tabs = h("div", { class: "ticker-tabs", role: "group", "aria-label": "Which items" }, tab(true, "For me"), tab(false, "Everything"));
    const typePick = h("select", { id: "ticker-type", onchange: (e) => { type = e.target.value; load(true); } },
      h("option", { value: "" }, "every type"), TYPES.map(([v, l]) => h("option", { value: v }, l)));
    const areaField = h("input", { id: "ticker-area", placeholder: "e.g. web/", autocomplete: "off" });
    const filter = h("form", { class: "board-filter", role: "search", onsubmit: (e) => { e.preventDefault(); area = areaField.value.trim(); load(true); } },
      h("label", { for: "ticker-type" }, "Type"), typePick, h("label", { for: "ticker-area" }, "Area"), areaField,
      h("button", { type: "submit", class: "small" }, "Filter"));

    // New items arrive with the feed; they go on top when they fit the view.
    ctx.onEvents((events) => {
      const shownSeqs = () => new Set(Array.from(list.querySelectorAll("li.ticker-item")).map((li) => li.getAttribute("data-seq")));
      if (!events.some((e) => e.kind === "ticker" && !shownSeqs().has(String(e.seq)))) return;
      // The listing's own form, per reader and filter, from the newest page.
      M.api.get(query()).then((page) => {
        const known = shownSeqs();
        const add = page.items.filter((x) => !known.has(String(x.seq)));
        if (!add.length) return;
        const blank = list.querySelector("li.empty");
        if (blank) list.removeChild(blank);
        add.slice().reverse().forEach((x) => list.insertBefore(item(x), list.firstChild));
        status.done();
        append(status.el, h("span", null, add.length === 1 ? "1 new item." : add.length + " new items."));
      }, () => {});
    });

    append(root, toolbar,
      h("p", { class: "muted" }, "What changed in the project: merges, decisions, deploys, releases and notes. Texts are as the hub or the poster wrote them."),
      tabs, filter, status.el, list, more,
      await subscription(ctx),
      ctx.canAdmin ? postForm(ctx, () => load(true)) : null);
    await load(true, first);
  };

  // §17.8: the viewer's own follow and mute, changed by what is added or removed.
  async function subscription(ctx) {
    const box = h("section", { class: "ticker-sub", "aria-labelledby": "ticker-sub-title" }, h("h3", { id: "ticker-sub-title" }, "Follow and mute"));
    const status = M.statusLine();
    const body = h("div");
    let sub;
    try {
      sub = await M.api.get(ctx.base + "/ticker/subscription");
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, "Could not read your subscription: " + err.message));
      return box;
    }
    async function change(patch, words) {
      status.busy("Saving…");
      try {
        sub = await M.api.patch(ctx.base + "/ticker/subscription", patch);
      } catch (err) {
        status.fail("Not saved: ", said(err));
        return;
      }
      draw();
      status.done();
      append(status.el, h("span", { class: "ok" }, words));
    }
    const typeWord = (v) => (TYPES.find(([k]) => k === v) || [v, v])[1];
    function draw() {
      const chips = (list, kind) => sub[list][kind].map((v) => h("li", null, kind === "types" ? typeWord(v) : v, " ",
        h("button", { type: "button", class: "small", "aria-label": "Stop " + (list === "follow" ? "following " : "muting ") + v,
          onclick: () => change({ remove: { [list]: { [kind]: [v] } } }, (list === "follow" ? "No longer following " : "No longer muting ") + v + ".") }, "Remove")));
      const part = (list, title, hint) => h("div", { class: "ticker-sub-part" }, h("h4", null, title), h("p", { class: "hint" }, hint),
        sub[list].areas.length || sub[list].types.length
          ? h("ul", { class: "ticker-chips" }, chips(list, "areas"), chips(list, "types"))
          : h("p", { class: "muted" }, "None."));
      append(clear(body),
        part("follow", "You follow", "Items of these areas or types are for you, and wake you."),
        part("mute", "You mute", "Items of these never wake you; one you also follow is still listed for you, marked muted."));
    }
    const list = h("select", { id: "ticker-sub-list" }, h("option", { value: "follow" }, "Follow"), h("option", { value: "mute" }, "Mute"));
    const kind = h("select", { id: "ticker-sub-kind" }, h("option", { value: "areas" }, "an area"), h("option", { value: "types" }, "a type"));
    list.value = "follow";
    kind.value = "areas";
    const value = h("input", { id: "ticker-sub-value", placeholder: "web/ or release", autocomplete: "off", required: true });
    const form = h("form", { class: "inline-form", onsubmit: (e) => {
      e.preventDefault();
      const v = value.value.trim();
      if (!v) return;
      value.value = "";
      change({ add: { [list.value]: { [kind.value]: [v] } } }, (list.value === "follow" ? "Following " : "Muting ") + v + ".");
    } }, h("label", { for: "ticker-sub-list", class: "visually-hidden" }, "Follow or mute"), list,
    h("label", { for: "ticker-sub-kind", class: "visually-hidden" }, "Area or type"), kind,
    h("label", { for: "ticker-sub-value", class: "visually-hidden" }, "The area or type"), value,
    h("button", { type: "submit", class: "small" }, "Add"));
    draw();
    append(box, body, form, h("p", { class: "hint" }, "Types: merge, contract, decision, deploy, release, note. Changes apply to items written from now on."), status.el);
    return box;
  }

  // §17.6: a note, a deploy or a release, by an owner or admin.
  function postForm(ctx, onPosted) {
    const status = M.statusLine();
    const type = h("select", { id: "ticker-post-type" }, h("option", { value: "note" }, "Note"), h("option", { value: "deploy" }, "Deploy"), h("option", { value: "release" }, "Release"));
    const text = h("textarea", { id: "ticker-post-text", rows: "2", maxlength: "280", required: true });
    const url = h("input", { id: "ticker-post-url", type: "url", placeholder: "https://…" });
    const to = h("select", { id: "ticker-post-to" }, h("option", { value: "computed" }, "whom it concerns"), h("option", { value: "all" }, "everyone (wakes all)"), h("option", { value: "list" }, "these members, roles, areas"));
    const tokens = h("input", { id: "ticker-post-tokens", placeholder: "member:agt-b role:admin area:web/" });
    const areas = h("input", { id: "ticker-post-areas", placeholder: "hub/ web/" });
    const release = h("input", { id: "ticker-post-release", placeholder: "rel-0001" });
    const env = h("input", { id: "ticker-post-env", placeholder: "staging" });
    const ver = h("input", { id: "ticker-post-version", placeholder: "0.3.0 or a sha" });
    const log = h("input", { id: "ticker-post-log", type: "url", placeholder: "https://…" });
    const field = (id, label, input, cls) => h("div", { class: "field " + (cls || "") }, h("label", { for: id }, label), input);
    const forNote = field("ticker-post-areas", "Areas (for whom it concerns)", areas, "only-note");
    const forRelease = field("ticker-post-release", "Release card (done)", release, "only-release");
    const forDeploy = [field("ticker-post-env", "Environment", env, "only-deploy"), field("ticker-post-version", "Version or sha", ver, "only-deploy"), field("ticker-post-log", "Log URL", log, "only-deploy")];
    const forList = field("ticker-post-tokens", "Members, roles, areas", tokens, "only-list");
    const show = () => {
      forNote.hidden = type.value !== "note";
      forRelease.hidden = type.value !== "release";
      forDeploy.forEach((f) => { f.hidden = type.value !== "deploy"; });
      forList.hidden = to.value !== "list";
    };
    type.value = "note";
    to.value = "computed";
    type.addEventListener("change", show);
    to.addEventListener("change", show);
    const send = h("button", { type: "submit" }, "Post");
    const words = (s) => s.split(/\s+/).filter(Boolean);
    const form = h("form", { class: "project-form ticker-post", onsubmit: async (e) => {
      e.preventDefault();
      const body = { type: type.value, text: text.value.trim() };
      if (url.value.trim()) body.url = url.value.trim();
      if (to.value === "all") body.to = "all";
      if (to.value === "list") body.to = words(tokens.value);
      if (type.value === "note" && words(areas.value).length) body.areas = words(areas.value);
      if (type.value === "release") body.release_task_id = release.value.trim();
      if (type.value === "deploy") {
        const v = ver.value.trim();
        body.deploy = Object.assign({ environment: env.value.trim() }, /^[0-9a-f]{7,40}$/.test(v) ? { sha: v } : { version: v }, log.value.trim() ? { log_url: log.value.trim() } : {});
      }
      if (to.value === "all" && !window.confirm("Post to everyone? It wakes every member who has not muted it.")) return;
      send.disabled = true;
      status.busy("Posting…");
      try {
        await M.api.post(ctx.base + "/ticker", body);
      } catch (err) {
        status.fail("Not posted: ", said(err));
        return;
      } finally {
        send.disabled = false;
      }
      text.value = "";
      status.done();
      append(status.el, h("span", { class: "ok" }, "Posted."));
      onPosted();
    } },
    field("ticker-post-type", "Type", type), field("ticker-post-text", "Text (at most 280 characters, plain)", text), field("ticker-post-url", "Link (https, optional)", url),
    field("ticker-post-to", "To", to), forList, forNote, forRelease, forDeploy, send, status.el);
    show();
    return h("section", { class: "ticker-post-box", "aria-labelledby": "ticker-post-title" },
      h("h3", { id: "ticker-post-title" }, "Post to the ticker"),
      h("p", { class: "hint" }, "For what the hub cannot see: a deploy without a webhook, a release, a note the team must know. Merges and decisions are written by the hub."),
      form);
  }

  M.ticker = { whyWords, said };
})(window.Maity);
