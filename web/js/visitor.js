// A public project as a reader who is no member sees it (docs/api.md §16.9, tsk-jj1tfre7n6zb):
// the views a member has, read-only, drawn only from GET /public/pages/{path}. Nothing here
// writes, polls or reads another route. A card here has no form and no actions, so it is drawn
// from the board's classes and not with board.js, whose card needs a member's context; its id
// links to its own page, `<owner>/<slug>/tasks/<id>`, where the hub stores the text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl } = M.dom;

  const VIEWS = [
    { path: "", get label() { return M.t("nav.overview"); } },
    { path: "/board", get label() { return M.t("nav.board"); } },
    { path: "/team", get label() { return M.t("nav.members"); } },
    { path: "/organisation", get label() { return M.t("nav.organisation"); } },
    { path: "/why", get label() { return M.t("nav.why"); } },
  ];
  const PROJECT_KINDS = ["project", "board", "team", "organisation", "why", "card"];
  // The project's views that, signed out, draw sections across the page (the rest a column).
  const ACROSS = ["project", "board", "team", "organisation", "why"];
  const COUNTERS = {
    get cards_done() { return M.t("visitor.stat.cards_done"); },
    get reviews_given() { return M.t("visitor.stat.reviews_given"); },
    get prs_merged() { return M.t("visitor.stat.prs_merged"); },
    get handovers() { return M.t("visitor.stat.handovers"); },
  };
  const NOTE_STATES = {
    get incorporated() { return M.t("visitor.note.incorporated"); },
    get dismissed() { return M.t("visitor.note.dismissed"); },
  };
  const COLUMNS = {
    get proposed() { return M.t("cards.column.proposed"); },
    get open() { return M.t("cards.column.open"); },
    get in_progress() { return M.t("cards.column.in_progress"); },
    get blocked() { return M.t("cards.column.blocked"); },
    get review() { return M.t("cards.column.review"); },
    get done() { return M.t("cards.column.done"); },
    get cancelled() { return M.t("cards.column.cancelled"); },
  };

  // A person's name as a link to their page; the path comes from the hub, the check stays here.
  function who(person) {
    return M.route.isRoute(person.page) ? h("a", { href: person.page }, person.name) : h("span", null, person.name);
  }
  const external = (url, label) => {
    const safe = safeUrl(url);
    return safe ? h("a", { href: safe, rel: "nofollow ugc" }, label || url) : null;
  };
  const names = (people) => h("ul", null, people.map((p) => h("li", null, who(p), " (" + p.handle + ")")));
  // A person's or an agent's page names their role in each project (§16.9); a project's own
  // lists carry none.
  const projectList = (projects) => h("ul", null, projects.map((p) => h("li", null, h("a", { href: "/" + p.full_name }, p.name),
    p.role ? [" ", h("span", { class: "label-tag" }, M.trust.roleLabel(p.role))] : null)));

  // "YYYY-MM" as the month and year in the reader's language, never a day (§16.9). The 1st at
  // noon UTC, so no time zone moves it into another month; an unreadable value stays as given.
  function month(value) {
    const found = /^(\d{4})-(\d{2})$/.exec(value || "");
    if (!found) return String(value);
    return M.fmt.when(new Date(Date.UTC(+found[1], +found[2] - 1, 1, 12)), { year: "numeric", month: "long", timeZone: "UTC" });
  }
  // Member since, online, and for an agent its model and harness: each only as the hub sends it.
  function facts(d) {
    const items = [];
    if (d.member_since) items.push(h("li", null, M.t("visitor.member_since", { month: month(d.member_since) })));
    if (d.online === true) items.push(h("li", null, M.t("visitor.online")));
    if (d.model) items.push(h("li", null, M.t("visitor.model", { model: d.model })));
    if (d.harness) items.push(h("li", null, M.t("visitor.harness", { harness: d.harness })));
    return items.length ? h("ul", { class: "visitor-facts" }, items) : null;
  }

  function statistics(totals) {
    return h("ul", { class: "visitor-stats" }, Object.keys(COUNTERS).filter((key) => totals[key] !== null && totals[key] !== undefined)
      .map((key) => h("li", null, COUNTERS[key] + ": " + totals[key])));
  }

  function editMark(e) {
    const o = { who: holderLabel(e.by) || M.t("visitor.holder.member"), at: M.dom.formatTime(e.at) };
    return e.reason ? M.tn("visitor.note.edited_reason", Object.assign(o, { reason: e.reason })) : M.tn("visitor.note.edited", o);
  }

  function holderLabel(holder) {
    if (!holder) return null;
    if (holder === "member") return h("span", { class: "muted" }, M.t("visitor.holder.member"));
    if (holder === "agent") return h("span", { class: "muted" }, M.t("visitor.holder.agent"));
    return who(holder);
  }

  // ---- the project's hero, figures and tab bar, signed out (tsk-9482zxza3gs3) ------------
  // The approved mockup's project page (project.html, pp.css): a dark hero in the landing's dark
  // zone, the figures in a band under it, the views as a full-width bar under both. The rules are
  // /assets/landing/public-sections.css (the hub's, hub/src/maity_hub/landing_assets), on with the
  // frame's stylesheets (js/site-chrome.js).

  // The project's tile: it has no picture, so its letter in the accent colour, the first letter of
  // its name or else the first character of its slug, as the hub's /explore draws it
  // (hub/src/maity_hub/public_projects.py, monogram).
  function monogram(name, slug) {
    const letter = Array.from(name || "").find((c) => /\p{L}/u.test(c));
    return (letter || String(slug || "").slice(0, 1)).toUpperCase();
  }

  // A forge the repository button names by its own name; any other reads "Repository".
  const FORGE_HOSTS = { "github.com": "GitHub", "gitlab.com": "GitLab" };
  const HOST = /^https:\/\/(?:www\.)?([^/?#:]+)(?::\d+)?([^?#]*)/i;
  // GitHub's mark (Octicons, MIT), as app.js draws it beside a repository; drawn as nodes, the
  // dashboard's policy refuses an inline style.
  const GITHUB_MARK = "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z";
  function githubMark() {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    [["viewBox", "0 0 16 16"], ["aria-hidden", "true"], ["focusable", "false"], ["class", "ico"]].forEach(([k, v]) => svg.setAttribute(k, v));
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", GITHUB_MARK);
    p.setAttribute("fill", "currentColor");
    svg.appendChild(p);
    return svg;
  }

  // A project link's short word for the link row: a page of the repository by the dashboard's own
  // words (Issues, Wiki, Discussions), any other by its host and path ("t.me/unicorndevs"). The
  // full address stays the link's title.
  const REPO_PAGES = {
    get issues() { return M.t("project.link.issues"); },
    get wiki() { return M.t("project.link.wiki"); },
    get discussions() { return M.t("project.link.discussions"); },
  };
  function shortLabel(url, repo) {
    const base = repo ? repo.replace(/\/+$/, "").replace(/\.git$/, "") : null;
    if (base && url.toLowerCase().startsWith(base.toLowerCase() + "/")) {
      const page = url.slice(base.length + 1).split(/[/?#]/)[0].toLowerCase();
      if (Object.hasOwn(REPO_PAGES, page)) return REPO_PAGES[page];
    }
    const found = HOST.exec(url);
    return found ? (found[1] + found[2]).replace(/\/+$/, "") : url;
  }

  // A member's picture from its public address (§6.10) at the size the hub serves for it, or
  // their letter where the hub sends none (a person whose profile is off) or it does not load.
  // `kind`: "hu" a round person, "ag" an agent's rounded square, as the mockup draws them. The
  // name always stands beside it or in its link, so the picture itself says nothing (alt="").
  function face(p, kind, px) {
    const cls = `av ${kind} av-${px}`;
    const letter = () => h("span", { class: `${cls} ini`, "aria-hidden": "true" }, monogram(p.name, p.handle));
    const pic = typeof p.picture === "string" && p.picture ? `${p.picture}${p.picture.includes("?") ? "&" : "?"}s=${px > 32 ? 128 : 64}` : null;
    if (!pic) return letter();
    try {
      const img = h("img", { class: cls, src: pic, alt: "", width: String(px), height: String(px), decoding: "async" });
      img.addEventListener("error", () => { if (img.parentNode) img.parentNode.replaceChild(letter(), img); });
      return img;
    } catch (refused) {
      return letter(); // not an address the page may load (h() allows only the hub's own images)
    }
  }
  // Whether a member of the project's lists is an agent: by its page, which the hub builds.
  const agentPages = (d) => new Set((d.agents || []).map((a) => a.page));

  // Who is online, as the hub counts them (`online`), and who of them it names: their pictures as
  // a stack, the first STACK of them, and how many more.
  const STACK = 8;
  function rightNow(d) {
    const online = d.online;
    if (!online || !(online.humans > 0 || online.agents > 0)) return null;
    const people = M.t("visitor.now.people", { count: online.humans });
    const agents = M.t("visitor.now.agents", { count: online.agents });
    const said = online.humans > 0 && online.agents > 0 ? M.t("visitor.now.both", { people, agents })
      : M.t("visitor.now.one", { who: online.humans > 0 ? people : agents });
    const named = online.named || [];
    const bots = agentPages(d);
    const more = named.length - STACK;
    return h("div", { class: "ph-live" },
      h("p", { class: "eyebrow" }, M.t("visitor.now")),
      h("p", { class: "big" }, h("i", { class: "dot", "aria-hidden": "true" }), said),
      named.length ? h("div", { class: "stack" }, named.slice(0, STACK).map((p) => {
        const pic = face(p, bots.has(p.page) ? "ag" : "hu", 30);
        return M.route.isRoute(p.page) ? h("a", { href: p.page, title: p.name, "aria-label": p.name }, pic)
          : h("span", { role: "img", title: p.name, "aria-label": p.name }, pic);
      }), more > 0 ? h("span", { class: "more", title: M.t("visitor.now.more.label", { count: more }) }, M.t("visitor.now.more", { count: more })) : null) : null,
      h("p", { class: "muted" }, M.t("visitor.now.working")));
  }

  // The team as cards (the mockup's Team section): the people, then the agents, as the hub lists
  // them, the first TEAM_CARDS; each with the picture, name, handle, role, an agent's harness and
  // a dot while online. The whole list, the counted members too, is the Team tab's.
  const TEAM_CARDS = 12;
  function memberCard(p, kind, online) {
    const facts = [p.role ? h("span", { class: "chip role" }, M.trust.roleLabel(p.role)) : null,
      kind === "ag" && p.harness ? h("span", { class: "h" }, p.harness) : null].filter(Boolean);
    const inner = [face(p, kind, 44),
      h("span", { class: "mc-t" }, h("b", null, p.name), h("small", null, "@" + p.handle), facts.length ? h("span", { class: "mc-m" }, facts) : null),
      online ? h("i", { class: "dot", role: "img", "aria-label": M.t("visitor.online"), title: M.t("visitor.online") }) : null];
    return M.route.isRoute(p.page) ? h("a", { class: "mcard", href: p.page }, inner) : h("div", { class: "mcard" }, inner);
  }
  function teamSection(d, base) {
    const all = d.people.map((p) => [p, "hu"]).concat(d.agents.map((a) => [a, "ag"]));
    if (!all.length) return null;
    const up = new Set(((d.online && d.online.named) || []).map((p) => p.page));
    const people = d.people.length ? M.t("visitor.now.people", { count: d.people.length }) : null;
    const agents = d.agents.length ? M.t("visitor.now.agents", { count: d.agents.length }) : null;
    return h("section", { class: "sec team-cards" }, h("div", { class: "wrap" },
      h("div", { class: "sec-h" }, h("h2", null, M.t("nav.members")),
        h("p", { class: "muted" }, people && agents ? M.t("visitor.team.both", { people, agents }) : people || agents),
        typeof d.members === "number" ? h("a", { class: "more-l", href: base + "/team" }, M.t("visitor.team.all", { count: d.members })) : null),
      h("div", { class: "mgrid" }, all.slice(0, TEAM_CARDS).map(([p, kind]) => memberCard(p, kind, up.has(p.page))))));
  }

  // What happened lately (the ticker of §16.9: the last 7 days, at most 20 entries): the merges as
  // pull request cards with their facts, the decisions as a list under them.
  const when = (at) => h("time", { datetime: at }, M.dom.formatTime(at));
  function prCard(e) {
    const m = e.merge || {};
    const url = e.url ? safeUrl(e.url) : null;
    const facts = [m.author ? M.t("visitor.merged.by", { author: m.author }) : null,
      Array.isArray(m.areas) && m.areas.length ? M.t("visitor.merged.touches", { areas: m.areas.join(", ") }) : null].filter(Boolean);
    const inner = [
      h("span", { class: "pr-h" }, typeof m.pr === "number" ? h("span", { class: "num" }, "#" + m.pr) : null,
        h("span", { class: "merged" }, M.t("visitor.merged.pill")), when(e.at)),
      h("b", null, m.title || e.text),
      facts.length ? h("small", null, facts.join(" · ")) : null];
    return url ? h("a", { class: "pr", href: url, rel: "nofollow ugc" }, inner) : h("div", { class: "pr" }, inner);
  }
  function recently(ticker) {
    if (!ticker || !ticker.length) return null;
    const merges = ticker.filter((e) => e.type === "merge");
    const others = ticker.filter((e) => e.type !== "merge");
    return h("section", { class: "sec alt recently" }, h("div", { class: "wrap" },
      h("div", { class: "sec-h" }, h("h2", null, merges.length ? M.t("visitor.merged") : M.t("visitor.recently")),
        h("p", { class: "muted" }, M.t("visitor.merged.window"))),
      merges.length ? h("div", { class: "prgrid" }, merges.map(prCard)) : null,
      others.length ? h("ul", { class: "dec" }, others.map((e) => h("li", null, when(e.at), h("span", null, e.text)))) : null));
  }

  // ---- the Board, Team, Organisation and Why tabs, signed out (tsk-9482zxza3gs3, part 3) ----
  // The mockup's README, point 10: the tabs under the same hero, in the Overview's section style
  // (a section across the page, its heading, cards and chips); what they show stays as it was.
  // Signed in, a non-member's view keeps its lists (`framed` is false there).

  // A section of a tab: its heading, a line beside it, then its parts.
  const tabSection = (kind, title, note, parts) => h("section", { class: "sec tab-sec " + kind + "-sec" }, h("div", { class: "wrap" },
    h("div", { class: "sec-h" }, h("h2", null, title), note ? h("p", { class: "muted" }, note) : null), parts));
  // A member's page as the hub builds it: an agent's is `/<owner>/agents/<handle>`, a person's `/<handle>`.
  const isAgentPage = (page) => /^\/[^/]+\/agents\/[^/]+$/.test(page || "");
  // "3 people and 26 agents", the Overview's words, for the members a tab names.
  function headcount(people, agents) {
    const p = people ? M.t("visitor.now.people", { count: people }) : null;
    const a = agents ? M.t("visitor.now.agents", { count: agents }) : null;
    return p && a ? M.t("visitor.team.both", { people: p, agents: a }) : p || a;
  }

  // The dark hero: the crumb `owner / slug`, the tile, the title and the state; on the Overview
  // the about text, the repository and the project's links as one row, and who is online beside it.
  // The other views carry only the parts their own answer has. `cta` is the slot the frame's
  // model fills with the header's own call to action (its address, only where the hub offers it).
  function hero(answer, d, base, reporting, cta) {
    const [owner, slug] = base.split("/").filter(Boolean);
    const overview = answer.kind === "project";
    const title = overview ? d.name : answer.kind === "card" ? d.title : slug;
    const repo = overview && d.repository_url ? safeUrl(d.repository_url) : null;
    const host = repo ? (HOST.exec(repo) || [])[1] : null;
    const forge = host ? FORGE_HOSTS[host.toLowerCase()] : null;
    const repoButton = repo ? h("a", { class: "btn btn-secondary", href: repo, rel: "nofollow ugc", title: repo },
      forge === "GitHub" ? githubMark() : null, forge || M.t("project.link.repository")) : null;
    const links = overview ? d.links.map((url) => {
      const safe = safeUrl(url);
      return safe ? h("a", { href: safe, rel: "nofollow ugc", title: safe }, shortLabel(safe, repo)) : null;
    }).filter(Boolean) : [];
    return h("section", { class: "phero hero dz" }, h("div", { class: "wrap" },
      h("div", { class: "ph-main" },
        h("p", { class: "crumb" }, owner, " / ", answer.path === base ? slug : h("a", { href: base }, slug)),
        h("div", { class: "ph-title" },
          answer.kind === "card" ? null : h("span", { class: "pmark", "aria-hidden": "true" }, monogram(overview ? d.name : "", slug)),
          h("h1", null, title),
          overview ? h("span", { class: "chip state" }, M.dom.word("project", d.state)) : null),
        overview && d.about ? h("div", { class: "sub about" }, M.markdown(d.about)) : null,
        h("div", { class: "cta" }, cta, repoButton),
        links.length ? h("p", { class: "plinks" }, links.flatMap((a, i) => (i ? [" · ", a] : [a]))) : null,
        reporting ? [h("p", { class: "report-row" }, reporting.button), reporting.slot] : null),
      overview ? rightNow(d) : null));
  }

  // The figures band: the members, as many as the Team tab lists (`members`, §16.9: those it
  // names and those it only counts), and the agents' four counts of the last 30 days. A figure that is 0 or that the hub
  // left empty is not shown (the mockup's README, decided by the marketing head); none, no band.
  function band(d) {
    const figures = [[M.t("visitor.stat.members"), d.members, false]]
      .concat(Object.keys(COUNTERS).map((key) => [COUNTERS[key], d.statistics.totals[key], true]))
      .filter(([, n]) => typeof n === "number" && n > 0);
    if (!figures.length) return null;
    return h("section", { class: "band" }, h("div", { class: "wrap stats5" }, figures.map(([label, n, window]) => h("div", { class: "stat" },
      h("b", null, M.fmt.number(n)), h("span", { class: "label" }, label), window ? h("small", null, M.t("visitor.stat.window")) : null))));
  }

  // The project's views as a bar across the page, under the hero and the band.
  function tabBar(answer, base, title) {
    return h("nav", { class: "ptabs", "aria-label": title }, h("div", { class: "wrap" }, VIEWS.map((v) => h("a", {
      href: base + v.path,
      class: "view-tab",
      "aria-current": base + v.path === answer.path || (answer.kind === "card" && v.path === "/board") ? "page" : null,
    }, v.label))));
  }

  const draw = {
    // `framed`: signed out, in the landing's frame, where the hero and the band already show the
    // state, the about text, the links, who is online and the figures; the team and what happened
    // lately follow as the mockup's sections, each across the page.
    project(d, base, framed) {
      if (framed) return [teamSection(d, base), recently(d.ticker)];
      return [
        h("p", { class: "muted" }, M.dom.word("project", d.state)),
        d.about ? h("div", { class: "about" }, M.markdown(d.about)) : null,
        d.repository_url ? h("p", null, external(d.repository_url)) : null,
        d.links.map((url) => h("p", null, external(url))),
        d.people.length ? [h("h2", null, M.t("visitor.people")), names(d.people)] : null,
        d.agents.length ? [h("h2", null, M.t("visitor.agents")), names(d.agents)] : null,
        d.ticker && d.ticker.length ? [h("h2", null, M.t("visitor.recently")), h("ul", { class: "visitor-ticker" }, d.ticker.map((e) => h("li", null,
          h("span", { class: "muted" }, M.dom.formatTime(e.at)), " ", (e.url && external(e.url, e.text)) || e.text)))] : null,
        d.online ? [h("h2", null, M.t("visitor.online")),
          h("p", null, M.t("visitor.online.humans", { count: d.online.humans }), " · ", M.t("visitor.online.agents", { count: d.online.agents })),
          d.online.named.length ? names(d.online.named) : null] : null,
        h("h2", null, M.t("visitor.statistics")), statistics(d.statistics.totals),
      ];
    },
    board(d, base, framed) {
      // The columns scroll sideways on a phone. A card's link scrolls them by keyboard; a board with
      // no card has none, so there the columns are a named region that takes the focus (WCAG 2.1.1),
      // and a board with cards gets no extra stop before them (#1720's review).
      const empty = !d.columns.some((col) => col.cards.length);
      const region = empty ? { role: "region", tabindex: "0", "aria-label": M.t("nav.board") } : {};
      // Framed, under the section's own h2: a column is an h3, a card's title an h4, its label a chip.
      const [colH, cardH] = framed ? ["h3", "h4"] : ["h2", "h3"];
      const columns = h("div", Object.assign({ class: "columns" }, region), d.columns.map((col) => h("section", { class: "column", "data-status": col.status, "aria-label": COLUMNS[col.status] || col.status },
        h(colH, null, (COLUMNS[col.status] || col.status) + " (" + col.cards.length + ")"),
        col.cards.map((c) => h("article", { class: "card", "data-card": c.id, "aria-label": c.title },
          h("header", null, h("a", { class: "card-id", href: base + "/tasks/" + c.id }, c.id), c.label ? h("span", { class: framed ? "chip label" : "label-tag" }, M.dom.word("label", c.label)) : null),
          h(cardH, null, c.title),
          holderLabel(c.holder))))));
      if (!framed) return columns;
      const count = d.columns.reduce((n, col) => n + col.cards.length, 0);
      return tabSection("board", M.t("nav.board"), M.t("overview.board.cards", { count }), columns);
    },
    card(d) {
      return [
        h("p", null, h("span", { class: "card-id" }, d.id), " ", h("span", { class: "label-tag" }, COLUMNS[d.status] || d.status),
          d.label ? [" ", h("span", { class: "label-tag" }, M.dom.word("label", d.label))] : null,
          d.holder ? [" ", holderLabel(d.holder)] : null),
        d.body && d.body.trim() ? h("div", { class: "about" }, M.markdown(d.body)) : null,
        d.notes && d.notes.length ? [h("h2", null, M.t("cardpanel.notes")), h("ol", { class: "card-notes" }, d.notes.map((n) => h("li", { "data-note": n.id },
          h("p", { class: "muted" }, holderLabel(n.author), " · ", M.dom.formatTime(n.created_at), NOTE_STATES[n.state] ? " · " + NOTE_STATES[n.state] : "",
            // The edit mark as the hub's own page has it (§16.9, a card's page): the editor named as a holder, the date,
            // the reason; never the old text, and none on a removed note.
            n.edited && !n.redacted ? [" · ", editMark(n.edited)] : null),
          n.redacted ? h("p", { class: "muted" }, M.t("jfa.redacted")) : h("div", { class: "about" }, M.markdown(n.body || "")))))] : null,
      ];
    },
    team(d, base, framed) {
      if (framed) {
        // The members it names as the Overview's cards (picture or letter, name, @handle, role chip),
        // the people first; those it only counts as chips with their number under them.
        const named = d.shown.filter((p) => !isAgentPage(p.page)).map((p) => [p, "hu"])
          .concat(d.shown.filter((p) => isAgentPage(p.page)).map((p) => [p, "ag"]));
        const people = named.filter(([, kind]) => kind === "hu").length;
        return tabSection("team", M.t("nav.members"), headcount(people, named.length - people), [
          named.length ? h("div", { class: "mgrid" }, named.map(([p, kind]) => memberCard(p, kind, false))) : null,
          d.others.length ? [h("h3", null, M.t("visitor.others")),
            h("ul", { class: "role-counts" }, d.others.map((o) => h("li", null, h("b", null, M.fmt.number(o.count)), h("span", { class: "chip role" }, M.trust.roleLabel(o.role)))))] : null,
        ]);
      }
      return [
        h("ul", null, d.shown.map((p) => h("li", null, who(p), " (" + p.handle + ") ", h("span", { class: "muted" }, M.trust.roleLabel(p.role))))),
        d.others.length ? [h("h2", null, M.t("visitor.others")),
          h("ul", null, d.others.map((o) => h("li", null, o.count + " × " + M.trust.roleLabel(o.role))))] : null,
      ];
    },
    organisation(d, base, framed) {
      const below = (index) => d.nodes.filter((n) => n.reports_to === index);
      if (framed) {
        // The same tree, each node a small card: a named member's picture or letter, name, @handle
        // and role chip, a link to their page; one the page does not name only its role chip.
        const card = (n) => {
          if (!n.person) return h("span", { class: "onode anon" }, h("span", { class: "chip role" }, M.trust.roleLabel(n.role)));
          const p = n.person;
          const inner = [face(p, isAgentPage(p.page) ? "ag" : "hu", 30),
            h("span", { class: "mc-t" }, h("b", null, p.name), h("small", null, "@" + p.handle)),
            h("span", { class: "chip role" }, M.trust.roleLabel(n.role))];
          return M.route.isRoute(p.page) ? h("a", { class: "onode", href: p.page }, inner) : h("span", { class: "onode" }, inner);
        };
        const tree = (list, seen) => (list.length ? h("ul", null, list.map((n) => {
          const next = new Set([...seen, n.index]);
          return h("li", null, card(n), tree(below(n.index).filter((c) => !next.has(c.index)), next));
        })) : null);
        const named = d.nodes.filter((n) => n.person);
        const people = named.filter((n) => !isAgentPage(n.person.page)).length;
        return tabSection("organisation", M.t("nav.organisation"), headcount(people, named.length - people),
          h("div", { class: "otree" }, tree(below(null), new Set())));
      }
      // A line back to a node already drawn is not followed: the answer is data, not a promise.
      const node = (n, seen) => h("li", null, n.person ? who(n.person) : h("span", { class: "muted" }, M.trust.roleLabel(n.role)),
        n.person ? h("span", { class: "muted" }, " " + M.trust.roleLabel(n.role)) : null,
        branch(below(n.index).filter((c) => !seen.has(c.index)), new Set([...seen, n.index])));
      const branch = (list, seen) => (list.length ? h("ul", null, list.map((n) => node(n, new Set([...seen, n.index])))) : null);
      return h("div", { class: "org-box" }, branch(below(null), new Set()));
    },
    why(d, base, framed) {
      if (framed) {
        // The entries' count beside the heading, the family as cards with their letter (each a link
        // to its published dashboard where there is one), what needs attention as lines with a chip.
        if (!d.readable) return tabSection("why", M.t("nav.why"), null, h("p", { class: "muted" }, M.t("visitor.why.unread")));
        const kin = (m) => {
          const label = m.name || m.path;
          const url = m.dashboard_url ? safeUrl(m.dashboard_url) : null;
          const inner = [h("span", { class: "pmark sm", "aria-hidden": "true" }, monogram(label, m.path)),
            h("span", { class: "mc-t" }, h("b", null, label), m.name && m.path ? h("small", null, m.path) : null)];
          return url ? h("a", { class: "mcard", href: url, rel: "nofollow ugc" }, inner) : h("div", { class: "mcard" }, inner);
        };
        return tabSection("why", M.t("nav.why"), M.t("visitor.why.entries", { count: d.summary.entries }), [
          d.family.length ? [h("h3", null, M.t("visitor.why.family")), h("div", { class: "mgrid" }, d.family.map(kin))] : null,
          d.attention.length ? [h("h3", null, M.t("visitor.why.attention")),
            h("ul", { class: "dec att" }, d.attention.map((a) => h("li", null, h("span", { class: "chip status" }, M.why.statusWord(a.status)),
              h("span", null, external(a.link, a.title) || a.title))))] : null,
        ]);
      }
      if (!d.readable) return h("p", { class: "muted" }, M.t("visitor.why.unread"));
      return [
        h("p", null, M.t("visitor.why.entries", { count: d.summary.entries })),
        d.family.length ? [h("h2", null, M.t("visitor.why.family")),
          h("ul", null, d.family.map((m) => h("li", null, external(m.dashboard_url, m.name || m.path) || (m.name || m.path))))] : null,
        d.attention.length ? [h("h2", null, M.t("visitor.why.attention")),
          h("ul", null, d.attention.map((a) => h("li", null, external(a.link, a.title) || a.title, " ", h("span", { class: "label-tag" }, M.why.statusWord(a.status)))))] : null,
      ];
    },
    person(d) {
      return [
        d.bio ? h("p", null, d.bio) : null,
        d.website ? h("p", null, external(d.website)) : null,
        d.social ? h("ul", null, Object.keys(d.social).map((net) => h("li", null, net + ": " + d.social[net]))) : null,
        facts(d),
        d.projects.length ? [h("h2", null, M.t("visitor.projects")), projectList(d.projects)] : null,
        // A person's own three counts, only while they chose to show them (`public_stats`).
        d.statistics ? [h("h2", null, M.t("visitor.statistics.own")), statistics(d.statistics)] : null,
        d.agents.length ? [h("h2", null, M.t("visitor.agents")), names(d.agents)] : null,
      ];
    },
    agent(d) {
      return [
        h("p", null, who(d.owner)),
        facts(d),
        h("h2", null, M.t("visitor.projects")), projectList(d.projects),
        h("h2", null, M.t("visitor.statistics")), statistics(d.statistics),
      ];
    },
    // A person's agents (§16.9, "A person's agents"): drawn as the signed-in person view draws
    // the same list (js/person.js), a sentence where none is listed.
    person_agents(d) {
      return [h("h2", null, M.t("person.tab.agents")), M.person.agentList(d.agents)];
    },
    organisation_page(d) {
      return d.projects.length ? [h("h2", null, M.t("visitor.projects")), projectList(d.projects)] : null;
    },
  };

  // The project's address under which a view of it stands: `<owner>/<slug>`.
  const projectBase = (path) => "/" + path.split("/").filter(Boolean).slice(0, 2).join("/");

  // Whether the address can name a stored page at all: the hub is not asked for the rest.
  function canBePublic(where, path) {
    const parts = path.split("/").filter(Boolean);
    if (where.scope === "person") return parts.length === 1 || (parts.length === 2 && where.tab === "agents");
    if (where.scope !== "project") return false;
    if (parts[1] === "agents") return parts.length === 3;
    if (parts[2] === "tasks") return parts.length === 4;
    if (parts[2] === "overview") return parts.length === 3 || (parts.length === 4 && ["project", "swarm"].includes(parts[3]));
    return parts.length === 2 || (parts.length === 3 && ["board", "team", "organisation", "why"].includes(parts[2]));
  }

  // The member Overview's addresses (§16.11) read the project's own page, the public overview
  // (§16.9, the maintainer's decision of 2026-11-01): the badge links to /overview (§6.20). Its swarm
  // tab is the members' alone; null there, where the caller decides. An agent's page is its own:
  // `overview` is a handle an agent may hold (hub/src/maity_hub/paths.py, `handle_reserved`).
  function storedPath(path) {
    const parts = path.split("/").filter(Boolean);
    if (parts[1] === "agents" || parts[2] !== "overview") return path;
    return parts[3] === "swarm" ? null : "/" + parts.slice(0, 2).join("/");
  }

  // Draws the page of `path` when the hub stores one; false when it stores none, for the
  // caller's own answer (the login, or not_found); null signed out when the read failed otherwise.
  async function page(main, header, where, path, { signedIn, brand, tools, head, live }) {
    if (!canBePublic(where, path)) return false;
    const stored = storedPath(path);
    if (stored === null) {
      // The swarm: a visitor keeps the login, which goes on here after the sign-in (§16.11); a
      // signed-in non-member is taken to the overview instead of being told they are none, but
      // only where the project has a page: an earlier address (a rename, a transfer) has none, and
      // the caller then leads a member on to the current one, the tab kept.
      if (!signedIn) return false;
      try {
        await M.api.get("/public/pages/" + path.split("/").filter(Boolean).slice(0, 2).join("/"));
      } catch (err) {
        if (err.status === 404) return false;
        throw err;
      }
      if (live()) M.route.go(path.replace(/\/swarm\/?$/, ""), { replace: true });
      return true;
    }
    let answer;
    try {
      answer = await M.api.get("/public/pages/" + stored.replace(/^\/+/, ""));
    } catch (err) {
      // No page (404): false, and the caller's answer stands, the login at a dashboard route or
      // "not found" at a handle or an unknown view word (app.js, showsVisitorNothing). Signed
      // out, any other failed read is null: the caller keeps the login, which is still a way on,
      // and never says "not found" for a page it could not read. Signed in, it is said as any
      // failed page is.
      if (err.status === 404) return false;
      if (!signedIn) return null;
      throw err;
    }
    if (!live()) return true;
    const d = answer.data;
    const inProject = PROJECT_KINDS.includes(answer.kind);
    const base = inProject ? projectBase(answer.path) : answer.path;
    if (signedIn) {
      await head();
      if (!live()) return true;
    } else {
      const signIn = h("a", { class: "visitor-sign-in", href: M.withNext("/login", path) }, M.t("visitor.sign_in"));
      append(clear(header), h("div", { class: "bar" }, brand, signIn, tools));
    }
    // A person's two pages carry the tabs Profile and Agents (§16.9), as the person view does.
    const personTab = { person: "profile", person_agents: "agents" }[answer.kind] || null;
    const title = answer.kind === "card" ? d.title
      : answer.kind === "person_agents" ? M.t("person.title.agents", { name: (d.owner && d.owner.name) || base.split("/")[1] })
        : d.name || base.slice(1);
    // Report what this page shows (§16.8, tsk-7ze5w6ymf7bw), named as the page names it: a person by
    // the handle, an agent by its global name `<owner>/<handle>`, a project by its full name, a card by
    // its id with the project. Signed out, a link to the sign-in that comes back with the form open.
    const report = M.report ? reportOf(answer, base) : null;
    const reporting = report ? M.report.control(report.target, report.what, { signedOut: signedIn ? null : path }) : null;
    if (!signedIn && inProject) {
      // Signed out, a project's page in the approved mockup's layout (tsk-9482zxza3gs3): the hero,
      // the figures on the Overview, the views as a bar, then the view itself in the stored pages' look.
      const cta = h("span", { class: "cta-slot" });
      append(clear(main), h("section", { class: "view-visitor public-view", "data-kind": answer.kind },
        hero(answer, d, base, reporting, cta),
        answer.kind === "project" ? band(d) : null,
        tabBar(answer, base, title),
        // The Overview and the Board, Team, Organisation and Why tabs draw their own sections across
        // the page; a card's page stands in the stored pages' column.
        ACROSS.includes(answer.kind) ? draw[answer.kind](d, base, true)
          : h("div", { class: "stored-page" }, h("div", { class: "wrap" }, draw[answer.kind] ? draw[answer.kind](d, base, true) : null))));
      document.title = title;
      // The hero's "Try it" leads where the header's call to action does (§16.7.5, the landing
      // hero's primary button): its address from the frame's model, and none where it has none.
      M.siteChrome.enter(path, (model) => {
        const offer = model.header && model.header.cta;
        if (offer) append(clear(cta), M.siteChrome.link(Object.assign({}, offer, { label: M.t("visitor.hero.try") }), { class: "btn btn-primary" }));
      }, { next: path });
      if (reporting && reporting.open && M.report.asked()) reporting.open();
      return true;
    }
    const content = [
      h("h1", null, title),
      reporting ? [h("p", { class: "report-row" }, reporting.button), reporting.slot] : null,
      inProject ? h("nav", { class: "view-tabs", "aria-label": title }, VIEWS.map((v) => h("a", {
        href: base + v.path,
        class: "view-tab",
        // A card's page belongs to the Board, the tab it is reached from.
        "aria-current": base + v.path === answer.path || (answer.kind === "card" && v.path === "/board") ? "page" : null,
      }, v.label))) : null,
      personTab ? M.person.tabs(answer.path.split("/").filter(Boolean)[0], personTab) : null,
      draw[answer.kind] ? draw[answer.kind](d, base) : null];
    // Signed out the page stands in the landing's frame (§16.7.5), as the hub's stored pages do:
    // its header and footer around it, the content in the stored pages' look (public-pages.css,
    // .stored-page). The app's bar above stays only for where the frame cannot be read.
    append(clear(main), signedIn
      ? h("section", { class: "view-visitor", "data-kind": answer.kind }, content)
      : h("section", { class: "view-visitor stored-page", "data-kind": answer.kind }, h("div", { class: "wrap" }, content)));
    document.title = title;
    if (!signedIn) M.siteChrome.enter(path, null, { next: path });
    if (reporting && reporting.open && M.report.asked()) reporting.open();
    return true;
  }

  // What a page reports, and the word for its button; null where it names no one target.
  function reportOf(answer, base) {
    const parts = answer.path.split("/").filter(Boolean);
    if (answer.kind === "person") return { target: { type: "profile", id: parts[0] }, what: "person" };
    if (answer.kind === "agent") return { target: { type: "profile", id: parts[0] + "/" + parts[2] }, what: "agent" };
    if (answer.kind === "card") return { target: { type: "card", id: parts[3], project: base.slice(1) }, what: "card" };
    if (PROJECT_KINDS.includes(answer.kind)) return { target: { type: "project", id: base.slice(1) }, what: "project" };
    return null;
  }

  M.visitor = { page };
})(window.Maity);
