// Behaviour smoke test for the dashboard: runs the page's scripts against a
// minimal DOM shim in Node and walks every view in fixture mode and, with a
// fake hub, in API mode. It is not a browser: layout, CSS and real events
// are not covered. Needs a node binary only, no packages.
//
//   node tools/smoke.js .        (from web/; `make smoke`)
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const WEB = process.argv[2];

class Node_ {
  constructor() { this.childNodes = []; this.parentNode = null; }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() { const p = this.parentNode; return (p && p.childNodes[p.childNodes.indexOf(this) + 1]) || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(typeof c === "string" ? new Text_(c) : c)); }
  prepend(c) { c.parentNode = this; this.childNodes.unshift(c); }
  insertBefore(c, ref) { c.parentNode = this; const i = ref ? this.childNodes.indexOf(ref) : -1; if (i < 0) this.childNodes.push(c); else this.childNodes.splice(i, 0, c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  replaceChild(c, old) { const i = this.childNodes.indexOf(old); if (i < 0) return old; if (c.parentNode) c.parentNode.removeChild(c); this.childNodes[i] = c; c.parentNode = this; old.parentNode = null; return old; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.childNodes = []; if (v !== "") this.appendChild(new Text_(String(v))); }
}
// A browser's querySelectorAll answers a NodeList, which has forEach and
// indices but no find, some or map. The page's own scripts (js/…) get one
// that throws on those, as a browser would; the tests below may keep
// using array methods on it.
const ARRAY_ONLY = new Set(["find", "findIndex", "findLast", "some", "every", "map", "filter", "reduce", "includes", "indexOf",
  "slice", "concat", "flatMap", "join", "sort"]);
function nodeList(items) {
  return new Proxy(items, {
    get(target, prop, receiver) {
      if (typeof prop === "string" && ARRAY_ONLY.has(prop)) {
        const caller = (new Error().stack || "").split("\n")[2] || "";
        if (/[(\s]js\/[\w-]+\.js:\d+/.test(caller)) throw new TypeError("NodeList has no " + prop + " (" + caller.trim() + ")");
      }
      return Reflect.get(target, prop, receiver);
    },
  });
}
class Text_ extends Node_ { constructor(t) { super(); this.t = t; } get textContent() { return this.t; } }
class El extends Node_ {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.attrs = {}; this.listeners = {}; this.className = ""; this.value = ""; this.disabled = false; this.style = { setProperty(k, v) { this[k] = v; } }; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "id") this.id = v; }
  getAttribute(k) { return k === "class" ? this.className : this.attrs[k]; }
  removeAttribute(k) { delete this.attrs[k]; }
  get classList() {
    const names = () => this.className.split(" ").filter(Boolean);
    const set = (list) => { this.className = list.join(" "); };
    return {
      contains: (c) => names().includes(c),
      toggle: (c, on) => { const has = names().includes(c); const want = on === undefined ? !has : on; set(want ? (has ? names() : names().concat(c)) : names().filter((x) => x !== c)); return want; },
    };
  }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, extra) { const e = Object.assign({ target: this, preventDefault() {}, key: "" }, extra || {}); (this.listeners[t] || []).forEach((f) => f(e)); }
  click() { this.dispatch("click"); }
  requestSubmit() { this.dispatch("submit"); }
  focus() {}
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  matches(sel) {
    return sel.split(",").some((s) => {
      s = s.trim();
      const m = /^([a-z]*)((?:\.[\w-]+)*)(?:\[([\w-]+)="([^"]*)"\])?$/.exec(s);
      if (!m) throw new Error("selector " + s);
      if (m[1] && this.tagName !== m[1].toUpperCase()) return false;
      const cls = this.className.split(/\s+/);
      if (m[2] && !m[2].split(".").filter(Boolean).every((c) => cls.includes(c))) return false;
      if (m[3] && this.attrs[m[3]] !== m[4]) return false;
      return true;
    });
  }
  all() { const out = []; const walk = (n) => n.childNodes.forEach((c) => { if (c instanceof El) { out.push(c); walk(c); } }); walk(this); return out; }
  querySelectorAll(sel) {
    const parts = sel.split(/\s+(?![^\[]*\])/);
    if (sel.includes(",")) return nodeList(this.all().filter((e) => e.matches(sel)));
    let set = [this];
    parts.forEach((p) => { set = [...new Set(set.flatMap((n) => n.all().filter((e) => e.matches(p))))]; });
    return nodeList(set);
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const header = new El("header"); header.id = "header";
const head = new El("head");
const main = new El("main"); main.id = "main";
const docListeners = {};
const document = {
  createElement: (t) => new El(t),
  createElementNS: (ns, t) => new El(t),
  createTextNode: (t) => new Text_(t),
  head,
  documentElement: new El("html"),
  getElementById: (id) => ({ header, main })[id],
  querySelector: (s) => header.querySelector(s) || main.querySelector(s),
  addEventListener: (t, f) => { docListeners[t] = f; },
  removeEventListener: (t, f) => { if (docListeners[t] === f) delete docListeners[t]; },
  title: "",
  cookie: "",
};
// Intervals are recorded, not run: the test fires them when it wants to.
const intervals = new Map();
let intervalId = 0;
const win = {
  location: { protocol: "file:", search: "", hash: "", replace(h) { this.hash = h; setTimeout(() => win.onhashchange(), 0); } },
  addEventListener: (t, f) => { win["on" + t] = f; },
  removeEventListener: (t, f) => { if (win["on" + t] === f) win["on" + t] = null; },
  confirm: () => true,
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id),
  setInterval: (fn) => { intervalId += 1; intervals.set(intervalId, fn); return intervalId; },
  clearInterval: (id) => { intervals.delete(id); },
};
const fireIntervals = async () => { for (const fn of [...intervals.values()]) await fn(); };
const ctx = { window: win, document, Node: Node_, URL, URLSearchParams, Uint8Array, console, Promise, JSON, Date, Set, Object, Array, Number, String, Error };
win.window = win;
vm.createContext(ctx);
const html = fs.readFileSync(path.join(WEB, "index.html"), "utf8");
expect0(!html.includes("fixtures/fixtures.js"), "index.html does not load the fixture bundle");
// In a browser api.js loads the bundle on file:// by itself; here it is run up front.
vm.runInContext(fs.readFileSync(path.join(WEB, "fixtures/fixtures.js"), "utf8"), ctx, { filename: "fixtures.js" });
[...html.matchAll(/<script src="([^"]+)"/g)].forEach((m) => vm.runInContext(fs.readFileSync(path.join(WEB, m[1]), "utf8"), ctx, { filename: m[1] }));

function expect0(cond, what) { if (!cond) { console.log("FAIL " + what); process.exitCode = 1; } else console.log("ok   " + what); }
const tick = () => new Promise((r) => setTimeout(r, 20));
const text = (el) => el.textContent.replace(/\s+/g, " ");
let failures = 0;
const throws = (fn) => { try { fn(); return false; } catch (e) { return true; } };
function expect(cond, what) { console.log((cond ? "ok   " : "FAIL ") + what); if (!cond) failures++; }

ctx.navigator = { clipboard: { writeText: async (t) => { ctx.copied = t; } } };
(async () => {
  async function go(hash) { win.location.hash = hash; win.onhashchange(); await tick(); await tick(); }
  // A chip's text starts with its monogram (or nothing, for a logo), then the name.
  const chip = (label) => header.querySelectorAll(".switcher a").find((a) => a.textContent.replace(/^[A-Z?]{1,2}(?=[A-Z+])/, "").startsWith(label)
    || a.querySelectorAll(".project-mark").length && a.textContent.slice(a.querySelector(".project-mark").textContent.length).startsWith(label));
  const chipCount = (label) => { const c = chip(label) && chip(label).querySelector(".count"); return c ? c.textContent : ""; };
  const btn = (root, label) => root.querySelectorAll("button").find((b) => b.textContent === label);
  // The gear menu in the header: the hub's and one's own, not the project's.
  const gearButton = () => header.querySelectorAll("button").find((b) => b.getAttribute("aria-label") === "Settings");
  // Project settings are the project's Settings tab (the maintainer's request): the helper opens it,
  // drawn afresh; a test moves on by its next go().
  const onSettings = () => /^#\/[^/]+\/[^/]+\/settings$/.test(win.location.hash);
  const projectSettings = async () => {
    const full = (/^#\/([^/]+\/[^/]+)/.exec(win.location.hash) || [])[1];
    await go("#/" + full + "/settings"); for (let k = 0; k < 6; k++) await tick();
  };
  const byId = (id) => main.all().find((e) => e.id === id) || header.all().find((e) => e.id === id);
  // A browser compiles `pattern` as ^(?:…)$ with the v flag and ignores one that does not compile.
  const badPatterns = () => main.all().filter((e) => e.attrs.pattern !== undefined).filter((e) => {
    try { new RegExp("^(?:" + e.attrs.pattern + ")$", "v"); return false; } catch (err) { return true; }
  }).map((e) => e.id);
  const gets = [];
  const realGet = win.Maity.api.get;
  win.Maity.api.get = (p) => { gets.push(p); return realGet(p); };
  const realAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => { gets.push(p); return realAll(p); };
  docListeners.DOMContentLoaded(); await tick(); await tick();
  // The title without the count of what asks for the human (js/notify.js).
  const plainTitle = () => document.title.replace(/^\(\d+\) /, "");
  expect(win.location.hash === "#/all", "empty hash with two projects lands on #/all");
  expect(!main.querySelector(".error"), "cross-project inbox renders");
  expect(gets.some((p) => p.startsWith("/requests")) && !main.querySelector(".lead-projects") && !header.querySelector(".lead-chat"),
    "#/all renders requests; no lead strip (the lead is behind the header's Chat button)");
  expect(!text(main).includes("null") && !text(header).includes("null"), "no stray 'null' text");
  // With notifications (docs/api.md §18.2): requests plus unread chats and mentions; Maity has one of each unread.
  // The total also holds a personal request of a project the human is no member of (member: false), on no project's pill.
  expect(chipCount("All projects") === "7" && chipCount("Maity") === "5" && chipCount("Sample shop") === "1", "switcher counts 7 / 5 / 1");
  expect(document.title.startsWith("(7) "), "the tab title starts with what asks for the human");
  const allChip = header.querySelectorAll("nav.switcher a").find((a) => a.textContent.startsWith("All projects")).querySelector(".count");
  expect(allChip.getAttribute("aria-label") === "5 open, 1 unread in chats, 1 mention", "the All projects count says what it is made of, as the pills do");
  expect(main.querySelectorAll(".project-label").length === 6, "every entry labelled with its project, a personal request as Personal");
  const firstRow = main.querySelector("li.entry .entry-row");
  expect(firstRow && firstRow.childNodes[0].tagName === "A" && firstRow.childNodes[0].className === "project-label"
    && /^#\/maintainer\/(maity|sample)\/inbox$/.test(firstRow.childNodes[0].getAttribute("href")) && firstRow.childNodes[1].className === "entry-head",
    "inbox: each entry's project badge is a link to the project, before the entry");
  expect(main.querySelectorAll("li.entry .entry-head").every((b) => /^(Personal, Elsewhere|Personal, Maity|Maity|Sample shop): /.test(b.querySelector(".visually-hidden").textContent)),
    "inbox: the project's name starts each entry's accessible name");
  // Logos (docs/api.md §11.2): Maity has an image, Sample shop a monogram.
  const markOf = (label) => chip(label).querySelector(".project-mark");
  expect(markOf("Maity").tagName === "IMG" && markOf("Maity").getAttribute("src") === "fixtures/maity/logo.png" && markOf("Maity").getAttribute("alt") === "",
    "logo: the switcher shows a project's logo, decorative next to its name");
  expect(markOf("Sample shop").tagName === "SPAN" && markOf("Sample shop").textContent === "SS" && markOf("Sample shop").getAttribute("aria-hidden") === "true"
    && /^#[0-9a-f]{6}$/.test(markOf("Sample shop").style.background), "logo: without one, a monogram from the initials in a colour of the slug");
  expect(main.querySelectorAll(".project-label .project-mark").length === 4, "logo: every #/all entry carries its project's mark");
  expect(!gets.includes("/projects"), "logo: with logos on /me's projects, no extra read of the project views");
  const refuses = (src) => { try { win.Maity.dom.h("img", { src }); return false; } catch (e) { return true; } };
  expect(refuses("https://evil.example/x.png") && refuses("blob:https://evil.example/x") && refuses("//evil.example/x.png")
    && refuses("/api/v1/projects/../logo?v=1") && !refuses("fixtures/maity/logo.png") && !refuses("/api/v1/projects/maintainer/maity/logo?v=%22f1%22"),
    "dom: an image is a local file or the hub's own image, never another origin, not even https");
  let cur = main.querySelector(".current");
  expect(cur && text(cur).includes("rounding fix") && text(cur).includes("Review") && text(cur).includes("urgent"), "urgent first (Sample shop, with its state)");
  expect(cur && !btn(cur, "Later (stays open)") && btn(cur, "Later"), "local Later button present");
  btn(cur, "Later").click(); await tick();
  cur = main.querySelector(".current");
  expect(cur && text(cur).includes("Argon2id"), "Later moves to the next entry without answering");
  expect(chipCount("All projects") === "7", "Later sends nothing, counts unchanged");
  btn(cur, "SHA-256 + pepper").click(); await tick(); await tick();
  expect(chipCount("All projects") === "6" && chipCount("Maity") === "4", "answer re-reads /me counts");
  const projSort = byId("inbox-sort"); projSort.value = "project"; projSort.dispatch("change"); await tick();
  const sortLabels = main.querySelectorAll(".project-label").map((el) => el.textContent);
  expect(sortLabels[0].startsWith("Personal") && sortLabels.find((t) => !t.startsWith("Personal")).startsWith("Maity"), "sort by project: the personal requests first, then the projects");
  // A project filter and grouping by project.
  const pf = byId("inbox-project");
  expect(pf.querySelectorAll("option").map((o) => o.textContent).join("|") === "every project|Maity|Sample shop", "inbox: the project options carry no counts that could go stale");
  pf.value = "maintainer/sample"; pf.dispatch("change"); await tick();
  expect(main.querySelectorAll("li.entry").length === 1 && text(main.querySelector("li.entry")).includes("Sample shop"), "inbox: filtered to one project");
  // The filter is the cross-project view's: a project's own inbox shows its entries.
  await go("#/maintainer/maity/inbox");
  // A project's inbox: its own open requests and the open personal requests about it (§7, §18.2), as its tab counts them.
  const maityOpenNow = (await win.Maity.api.get("/me")).projects.find((x) => x.slug === "maity").open_requests
    + (await win.Maity.api.getAll("/requests")).items.filter((r) => r.personal && r.status === "open" && r.project && r.project.full_name === "maintainer/maity").length;
  expect(maityOpenNow > 0 && main.querySelectorAll("li.entry").length === maityOpenNow, "inbox: a project's inbox ignores the cross-project filter, and holds its personal requests too");
  await go("#/all");
  expect(byId("inbox-project").value === "maintainer/sample" && main.querySelectorAll("li.entry").length === 1, "inbox: back in all projects, the filter is still set");
  byId("inbox-project").value = ""; byId("inbox-project").dispatch("change"); await tick();
  const grp = byId("inbox-group"); grp.checked = true; grp.dispatch("change"); await tick();
  const groupHeads = main.querySelectorAll("section.entry-group").map((x) => x.childNodes[0].childNodes[0].textContent);
  expect(JSON.stringify(groupHeads) === JSON.stringify(["Personal", "Maity", "Sample shop"]) && main.querySelectorAll("li.entry").length === 5
    && main.querySelectorAll("section.entry-group").every((sec) => sec.querySelector("ol.entries") && sec.querySelector("ol.entries").childNodes.every((li) => li.className.includes("entry"))),
    "inbox: grouped by project, in the switcher's order, each group its own list " + JSON.stringify(groupHeads));
  // The entry expanded is the first on screen, not the first of the ungrouped order.
  // (By priority, Sample shop's urgent one leads the ungrouped order; grouped, the personal one comes first.)
  byId("inbox-sort").value = "priority"; byId("inbox-sort").dispatch("change"); await tick();
  expect(main.querySelectorAll("li.entry")[0].className.includes("current") && !main.querySelectorAll("section.entry-group")[1].querySelector("li.current"),
    "inbox: grouped, the expanded entry is the first on screen");
  grp.checked = false; grp.dispatch("change"); await tick();

  await go("#/maintainer/maity/inbox");
  expect(text(header).includes("Build") && text(header).includes("Fixtures") && header.querySelectorAll("button").some((b) => (b.getAttribute("aria-label") || "").startsWith("Your profile: ")), "project header: state, fixtures label, sign out");
  expect(chip("Maity").getAttribute("aria-current") === "page", "switcher marks the current project");
  const sRow = header.querySelector(".switcher-row");
  expect(sRow && sRow.childNodes[0].className === "switcher" && sRow.childNodes[1].className === "project-state"
    && sRow.childNodes[1].querySelector(".state") && !header.querySelector(".bar .state"),
    "header: the state and the settings sit at the projects' right, apart, not in the top bar");
  let c2 = main.querySelector(".current");
  expect(c2 && text(c2).includes("Merge PR #2") && text(c2).includes("On behalf of") && text(c2).includes("Reviewer · member · reviewer"), "consent without options, on_behalf_of shown");
  expect(btn(c2, "go") && btn(c2, "no") && !btn(c2, "Discuss"), "replies go/no from the hub, no discuss");
  expect(btn(c2, "go").className === "reply primary" && btn(c2, "no").className === "reply", "only the hub's go of a consent is primary");
  expect(JSON.stringify(c2.querySelector(".replies").querySelectorAll("button").map((b) => b.textContent)) === JSON.stringify(["Later", "Neither — let's talk", "no", "go"]),
    "the replies at the right edge: Later and talk first, the primary one last");
  // A request's stored mention links to the member; the @ picker in its free text.
  const hashHead = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("Name of the CLI binary"));
  if (hashHead.attrs["aria-expanded"] !== "true") { hashHead.click(); await tick(); }
  const hashEntry = main.querySelector(".current");
  const triedLink = hashEntry.querySelectorAll("a.mention").find((a) => a.textContent === "@agent-b");
  expect(triedLink && triedLink.getAttribute("href") === "#/maintainer/maity/members/agt-b", "mentions: a request's tried links its stored mention");
  const freeText = hashEntry.querySelector(".free-text textarea");
  const pickList = hashEntry.querySelector(".mention-list");
  const options = () => pickList.querySelectorAll("li").map((li) => li.querySelector(".mention-handle").textContent);
  freeText.value = "Ask @age"; freeText.dispatch("input"); await tick(); await tick();
  expect(!pickList.hidden && JSON.stringify(options()) === JSON.stringify(["@agent-a", "@agent-b", "@agent-c", "@agent-d"])
    && freeText.getAttribute("aria-expanded") === undefined && freeText.getAttribute("aria-activedescendant") === pickList.attrs.id + "-0",
    "mentions: @ offers the project's members by handle " + JSON.stringify(options()));
  freeText.dispatch("keydown", { key: "ArrowDown" }); freeText.dispatch("keydown", { key: "Enter" }); await tick();
  expect(freeText.value === "Ask @agent-b " && pickList.hidden && !freeText.getAttribute("aria-activedescendant"), "mentions: arrow and Enter put the handle in");
  freeText.value = "mail me@age"; freeText.dispatch("input"); await tick();
  expect(pickList.hidden, "mentions: an @ inside a word offers nothing");
  const CR = (t) => JSON.stringify(win.Maity.mentionCode(t));
  expect(CR("a `b` c") === "[[2,5]]" && CR("x ``a`b`` y") === "[[2,9]]" && CR("`open") === "[]"
    && CR("t\n```js\n@x\n```\nz") === "[[2,15]]" && CR("~~~\n@x") === "[[0,6]]" && CR("``a`") === "[]",
    "mentions: code as §8.6 reads it — spans by matching runs, fences to their close or the end, an unclosed run is text");
  freeText.value = "`@age` and more"; freeText.selectionStart = 5; freeText.dispatch("input"); await tick();
  expect(pickList.hidden, "mentions: nothing inside an inline code span");
  freeText.selectionStart = undefined;
  freeText.value = "```\nAsk @age"; freeText.dispatch("input"); await tick();
  expect(pickList.hidden, "mentions: nothing inside a fenced block");
  freeText.value = "``x`` @age"; freeText.dispatch("input"); await tick(); await tick();
  expect(!pickList.hidden, "mentions: after a closed span, offered again");
  freeText.dispatch("keydown", { key: "Escape" });
  freeText.value = "`@age"; freeText.dispatch("input"); await tick(); await tick();
  expect(!pickList.hidden, "mentions: an unclosed backtick is text, as the hub reads it");
  freeText.dispatch("keydown", { key: "Escape" });
  freeText.value = "@m"; freeText.dispatch("input"); await tick();
  expect(pickList.hidden, "mentions: the writer is not offered");
  freeText.value = "@r"; freeText.dispatch("input"); await tick();
  freeText.dispatch("keydown", { key: "Escape" }); await tick();
  expect(pickList.hidden && freeText.value === "@r", "mentions: Escape closes, the text stays");
  freeText.value = "";
  // A slow member list: what is typed meanwhile, or a blur, wins over the late answer.
  const slowText = document.createElement("textarea");
  let releaseList = null;
  let listCalls = 0;
  const slowList = win.Maity.mentionPicker(slowText, () => { listCalls += 1;
    return listCalls === 1 ? Promise.reject(new Error("down")) : new Promise((r) => { releaseList = () => r([{ id: "agt-b", handle: "agent-b", display_name: "Agent B" }]); }); }, "me");
  slowText.value = "@a"; slowText.dispatch("input"); await tick(); await tick();
  expect(slowList.hidden && listCalls === 1, "mentions: a failed member read shows nothing");
  slowText.value = "@a"; slowText.dispatch("input"); await tick();
  expect(listCalls === 2, "mentions: the next @ reads the members again");
  slowText.dispatch("blur");
  releaseList(); await tick(); await tick();
  expect(slowList.hidden && !slowText.getAttribute("aria-activedescendant"), "mentions: an answer after a blur draws nothing");
  // Global names (docs/api.md §6.3, §8.6): where two agents share a short handle the picker offers and
  // inserts the long form; a human who shares one with an agent keeps the short one.
  const idBoxGn = (nodes) => { const box = document.createElement("div"); win.Maity.dom.append(box, nodes); return box; };
  const gnText = document.createElement("textarea");
  const gnList = win.Maity.mentionPicker(gnText, () => Promise.resolve([
    { id: "agt-1", kind: "agent", handle: "agent-b", name: "oliver/agent-b", display_name: "Oliver's B" },
    { id: "agt-2", kind: "agent", handle: "agent-b", name: "anna/agent-b", display_name: "Anna's B" },
    { id: "agt-3", kind: "agent", handle: "agent-c", name: "oliver/agent-c", display_name: "C" },
    { id: "hum-o", kind: "human", handle: "oliver", display_name: "Oliver" },
    { id: "agt-4", kind: "agent", handle: "oliver", name: "anna/oliver", display_name: "Anna's Oliver" }]), "me");
  gnText.value = "@a"; gnText.dispatch("input"); await tick(); await tick();
  const gnOpts = () => gnList.querySelectorAll("li.mention-option").map((li) => text(li.childNodes[0]));
  expect(JSON.stringify(gnOpts()) === JSON.stringify(["@oliver/agent-b", "@anna/agent-b", "@agent-c"]), "global names: the picker offers the long form where the short one is shared " + JSON.stringify(gnOpts()));
  gnList.querySelectorAll("li.mention-option")[1].dispatch("mousedown"); await tick();
  expect(gnText.value === "@anna/agent-b ", "global names: picking inserts the long form");
  gnText.value = "@anna/"; gnText.dispatch("input"); await tick();
  expect(JSON.stringify(gnOpts()) === JSON.stringify(["@anna/agent-b", "@anna/oliver"]), "global names: typing the long form narrows the picker " + JSON.stringify(gnOpts()));
  gnList.querySelectorAll("li.mention-option")[0].dispatch("mousedown"); await tick();
  expect(gnText.value === "@anna/agent-b ", "global names: and picking completes it");
  gnText.value = "@ol"; gnText.dispatch("input"); await tick();
  expect(JSON.stringify(gnOpts()) === JSON.stringify(["@oliver", "@anna/oliver"]), "global names: a human comes first and keeps the short handle");
  gnText.dispatch("keydown", { key: "Escape" });
  gnText.value = "@agent-b#wl"; gnText.dispatch("input"); await tick();
  expect(gnList.hidden && gnText.value === "@agent-b#wl", "global names: an instance #id being typed offers nothing and is left as typed");
  const gnRefused = win.Maity.dom.ambiguousMention(new win.Maity.api.ApiError("x", 400, "/x", "invalid",
    { fields: { body: "ambiguous_mention" }, mentions: { "agent-b": ["anna/agent-b", "oliver/agent-b"] } }));
  expect(gnRefused && gnRefused.message === "@agent-b is 2 agents here: write @anna/agent-b or @oliver/agent-b."
    && win.Maity.dom.ambiguousMention(new win.Maity.api.ApiError("x", 400, "/x", "invalid", { fields: { body: "too_many_mentions" } })) === null,
    "global names: the hub's ambiguous_mention in words with the long forms");
  const gnStored = idBoxGn(win.Maity.dom.withMentions("Ask @anna/shop-dev now", [{ member_id: "agt-s2", handle: "shop-dev", name: "anna/shop-dev", field: "summary", offset: 4, length: 14 }],
    "summary", (id) => "/m/" + id));
  expect(gnStored.querySelector("a.mention") && text(gnStored.querySelector("a.mention")) === "@anna/shop-dev" && gnStored.querySelector("a.mention").getAttribute("href") === "#/m/agt-s2",
    "global names: a stored long mention is a link to its member");
  // A project with two shop-dev of different owners (fixtures/sample): both by their global names; a
  // project without a shared handle keeps the short ones; the hub's refusal of the short form is said.
  // The old Join and Organisation addresses are gone (§16.11): no view, no redirect.
  await go("#/maintainer/sample/org"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("No such view") && !main.querySelector(".org-tree"), "org: the old address is no view");
  await go("#/maintainer/sample/join"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("No such view"), "join: the old address is no view");
  await go("#/maintainer/sample/members"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes(" @anna/shop-dev") && text(main).includes(" @maintainer/shop-dev") && text(main).includes(" @maintainer") && !text(main).includes("@hum-"),
    "global names: and in Members; the human by the short handle");
  await go("#/maintainer/sample/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("join-agent").querySelectorAll("option").some((o) => text(o).startsWith("Shop Dev (@maintainer/shop-dev)"))
    && byId("join-agent").querySelectorAll("option").some((o) => text(o).startsWith("Agent B (@agent-b)")),
    "global names: the join panel names a profile long only where its handle is shared in the project");
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes(" @agent-b") && !text(main).includes("/agent-b"), "global names: no shared handle, the short one");
  // Someone with the same short handle joins while Members is open: the refresh shows both by their long names.
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const gnAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? gnAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-b9", kind: "agent", handle: "agent-b",
    name: "anna/agent-b", display_name: "Anna's B", trust: "member", role: "coder", reports_to: null, areas: [], capabilities: [], presence: "offline", last_seen_at: null }]), next_cursor: null })) : gnAll(p));
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes(" @maintainer/agent-b") && text(main).includes(" @anna/agent-b"), "global names: a join seen by Members' refresh turns both into long names");
  win.Maity.api.getAll = gnAll;
  const gnPosts = [];
  const gnPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { gnPosts.push([p, b]); return gnPost(p, b); };
  await go("#/maintainer/sample/message"); for (let k = 0; k < 2; k++) await tick();
  expect(byId("message-to").querySelectorAll("option").some((o) => text(o) === "Anna's Shop Dev (@anna/shop-dev)"), "global names: the message's addressee list by the long names");
  byId("message-to").value = "all"; byId("message-body").value = "Ship it, @shop-dev.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector("form.message-form")).includes("Not sent: @shop-dev is 2 agents here: write @anna/shop-dev or @maintainer/shop-dev.")
    && byId("message-body").value === "Ship it, @shop-dev.", "global names: a short handle two agents share is refused with the long forms, the text kept");
  byId("message-body").value = "Ship it, @anna/shop-dev.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(gnPosts.length === 2 && text(main).includes("mentioned and notified: Anna's Shop Dev"), "global names: the long form is sent and resolves to that agent");
  win.Maity.api.post = gnPost;
  await go("#/maintainer/sample/messages"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".pmsg-mentions a").some((a) => text(a) === "@anna/shop-dev"), "global names: the message's stored mention by the long name where the short one is shared");
  await go("#/maintainer/maity/inbox");

  slowText.value = "@agent"; slowText.dispatch("input"); await tick(); await tick();
  expect(!slowList.hidden, "mentions: once read, the list is there at once");
  // A mention's link opens the member's page (js/member-page.js), its heading focused.
  const mlProto = Object.getPrototypeOf(main);
  const mlFocus = mlProto.focus;
  mlProto.focus = function () { document.activeElement = this; };
  await go(triedLink.getAttribute("href")); await tick(); await new Promise((r) => setTimeout(r, 5));
  const mpHead = byId("member-heading");
  expect(plainTitle() === "Members · Maity · Maity" && mpHead && text(mpHead).startsWith("Agent B") && document.activeElement === mpHead,
    "mentions: the link opens the member's page, its heading focused");
  await go("#/maintainer/maity/members/agt-nobody"); await tick();
  expect(text(main).includes("No member with the id agt-nobody in this project.") && !main.querySelector("tr.wanted"), "mentions: an unknown member is said");
  mlProto.focus = mlFocus; document.activeElement = undefined;
  // Back in the inbox, the entry the next checks answer is open again, in this view.
  await go("#/maintainer/maity/inbox");
  const mergeHead = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("Merge PR #2"));
  if (mergeHead.attrs["aria-expanded"] !== "true") { mergeHead.click(); await tick(); }
  c2 = main.querySelector(".current");
  expect(main.querySelectorAll("button").every((b) => !/reply-/.test(b.className)), "no reply id becomes a class");
  expect(text(c2).includes("Needs you in the session") && text(c2).includes("ses-a-0007"), "needs_in_session with member and session");
  btn(c2, "Neither — let's talk").click(); await tick(); await tick();
  c2 = main.querySelector(".current");
  expect(c2 && text(c2).includes("CLI binary") && text(c2).includes("context/join.md") && text(c2).includes("proceeds provisionally"), "next: decision with ktw_ref and while_open");
  const ta = c2.querySelector("textarea"); ta.value = "maity, as documented";
  btn(c2, "Send").click(); await tick(); await tick();
  expect(text(main).includes("No open requests."), "inbox empty");
  const show = byId("inbox-show"); show.value = "all"; show.dispatch("change"); await tick();
  expect(main.querySelectorAll(".entry").length === 4, "show all: 4 entries in maity, answered ones too");
  const sortSel = byId("inbox-sort"); sortSel.value = "agent"; sortSel.dispatch("change"); await tick();
  const names = main.querySelectorAll(".entry-head .meta").map((e) => e.textContent.split(" · ")[0]);
  expect(JSON.stringify(names) === JSON.stringify(["Agent A for Reviewer", "Agent B", "Agent C", "Agent D"].filter((n) => names.includes(n))) && names.length >= 3, "sort by agent: " + names.join(", "));

  // malformed and unknown routes
  await go("#/p/%E0%A4%A");
  expect(main.querySelector(".page-failed") && text(main.querySelector(".page-failed details")).includes("URI"), "malformed hash says the page could not load, the reason under Details");
  await go("#/maintainer/maity/constructor");
  expect(text(main).includes("No such view") && plainTitle() === "No such view · Maity", "prototype key is no view, sane title");
  await go("#/maintainer/maity/nonsense");
  expect(text(main).includes("No such view"), "unknown view");
  // Projects live in their owner's namespace (§6.25): /<owner>/<slug>. The address before it,
  // /p/<slug>, is gone (§16.11): read as any owner p, it leads nowhere, without a redirect.
  const nsSettle = async () => { await new Promise((r) => setTimeout(r, 5)); for (let k = 0; k < 4; k++) await tick(); };
  await go("#/p/maity/board"); await nsSettle();
  expect(win.location.hash === "#/p/maity/board" && !main.querySelector("section.view-board"), "namespace: the old /p/<slug> address leads nowhere, no redirect");
  // An alias of a project of one's own (a rename, a transfer): the hub answers with the current full name.
  const nsGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity-old" ? nsGet("/projects/maintainer/maity") : nsGet(p));
  await go("#/maintainer/maity-old/members"); await nsSettle();
  expect(win.location.hash === "#/maintainer/maity/members", "namespace: an alias leads to the current full name");
  win.Maity.api.get = nsGet;
  // A dashboard word is never a namespace.
  await go("#/runners/maity"); await nsSettle();
  expect(win.location.hash === "#/runners/maity" && !text(main).includes("not a member"), "namespace: the dashboard's own words are not read as an owner");
  // The API: a project's paths carry its owner; an old one-segment path is refused, never routed elsewhere.
  let nsOld = null;
  try { await win.Maity.api.get("/projects/maity/tasks"); } catch (err) { nsOld = err; }
  expect(nsOld && nsOld.status === 410 && nsOld.code === "project_path_outdated", "namespace: the fixture hub refuses an old project path with 410");
  expect(win.Maity.api.projectPath("ma int/ma ity") === "ma%20int/ma%20ity", "namespace: a full name's path keeps its one slash, each part encoded");
  // Outside its project a card or request id carries the project (§6.25, tsk-cns4d1d7ht4j); inside it stands alone.
  const nsIdText = (at) => win.Maity.dom.h("p", null, win.Maity.ids.link("see tsk-0123456789ab and agt-0123456789ab", at)).querySelectorAll("a").map((a) => a.textContent + "=" + a.getAttribute("href")).join(" ");
  expect(nsIdText({ slug: "maintainer/maity", outside: true }) === "maintainer/maity/tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab agt-0123456789ab=#/maintainer/maity/members/agt-0123456789ab"
    && nsIdText({ slug: "maintainer/maity" }) === "tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab agt-0123456789ab=#/maintainer/maity/members/agt-0123456789ab",
    "namespace: a card id outside its project reads with the project's full name, inside alone; a member id never");
  expect(win.Maity.ids.where({ scope: "chats", slug: "maintainer/maity", project: {} }).outside && !win.Maity.ids.where({ scope: "project", slug: "maintainer/maity", project: {} }).outside,
    "namespace: the global chat is outside a project, a project's own view is not");
  await go("#/all"); await nsSettle();
  const nsAllRefs = main.querySelectorAll("a.id-ref").filter((a) => /tsk-|req-/.test(a.textContent));
  expect(nsAllRefs.every((a) => /^maintainer\/(maity|sample)\/(tsk|req)-/.test(a.textContent)),
    "namespace: across projects a card or request id in a text reads with its project " + nsAllRefs.map((a) => a.textContent).join());
  // Project settings: the name, a rename by a human owner, the old name kept as an earlier one.
  await go("#/maintainer/maity/inbox"); await projectSettings();
  const nsNames = () => main.querySelector(".project-names");
  const nsTr0 = () => nsNames().querySelector("form.project-transfer");
  expect(nsNames() && text(nsNames()).includes("This project is maintainer/maity.") && !nsNames().querySelector(".project-aliases")
    && byId("project-rename").value === "maity", "namespace: settings name the project, its slug ready to rename");
  byId("project-rename").value = "tasks"; nsNames().querySelector("form.project-rename").dispatch("submit"); await nsSettle();
  expect(text(nsNames()).includes("part of the dashboard's addresses") && byId("project-rename").getAttribute("aria-invalid") === "true",
    "namespace: a route word is refused next to the field");
  // The shim fires no hashchange for an assigned hash: followed here as a browser would.
  byId("project-rename").value = "maity-hub"; nsNames().querySelector("form.project-rename").dispatch("submit"); await nsSettle(); await go(win.location.hash); await nsSettle();
  expect(win.location.hash === "#/maintainer/maity-hub/settings" && nsNames() && text(nsNames()).includes("This project is maintainer/maity-hub.")
    && text(nsNames().querySelector(".project-aliases")).includes("maintainer/maity"), "namespace: renamed, the page follows the new name, the old one listed as earlier");
  await go("#/maintainer/maity/board"); await nsSettle();
  expect(win.location.hash === "#/maintainer/maity-hub/board", "namespace: the old name still leads to the project");
  // Taken back: the old name is current again.
  await projectSettings();
  byId("project-rename").value = "maity"; nsNames().querySelector("form.project-rename").dispatch("submit"); await nsSettle(); await go(win.location.hash); await nsSettle();
  expect(win.location.hash === "#/maintainer/maity/settings" && text(nsNames().querySelector(".project-aliases")).includes("maintainer/maity-hub")
    && !text(nsNames().querySelector(".project-aliases")).includes("maintainer/maity,"), "namespace: a name taken back is current again");
  // At 8 earlier names a new one is refused, taking back one's own is not (as the hub, #487).
  let nsFull = null;
  try { await win.Maity.api.patch("/projects/maintainer/sample", { slug: "sample-new" }); } catch (err) { nsFull = err; }
  const nsBack = await win.Maity.api.patch("/projects/maintainer/sample", { slug: "sample-old" });
  const nsHome = await win.Maity.api.patch("/projects/maintainer/sample-old", { slug: "sample" });
  expect(nsFull && nsFull.code === "alias_limit" && nsBack.full_name === "maintainer/sample-old" && nsBack.aliases.length === 8
    && nsHome.full_name === "maintainer/sample" && nsHome.aliases.length === 8 && !nsHome.aliases.includes("maintainer/sample"),
    "namespace: at the alias limit a new name is refused, an earlier one of its own taken back");
  // Transfer: to another human owner, or into an organisation one owns or administers (§6.26); without either the way is said.
  expect(nsTr0() && byId("project-transfer-to").querySelectorAll("option").map((o) => o.getAttribute("value")).join() === "org-oz00team0001,org-oz00crew0001"
    && text(byId("project-transfer-to")).includes("@oz-team · OZ Team (organisation)"), "namespace: without another owner the transfer offers the organisations one owns or administers");
  const nsHasT = win.Maity.api.hubHas;
  win.Maity.api.hubHas = (m, p) => (p === "/orgs" ? Promise.resolve(false) : nsHasT(m, p));
  await go("#/maintainer/maity/inbox"); await projectSettings(); await nsSettle();
  expect(nsNames().querySelector(".project-transfer") && text(nsNames().querySelector(".project-transfer")).includes("make them an owner of it first"),
    "namespace: without another owner or an organisation the transfer says what comes first");
  win.Maity.api.hubHas = nsHasT;
  const nsGetT = win.Maity.api.get, nsPostT = win.Maity.api.post;
  const nsAnna = { id: "hum-anna", kind: "human", handle: "anna", display_name: "Anna", trust: "owner", role: "coder", areas: [], capabilities: [], presence: "offline" };
  const nsAdminOrg = { id: "org-oz00guild001", handle: "guild", display_name: "Guild", avatar_url: null, aliases: [], my_role: "admin", members_create_projects: false, public_page: "off" };
  const nsMemberOrg = Object.assign({}, nsAdminOrg, { id: "org-oz00club0001", handle: "club", display_name: "Club", my_role: "member" });
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? nsGetT(p).then((r) => Object.assign({}, r, { items: r.items.concat([nsAnna]) }))
    : p === "/orgs" ? nsGetT(p).then((r) => ({ items: r.items.concat([nsAdminOrg, nsMemberOrg]) })) : nsGetT(p));
  const nsTransfers = [];
  win.Maity.api.post = (p, b) => {
    if (p.endsWith("/transfer")) {
      nsTransfers.push([p, b]);
      if (b.to === "org-oz00team0001") return Promise.resolve({ id: "prj-x", full_name: "oz-team/maity", slug: "maity" });
      if (b.to === "org-oz00guild001") return Promise.resolve({ id: "req-tr02", class: "consent", status: "open" });
      return nsTransfers.length === 1 ? Promise.resolve({ id: "req-tr01", class: "consent", status: "open" })
        : Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: "step_up_required" }));
    }
    if (/\/requests\/req-tr01\/withdraw$/.test(p)) { nsTransfers.push([p, b]); return Promise.resolve({ id: "req-tr01", status: "withdrawn" }); }
    return nsPostT(p, b);
  };
  await go("#/maintainer/maity/inbox"); await projectSettings();
  const nsTr = () => nsNames().querySelector("form.project-transfer");
  await nsSettle();
  expect(nsTr() && byId("project-transfer-to").querySelectorAll("option").map((o) => o.getAttribute("value")).join() === "hum-anna,org-oz00team0001,org-oz00crew0001,org-oz00guild001",
    "namespace: the transfer offers the other human owners, then the organisations one owns or administers, not one one is only a member of");
  const nsConfirm = win.confirm;
  win.confirm = () => true;
  nsTr().dispatch("submit"); await nsSettle();
  expect(JSON.stringify(nsTransfers[0]) === JSON.stringify(["/projects/maintainer/maity/transfer", { to: "hum-anna" }]) && text(nsTr()).includes("moves when they accept"),
    "namespace: a transfer asks the receiver, the move waits for their go");
  btn(nsTr(), "Withdraw the request").click(); await nsSettle();
  expect(nsTransfers[1][0] === "/projects/maintainer/maity/requests/req-tr01/withdraw" && text(nsTr()).includes("Withdrawn."), "namespace: the request is withdrawn from where it was made");
  nsTr().dispatch("submit"); await nsSettle();
  expect(nsTr().querySelector("form.step-up") && text(nsTr()).includes("needs your second factor") && !text(nsTr()).includes("Not transferred"),
    "namespace: a step-up the hub asks for is asked in place");
  btn(nsTr(), "Cancel").click(); await nsSettle();
  expect(!nsTr().querySelector("form.step-up") && !text(nsTr()).includes("Not transferred"), "namespace: Cancel ends the transfer quietly");
  byId("project-transfer-to").value = "org-oz00guild001"; nsTr().dispatch("submit"); await nsSettle();
  expect(JSON.stringify(nsTransfers[nsTransfers.length - 1]) === JSON.stringify(["/projects/maintainer/maity/transfer", { to: "org-oz00guild001" }])
    && text(nsTr()).includes("Asked the owners of @guild. The project moves when one of them accepts"), "namespace: into an organisation one administers, its owners are asked");
  byId("project-transfer-to").value = "org-oz00team0001"; nsTr().dispatch("submit"); await nsSettle();
  expect(win.location.hash === "#/oz-team/maity/settings", "namespace: into an organisation one owns, the project moves at once and the page follows it");
  win.confirm = nsConfirm;
  win.Maity.api.get = nsGetT; win.Maity.api.post = nsPostT;
  await go("#/maintainer/maity/inbox"); await nsSettle();
  // The hub's limits in words; the namespace owner stays an owner.
  const nsSaid = win.Maity.projectNames.said;
  expect(nsSaid({ code: "alias_limit", details: { limit: 8 } }).message.includes("8 earlier names") && nsSaid({ code: "rate_limited" }).message.includes("3 renames and transfers a day")
    && nsSaid({ code: "invalid", details: { fields: { slug: "taken" } } }, "anna").message.includes("@anna has a project of that name"),
    "namespace: the limits of names said in words");
  expect(throws(() => win.Maity.dom.h("a", { href: "javascript:alert(1)" })), "h() refuses a javascript: href");
  expect(throws(() => win.Maity.dom.h("a", { onclick: "alert(1)" })), "h() refuses a string handler");

  await go("#/maintainer/maity/board");
  expect(!main.querySelector(".error"), "board renders");
  // Mentions (docs/api.md §8.6): stored ones become member links, nothing typed does.
  const reportMention = main.querySelectorAll("a.mention").find((a) => a.textContent === "@agent-d");
  expect(reportMention && reportMention.getAttribute("href") === "#/maintainer/maity/members/agt-d", "mentions: a report's stored mention links to the member");
  const wm = (t, ms, f) => win.Maity.dom.withMentions(t, ms, f || "body", (id) => "/m/" + id);
  const linkOf = (nodes) => nodes.filter((n) => typeof n !== "string");
  const emoji = wm("\u{1F642} hi @agent-b!", [{ member_id: "agt-b", handle: "agent-b", field: "body", offset: 5, length: 8 }]);
  expect(linkOf(emoji).length === 1 && linkOf(emoji)[0].textContent === "@agent-b" && emoji[emoji.length - 1] === "!",
    "mentions: offsets count code points, not UTF-16 units");
  expect(!linkOf(wm("hi @agent-c", [{ member_id: "agt-b", handle: "agent-b", field: "body", offset: 3, length: 8 }])).length,
    "mentions: a stored mention whose text does not match stays text");
  // An instance mention (§8.6, §6.17): @handle#id or @owner/handle#id links to the member, the instance in the title.
  const instShort = linkOf(wm("ping @agent-b#wqe2 now", [{ member_id: "agt-b", handle: "agent-b", name: "maintainer/agent-b", instance: "wqe2", field: "body", offset: 5, length: 13 }]));
  const instLong = linkOf(wm("ping @maintainer/agent-b#wqe2", [{ member_id: "agt-b", handle: "agent-b", name: "maintainer/agent-b", instance: "wqe2", field: "body", offset: 5, length: 24 }]));
  expect(instShort.length === 1 && instShort[0].textContent === "@agent-b#wqe2" && instShort[0].getAttribute("href") === "#/m/agt-b" && instShort[0].getAttribute("title") === "instance wqe2"
    && instLong.length === 1 && instLong[0].textContent === "@maintainer/agent-b#wqe2",
    "mentions: a stored instance mention, short or long, links to its member with the instance in the title");
  const teamSuffix = wm("ping @agent-b#wqe2", [{ member_id: "agt-b", handle: "agent-b", instance: null, field: "body", offset: 5, length: 8 }]);
  expect(linkOf(teamSuffix).length === 1 && linkOf(teamSuffix)[0].textContent === "@agent-b" && !linkOf(teamSuffix)[0].getAttribute("title")
    && teamSuffix[teamSuffix.length - 1] === "#wqe2", "mentions: a team mention followed by a #-looking suffix links the handle, the suffix stays text");
  expect(!linkOf(wm("ping @agent-b#k3pa", [{ member_id: "agt-b", handle: "agent-b", instance: "wqe2", field: "body", offset: 5, length: 13 }])).length,
    "mentions: a stored instance mention whose #id does not match stays text");
  expect(!linkOf(wm("hi @agent-b", [{ member_id: "agt-b", handle: "agent-b", field: "summary", offset: 3, length: 8 }])).length
    && !linkOf(wm("hi @agent-b", [])).length, "mentions: only this field's stored mentions, never a typed @");
  expect(wm("a @x @y", [{ member_id: "x", handle: "x", field: "body", offset: 2, length: 2 }, { member_id: "y", handle: "y", field: "body", offset: 5, length: 2 }])
    .map((n) => (typeof n === "string" ? n : "[" + n.textContent + "]")).join("") === "a [@x] [@y]", "mentions: several in one text, in order");
  ["Proposed", "Cancelled", "Context round", "Contract"].forEach((s) => expect(text(main).includes(s), "board shows " + s));
  expect(text(main).includes("Release 0.1.0") && text(main).includes("Not ready:") && text(main).includes("checklist item chk-2 is open"), "release readiness from the hub");
  const relCard = main.querySelectorAll("article.card").find((a) => a.getAttribute("aria-label").startsWith("0.1.0"));
  const prRow = (n) => relCard.querySelectorAll("tr").find((tr) => tr.textContent.startsWith("#" + n));
  expect(prRow(4).textContent.includes("not on the forge") && text(relCard).includes("#4 is not on the forge (a mistyped number"),
    "release: a PR the forge does not have, and its pr_not_found reason");
  expect(prRow(5).textContent.includes("unverified · typed as merged") && prRow(5).textContent.includes("never")
    && text(relCard).includes("#5 is not observed yet; what was typed or reported counts for nothing"),
    "release: a typed state is shown as a claim, unverified, not as merged");
  expect(prRow(1).querySelector(".pr-merged") && prRow(1).textContent.includes("merged"), "release: an observed merged PR is shown as merged");
  expect(relCard.querySelector(".groups li.unmet") && text(relCard).includes("Ship together") && text(relCard).includes("tsk-0005 (review) + tsk-0006 (open)"),
    "release: the ships_with group, incomplete");
  expect(text(relCard).includes("CHANGELOG has a section for this version · ") && text(relCard).includes("Tag v0.1.0: not on the forge"),
    "release: checklist with who ticked it; the tag as observed");
  // Release editing, for releases:write (the owner here).
  const relWrites = [];
  const realPost3 = win.Maity.api.post, realPatch3 = win.Maity.api.patch;
  win.Maity.api.post = (p, b) => { relWrites.push(["POST", p, b]); return realPost3(p, b); };
  win.Maity.api.patch = (p, b) => { relWrites.push(["PATCH", p, b]); return realPatch3(p, b); };
  const rel = () => main.querySelectorAll("article.card").find((a) => a.getAttribute("aria-label").startsWith("0.1.0"));
  const box2 = byId("chk-rel-0001-chk-2");
  expect(byId("chk-rel-0001-chk-1").checked === true && box2 && box2.checked === false, "release: checklist items are checkboxes with their state");
  box2.checked = true; box2.dispatch("change"); await tick(); await tick();
  expect(relWrites[0][0] === "POST" && relWrites[0][1] === "/projects/maintainer/maity/tasks/rel-0001/checklist/chk-2" && JSON.stringify(relWrites[0][2]) === JSON.stringify({ done: true })
    && byId("chk-rel-0001-chk-2").checked === true && text(rel()).includes("live version equals the tag · Maintainer"), "release: ticking an item posts done and shows who ticked it");
  const box1 = byId("chk-rel-0001-chk-1"); box1.checked = false; box1.dispatch("change"); await tick(); await tick();
  expect(JSON.stringify(relWrites[1][2]) === JSON.stringify({ done: false }) && byId("chk-rel-0001-chk-1").checked === false
    && !text(rel()).includes("CHANGELOG has a section for this version · "), "release: unticking an item clears who ticked it");
  btn(rel(), "Edit checklist").click(); await tick();
  const texts = rel().querySelectorAll("input.item-text");
  expect(texts.length === 2 && texts[0].value === "CHANGELOG has a section for this version", "release: the checklist editor starts with the items");
  texts[1].value = "live version equals the tag v0.1.0";
  btn(rel(), "Add").click(); await tick();
  rel().querySelectorAll("input.item-text")[2].value = "  announce it  ";
  btn(rel(), "Add").click(); await tick();  // an empty row is dropped
  rel().querySelector("form.rows-form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(relWrites[2]) === JSON.stringify(["PATCH", "/projects/maintainer/maity/tasks/rel-0001", { release: { checklist: [
    { id: "chk-1", text: "CHANGELOG has a section for this version" }, { id: "chk-2", text: "live version equals the tag v0.1.0" }, { text: "announce it" }] } }])
    && byId("chk-rel-0001-chk-3") && text(rel()).includes("announce it"), "release: the edited checklist keeps ids, the new item gets the next one");
  btn(rel(), "Typed pull requests").click(); await tick();
  const prRows = () => rel().querySelectorAll("form.rows-form li");
  expect(prRows().length === 4 && prRows()[0].querySelector("input.pr-number").value === "1" && prRows()[0].querySelector("select.pr-claim").value === "merged",
    "release: the typed PR editor starts with the typed PRs and their states");
  btn(prRows()[2], "Remove").click(); await tick();
  btn(rel(), "Add").click(); await tick();
  prRows()[3].querySelector("input.pr-number").value = "9"; prRows()[3].querySelector("select.pr-claim").value = "merged";
  rel().querySelector("form.rows-form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(relWrites[3][2]) === JSON.stringify({ release: { pull_requests_typed: [
    { number: 1, state: "merged" }, { number: 2, state: null }, { number: 5, state: "merged" }, { number: 9, state: "merged" }] } })
    && rel().querySelectorAll("tr").find((tr) => tr.textContent.startsWith("#9")).textContent.includes("unverified · typed as merged")
    && !rel().querySelectorAll("tr").some((tr) => tr.textContent.startsWith("#4")), "release: typed PRs are saved and a new one shows as unverified");
  btn(rel(), "Typed pull requests").click(); await tick();
  prRows()[0].querySelector("input.pr-number").value = "1.5";
  rel().querySelector("form.rows-form").dispatch("submit"); await tick();
  expect(relWrites.length === 4 && text(rel()).includes("a pull request number is a whole number from 1"), "release: a bad PR number is refused before sending");
  const prInput = (i) => prRows()[i].querySelector("input.pr-number");
  expect(prRows()[0].querySelector("input.pr-number").attrs["aria-label"] === "Pull request number, row 1"
    && prRows()[1].querySelector("input.pr-number").attrs["aria-label"] === "Pull request number, row 2", "release: each row's controls have their own label");
  for (const [value, says] of [["0", "(not 0)"], ["2147483649", "(not 2147483649)"], ["abc", "(not abc)"]]) {
    prInput(0).value = value;
    rel().querySelector("form.rows-form").dispatch("submit"); await tick();
    expect(relWrites.length === 4 && text(rel()).includes("Not saved: a pull request number is a whole number from 1 to 2147483648 " + says),
      "release: PR number " + value + " is refused before sending");
  }
  prInput(0).value = "2";
  rel().querySelector("form.rows-form").dispatch("submit"); await tick();
  expect(relWrites.length === 4 && text(rel()).includes("Not saved: #2 is listed twice"), "release: a PR number twice is refused before sending");
  win.Maity.api.patch = () => Promise.reject(new win.Maity.api.ApiError("closed", 409, "/x", "invalid_transition"));
  prRows()[0].querySelector("input.pr-number").value = "1";
  rel().querySelector("form.rows-form").dispatch("submit"); await tick(); await tick();
  expect(text(rel()).includes("this release is closed; its record does not change"), "release: a refusal of a closed release is put in words");
  win.Maity.api.post = realPost3; win.Maity.api.patch = realPatch3;
  // A tick on an item removed meanwhile: the hub answers 404.
  btn(rel(), "Cancel").click(); await tick();
  win.Maity.api.post = () => Promise.reject(new win.Maity.api.ApiError("Not found", 404, "/x", "not_found"));
  const box3 = byId("chk-rel-0001-chk-3"); box3.checked = true; box3.dispatch("change"); await tick(); await tick();
  expect(byId("chk-rel-0001-chk-3").checked === false && text(rel()).includes("Not saved: this item is gone (removed meanwhile); reload the board"),
    "release: a tick on a removed item says it is gone");
  win.Maity.api.post = realPost3;
  // The fixture keeps the hub's counter: a removed id is never given out again.
  btn(rel(), "Edit checklist").click(); await tick();
  btn(rel().querySelectorAll("form.rows-form li")[2], "Remove").click(); await tick();
  rel().querySelector("form.rows-form").dispatch("submit"); await tick(); await tick();
  btn(rel(), "Edit checklist").click(); await tick();
  btn(rel(), "Add").click(); await tick();
  rel().querySelectorAll("input.item-text")[2].value = "another";
  rel().querySelector("form.rows-form").dispatch("submit"); await tick(); await tick();
  expect(!byId("chk-rel-0001-chk-3") && byId("chk-rel-0001-chk-4"), "fixtures: a removed checklist id is not reused");
  // No releases:write: no editing.
  const realGet5 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? realGet5(p).then((m) => { m.projects.find((x) => x.slug === "maity").trust = "member"; return m; }) : realGet5(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board");
  expect(!byId("chk-rel-0001-chk-1") && !btn(rel(), "Edit checklist"), "release: no editing without releases:write");
  expect(!main.querySelector(".card-order"), "board: without tasks:admin no card offers Place");
  win.Maity.api.get = realGet5;
  await go("#/maintainer/sample/board");
  const closedRel = main.querySelectorAll("article.card").find((a) => a.getAttribute("aria-label").startsWith("0.3.0"));
  expect(closedRel && text(closedRel).includes("Closed: its pull requests, groups and readiness are the record frozen when it closed")
    && text(closedRel).includes("the hub observes nothing for this project (no forge probe)")
    && !text(closedRel).includes("it can be cancelled but not marked done") && text(closedRel).includes("Tag v0.3.0: not observed"),
    "closed release without a probe: frozen record, honest reason, no hint to act, tag not observed");
  expect(text(closedRel).includes("tsk-0021 + tsk-0022 (not in this release)") && !text(closedRel).includes("(review)")
    && closedRel.querySelector(".groups li.unknown"),
    "closed release: its group without live statuses, the partner outside depends_on named, neither green nor amber without a probe");
  expect(!btn(closedRel, "Edit checklist") && !closedRel.querySelectorAll("input").some((i) => i.attrs.type === "checkbox"), "closed release: no editing");
  const contractCard = main.querySelectorAll("article.card").find((a) => a.getAttribute("aria-label") === "Contract: receipt fields");
  expect(contractCard && text(contractCard).includes("Contract final · arbiter the admins · watched by "),
    "contract card: state, arbiter and watchers");
  await go("#/maintainer/maity/board");
  expect(text(main).includes("lease expired"), "expired lease shown");
  expect(text(main).includes("Checkpoint") && text(main).includes("Report"), "checkpoint and report shown");
  expect(main.querySelectorAll("a").some((a) => a.attrs.href === "https://github.com/oliver-zehentleitner/maity/pull/3"), "https PR link kept");

  // The agents live in Members (tsk-7v2snhk002ak): each agent's row opens with its briefing, credentials and pause.
  const agRow = (id) => main.querySelectorAll("tr.member").find((tr) => tr.attrs["data-member"] === id);
  const agOpen = async (id) => {
    agRow(id).querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click();
    for (let k = 0; k < 6; k++) await tick();
    return main.querySelectorAll("tr.member-manage").find((r) => r.id === "member-manage-" + id);
  };
  const realGetAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p.includes("/members/agt-c/credentials")
    ? Promise.reject(new win.Maity.api.ApiError("boom", 500, p, "internal")) : realGetAll(p));
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const agC = await agOpen("agt-c");
  expect(agC.querySelector(".member-credentials .error") && main.querySelectorAll(".error").length === 1, "one failing credentials call costs that agent's row its list");
  win.Maity.api.getAll = realGetAll;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(!main.querySelector(".error") && main.querySelectorAll(".members-agents tr.member").length === 5, "agents in Members: five agent rows");
  const agCRow = await agOpen("agt-c");
  expect(text(agCRow).includes("never resumed") && text(agCRow).includes("revoked") && text(agCRow).includes("replaced by a new clone"), "never resumed and revoked credentials");
  expect(text(agCRow).includes("Areas") && text(agCRow).includes("Capabilities"), "areas and capabilities");
  expect(!text(agCRow).includes("The agent was told at once"), "an agent's own pause is a declaration, without that line");
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const agB = await agOpen("agt-b");
  expect(text(agB.querySelector(".member-pause")).includes("A pause tells the agent at once and refuses it new work (claims, new cards)"),
    "the pause form says what a pause does");
  // Briefing: in the agent's row, edited in place with PATCH members.
  const patches = [];
  const realPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { patches.push([p, b]); return realPatch(p, b); };
  const bBox = () => main.querySelectorAll("tr.member-manage").find((r) => r.id === "member-manage-agt-b").querySelector(".briefing");
  expect(bBox() && text(bBox()).includes("You build the hub (hub/). First: the credential exchange"), "the briefing is shown in the agent's row");
  btn(bBox(), "Edit briefing").click(); await tick();
  expect(byId("briefing-agt-b") && byId("briefing-agt-b").value.startsWith("You build the hub"), "the editor starts with the briefing");
  byId("briefing-agt-b").value = "x".repeat(16 * 1024 + 1);
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick();
  expect(!patches.length && text(main).includes("the briefing is longer than 16,384 characters"), "a briefing over 16 KiB is refused before sending");
  // 16,384 characters pass however many bytes they take, as the hub counts.
  byId("briefing-agt-b").value = "é".repeat(16 * 1024);
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick(); await tick();
  expect(patches.length === 1 && [...patches[0][1].briefing].length === 16384, "a briefing of 16,384 two-byte characters is sent");
  patches.length = 0;
  btn(bBox(), "Edit briefing").click(); await tick();
  byId("briefing-agt-b").value = "  Review hub PRs first.  ";
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick(); await tick();
  expect(patches.length === 1 && patches[0][0] === "/projects/maintainer/maity/members/agt-b" && JSON.stringify(patches[0][1]) === JSON.stringify({ briefing: "  Review hub PRs first.  " })
    && !byId("briefing-agt-b") && text(main).includes("Review hub PRs first.") && text(main).includes("Set by @maintainer"),
    "a saved briefing is PATCHed as typed (Markdown keeps its spaces), shown, and says who set it");
  const bStored = (await win.Maity.api.getAll("/projects/maintainer/maity/members")).items.find((x) => x.id === "agt-b");
  expect(bStored.briefing_version > 1 && text(bBox()).includes("Set by @maintainer · version " + bStored.briefing_version),
    "a saved briefing shows the version the hub answered, not the one read before");
  btn(bBox(), "Edit briefing").click(); await tick();
  byId("briefing-agt-b").value = "";
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(patches[1][1]) === JSON.stringify({ briefing: null }) && text(main).includes("No briefing yet."), "an empty briefing clears it");
  win.Maity.api.patch = realPatch;
  // A hub without briefings (the sample fixtures carry no such key): nothing offered.
  await go("#/maintainer/sample/members"); for (let k = 0; k < 4; k++) await tick();
  const sampleAgent = main.querySelectorAll(".members-agents tr.member")[0];
  sampleAgent.querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click(); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector("tr.member-manage") && !main.querySelector(".briefing"), "no briefing editor where the hub has no briefings");
  await go("#/maintainer/sample/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("join-agent") && !byId("join-briefing"), "no briefing field in the join where the hub has no briefings");
  // Revoking keeps the credential listed, as revoked; the row stays open, its list read again.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const agARow = await agOpen("agt-a");
  const agConfirm = win.confirm;
  win.confirm = () => true;
  btn(agARow.querySelector(".credentials"), "Revoke").click(); for (let k = 0; k < 6; k++) await tick();
  win.confirm = agConfirm;
  const agAAfter = main.querySelectorAll("tr.member-manage").find((r) => r.id === "member-manage-agt-a");
  expect(agAAfter && agAAfter.querySelectorAll(".credentials li.revoked").length === 1, "revoke keeps the credential listed as revoked, the row open");
  // The team's rulebook (§6.18, tsk-xzbk67raztm0): in the agent's row, for its owner; the active count beside the limit.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const tmRow = await agOpen("agt-c");
  const tmForm = tmRow.querySelector("form.member-team");
  expect(tmForm && byId("team-max-agt-c").value === "3" && text(tmForm).includes("1 instance is active now") && byId("team-distribution-agt-c").value === "free"
    && byId("team-lead-agt-c").querySelectorAll("option").map((o) => o.getAttribute("value")).join() === ",k3pa",
    "team: the owner sees the rulebook in the agent's row, the active count beside the limit, the lead among its instances");
  const tmPatches = [];
  const tmPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { tmPatches.push([p, b]); return tmPatch(p, b); };
  byId("team-distribution-agt-c").value = "lead"; tmForm.dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(!tmPatches.length && text(tmForm).includes("A lead is needed"), "team: lead without a lead instance is refused before sending");
  byId("team-lead-agt-c").value = "k3pa"; byId("team-max-agt-c").value = "4";
  tmForm.dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(tmPatches.length === 1 && tmPatches[0][0] === "/projects/maintainer/maity/members/agt-c"
    && JSON.stringify(tmPatches[0][1]) === JSON.stringify({ team: { max_instances: 4, distribution: "lead", lead_instance: "k3pa" } }),
    "team: only what changed is sent " + JSON.stringify(tmPatches[0] && tmPatches[0][1]));
  win.Maity.api.patch = tmPatch;
  // Back to the fixture's rulebook, for the join cases further down.
  await win.Maity.api.patch("/projects/maintainer/maity/members/agt-c", { team: { max_instances: 3, distribution: "free", lead_instance: null } });
  // The quota link's route: the row open, the focus on the limit.
  const tmProto = Object.getPrototypeOf(main), tmFocus = tmProto.focus;
  tmProto.focus = function () { document.activeElement = this; };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/agt-c/rulebook"); for (let k = 0; k < 4; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  expect(byId("team-max-agt-c") && document.activeElement === byId("team-max-agt-c"), "team: the rulebook route opens the row at the limit");
  tmProto.focus = tmFocus; document.activeElement = undefined;
  // A lead revoked since stays chosen, marked; saving the limit alone does not clear it.
  const tmLeadAll = win.Maity.api.getAll, tmLeadGet = win.Maity.api.get;
  const tmGoneLead = (r) => Object.assign({}, r, { items: r.items.map((x) => (x.id === "agt-c" ? Object.assign({}, x, { team: Object.assign({}, x.team, { lead_instance: "old1", distribution: "lead" }) }) : x)), next_cursor: null });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? tmLeadAll(p).then(tmGoneLead) : tmLeadAll(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? tmLeadGet(p).then(tmGoneLead) : tmLeadGet(p));
  const tmLeadPatches = [];
  win.Maity.api.patch = (p, b) => { tmLeadPatches.push(b); return Promise.resolve({}); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/agt-c/rulebook"); for (let k = 0; k < 4; k++) await tick();
  const tmLead = byId("team-lead-agt-c");
  expect(tmLead && tmLead.value === "old1" && tmLead.querySelectorAll("option").some((o) => o.getAttribute("value") === "old1" && o.textContent === "#old1 (revoked)"),
    "team: a revoked lead stays chosen, marked revoked");
  byId("team-max-agt-c").value = "5"; main.querySelectorAll("form.member-team").find((f) => f.contains(byId("team-max-agt-c"))).dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(tmLeadPatches.length === 1 && JSON.stringify(tmLeadPatches[0]) === JSON.stringify({ team: { max_instances: 5 } }),
    "team: saving the limit leaves a revoked lead alone " + JSON.stringify(tmLeadPatches[0]));
  win.Maity.api.patch = tmPatch; win.Maity.api.getAll = tmLeadAll; win.Maity.api.get = tmLeadGet;
  // The maintainer's report (tsk-pj6n7sxertx5): the limit raised in the rulebook, + Add an agent offers the
  // new instances at once, without a reload: the panel reads the members Agents just saved.
  const teamOf = (id) => main.querySelectorAll("form.member-team").find((f) => f.contains(byId("team-max-" + id)));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 6; k++) await tick();
  byId("team-max-agt-b").value = "3"; teamOf("agt-b").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  main.querySelector("button.join-open").click(); for (let k = 0; k < 6; k++) await tick();
  byId("join-agent").value = "agt-b"; byId("join-agent").dispatch("change");
  expect(text(byId("join-quota")) === "1 of 3 instances active.", "team: a raised limit is offered under + Add an agent without a reload: " + text(byId("join-quota")));
  await win.Maity.api.patch("/projects/maintainer/maity/members/agt-b", { team: { max_instances: 1 } });
  // Changed elsewhere since the view was drawn: opening the panel reads the members again.
  btn(main.querySelector(".join-panel"), "Cancel").click(); await tick();
  main.querySelector("button.join-open").click(); for (let k = 0; k < 6; k++) await tick();
  byId("join-agent").value = "agt-b"; byId("join-agent").dispatch("change");
  expect(text(byId("join-quota")) === "1 of 1 instances active; another one is over the team's limit.",
    "team: opening + Add an agent reads the members again, a limit changed elsewhere shows: " + text(byId("join-quota")));
  // The panel open while the rulebook is saved: its count follows at once, the agent still chosen (antigravity's P3 on #616).
  byId("team-max-agt-b").value = "2"; teamOf("agt-b").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".join-panel").hidden && byId("join-agent").value === "agt-b" && text(byId("join-quota")) === "1 of 2 instances active.",
    "team: with the panel open, a saved rulebook redraws its count, the agent still chosen: " + text(byId("join-quota")));
  await win.Maity.api.patch("/projects/maintainer/maity/members/agt-b", { team: { max_instances: 1 } });
  btn(main.querySelector(".join-panel"), "Cancel").click(); await tick();
  // Another owner's agent: no rulebook, even for an admin.
  const tmOthers = win.Maity.api.getAll;
  const tmOthersGet = win.Maity.api.get;
  const tmOtherOwner = (r) => Object.assign({}, r, { items: r.items.map((x) => (x.id === "agt-b" ? Object.assign({}, x, { owner_id: "hum-other" }) : x)), next_cursor: null });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? tmOthers(p).then(tmOtherOwner) : tmOthers(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? tmOthersGet(p).then(tmOtherOwner) : tmOthersGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const tmOther = await agOpen("agt-b");
  expect(tmOther && !tmOther.querySelector("form.member-team"), "team: another owner's agent shows no rulebook, even to an admin");
  win.Maity.api.getAll = tmOthers; win.Maity.api.get = tmOthersGet;

  // The theme (System, Light, Dark), signed in: no switch in the header; Your account sets it, kept per browser on <html> as data-theme.
  const thButton = () => header.querySelectorAll("button").find((b) => (b.getAttribute("aria-label") || "").startsWith("Theme: "));
  const thHtml = document.documentElement;
  const thStore = {};
  win.localStorage = { getItem: (k) => (k in thStore ? thStore[k] : null), setItem: (k, v) => { thStore[k] = String(v); }, removeItem: (k) => { delete thStore[k]; } };
  expect(!thButton() && !header.querySelector(".theme-menu") && thHtml.attrs["data-theme"] === undefined,
    "theme: signed in, no theme switch in the header; System by default, no data-theme on <html>");
  const thProto = Object.getPrototypeOf(header);
  const thFocusWas = thProto.focus;
  thProto.focus = function () { document.activeElement = this; };
  await go("#/account/theme"); for (let k = 0; k < 3; k++) await tick();
  const thRadio = (t) => byId("theme-" + t);
  expect(thRadio("system") && thRadio("system").checked && !thRadio("light").checked && !thRadio("dark").checked
    && main.querySelector("fieldset.theme-choice").getAttribute("aria-labelledby") === "theme-heading" && text(byId("theme-heading")) === "Theme"
    && document.activeElement === byId("theme-heading"),
    "theme: #/account/theme focuses the account's Theme, three choices, the current one checked");
  thProto.focus = thFocusWas; document.activeElement = undefined;
  const thChoose = async (t) => { thRadio(t).checked = true; thRadio(t).dispatch("change"); await tick(); };
  await thChoose("dark");
  expect(thHtml.attrs["data-theme"] === "dark" && thStore["maity.theme"] === "dark", "theme: Dark in the account sets data-theme=dark and is kept");
  await thChoose("light");
  expect(thHtml.attrs["data-theme"] === "light" && thStore["maity.theme"] === "light", "theme: Light sets data-theme=light");
  await thChoose("system");
  expect(thHtml.attrs["data-theme"] === undefined && !("maity.theme" in thStore), "theme: System removes both");
  // Storage that refuses: the pick still applies, nothing throws.
  win.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
  await thChoose("dark");
  expect(thHtml.attrs["data-theme"] === "dark", "theme: without storage the pick applies to this page");
  await thChoose("system");
  delete win.localStorage;
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  // Both ways to dark hold the same tokens: the system's (unless Light was picked) and an explicit Dark.
  const thCss = fs.readFileSync(path.join(WEB, "css/app.css"), "utf8");
  const thDark = (sel) => { const m = thCss.split(sel + " {")[1]; return m ? m.split("}")[0].replace(/\s+/g, " ").trim() : ""; };
  expect(thCss.includes('@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {') && thDark(':root[data-theme="dark"]').includes("--bg: #111418;")
    && thDark(':root:not([data-theme="light"])') === thDark(':root[data-theme="dark"]'),
    "theme: the dark tokens apply by the system unless Light is picked, and when Dark is picked, the same in both");
  expect(/@media \(max-width: 600px\) \{\s+\.bar > \.project \{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset\(50%\);/.test(thCss),
    "header: at phone width the text beside the logo is hidden from sight, still read out");
  // The brand (web/brand/BRAND.md): the 28 px header lockup in the page's theme, the favicons, the loader.
  const brImgs = header.querySelector(".brand").querySelectorAll("img");
  expect(brImgs.length === 2 && brImgs.map((i) => i.getAttribute("src")).join(" ") === "brand/maity-lockup.svg brand/maity-lockup-dark.svg"
    && brImgs.every((i) => i.getAttribute("alt") === "Maity" && i.getAttribute("height") === "28"), "brand: the header's title is the lockup, one file per theme, named Maity");
  expect(thCss.includes(".brand-lockup.brand-dark { display: none; }")
    && thCss.includes(':root:not([data-theme="light"]) .brand-lockup.brand-dark { display: block; }')
    && thCss.includes(':root[data-theme="dark"] .brand-lockup.brand-light { display: none; }'),
    "brand: the dark lockup shows where the page is dark, by the system or by the pick");
  expect(['rel="icon" href="brand/favicon.svg"', 'rel="apple-touch-icon" href="brand/apple-touch-icon.png"', 'property="og:image" content="brand/og-image.png"', 'href="brand/loader.css"']
    .every((x) => html.includes(x)) && /<p class="page-loading" role="status"><svg class="maity-loader"[^]*<\/svg> Loading Maity…<\/p>/.test(html)
    && !/ style=/.test(html.split('<main id="main">')[1]), "brand: favicons, the social image and the page loader, with no inline style (CSP)");
  expect(!main.querySelector(".page-loading"), "brand: the first view replaces the loader");
  // The header with the lockup is in the page itself, before any script or hub call (tsk-vb0dgwhrkvsn).
  expect(/<header id="header"><div class="bar"><h1 class="brand"><img class="brand-lockup brand-light" src="brand\/maity-lockup.svg" alt="Maity"[^>]*><img class="brand-lockup brand-dark" src="brand\/maity-lockup-dark.svg" alt="Maity"[^>]*><\/h1><\/div><\/header>/.test(html)
    && !/ style=/.test(html.split('<header id="header">')[1].split("</header>")[0]),
    "loading: the header with the lockup is static in the page, before any script runs");
  expect(thCss.includes("body:has(> main > .page-loading, > main > .page-failed)") && thCss.includes("main:has(> .page-loading, > .page-failed) { flex: 1;")
    && thCss.includes(".page-loading { display: flex; flex-direction: column; align-items: center; justify-content: center;")
    && thCss.includes("animation: page-loading-shows 0s linear 300ms forwards") && thCss.includes(".page-loading .maity-loader { width: 48px; height: 48px; }"),
    "loading: the loader (48 px, its word under it, after 300 ms) and a failure are centred in what the header leaves of the screen");
  // A page that cannot load: the header and its lockup stay, the failure stands centred, Try again loads again.
  const ldgGet = win.Maity.api.get;
  let ldgFail = true;
  win.Maity.api.get = (p) => (ldgFail && p === "/auth/session" ? Promise.reject(new win.Maity.api.ApiError("The hub did not answer: offline", 0, p)) : ldgGet(p));
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const ldgBox = main.querySelector(".page-failed");
  const ldgAgain = ldgBox && ldgBox.querySelectorAll("button").find((b) => b.textContent === "Try again");
  const ldgTitle = ldgBox && ldgBox.querySelector(".page-failed-title");
  const ldgDetails = ldgBox && ldgBox.querySelector("details");
  expect(ldgBox && ldgBox.parentNode === main && ldgTitle && ["Maity can't reach its hub", "The sample data didn't load"].includes(text(ldgTitle))
    && ldgBox.querySelectorAll("img.page-failed-mark").length === 2 && !ldgBox.querySelector(".error")
    && ldgDetails && text(ldgDetails.querySelector("summary")) === "Details" && text(ldgDetails).includes("The hub did not answer: offline")
    && ldgAgain && ldgAgain.classList.contains("primary") && ldgAgain.parentNode.classList.contains("page-failed-actions")
    && !ldgBox.querySelectorAll("button").some((b) => b.textContent === "Sign in again")
    && header.querySelector(".brand") && header.querySelector(".brand").querySelectorAll("img").length === 2,
    "loading: a page that could not load keeps the header, says in plain words what does not work, the reason under Details, Try again primary");
  // A session gone (401 past /auth/session): Sign in again beside Try again.
  win.Maity.api.get = (p) => (ldgFail && p === "/me" ? Promise.reject(new win.Maity.api.ApiError("session expired", 401, p, "unauthenticated")) : ldgGet(p));
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const ldgSignIn = main.querySelectorAll(".page-failed-actions button").map((b) => b.textContent);
  expect(JSON.stringify(ldgSignIn) === JSON.stringify(["Sign in again", "Try again"]), "loading: a lost session offers Sign in again before Try again");
  win.Maity.api.get = (p) => (ldgFail && p === "/auth/session" ? Promise.reject(new win.Maity.api.ApiError("The hub did not answer: offline", 0, p)) : ldgGet(p));
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  ldgFail = false;
  ldgAgain.click(); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".page-failed") && !main.querySelector(".page-loading") && main.querySelector("section.view"),
    "loading: Try again loads the page");
  win.Maity.api.get = ldgGet;
  expect(/<script src="js\/theme.js"><\/script>/.test(html) && html.indexOf("js/theme.js") < html.indexOf("js/dom.js"),
    "theme: applied before the first paint, by a script in <head> without defer");
  // Users of this hub (docs/api.md §16.1), for the instance admin only.
  gearButton().click(); await tick();
  expect(JSON.stringify(gearButton().parentNode.querySelectorAll(".menu-item").map((el) => el.textContent)) === JSON.stringify(["Agents", "Runners", "Instance administration"])
    && gearButton().attrs["aria-haspopup"] === "menu", "header: the gear menu has one's agents, the runners and, for the instance admin, the users");
  const tabNames = header.querySelectorAll("nav.views a").map((a) => a.textContent.replace(/\d+$/, ""));
  expect(tabNames[tabNames.length - 1] === "Settings" && tabNames.indexOf("Runners") < tabNames.indexOf("Settings")
    && tabNames.indexOf("Why") < tabNames.indexOf("Settings") && tabNames.indexOf("Why") > tabNames.indexOf("Runners"),
    "header: the project's Settings are its last tab, after Runners and Why " + JSON.stringify(tabNames));
  const usersLink = header.querySelectorAll("a.menu-item").find((a) => a.textContent === "Instance administration");
  expect(usersLink && usersLink.getAttribute("href") === "#/admin", "users: in the settings menu for the instance admin");
  gearButton().click(); await tick();
  // The users are the Users section of #/admin; the old #/admin/users is no view (tsk-qeh64f8gpvnd).
  await go("#/admin/users"); await tick();
  expect(text(main).includes("No such view") && !main.querySelector("table.users"), "users: #/admin/users is no longer a route of its own");
  const usersOpen = async () => {
    await go("#/all"); await go("#/admin"); for (let k = 0; k < 6; k++) await tick();
    const pickUsers = main.querySelectorAll("nav.admin-nav button").find((b) => b.textContent === "Users");
    if (pickUsers) { pickUsers.click(); await tick(); }
  };
  await usersOpen();
  const userRows = () => main.querySelectorAll("table.users tbody tr");
  const userNames = () => userRows().map((tr) => tr.querySelector(".user-name").textContent);
  expect(plainTitle() === "Instance administration · Maity" && byId("admin-users") && !byId("admin-users").hidden
    && JSON.stringify(userNames()) === JSON.stringify(["Guest Reviewer", "Maintainer", "Ops on call"]),
    "users: every human, by handle, in the Users section of the instance administration");
  const meRow = userRows().find((tr) => text(tr).includes("Maintainer"));
  expect(text(meRow).includes("(you)") && text(meRow).includes("instance admin") && /Projects2|>2</.test(meRow.querySelectorAll("td").map((td) => td.attrs["data-label"] + td.textContent).join("")),
    "users: the admin's own row, its counts");
  const opsRow = userRows().find((tr) => text(tr).includes("Ops on call"));
  expect(opsRow.className === "disabled" && text(opsRow).includes("disabled") && text(userRows()[0]).includes("never"), "users: a disabled account, a never-signed-in one");
  const uq = byId("users-q"); uq.value = "OPS"; uq.dispatch("input");
  await new Promise((r) => setTimeout(r, 350)); await tick();
  expect(JSON.stringify(userNames()) === JSON.stringify(["Ops on call"]), "users: search by handle or name, case-insensitive");
  uq.value = ""; const ud = byId("users-disabled"); ud.value = "false"; ud.dispatch("change"); await tick(); await tick();
  expect(JSON.stringify(userNames()) === JSON.stringify(["Guest Reviewer", "Maintainer"]), "users: only active accounts");
  // Paged by the hub's cursor: Load more appends.
  const uGet = win.Maity.api.get;
  const uPaths = [];
  win.Maity.api.get = (p) => {
    if (!p.startsWith("/admin/users")) return uGet(p);
    uPaths.push(p);
    return uGet(p.replace("limit=50", "limit=1"));
  };
  ud.value = ""; ud.dispatch("change"); await tick(); await tick();
  expect(userRows().length === 1 && btn(main, "Load more") && text(main).includes("1+ account"), "users: one page, and more to load");
  const uProto = Object.getPrototypeOf(main);
  const uFocus = uProto.focus;
  uProto.focus = function () { document.activeElement = this; };
  btn(main, "Load more").click(); await tick(); await tick();
  expect(userRows().length === 2 && uPaths[uPaths.length - 1].includes("cursor=1"), "users: Load more reads the next page by its cursor");
  expect(document.activeElement === userRows()[1].querySelector("th"), "users: after Load more the focus is on the first new row");
  uProto.focus = uFocus; document.activeElement = undefined;
  // A cursor belongs to its filter: typing ends the old paging at once, and the
  // next page then asks with the filter it was read with, not what is typed.
  uq.value = "a"; uq.dispatch("input");
  expect(!btn(main, "Load more"), "users: a filter edit takes Load more away at once");
  await new Promise((r) => setTimeout(r, 350)); await tick(); await tick();
  uq.value = "m"; uq.dispatch("input"); uq.value = "a";
  btn(main, "Load more") && btn(main, "Load more").click();
  await tick(); await tick();
  expect(!uPaths.some((p) => p.includes("cursor=") && p.includes("q=m")), "users: no next page is read with a filter it was not given for");
  // A slower, older answer never replaces a newer one.
  let slow = true;
  win.Maity.api.get = (p) => {
    if (!p.startsWith("/admin/users")) return uGet(p);
    const answer = uGet(p);
    if (slow && p.includes("q=guest")) { slow = false; return new Promise((r) => setTimeout(r, 500)).then(() => answer); }
    return answer;
  };
  uq.value = "guest"; uq.dispatch("input"); await new Promise((r) => setTimeout(r, 330));
  uq.value = "ops"; uq.dispatch("input"); await new Promise((r) => setTimeout(r, 400)); await tick();
  const sawOps = JSON.stringify(userNames()) === JSON.stringify(["Ops on call"]);
  await new Promise((r) => setTimeout(r, 300)); await tick();
  expect(sawOps && JSON.stringify(userNames()) === JSON.stringify(["Ops on call"]), "users: a delayed older search answer, arriving after the newer one, is dropped " + JSON.stringify(userNames()));
  // The endpoint itself refusing (403) is said, not hidden.
  win.Maity.api.get = (p) => (p.startsWith("/admin/users") ? Promise.reject(new win.Maity.api.ApiError("instance:admin needed", 403, p, "forbidden")) : uGet(p));
  await usersOpen();
  expect(text(main).includes("The users could not be read: instance:admin needed"), "users: the endpoint's 403 is said");
  uq.value = "";
  // A hub without the list, and someone who is not the instance admin.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => p === "/openapi.json" ? Promise.resolve({ paths: {} }) : (p.startsWith("/admin/users") ? Promise.reject(new win.Maity.api.ApiError("nope", 404, p, "not_found")) : uGet(p));
  await usersOpen();
  expect(!main.querySelector("table.users") && !main.querySelectorAll("nav.admin-nav button").some((b) => b.textContent === "Users") && !main.querySelector(".error"),
    "users: a hub without the list has no Users section");
  win.Maity.api.get = (p) => (p === "/me" ? uGet(p).then((x) => { x.member.instance_admin = false; return x; }) : uGet(p));
  await usersOpen();
  expect(!header.querySelectorAll("a").some((a) => a.textContent === "Instance administration") && text(main).includes("Only the instance admin can open this area.")
    && !main.querySelector("table.users"), "users: no link and no list for anyone else");
  win.Maity.api.get = uGet; win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox");
  // Project → Runners (docs/api.md §15.4): the runners allowed in a project.
  const prTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Runners");
  expect(prTab() && prTab().getAttribute("href") === "#/maintainer/maity/runners", "project runners: a tab for the project's admin");
  const prWrites = [];
  const prPost = win.Maity.api.post, prDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { prWrites.push(["POST", p, b]); return prPost(p, b); };
  win.Maity.api.del = (p) => { prWrites.push(["DELETE", p]); return prDel(p); };
  await go("#/maintainer/maity/runners"); await tick();
  const prCard = (name) => main.querySelectorAll("article.runner").find((a) => a.getAttribute("aria-label") === name);
  expect(plainTitle() === "Runners · Maity · Maity" && main.querySelectorAll("article.runner").length === 2 && prCard("cluster") && prCard("home-laptop"),
    "project runners: the attached runners, by name");
  const prLaptop = text(prCard("home-laptop"));
  expect(prLaptop.includes("online") && prLaptop.includes("1 agent running here") && prLaptop.includes("Claude Code 2.1.308")
    && prLaptop.includes("Agents on home-laptop run as one user, oliver") && !prLaptop.includes("does not allow"),
    "project runners: presence, agents running here, capabilities in plain words");
  expect(text(prCard("cluster")).includes("Its credential was revoked: it starts nothing until it is paired again"), "project runners: a revoked runner says it starts nothing");
  const prAllN = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/runners"
    ? prAllN(p).then((r) => ({ items: r.items.map((a) => (a.runner.name === "cluster" ? Object.assign({}, a, { runner: Object.assign({}, a.runner, { credential_state: "none" }) }) : a)), next_cursor: null }))
    : prAllN(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/runners"); await tick();
  expect(text(prCard("cluster")).includes("It has not been paired yet: it starts nothing until it is") && !text(prCard("cluster")).includes("again"),
    "project runners: a runner never paired is not told to pair again");
  win.Maity.api.getAll = prAllN;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/runners"); await tick();
  const prSelect = byId("allow-runner");
  expect(prSelect && prSelect.querySelectorAll("option").length === 1 && prSelect.value === "rnr-0003", "project runners: only the own runners not attached here are offered");
  // The 30-second refresh leaves an unchanged Allow form and the focused Detach where they are.
  const prProto = Object.getPrototypeOf(prSelect);
  const prFocus = prProto.focus;
  prProto.focus = function () { document.activeElement = this; };
  const clusterDetach = btn(prCard("cluster"), "Detach");
  clusterDetach.focus();
  const prAll0 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/runners"
    ? prAll0(p).then((r) => ({ items: r.items.map((a) => (a.runner.name === "cluster" ? Object.assign({}, a, { active_placements: 3 }) : a)), next_cursor: null }))
    : prAll0(p));
  await fireIntervals(); await tick(); await tick();
  expect(byId("allow-runner") === prSelect && text(prCard("cluster")).includes("3 agents running here") && document.activeElement !== clusterDetach
    && document.activeElement === btn(prCard("cluster"), "Detach"), "project runners: a refresh redraws a changed card and keeps the Allow form and the focus on the same Detach");
  win.Maity.api.getAll = prAll0;
  // A new runner of one's own changes the Allow form; the focus in it comes back to the select.
  byId("allow-runner").focus();
  win.Maity.api.getAll = (p) => (p === "/runners"
    ? prAll0(p).then((r) => ({ items: r.items.concat([Object.assign({}, r.items.find((x) => x.id === "rnr-0003"), { id: "rnr-0099", name: "spare-box" })]), next_cursor: null }))
    : prAll0(p));
  await fireIntervals(); await tick(); await tick();
  expect(byId("allow-runner") !== prSelect && document.activeElement === byId("allow-runner") && byId("allow-runner").querySelectorAll("option").length === 2,
    "project runners: a rebuilt Allow form gets the focus back");
  win.Maity.api.getAll = prAll0;
  await fireIntervals(); await tick(); await tick();
  main.querySelector(".allow-runner form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect((document.activeElement === main.querySelector(".view-runners .send-status") || (document.activeElement && document.activeElement.className.startsWith("send-status")))
    && text(document.activeElement).includes("build-box is allowed here."), "project runners: after an action the status line has the focus and says what happened");
  prProto.focus = prFocus; document.activeElement = undefined;
  expect(JSON.stringify(prWrites[0]) === JSON.stringify(["POST", "/projects/maintainer/maity/runners", { runner_id: "rnr-0003" }]) && prCard("build-box")
    && text(prCard("build-box")).includes("Its own configuration does not allow maintainer/maity, so it starts nothing here"),
    "project runners: allowed, and warned where its own configuration does not allow the project");
  expect(text(main).includes("All your runners are allowed here."), "project runners: nothing left to allow");
  let prAsked = "";
  const prConfirm = win.confirm;
  win.confirm = (q) => { prAsked = q; return true; };
  // The count is read when Detach is pressed: an agent started meanwhile is named.
  const prAll1 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/runners"
    ? prAll1(p).then((r) => ({ items: r.items.map((a) => (a.runner.name === "home-laptop" ? Object.assign({}, a, { active_placements: 2 }) : a)), next_cursor: null }))
    : prAll1(p));
  win.confirm = (q) => { prAsked = q; return false; };
  btn(prCard("home-laptop"), "Detach").click(); for (let k = 0; k < 4; k++) await tick();
  expect(prAsked.includes("of the 2 agents it runs here"), "project runners: the confirmation names the agents running now, not at the last refresh");
  win.Maity.api.getAll = prAll1;
  win.confirm = (q) => { prAsked = q; return true; };
  btn(prCard("home-laptop"), "Detach").click(); for (let k = 0; k < 4; k++) await tick();
  expect(prAsked === "Detach home-laptop from Maity? The hub closes the placement of the 1 agent it runs here, and the runner stops it."
    && JSON.stringify(prWrites[1]) === JSON.stringify(["DELETE", "/projects/maintainer/maity/runners/rnr-0002"]) && !prCard("home-laptop")
    && text(main).includes("home-laptop is detached from Maity."),
    "project runners: detaching names the agents it stops");
  btn(prCard("build-box"), "Detach").click(); for (let k = 0; k < 4; k++) await tick();
  expect(prAsked === "Detach build-box from Maity? Nothing runs on it here.", "project runners: detaching a runner with nothing running says so");
  win.confirm = () => false;
  btn(prCard("cluster"), "Detach").click(); await tick();
  expect(prWrites.length === 3 && prCard("cluster"), "project runners: a declined detach sends nothing");
  win.confirm = prConfirm;
  // A runner attached meanwhile (another tab): said, and the list re-read.
  win.Maity.api.post = (p, b) => Promise.reject(new win.Maity.api.ApiError("the runner is attached already", 409, p, "already_attached", {}));
  main.querySelector(".allow-runner form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("It was allowed here already."), "project runners: already attached is no failure");
  // Put the fixtures back for the instance-level view.
  win.Maity.api.post = prPost; win.Maity.api.del = prDel;
  await prPost("/projects/maintainer/maity/runners", { runner_id: "rnr-0002" });
  // A refusal fails loud, as in every view; the empty state; no tab for a member.
  const prAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/runners" ? Promise.reject(new win.Maity.api.ApiError("nope", 404, p, "not_found")) : prAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/runners"); await tick();
  expect(main.querySelector(".error") && !text(main).includes("cannot allow runners"), "project runners: a 404 is an error, not a missing feature");
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/runners" || p === "/runners" ? Promise.resolve({ items: [], next_cursor: null }) : prAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/runners"); await tick();
  expect(text(main).includes("No runner is allowed in this project yet.") && text(main).includes("You have no runner yet. Pair one on the Runners page."),
    "project runners: the empty state points to pairing");
  win.Maity.api.getAll = prAll;
  const prGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? prGet(p).then((m) => { m.projects.find((x) => x.slug === "maity").trust = "member"; return m; }) : prGet(p));
  await go("#/maintainer/maity/runners"); await tick();
  expect(!prTab() && text(main).includes("No such view."), "project runners: no tab and no view for a member");
  win.Maity.api.get = prGet;
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();

  // The change ticker's settings and the forge webhook in Project settings (tsk-a3cj2canahy3, §17.3, §17.4).
  await go("#/maintainer/maity/inbox"); await projectSettings();
  expect(byId("ticker-enabled") && byId("ticker-enabled").checked && byId("ticker-files").value === "docs/api.md"
    && byId("ticker-implementers").value === "8: area:hub/ area:web/\n15: member:agt-b\n*: area:hub/"
    && main.querySelectorAll("a").some((a) => a.getAttribute("href") === "#/maintainer/maity/ticker"),
    "ticker settings: on, the contract file and who implements which section, written as lines; one's follows in the Ticker");
  byId("ticker-implementers").value = "8: area:hub/ member:agt-gone\n*: role:nobody"; byId("ticker-implementers").dispatch("input");
  expect(!byId("ticker-unresolved").hidden && text(byId("ticker-unresolved")).includes("member:agt-gone") && text(byId("ticker-unresolved")).includes("role:nobody"),
    "ticker settings: a token that names nobody now is said as unresolved");
  const tsetPatches = [];
  const tsetPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { tsetPatches.push([p, b]); return tsetPatch(p, b); };
  byId("ticker-implementers").value = "eight area:hub/"; main.querySelector("form.ticker-settings").dispatch("submit"); await tick();
  expect(!tsetPatches.length && text(main.querySelector("form.ticker-settings .send-status")).includes("write it as"), "ticker settings: a line that is no mapping is refused before sending");
  byId("ticker-enabled").checked = false; byId("ticker-files").value = "docs/api.md\ndocs/runner.md";
  byId("ticker-implementers").value = "8.2: area:web/\n*: trust:admin";
  main.querySelector("form.ticker-settings").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(tsetPatches.length === 1 && JSON.stringify(tsetPatches[0][1]) === JSON.stringify({ settings: { ticker: { enabled: false,
    contract_files: ["docs/api.md", "docs/runner.md"], contract_implementers: { "8.2": ["area:web/"], "*": ["trust:admin"] } } } }),
    "ticker settings: saved whole, as the hub takes the setting " + JSON.stringify(tsetPatches[0] && tsetPatches[0][1]));
  win.Maity.api.patch = tsetPatch;
  // The webhook: none yet; made, the secret shown once with the address; rotated after a confirm; removed.
  await go("#/maintainer/maity/inbox"); await projectSettings();
  const whBox = () => main.querySelector("section.webhook");
  expect(whBox() && text(whBox()).includes("Secret") && text(whBox()).includes("none") && btn(whBox(), "Create a secret"), "webhook: none set, Create a secret");
  btn(whBox(), "Create a secret").click(); for (let k = 0; k < 6; k++) await tick();
  const whSecret = whBox().querySelector(".webhook-secret-value");
  expect(whSecret && /^whsec_/.test(text(whSecret)) && text(whBox()).includes("/api/v1/projects/maintainer/maity/forge/webhook") && text(whBox()).includes("Shown only now")
    && btn(whBox(), "Rotate the secret") && btn(whBox(), "Remove the secret"), "webhook: a made secret is shown once with the payload URL, then Rotate and Remove");
  const whConfirm = win.confirm;
  let whAsked = 0;
  win.confirm = () => { whAsked += 1; return false; };
  btn(whBox(), "Rotate the secret").click(); for (let k = 0; k < 4; k++) await tick();
  expect(whAsked === 1 && text(whBox().querySelector(".webhook-secret-value")) === text(whSecret), "webhook: rotating asks first; declined, nothing changes");
  win.confirm = () => true;
  btn(whBox(), "Remove the secret").click(); for (let k = 0; k < 6; k++) await tick();
  expect(btn(whBox(), "Create a secret") && !whBox().querySelector(".webhook-secret-value"), "webhook: removed, none set again");
  win.confirm = whConfirm;
  // Made, but the read after it fails: the secret from the POST is still shown, once.
  const whGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/forge/webhook" && whGetFail ? Promise.reject(new win.Maity.api.ApiError("down", 503, p, "internal", {})) : whGet(p));
  let whGetFail = true;
  btn(whBox(), "Create a secret").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(whBox()).includes("The webhook could not be read") && whBox().querySelector(".webhook-secret-value")
    && /^whsec_/.test(text(whBox().querySelector(".webhook-secret-value"))) && btn(whBox(), "Read it again"),
    "webhook: a made secret is shown even when the read after it fails");
  whGetFail = false;
  const whKept = text(whBox().querySelector(".webhook-secret-value"));
  btn(whBox(), "Read it again").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(whBox().querySelector(".webhook-secret-value")) === whKept && btn(whBox(), "Rotate the secret"), "webhook: read again, the same secret still shown");
  win.Maity.api.get = whGet;
  win.confirm = () => true;
  btn(whBox(), "Remove the secret").click(); for (let k = 0; k < 6; k++) await tick();
  win.confirm = whConfirm;
  // An area token resolves as the hub resolves it (hub/ticker.py contains).
  const tsC = win.Maity.tickerSettings.contains;
  expect(tsC("/", "hub/") && tsC("hub", "hub/") && tsC("hub/", "hub") && tsC("hub/", "hub/src") && !tsC("hub", "hubris") && !tsC("hub/src", "hub"),
    "ticker settings: an area contains a path as the hub reads it");
  await go("#/maintainer/maity/inbox");

  // Runners (docs/api.md §15): the instance-level view.
  // Runners are the person's (tsk-cb6myw32def0): in the gear menu, not beside the projects.
  expect(!header.querySelectorAll(".switcher a").some((a) => a.textContent === "Runners"), "runners: no link in the projects' row");
  gearButton().click(); await tick();
  const runnersLink = gearButton().parentNode.querySelectorAll(".menu-item").find((a) => a.textContent === "Runners");
  expect(runnersLink && runnersLink.getAttribute("href") === "#/runners", "runners: in the gear menu");
  gearButton().click(); await tick();
  const rWrites = [];
  const rPost = win.Maity.api.post, rPatch = win.Maity.api.patch, rDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { rWrites.push(["POST", p, b]); return rPost(p, b); };
  win.Maity.api.patch = (p, b) => { rWrites.push(["PATCH", p, b]); return rPatch(p, b); };
  win.Maity.api.del = (p) => { rWrites.push(["DELETE", p]); return rDel(p); };
  await go("#/runners"); await tick();
  gearButton().click(); await tick();
  const runnersHere = gearButton().parentNode.querySelectorAll(".menu-item").find((a) => a.textContent === "Runners");
  expect(!runnersLink.getAttribute("aria-current") && runnersHere && runnersHere.getAttribute("aria-current") === "page",
    "runners: the gear menu marks the page shown");
  gearButton().click(); await tick();
  const card = (name) => main.querySelectorAll("article.runner").find((a) => a.getAttribute("aria-label") === name);
  expect(plainTitle() === "Runners · Maity" && main.querySelectorAll("article.runner").length === 3, "runners: the view lists the runners");
  const laptop = text(card("home-laptop"));
  expect(laptop.includes("online") && laptop.includes("this machine") && laptop.includes("Allowed in maintainer/maity.")
    && laptop.includes("Claude Code 2.1.308 · kept to its command allowlist · a session you can attach to (tmux); or woken by events, no open session (no tokens while idle)")
    && laptop.includes("opencode is not installed on home-laptop")
    && laptop.includes("Agents on home-laptop run as one user, oliver, and can see each other's files, as the runner itself does.")
    && laptop.includes("Credential rcrd-0002-0001"), "runners: a local runner in plain words, its tools and who can see what");
  const box = text(card("build-box"));
  expect(box.includes("hosts build-1, build-2") && box.includes("host build-2: 0 of 2 agents running · unreachable since")
    && box.includes("Each agent on build-1 runs as its own user") && box.includes("in its OS sandbox")
    && box.includes("every new agent waits for approval on that machine") && box.includes("Not allowed in any project yet"),
    "runners: an ssh runner: hosts, an unreachable one, own users, local approval");
  const cluster = text(card("cluster"));
  expect(cluster.includes("revoked") && cluster.includes("pods in maity-agents") && cluster.includes("pi 0.9.1 · without a command allowlist: its pod is the only boundary")
    && cluster.includes("Each agent on maity-agents runs in its own pod"), "runners: a revoked cluster runner, a tool without an allowlist");
  expect(!text(main).includes("Open pairings"), "runners: an expired pairing is not listed as open");
  // Pair: the name is checked first; the line is shown once, with the starter configuration.
  byId("pair-name").value = "New Laptop";
  main.querySelector("form.pair-form").dispatch("submit"); await tick();
  expect(!rWrites.length && text(main).includes("No pairing line: the name: Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit."), "runners: a bad name is refused before sending");
  expect(text(main.querySelector("form.pair-form")).includes("Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit.") && byId("pair-name").getAttribute("aria-describedby") === "pair-name-rule",
    "runners: the name's rule is said up front");
  byId("pair-name").value = "new-laptop";
  main.querySelector("form.pair-form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(JSON.stringify(rWrites[0]) === JSON.stringify(["POST", "/runners/enrollments", { name: "new-laptop", ttl_seconds: 900, attach: ["maintainer/maity", "maintainer/sample"] }]),
    "runners: pairing asks for an enrollment that allows the chosen projects");
  const steps = main.querySelector(".pair-steps");
  const config = text(steps.querySelector(".runner-config"));
  expect(text(steps).includes("maity runner pair https://maity.example/r/FIXTURE-") && text(steps).includes("pipx install")
    && text(steps).includes("maity runner check") && text(steps).includes("maity runner serve"), "runners: the steps: install, configure, pair, check, serve");
  expect(config.includes('url = "https://maity.example"') && config.includes('projects = ["maintainer/maity", "maintainer/sample"]')
    && config.includes('"github.com/oliver-zehentleitner/maity"') && config.includes('"github.com/example/sample-shop"')
    && config.includes("[harness.claude-code]") && config.includes('layout = "single"') && !config.includes("FIXT-URE0") && !config.includes("/r/FIXTURE"),
    "runners: the starter configuration names the hub, the projects and their repositories, and no secret");
  expect(["state_dir", "workspaces", "tmux_socket", "max_agents", "default_mode", "default_model", "binary"].every((k) => !config.includes(k + " =")),
    "runners: the starter configuration holds only the keys without a default");
  expect(text(steps).includes("installs the published CLI, which brings maity runner pair, check, serve and stop-all")
    && text(steps).includes("Start it: maity runner serve.") && !text(steps).includes("not in the CLI yet"),
    "runners: the steps name the published CLI and how to start the runner");
  const hostile = win.Maity.runnerStarterConfig("https://h.example", [{ full_name: "a\"b\\c\u007f\n\ud800", repository: null }]);
  expect(hostile.includes('projects = ["a\\"b\\\\c\\u007f\\u000a\ufffd"]'), "runners: TOML strings escape quotes, backslashes, control characters and DEL; a lone surrogate is replaced");
  expect(win.Maity.runnerStarterConfig("https://h.example", []).includes("projects = []   # none chosen"), "runners: no project chosen is said in the configuration");
  expect(win.Maity.runnerConfigCommand("x\n").includes("(set -C; umask 077; cat > ~/.config/maity-runner/runner.toml) <<'EOF'\nx\nEOF"),
    "runners: the command writes the configuration owner-only and never over an existing one");
  expect(text(main).includes("Open pairings") && text(main).includes("new-laptop"), "runners: the open pairing is listed, revocable");
  await go("#/all"); await go("#/runners"); await tick();
  expect(!main.querySelector(".pair-steps") && !text(main).includes("FIXT-URE0-RUNR"), "runners: the pairing line is gone after leaving the view");
  // Re-pair keeps the runner and the configuration.
  btn(card("home-laptop"), "Re-pair").click(); await tick(); await tick(); await tick();
  expect(rWrites.some((w) => JSON.stringify(w[2]) === JSON.stringify({ runner_id: "rnr-0002" })) && text(main.querySelector(".pair-steps")).includes("Keep your existing configuration"),
    "runners: re-pairing asks for a line for the same runner");
  await fireIntervals(); await tick();
  expect(text(main.querySelector(".pair-wait")).includes("Waiting for the runner") && main.querySelector(".pair-line-step pre"),
    "runners: a re-pair waits for the new credential, not the old one");
  const rAll0 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => rAll0(p).then((a) => (p !== "/runners" ? a : { items: a.items.map((r) => (r.id !== "rnr-0002" ? r
    : Object.assign({}, r, { credential: Object.assign({}, r.credential, { id: "rcrd-0002-0002" }) }))), next_cursor: null }));
  await fireIntervals(); await tick();
  expect(text(main.querySelector(".pair-wait")).includes("home-laptop is online.") && !main.querySelector(".pair-line-step pre")
    && text(main.querySelector(".pair-line-step")).includes("Paired; the line is used up."), "runners: the used line leaves the page once paired");
  win.Maity.api.getAll = rAll0;
  // Rename, revoke, remove.
  byId("runner-name-rnr-0003").value = "home-laptop";
  card("build-box").querySelector("form.rename").dispatch("submit"); await tick(); await tick(); await tick();
  expect(text(main).includes("Renaming failed") && text(main).includes("you have a runner of that name"), "runners: a taken name is refused by the hub");
  byId("runner-name-rnr-0003").value = "builder";
  card("build-box").querySelector("form.rename").dispatch("submit"); await tick(); await tick(); await tick();
  expect(card("builder") && JSON.stringify(rWrites.find((w) => w[0] === "PATCH" && w[2].name === "builder")) === JSON.stringify(["PATCH", "/runners/rnr-0003", { name: "builder" }]),
    "runners: renamed");
  // A periodic read still in flight when the revoke reloads answers last: it draws nothing.
  const rAll1 = win.Maity.api.getAll;
  let releaseStale = null;
  win.Maity.api.getAll = (p) => {
    if (p !== "/runners" || releaseStale) return rAll1(p);
    const stale = rAll1(p).then((a) => JSON.parse(JSON.stringify(a)));
    return new Promise((resolve) => { releaseStale = () => resolve(stale); });
  };
  const periodic = fireIntervals(); await tick();
  win.Maity.api.getAll = rAll1;
  btn(card("builder"), "Revoke").click(); await tick(); await tick(); await tick();
  expect(text(card("builder")).includes("revoked") && !btn(card("builder"), "Revoke"), "runners: revoked, no second Revoke");
  releaseStale(); await periodic; await tick(); await tick();
  expect(text(card("builder")).includes("revoked") && !btn(card("builder"), "Revoke"), "runners: an older periodic read answering late does not undo the revoke");
  // A slow periodic read is not overtaken by the next tick: it lands.
  let releaseSlow = null;
  win.Maity.api.getAll = (p) => {
    if (p !== "/runners") return rAll1(p);
    const renamed = rAll1(p).then((a) => ({ items: a.items.map((r) => (r.id !== "rnr-0003" ? r : Object.assign({}, r, { name: "slow-box" }))), next_cursor: null }));
    return new Promise((resolve) => { releaseSlow = () => resolve(renamed); });
  };
  const rSlowRead = fireIntervals(); await tick();
  const rFirstRelease = releaseSlow; releaseSlow = null;
  const rNextTick = fireIntervals(); await tick();
  expect(releaseSlow === null, "runners: no second periodic read while one is in flight");
  rFirstRelease(); await rSlowRead; await rNextTick; await tick(); await tick();
  expect(card("slow-box"), "runners: a slow periodic read still draws once it answers");
  win.Maity.api.getAll = rAll1;
  await fireIntervals(); await tick(); await tick();
  btn(card("home-laptop"), "Remove").click(); await tick(); await tick(); await tick();
  expect(!card("home-laptop") && text(main).includes("home-laptop was removed.") && text(main).includes("Agent B · running")
    && text(main).includes("maity runner stop-all"), "runners: removed, with the agents still running that are now the operator's to end");
  win.Maity.api.post = rPost; win.Maity.api.patch = rPatch; win.Maity.api.del = rDel;
  const realAll2 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/runners" || p === "/runners/enrollments" ? Promise.resolve({ items: [], next_cursor: null }) : realAll2(p));
  await go("#/all"); await go("#/runners"); await tick();
  expect(text(main).includes("No runner yet. A runner is a small service on your machine that starts agents for you.") && byId("pair-name"),
    "runners: the empty state, with the pairing form");
  win.Maity.api.getAll = realAll2;
  // Leaving a view: until the next one is drawn, the old one stays on screen but takes no
  // click (inert), so an action there cannot be answered into a view that is gone.
  const lvGet = win.Maity.api.get;
  let lvRelease = null;
  win.Maity.api.get = (p) => (p === "/auth/session" && !lvRelease ? new Promise((resolve) => { lvRelease = () => resolve(lvGet(p)); }) : lvGet(p));
  const lvOld = main.querySelector("section.view-runners");
  win.location.hash = "#/all"; win.onhashchange(); await tick();
  expect(lvOld && lvOld.parentNode === main && lvOld.getAttribute("inert") === "", "navigation: the view being left stays shown but is inert until the next is drawn");
  win.Maity.api.get = lvGet;
  lvRelease(); for (let k = 0; k < 6; k++) await tick();
  const lvNew = main.querySelector("section.view-all");
  expect(lvNew && lvNew.getAttribute("inert") === undefined && !main.querySelector("section.view-runners"), "navigation: the view drawn next takes clicks again");
  await go("#/maintainer/maity/inbox");

  // Trust × role (docs/api.md §2.3, tsk-tx9qcehevfnk): an owner is offered every trust for a human, never owner for an agent,
  // and the role proxy only with trust admin; trust and role go out on their own.
  const trPatch = win.Maity.api.patch, trGet = win.Maity.api.get, trAll = win.Maity.api.getAll;
  const trSent = [];
  win.Maity.api.patch = (p, b) => { trSent.push([p, b]); return trPatch(p, b); };
  const trOpts = (el) => el.querySelectorAll("option").map((o) => o.getAttribute("value")).join();
  await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("agt-d");
  expect(trOpts(byId("member-trust-agt-d")) === "admin,member,guest" && !trOpts(byId("member-role-agt-d")).split(",").includes("proxy"),
    "trust: an owner offers an agent admin, member and guest, and no proxy while its trust is member");
  byId("member-trust-agt-d").value = "admin"; byId("member-trust-agt-d").dispatch("change");
  expect(trOpts(byId("member-role-agt-d")).split(",").includes("proxy"), "trust: with trust admin the owner may make it a proxy");
  byId("member-trust-agt-d").value = "guest"; byId("member-trust-agt-d").dispatch("change");
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(trSent[0]) === JSON.stringify(["/projects/maintainer/maity/members/agt-d", { trust: "guest" }]) && text(main.querySelectorAll("tr.member").find((tr) => tr.getAttribute("data-member") === "agt-d")).includes("guest · coder"),
    "trust: a changed trust goes out alone, and the row says trust and role");
  await trPatch("/projects/maintainer/maity/members/agt-d", { trust: "member" });
  // A guest is never a target (§2.3): not offered as whom another member reports to.
  const trGuest = (r) => Object.assign({}, r, { items: r.items.map((m) => (m.id === "agt-c" ? Object.assign({}, m, { trust: "guest" }) : m)) });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? trAll(p).then(trGuest) : trAll(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? trGet(p).then(trGuest) : trGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("agt-d");
  expect(!trOpts(byId("member-reports-agt-d")).split(",").includes("agt-c") && trOpts(byId("member-reports-agt-d")).split(",").includes("agt-a"),
    "trust: a guest is not offered as whom a member reports to");
  win.Maity.api.getAll = trAll; win.Maity.api.get = trGet;
  // An admin who is no owner (owner_only): neither trust owner or admin nor the role proxy is offered.
  win.Maity.api.get = (p) => (p === "/me" ? trGet(p).then((m) => { m.projects.find((x) => x.slug === "maity").trust = "admin"; return m; }) : trGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("agt-d");
  expect(trOpts(byId("member-trust-agt-d")) === "member,guest" && !trOpts(byId("member-role-agt-d")).split(",").includes("proxy")
    && trOpts(byId("invite-trust")) === "member,guest",
    "trust: an admin who is no owner is offered neither owner, admin nor proxy, here or for an invitation");
  // An owner's row offers a non-owner no removal (owner_only, §2.3).
  await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("hum-maintainer");
  expect(main.querySelector("tr.member-manage") && !btn(main.querySelector("tr.member-manage"), "Remove from the project"),
    "trust: an admin who is no owner is offered no removal of an owner");
  win.Maity.api.get = trGet;
  // A proxy holds trust admin only: its trust changed, its role becomes coder; and it never governs (§2.3).
  const trProxy = (r) => Object.assign({}, r, { items: r.items.map((m) => (m.id === "agt-d" ? Object.assign({}, m, { trust: "admin", role: "proxy" }) : m)) });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? trAll(p).then(trProxy) : trAll(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? trGet(p).then(trProxy) : trGet(p));
  trSent.length = 0;
  win.Maity.api.patch = (p, b) => { trSent.push([p, b]); return Promise.resolve({}); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("agt-d");
  expect(byId("member-role-agt-d").value === "proxy", "trust: a proxy's row shows its role");
  byId("member-trust-agt-d").value = "member"; byId("member-trust-agt-d").dispatch("change");
  expect(byId("member-role-agt-d").value === "coder" && !trOpts(byId("member-role-agt-d")).split(",").includes("proxy"),
    "trust: a proxy whose trust is no longer admin becomes a coder, proxy no longer offered");
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(trSent[0] && trSent[0][1]) === JSON.stringify({ trust: "member", role: "coder" }), "trust: both go out together, as the hub requires");
  win.Maity.api.getAll = trAll; win.Maity.api.get = trGet; win.Maity.api.patch = trPatch;
  expect(!win.Maity.trust.governs({ trust: "admin", role: "proxy" }) && !win.Maity.trust.reviews({ trust: "admin", role: "proxy" })
    && win.Maity.trust.governs({ trust: "admin", role: "reviewer" }) && !win.Maity.trust.reviews({ trust: "guest", role: "reviewer" }),
    "trust: a proxy never governs; an admin reviewer does; a guest reviewer reviews nothing");
  // A guest creates no group chat (§9.2).
  win.Maity.api.get = (p) => (p === "/me" ? trGet(p).then((m) => { m.projects.find((x) => x.slug === "maity").trust = "guest"; return m; }) : trGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".chat-list-pane") && !main.querySelector("a.new-group"), "trust: a guest is offered no new group chat");
  win.Maity.api.get = trGet; win.Maity.api.patch = trPatch;
  await go("#/maintainer/maity/inbox");

  // Why: the Keep the Why export (docs/api.md §11.3), from the published maity.dev family.
  const whyTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Why");
  expect(whyTab() && whyTab().getAttribute("href") === "#/maintainer/maity/why", "why: a tab where the hub has the export");
  const whyGets = [];
  const realGet6 = win.Maity.api.get;
  win.Maity.api.get = (p) => { whyGets.push(p); return realGet6(p); };
  await go("#/maintainer/maity/why");
  expect(plainTitle() === "Why · Maity · Maity" && text(main).includes("1 entry needs attention · 71 entries in 4 parts of the project")
    && text(main).includes("Linter: 0 errors, 0 warnings."), "why: the family's summary");
  const rows = main.querySelectorAll(".why-members tbody tr");
  expect(rows.length === 4 && rows[0].textContent.startsWith("the project root") && rows[1].textContent.startsWith("hub · hub/")
    && rows[1].querySelector("a").getAttribute("href") === "https://maity.dev/keep-the-why-dashboard/hub/", "why: one row per part, linking to its dashboard");
  const entryLink = main.querySelectorAll(".why-entries a").find((a) => a.textContent === "Platforms changed underneath the build");
  expect(entryLink && entryLink.getAttribute("href") === "https://maity.dev/keep-the-why-dashboard/#entry/f3bec014-28b7-4bfe-9ca8-304f1481fceb"
    && text(main.querySelector(".why-group")).includes("open") && text(main).includes("Incidents of the build · incident"),
    "why: the entry that needs attention, grouped by part, linking into the published dashboard");
  btn(main, "Read again").click(); await tick(); await tick();
  expect(whyGets.includes("/projects/maintainer/maity/keep-the-why?max_age=0"), "why: Read again asks for a fresh read");
  // A member that fails, a root that cannot be read, strings and links from the export.
  const baseAnswer = await realGet6("/projects/maintainer/maity/keep-the-why");
  const withFailed = JSON.parse(JSON.stringify(baseAnswer));
  withFailed.members[3].error = { code: "ktw_unavailable", reason: "timeout" };
  withFailed.summary.failed = 1;
  withFailed.attention.push({ member: "web", id: "x", uuid: null, title: "<b>not markup</b>", type: ["question"], status: "needs-review",
    file: "views.md", topic: null, link: "javascript:alert(1)" });
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why") ? Promise.resolve(withFailed) : realGet6(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/why");
  const webRow = main.querySelectorAll(".why-members tbody tr")[3];
  expect(webRow.className === "failed" && text(webRow).includes("Could not be read: its state.json did not answer in time. Shown is its last good read.")
    && text(main).includes("· 1 could not be read"), "why: a part that fails is named with its reason and its last good read");
  const odd = main.querySelectorAll(".why-entries li").find((li) => li.textContent.includes("<b>not markup</b>"));
  expect(odd && !odd.querySelector("a") && !odd.querySelector("b"), "why: an export's strings are text, a link that is not https is none");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why")
    ? Promise.reject(new win.Maity.api.ApiError("root unreadable", 503, p, "ktw_unavailable", { reason: "forge_unavailable", last: Object.assign({}, baseAnswer, { fresh: false }) }))
    : realGet6(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/why");
  expect(text(main).includes("The hub could not read the project's root .keep-the-why just now (the forge did not give the hub the repository's root .keep-the-why). Shown is its last good read")
    && main.querySelectorAll(".why-members tbody tr").length === 4, "why: the root unreadable, the last good read is shown and said so");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why")
    ? Promise.reject(new win.Maity.api.ApiError("root unreadable", 503, p, "ktw_unavailable", { reason: "forge_unavailable" })) : realGet6(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/why");
  expect(text(main).includes("could not read the project's root .keep-the-why") && !main.querySelector(".why-members") && btn(main, "Read again"),
    "why: no last read, only the note, and Read again");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why") ? Promise.reject(new win.Maity.api.ApiError("boom", 500, p, "internal")) : realGet6(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/why");
  expect(main.querySelector(".error") && btn(main, "Read again"), "why: any other error, with Read again");
  // Read again is off while its read runs.
  let release;
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why?max_age=0") ? new Promise((r) => { release = () => r(baseAnswer); }) : realGet6(p));
  const again = btn(main, "Read again"); again.click(); await tick();
  expect(again.disabled === true, "why: Read again is disabled while a read runs");
  release(); await tick(); await tick();
  expect(btn(main, "Read again") && !btn(main, "Read again").disabled, "why: and on again after it");
  // Linter counts per field; an entry link outside its part's dashboard is no link.
  const odd2 = JSON.parse(JSON.stringify(baseAnswer));
  odd2.members[1].summary.findings = { errors: 2, warnings: null };
  odd2.attention.push({ member: "hub", id: "y", uuid: "u", title: "Elsewhere", type: [], status: "open", file: "a.md", topic: null,
    link: "https://maity.dev/keep-the-why-dashboard/#entry/u" });
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/keep-the-why") ? Promise.resolve(odd2) : realGet6(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/why");
  expect(text(main.querySelectorAll(".why-members tbody tr")[1]).includes("2 errors, — warnings"), "why: a missing linter count is shown as such, per field");
  const elsewhere = main.querySelectorAll(".why-entries li").find((li) => li.textContent.includes("Elsewhere"));
  expect(elsewhere && !elsewhere.querySelector("a"), "why: an entry link that leaves its part's dashboard is no link");
  win.Maity.api.get = realGet6;
  await go("#/maintainer/sample/why");
  expect(text(main).includes("This project publishes no Keep the Why dashboard yet.") && text(main).includes("dashboard-state line") && btn(main, "Read again"),
    "why: not configured, said so with what the hub reads");
  // A hub that does not know the export: no tab.
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? realGet6(p).then((v) => { delete v.keep_the_why_export; return v; }) : realGet6(p));
  await go("#/maintainer/maity/inbox");
  expect(!whyTab(), "why: no tab where the hub has no export field");
  win.Maity.api.get = realGet6;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 4; k++) await tick();
  const tree = main.querySelector(".org-tree");
  expect(tree.childNodes.length === 1 && text(tree).includes("(by area)") && text(main).includes("Policy: hierarchical"), "org tree by areas, policy preset, in the Overview");

  // Presence is re-read in place in Members; an open row's form is kept.
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const realGet3 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members"
    ? realGet3(p).then((r) => { r.items.forEach((m) => { m.presence = "away"; }); return r; })
    : realGet3(p));
  main.querySelectorAll(".members-agents tr.member")[0].querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click(); for (let k = 0; k < 4; k++) await tick();
  const pauseBefore = main.querySelector("form.member-pause");
  await fireIntervals(); await tick(); await tick();
  const labels = main.querySelectorAll("tr.member").map((tr) => tr.childNodes.find((td) => td.attrs && td.attrs["data-label"] === "Presence")).filter(Boolean);
  expect(labels.length > 0 && labels.every((td) => text(td).startsWith(" Away") || text(td).startsWith("Away")), "presence re-read in place");
  expect(main.querySelector("form.member-pause") === pauseBefore, "the presence refresh keeps the forms");
  win.Maity.api.getAll = realGet3;

  // Avatars: generated from the member id, the same on every client.
  const AV = win.Maity.avatar;
  expect(JSON.stringify(AV.cells("agt-a")) === '[[0,0],[4,0],[2,0],[1,1],[3,1],[0,2],[4,2],[1,2],[3,2],[2,2],[0,3],[4,3],[2,3],[0,4],[4,4]]'
    && AV.hueOf("agt-a") === 340 && AV.hueOf("agt-b") === 153, "avatars: a fixed id gives a fixed picture (FNV-1a), on every client");
  const mirrored = (id) => AV.cells(id).every(([c, r]) => AV.cells(id).some(([c2, r2]) => c2 === 4 - c && r2 === r));
  expect(["agt-a", "agt-b", "hum-maintainer", "", "?", "\u{1F642}"].every((id) => mirrored(id) && AV.cells(id).length > 0 && AV.hueOf(id) >= 0 && AV.hueOf(id) < 360)
    && JSON.stringify(AV.cells("agt-a")) !== JSON.stringify(AV.cells("agt-b")), "avatars: mirrored, never empty, different ids differ");
  const pic = AV({ id: "agt-a" }, 28);
  expect(pic.tagName === "SVG" && pic.attrs["aria-hidden"] === "true" && pic.attrs.width === "28" && pic.style["--avatar-h"] === "340"
    && pic.querySelectorAll("rect").length === 16, "avatars: an SVG of nodes, decorative, its hue as a custom property");
  expect(AV({ id: "agt-a", avatar_url: "https://evil.example/x.png" }).tagName === "SVG", "avatars: a picture the page may not load falls back to the generated one");
  expect(AV({ id: "agt-a", avatar_url: "/api/v1/projects/maintainer/maity/logo?v=1" }).tagName === "IMG", "avatars: a picture the page may load wins");
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const avA = main.querySelectorAll("tr.member").find((tr) => tr.attrs["data-member"] === "agt-a");
  expect(avA && avA.querySelector("svg") && avA.querySelector("svg").style["--avatar-h"] === "340", "avatars: in the agent's row on Members");
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".org-node svg").length === main.querySelectorAll(".org-node").length, "avatars: in the organisation, one per member");
  // Managing cards on the board (docs/api.md §6.4).
  const T = win.Maity.boardEdit.targets;
  const bctx = { me: { id: "hum-maintainer" }, trust: "owner", role: "coder", project: { policy: { done_authority: "reviewer" } } };
  const tc = (status, extra) => Object.assign({ id: "x", status, created_by: "agt-a", claim: null }, extra || {});
  expect(JSON.stringify(T(bctx, tc("proposed"))) === JSON.stringify(["open", "cancelled"])
    && JSON.stringify(T(bctx, tc("review"))) === JSON.stringify(["done", "in_progress", "cancelled"])
    && JSON.stringify(T(bctx, tc("in_progress"))) === JSON.stringify(["cancelled"]) && !T(bctx, tc("done")).length,
    "board: an owner's moves, as the hub allows them");
  const mctx = Object.assign({}, bctx, { trust: "member", role: "coder" });
  expect(!T(mctx, tc("proposed")).length && JSON.stringify(T(mctx, tc("open", { created_by: "hum-maintainer" }))) === JSON.stringify(["proposed", "cancelled"])
    && !T(mctx, tc("review")).length && JSON.stringify(T(Object.assign({}, mctx, { trust: "member", role: "reviewer" }), tc("review"))) === JSON.stringify(["done", "in_progress"]),
    "board: a member moves only its own cards; a reviewer has done authority");
  expect(JSON.stringify(T(Object.assign({}, mctx, { project: { policy: { done_authority: "holder" } } }), tc("in_progress", { claim: { holder: "hum-maintainer" } }))) === JSON.stringify(["done"]),
    "board: with holder authority the holder moves its card to done");
  const bWrites = [];
  const bPatch = win.Maity.api.patch, bPost = win.Maity.api.post;
  win.Maity.api.patch = (p, b) => { bWrites.push(["PATCH", p, b]); return bPatch(p, b); };
  win.Maity.api.post = (p, b) => { bWrites.push(["POST", p, b]); return bPost(p, b); };
  await go("#/maintainer/maity/board");
  const bCard = (id) => main.querySelectorAll("article.card").find((a) => a.attrs["data-card"] === id);
  const colOf = (id) => main.querySelectorAll("section.column").find((col) => col.querySelectorAll("article.card").some((a) => a.attrs["data-card"] === id));
  // The card's controls: the column and the assignee as menus, Place as four arrows (docs/api.md §6.4).
  const bMenu = (id, cls) => bCard(id).querySelector("." + cls + " .menu-button");
  const bPick = async (id, cls, label) => {
    bMenu(id, cls).click(); await tick();
    const item = bCard(id).querySelectorAll("." + cls + " .menu-item").find((b) => text(b).trim() === label);
    if (!item) throw new Error("no menu item " + label + " in " + id + ": " + bCard(id).querySelectorAll("." + cls + " .menu-item").map((b) => text(b)).join("|"));
    item.click(); for (let k = 0; k < 4; k++) await tick();
  };
  const bArrow = (id, way) => bCard(id).querySelector(".card-order .place-" + way);
  expect(bCard("tsk-0008").attrs.draggable === "true" && !bCard("tsk-0003").attrs.draggable && !bCard("tsk-0003").querySelector(".card-move"),
    "board: a card that may move is draggable and has a status menu; a closed one has neither");
  expect(!main.querySelector("article.card select") && main.querySelectorAll("article.card .card-actions").every((row) => row.querySelectorAll("form").length === 0),
    "board: no card carries a select-and-button form any more");
  // The header names whose card it is; the claim line leads with its state as a dot; a checkpoint is two lines.
  const bWho = bCard("tsk-0006").querySelector("header .card-assignee");
  expect(bWho && text(bWho).includes("@agent-c") && bWho.getAttribute("href") === "#/maintainer/maity/members/agt-c" && bWho.getAttribute("title") === "Agent C" && bWho.getAttribute("aria-label") === "Assigned to Agent C"
    && bWho.classList.contains("kind-agent") && !bCard("tsk-0008").querySelector(".card-assignee"),
    "board: the assignee sits in the card's header as @handle, the full name as tooltip and name; none when unassigned");
  const bClaim = (id) => bCard(id).querySelector("p.claim");
  expect(bClaim("tsk-0001").classList.contains("live") && bClaim("tsk-0001").querySelector(".claim-dot.live") && text(bClaim("tsk-0001")).includes("Claimed by @agent-a")
    && bClaim("tsk-0007").classList.contains("expired") && text(bClaim("tsk-0007")).includes("lease expired")
    && bClaim("tsk-0006").querySelector(".claim-dot.none") && text(bClaim("tsk-0006")).includes("Assigned, not claimed"),
    "board: the claim line: live, expired, or not claimed, each led by its dot");
  const bCp = bCard("tsk-0004").querySelector(".checkpoint .clamp");
  expect(bCp && bCp.getAttribute("title").replace(/\s+/g, " ") === text(bCp).trim() && text(bCp).startsWith("Done: "), "board: a checkpoint is clamped, its whole text the tooltip");
  const bProto = Object.getPrototypeOf(main);
  const bFocus = bProto.focus;
  bProto.focus = function () { document.activeElement = this; };
  expect(text(bMenu("tsk-0008", "card-move")).startsWith("Proposed") && bMenu("tsk-0008", "card-move").getAttribute("aria-haspopup") === "menu",
    "board: the status menu shows the card's column");
  bMenu("tsk-0008", "card-move").click(); await tick();
  expect(JSON.stringify(bCard("tsk-0008").querySelectorAll(".card-move .menu-item").map((b) => text(b).trim())) === JSON.stringify(["Move to Open", "Move to Cancelled"]),
    "board: it offers the allowed columns");
  bMenu("tsk-0008", "card-move").click(); await tick();
  await bPick("tsk-0008", "card-move", "Move to Open");
  expect(JSON.stringify(bWrites[0]) === JSON.stringify(["PATCH", "/projects/maintainer/maity/tasks/tsk-0008", { status: "open" }])
    && colOf("tsk-0008").attrs["data-status"] === "open" && text(main).includes("tsk-0008 is now open."), "board: moved with the menu");
  expect(document.activeElement && document.activeElement.getAttribute("data-focus") === "move:tsk-0008", "board: the focus stays on the moved card's menu");
  bProto.focus = bFocus; document.activeElement = undefined;
  // Dragging: allowed columns marked, the others refused; a refused drop sends nothing.
  bCard("tsk-0008").dispatch("dragstart", { dataTransfer: null });
  const colEl = (st) => main.querySelectorAll("section.column").find((col) => col.attrs["data-status"] === st);
  expect(colEl("proposed").classList.contains("drop-ok") && colEl("cancelled").classList.contains("drop-ok")
    && colEl("done").classList.contains("drop-refused") && !colEl("open").classList.contains("drop-refused"), "board: while dragging, the allowed columns are marked, the others refused");
  colEl("done").dispatch("dragover"); bCard("tsk-0008").dispatch("dragend"); await tick();
  expect(bWrites.length === 1 && text(main).includes("Not moved: tsk-0008 cannot go to Done.") && !colEl("done").classList.contains("drop-refused"),
    "board: a drop on a refused column is said, nothing sent");
  bCard("tsk-0008").dispatch("dragstart", { dataTransfer: null });
  colEl("proposed").dispatch("drop"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[1]) === JSON.stringify(["PATCH", "/projects/maintainer/maity/tasks/tsk-0008", { status: "proposed" }]) && colOf("tsk-0008").attrs["data-status"] === "proposed",
    "board: dropped on an allowed column, moved");
  // The hub's refusal, in words.
  win.Maity.api.patch = (p) => Promise.reject(new win.Maity.api.ApiError("no", 409, p, "dependencies_open", { open: ["tsk-0001"] }));
  bProto.focus = function () { document.activeElement = this; };
  await bPick("tsk-0005", "card-move", "Move to Done");
  expect(text(main).includes("Moving failed: Not done yet: a card it depends on is still open."), "board: the hub's refusal is said in words");
  expect(document.activeElement && document.activeElement === bMenu("tsk-0005", "card-move") && bCard("tsk-0005").querySelector(".card-move .menu").hidden,
    "board: after a refused move the focus is back on the card's status menu button, the menu closed");
  bProto.focus = bFocus; document.activeElement = undefined;
  win.Maity.api.patch = (p, b) => { bWrites.push(["PATCH", p, b]); return bPatch(p, b); };
  // Assign, and the live lease refused.
  await bPick("tsk-0006", "card-assign", "@agent-d");
  expect(JSON.stringify(bWrites[bWrites.length - 1]) === JSON.stringify(["POST", "/projects/maintainer/maity/tasks/tsk-0006/assign", { assignee: "agt-d" }])
    && text(main).includes("tsk-0006 is assigned to Agent D."), "board: assigned");
  await bPick("tsk-0001", "card-assign", "@agent-b");
  expect(text(main).includes("Assigning failed: It is claimed with a live lease"), "board: a live lease is not taken over, said in words");
  // Order within a column (docs/api.md §6.4): by rank, then created_at, then id.
  const colIds = (st) => colEl(st).querySelectorAll("article.card").map((a) => a.attrs["data-card"]);
  expect(JSON.stringify(colIds("in_progress")) === JSON.stringify(["tsk-0009", "tsk-0001", "tsk-0007"]), "board: a column in the hub's order, a ranked card first " + JSON.stringify(colIds("in_progress")));
  const enabled = (id) => ["top", "up", "down", "bottom"].filter((w) => bArrow(id, w).attrs.disabled === undefined);
  expect(JSON.stringify(enabled("tsk-0009")) === JSON.stringify(["down", "bottom"]) && JSON.stringify(enabled("tsk-0001")) === JSON.stringify(["top", "up", "down", "bottom"])
    && JSON.stringify(enabled("tsk-0007")) === JSON.stringify(["top", "up"]),
    "board: Place offers the moves the card's place allows; the others are disabled");
  expect(bCard("tsk-0009").querySelector(".card-order").getAttribute("role") === "group" && bCard("tsk-0009").querySelector(".card-order").getAttribute("aria-label") === "Place in column"
    && JSON.stringify(["top", "up", "down", "bottom"].map((w) => bArrow("tsk-0009", w).getAttribute("aria-label"))) === JSON.stringify(["Move to top", "Move up", "Move down", "Move to bottom"]),
    "board: the arrows are a named group, each with its own name");
  expect(!main.querySelectorAll("section.column").find((col) => col.attrs["data-status"] === "done").querySelector(".card-order"), "board: closed cards keep their order");
  bProto.focus = function () { document.activeElement = this; };
  const ordBefore = bWrites.length;
  bArrow("tsk-0009", "down").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[ordBefore]) === JSON.stringify(["POST", "/projects/maintainer/maity/tasks/tsk-0009/move", { after: "tsk-0001" }])
    && JSON.stringify(colIds("in_progress")) === JSON.stringify(["tsk-0001", "tsk-0009", "tsk-0007"]) && text(main).includes("tsk-0009 is now below tsk-0001."),
    "board: Move down places the card below its neighbour, once the hub answered");
  expect(document.activeElement && document.activeElement.getAttribute("data-focus") === "order:tsk-0009:down", "board: the focus stays on the placed card's arrow");
  bArrow("tsk-0007", "top").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[bWrites.length - 1][2]) === JSON.stringify({ to: "top" }) && JSON.stringify(colIds("in_progress")) === JSON.stringify(["tsk-0007", "tsk-0001", "tsk-0009"]),
    "board: Move to top");
  expect(document.activeElement && /^order:tsk-0007:(down|bottom)$/.test(document.activeElement.getAttribute("data-focus") || ""),
    "board: at the top its Move to top is disabled, so the focus goes to an arrow that still works " + (document.activeElement && document.activeElement.getAttribute("data-focus")));
  bProto.focus = bFocus; document.activeElement = undefined;
  // Dragging within the column: above or below the card it is let go over.
  bCard("tsk-0009").dispatch("dragstart", { dataTransfer: null });
  expect(colEl("in_progress").classList.contains("drop-ok"), "board: its own column takes it while dragging");
  const overCard = bCard("tsk-0007").querySelector(".card-id");
  colEl("in_progress").dispatch("dragover", { target: overCard });
  expect(bCard("tsk-0007").classList.contains("drop-before"), "board: the spot above the card is marked");
  colEl("in_progress").dispatch("drop", { target: overCard }); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[bWrites.length - 1]) === JSON.stringify(["POST", "/projects/maintainer/maity/tasks/tsk-0009/move", { before: "tsk-0007" }])
    && JSON.stringify(colIds("in_progress")) === JSON.stringify(["tsk-0009", "tsk-0007", "tsk-0001"]) && !main.querySelector("article.drop-before"),
    "board: dropped over a card's upper half, placed above it");
  bCard("tsk-0009").dispatch("dragstart", { dataTransfer: null });
  const lower = bCard("tsk-0001");
  lower.getBoundingClientRect = () => ({ top: 0, height: 100 });
  colEl("in_progress").dispatch("drop", { target: lower, clientY: 80 }); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[bWrites.length - 1][2]) === JSON.stringify({ after: "tsk-0001" }) && colIds("in_progress")[2] === "tsk-0009",
    "board: dropped over a card's lower half, placed below it");
  // A neighbour that moved meanwhile: the board is read again and says so.
  win.Maity.api.post = (p, b) => Promise.reject(new win.Maity.api.ApiError("gone", 400, p, "invalid", {}));
  bArrow("tsk-0007", "down").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Reordering failed: the card next to it moved or changed meanwhile; the board shows the order as it is now."),
    "board: a stale neighbour re-reads the board and says so");
  // A not_found while card and neighbour are still in place: a hub without the endpoint.
  win.Maity.api.post = (p, b) => Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {}));
  bArrow("tsk-0007", "down").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Reordering failed: this hub does not order cards yet."), "board: a hub without the move endpoint is said as such");
  win.Maity.api.post = (p, b) => { bWrites.push(["POST", p, b]); return bPost(p, b); };
  // The mock as the hub: a neighbour in another column is invalid; a member may not order.
  let otherCol = null;
  try { await bPost("/projects/maintainer/maity/tasks/tsk-0001/move", { before: "tsk-0006" }); } catch (err) { otherCol = err; }
  expect(otherCol && otherCol.code === "invalid", "board: the mock refuses a neighbour from another column");

  // Filters by member and area.
  const fm = byId("board-member"); fm.value = "agt-b"; fm.dispatch("change");
  const visibleIds = () => main.querySelectorAll("article.card").map((a) => a.attrs["data-card"]).sort();
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0004", "tsk-0005"]), "board: filtered by member " + JSON.stringify(visibleIds()));
  fm.value = ""; fm.dispatch("change"); const fa = byId("board-area"); fa.value = "cli/"; fa.dispatch("change");
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0006"]), "board: filtered by area");
  fa.value = "web/"; fa.dispatch("change"); fm.value = "agt-b"; fm.dispatch("change");
  expect(!visibleIds().length && text(main).includes("No card matches the filter."), "board: no match, said");
  fm.value = ""; fm.dispatch("change"); fa.value = ""; fa.dispatch("change");
  // Search filters immediately; the hub adds notes/reports and older closed cards.
  const searchInput = byId("board-search");
  const beforeSearch = visibleIds();
  searchInput.value = "ＴＳＫ－０００６"; searchInput.dispatch("input");
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0006"]), "board search: immediate NFKC filter");
  const savedGetAll = win.Maity.api.getAll;
  const searchCalls = [];
  let finishSearch;
  win.Maity.api.getAll = async (path) => {
    searchCalls.push(path);
    if (path.includes("q=delayed")) return new Promise((resolve) => { finishSearch = resolve; });
    return { items: [{ id: "tsk-old", title: "An old card", body: "", kind: "task", status: "done",
      match: ["note"], depends_on: [], ships_with: [] }], next_cursor: null };
  };
  searchInput.value = "note-only"; searchInput.dispatch("input");
  main.querySelector("form.board-filter").dispatch("submit"); await tick();
  expect(searchCalls[0].includes("status=all&q=note-only") && !searchCalls[0].includes("closed_after"), "board search: full history query");
  expect(visibleIds().includes("tsk-old") && text(main).includes("Matched: note")
    && text(main).includes("Closed · outside board window"), "board search: remote note match and old closed marker");
  searchInput.value = "delayed"; searchInput.dispatch("input");
  main.querySelector("form.board-filter").dispatch("submit"); await tick();
  btn(main, "Clear search").click();
  finishSearch({ items: [], next_cursor: null }); await tick();
  expect(JSON.stringify(visibleIds()) === JSON.stringify(beforeSearch), "board search: clear restores and ignores late response");
  win.Maity.api.getAll = async () => { throw new Error("offline"); };
  searchInput.value = "tsk-0006"; searchInput.dispatch("input");
  main.querySelector("form.board-filter").dispatch("submit"); await tick();
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0006"]) && text(main).includes("Search failed: offline"),
    "board search: failure keeps local matches and reports error");
  searchInput.value = "x".repeat(201); searchInput.dispatch("input");
  main.querySelector("form.board-filter").dispatch("submit"); await tick();
  expect(text(main).includes("Search must be at most 200 characters."), "board search: overlong query refused locally");
  btn(main, "Clear search").click();
  win.Maity.api.getAll = savedGetAll;
  const fixtureSearch = await savedGetAll("/projects/maintainer/maity/tasks?status=all&q=" + encodeURIComponent("ＴＳＫ－０００６"));
  expect(fixtureSearch.items.length === 1 && fixtureSearch.items[0].id === "tsk-0006"
    && fixtureSearch.items[0].match.includes("id"), "board search: fixture query uses Unicode matching");
  // A new card.
  btn(main, "New card").click(); await tick();
  const nf = main.querySelector("form.new-card");
  const shipIds = byId("new-card-ships").querySelectorAll("option").map((o) => o.attrs.value);
  const depIds = byId("new-card-depends").querySelectorAll("option").map((o) => o.attrs.value);
  expect(!shipIds.includes("rel-0001") && depIds.includes("rel-0001"), "board: a release is never offered to ship with; it may be depended on");
  expect(nf && btn(main, "New card").getAttribute("aria-expanded") === "true" && byId("new-card-assigned"), "board: New card opens the form; an admin may assign");
  nf.dispatch("submit"); await tick();
  expect(!bWrites.some((w) => w[1] === "/projects/maintainer/maity/tasks") && text(main).includes("Not created: the card needs a title"), "board: no card without a title");
  byId("new-card-title").value = "Web: a card from the board";
  byId("new-card-area").value = "web/board/";
  byId("new-card-status").value = "open";
  byId("new-card-label").value = "feature";
  byId("new-card-assigned").value = "agt-d";
  byId("new-card-depends").querySelectorAll("option").find((o) => o.attrs.value === "tsk-0007").selected = true;
  nf.dispatch("submit"); for (let k = 0; k < 5; k++) await tick();
  const createdW = bWrites.find((w) => w[1] === "/projects/maintainer/maity/tasks");
  expect(JSON.stringify(createdW) === JSON.stringify(["POST", "/projects/maintainer/maity/tasks", { title: "Web: a card from the board", kind: "task", status: "open",
    label: "feature", area: "web/board/", assigned_to: "agt-d", depends_on: ["tsk-0007"] }]) && colOf("tsk-f001") && colOf("tsk-f001").attrs["data-status"] === "open"
    && !main.querySelector("form.new-card"), "board: a new card, created in Open");
  expect(byId("board-area").querySelectorAll("option").some((o) => o.attrs.value === "web/board/"), "board: the area filter offers a new card's area");
  // Cancel the new card again with the menu; its menu goes, so the focus goes to what was said.
  const bProto2 = Object.getPrototypeOf(main);
  const bFocus2 = bProto2.focus;
  bProto2.focus = function () { document.activeElement = this; };
  await bPick("tsk-f001", "card-move", "Move to Cancelled");
  expect(colOf("tsk-f001").attrs["data-status"] === "cancelled" && !bCard("tsk-f001").querySelector(".card-move")
    && document.activeElement && document.activeElement.className.includes("send-status") && text(document.activeElement).includes("tsk-f001 is now cancelled."),
    "board: cancelled with the menu; the focus goes to the status line");
  bProto2.focus = bFocus2; document.activeElement = undefined;
  let relShip = null;
  try { await bPost("/projects/maintainer/maity/tasks", { title: "x", ships_with: ["rel-0001"] }); } catch (err) { relShip = err; }
  expect(relShip && relShip.details.fields.ships_with === "release_card", "board: the mock refuses shipping with a release, as the hub does");
  win.Maity.api.patch = bPatch; win.Maity.api.post = bPost;
  // A project in review asks for a reason.
  await go("#/maintainer/sample/board");
  btn(main, "New card").click(); await tick();
  byId("new-card-title").value = "Something during the review";
  main.querySelector("form.new-card").dispatch("submit"); await tick();
  expect(byId("new-card-reason") && text(main).includes("Not created: the project is in review"), "board: in review a new card needs a reason");
  // The released mark (§6.1): beside the state in the header, on the overview and in Project settings; none where unset.
  const relMark = () => header.querySelector(".project-state .released");
  expect(relMark() && text(relMark()) === "Released" && relMark().getAttribute("title").startsWith("Released since ")
    && relMark().getAttribute("title").includes("migrations stay backward compatible"), "released: the header marks a released project, the rules in its title");
  await go("#/maintainer/sample/overview"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".overview .released") && main.querySelector(".overview .state-review"), "released: the overview shows the state and the mark");
  await projectSettings(); await tick();
  expect(main.querySelector(".released-note") && text(main.querySelector(".released-note")).includes("for good"), "released: Project settings say it is never cleared");
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  expect(!relMark(), "released: no mark on a project that is not released");
  await go("#/maintainer/maity/inbox");
  // Members (docs/api.md §6.2): humans and agents, managed by an admin.
  const membersTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Members");
  expect(membersTab && membersTab.getAttribute("href") === "#/maintainer/maity/members", "members: a tab");
  // The reviewer's one credential, revoked further down (the fixture's has none).
  const rvAll = win.Maity.api.getAll;
  let rvRevoked = null;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members/agt-r/credentials"
    ? Promise.resolve({ items: [{ id: "crd-r-0001", client: "cli", created_at: "2026-10-20T10:00:00Z", resumed_at: "2026-10-20T10:01:00Z",
      last_used_at: "2026-10-27T10:00:00Z", last_used_via: "signed", revoked_at: rvRevoked, revoked_by: rvRevoked ? "hum-maintainer" : null, revoked_reason: null }], next_cursor: null })
    : rvAll(p));
  await go("#/maintainer/maity/members");
  const mRow = (name) => main.querySelectorAll("tr.member").find((tr) => tr.querySelector(".member-name").textContent === name);
  const tables = main.querySelectorAll("table.members");
  expect(plainTitle() === "Members · Maity · Maity" && tables.length === 2 && tables[0].querySelectorAll("tr.member").length === 1
    && tables[1].querySelectorAll("tr.member").length === 5 && text(main).includes("Humans (1)") && text(main).includes("Agents (5)"),
    "members: humans first, then agents");
  const ths = tables[1].querySelector("thead").querySelectorAll("th").map((t) => t.textContent);
  expect(JSON.stringify(ths) === JSON.stringify(["Name", "Trust and role", "Owner", "Presence", "Joined", "Paused", "Keep the Why", "Actions"]),
    "members: an admin's agent columns, with the owner; the credentials are in Manage and on Agents " + JSON.stringify(ths));
  expect(text(mRow("Agent C")).includes("paused itself") && text(mRow("Agent C")).includes("Waiting for the API contract")
    && mRow("Agent C").classList.contains("paused"), "members: a paused agent says by whom and why");
  expect(text(mRow("Agent A")).includes("Maintainer") && !/ active/.test(text(mRow("Agent A"))) && text(mRow("Maintainer")).includes("owner"),
    "members: the owner, no credentials summary in the list");
  // Every entry has a Chat: one's own agent its direct chat, anyone else a group chat with them chosen; oneself none.
  const chatOf = (name) => mRow(name).querySelectorAll("a").find((a) => a.classList.contains("member-chat"));
  expect(chatOf("Agent A") && chatOf("Agent A").getAttribute("href") === "#/maintainer/maity/chat/agt-a" && !chatOf("Maintainer"),
    "members: one's own agent's Chat is its direct chat; oneself has none");
  const chatOther = () => main.querySelectorAll("tr.member").map((tr) => tr.querySelectorAll("a").find((a) => a.classList.contains("member-chat")))
    .find((a) => a && a.getAttribute("href").includes("chat/new?with="));
  // agt-b another owner's here: its row offers a group chat, unless the project is closed or one is a guest.
  const coGet = win.Maity.api.get, coAll = win.Maity.api.getAll;
  const coOther = (r) => Object.assign({}, r, { items: r.items.map((x) => (x.id === "agt-b" ? Object.assign({}, x, { owner_id: "hum-other" }) : x)), next_cursor: null });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? coAll(p).then(coOther) : coAll(p));
  const coGetOther = (p) => (p === "/projects/maintainer/maity/members" ? coGet(p).then(coOther) : coGet(p));
  win.Maity.api.get = coGetOther;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(chatOther() && chatOther().getAttribute("href") === "#/maintainer/maity/chat/new?with=agt-b", "members: another owner's agent's Chat is a new group chat with it chosen");
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? coGet(p).then((x) => Object.assign({}, x, { state: "archived" })) : coGetOther(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(!chatOther() && chatOf("Agent A"), "members: a closed project offers no new group chat from a row, one's own agent's chat stays");
  win.Maity.api.get = (p) => (p === "/me" ? coGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "guest"; return x; }) : coGetOther(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(!chatOther(), "members: a human guest is offered no new group chat from a row");
  win.Maity.api.get = coGet; win.Maity.api.getAll = coAll;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const mWrites = [];
  const mPatch = win.Maity.api.patch, mDel = win.Maity.api.del;
  win.Maity.api.patch = (p, b) => { mWrites.push(["PATCH", p, b]); return mPatch(p, b); };
  win.Maity.api.del = (p) => { mWrites.push(["DELETE", p]); return Promise.resolve({ removed_at: "2026-10-22T10:00:00Z" }); };
  // Focus follows by key: Manage to the opened row's role, Done back to Manage.
  const elProto = Object.getPrototypeOf(main);
  const focus0 = elProto.focus;
  elProto.focus = function () { document.activeElement = this; };
  btn(mRow("Agent D"), "Manage").click(); await tick();
  expect(document.activeElement && document.activeElement.tagName === "SELECT" && document.activeElement.id === "member-role-agt-d",
    "members: Manage moves the focus to the row's role");
  btn(mRow("Agent D"), "Done").click(); await tick();
  expect(document.activeElement === btn(mRow("Agent D"), "Manage"), "members: Done gives the focus back to Manage");
  // Presence is refreshed in place: an open row and its select stay the same elements.
  btn(mRow("Agent D"), "Manage").click(); await tick();
  const openSelect = main.querySelector("tr.member-manage select");
  const pAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => pAll(p).then((r) => (p !== "/projects/maintainer/maity/members" ? r
    : { items: r.items.map((x) => (x.id === "agt-d" ? Object.assign({}, x, { presence: "away" }) : x)), next_cursor: null }));
  await fireIntervals(); await tick(); await tick();
  expect(main.querySelector("tr.member-manage select") === openSelect && text(mRow("Agent D")).includes("Away"), "members: presence refreshed in place, the open row untouched");
  win.Maity.api.getAll = pAll;
  elProto.focus = focus0; document.activeElement = undefined;
  const dManage = main.querySelector("tr.member-manage");
  expect(dManage && btn(mRow("Agent D"), "Done") && btn(mRow("Agent D"), "Done").getAttribute("aria-expanded") === "true", "members: Manage opens the row");
  const dRole = byId("member-role-agt-d"); dRole.value = "reviewer";
  dManage.querySelector("form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[0]) === JSON.stringify(["PATCH", "/projects/maintainer/maity/members/agt-d", { role: "reviewer" }]) && text(mRow("Agent D")).includes("reviewer"),
    "members: the role changed");
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); await tick();
  expect(mWrites.length === 1, "members: no pause without a reason");
  main.querySelector("tr.member-manage form.member-pause input").value = "quota";
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[1][2]) === JSON.stringify({ paused: { reason: "quota" } }) && text(mRow("Agent D")).includes("quota"), "members: an agent paused with a reason");
  btn(main.querySelector("tr.member-manage"), "Clear pause").click(); for (let k = 0; k < 4; k++) await tick();
  byId("member-role-agt-d").value = "coder";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(mRow("Agent D")).includes("quota") && text(mRow("Agent D")).includes("member · coder"), "members: pause cleared, role back");
  btn(mRow("Agent D"), "Done").click(); await tick();
  btn(mRow("Maintainer"), "Manage").click(); await tick();
  const ownerSel = byId("member-trust-hum-maintainer");
  expect(ownerSel.querySelectorAll("option").map((o) => o.attrs.value).join() === "owner,admin,member,guest" && !main.querySelector("tr.member-manage form.member-pause"),
    "members: a human can be owner, has no pause");
  ownerSel.value = "admin";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Saving failed: The project's last owner cannot be demoted or removed.") && text(mRow("Maintainer")).includes("owner"),
    "members: the last owner is not demoted, said in words");
  // §6.25: the project's namespace owner stays an owner, said with where to go instead.
  const noPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => (p === "/projects/maintainer/maity/members/hum-maintainer"
    ? Promise.reject(new win.Maity.api.ApiError("x", 409, p, "namespace_owner", { projects: ["maintainer/maity"] })) : noPatch(p, b));
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Saving failed: the project lives in this person's namespace, or they own the organisation it belongs to, so they stay an owner; transfer the project first"),
    "members: the namespace owner is not demoted, said with the way out");
  win.Maity.api.patch = noPatch;
  btn(mRow("Maintainer"), "Done").click(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  expect(byId("member-trust-agt-r").querySelectorAll("option").every((o) => o.attrs.value !== "owner"), "members: an agent is never offered owner");
  let mAsked = "";
  const mConfirm = win.confirm;
  win.confirm = (q) => { mAsked = q; return true; };
  btn(main.querySelector("tr.member-manage"), "Remove from the project").click(); for (let k = 0; k < 4; k++) await tick();
  win.confirm = mConfirm;
  expect(mAsked === "Remove Reviewer from Maity? Its credentials are revoked and the cards it claimed are released."
    && JSON.stringify(mWrites[mWrites.length - 1]) === JSON.stringify(["DELETE", "/projects/maintainer/maity/members/agt-r"]), "members: removing asks first and says what it does");
  // The full edit (docs/api.md §6.2): reports to, areas, capabilities, briefing, in one PATCH.
  win.Maity.api.patch = mPatch; win.Maity.api.del = mDel;
  const eWrites = [];
  win.Maity.api.patch = (p, b) => { eWrites.push([p, b]); return mPatch(p, b); };
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const eRow = () => main.querySelector("tr.member-manage");
  const eSel = (k) => eRow().querySelectorAll("select").find((x) => (x.id || "").startsWith("member-" + k + "-"));
  const eIn = () => eRow().querySelector("form.member-edit").querySelectorAll("input");
  const submitEdit = async () => { eRow().querySelector("form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick(); };
  expect(eSel("reports").value === "agt-a" && !eSel("reports").querySelectorAll("option").some((o) => o.attrs.value === "agt-r")
    && eSel("reports").querySelectorAll("option")[0].textContent === "nobody", "members: reports to offers nobody and everyone else, set to the current one");
  await submitEdit();
  expect(!eWrites.length && text(main).includes("Nothing changed."), "members: nothing changed, nothing sent");
  // What the Agents page had is in the manage row (tsk-7v2snhk002ak): the briefing, the credentials with Revoke, the pause once.
  for (let k = 0; k < 4; k++) await tick();
  expect(eRow().querySelector(".briefing") && (btn(eRow().querySelector(".briefing"), "Edit briefing") || btn(eRow().querySelector(".briefing"), "Write a briefing")),
    "members: an agent's manage row holds its briefing");
  expect(eRow().querySelector(".member-credentials .credentials") && eRow().querySelectorAll("form.member-pause, .member-pause").length === 1,
    "members: and its credentials, and one pause");
  // Revoked here: the row stays open, its list read again in place, the focus on its heading.
  const rvCreds = () => eRow().querySelector(".member-credentials");
  const rvItem = rvCreds().querySelectorAll("li").find((li) => btn(li, "Revoke"));
  if (rvItem) {
    const rvId = rvItem.querySelector("code").textContent;
    const rvPost = win.Maity.api.post;
    let rvSent = null;
    win.Maity.api.post = (p, b) => (/\/revoke$/.test(p) ? (rvSent = p, rvRevoked = "2026-10-27T11:00:00Z", Promise.resolve({})) : rvPost(p, b));
    const rvProto = Object.getPrototypeOf(rvItem), rvFocus = rvProto.focus;
    rvProto.focus = function () { document.activeElement = this; };
    btn(rvItem, "Revoke").click(); for (let k = 0; k < 6; k++) await tick();
    rvProto.focus = rvFocus;
    win.Maity.api.post = rvPost;
    const rvAfter = eRow() && rvCreds().querySelectorAll("li").find((li) => li.querySelector("code").textContent === rvId);
    expect(rvSent && rvSent.endsWith("/credentials/" + rvId + "/revoke") && rvAfter && rvAfter.className.includes("revoked") && !btn(rvAfter, "Revoke")
      && document.activeElement === rvCreds().querySelector(".credentials-title"), "members: a credential revoked in the row, the row stays open");
    document.activeElement = undefined;
  } else expect(false, "members: the reviewer has a credential to revoke");
  win.Maity.api.getAll = rvAll;
  eSel("reports").value = "agt-d"; eSel("reports").dispatch("change");
  eIn()[0].value = "docs/, web/tools/, docs/"; eIn()[0].dispatch("input");
  eIn()[1].checked = true; eIn()[1].dispatch("change");
  // Edits survive a redraw (here: another row opened and closed, each a
  // rebuild of the table), and are sent as typed.
  const formBefore = eRow().querySelector("form.member-edit");
  const pauseIn = () => eRow().querySelector(".member-pause input");
  pauseIn().value = "quota, half typed"; pauseIn().dispatch("input");
  btn(mRow("Agent D"), "Manage").click(); await tick();
  btn(mRow("Agent D"), "Done").click(); await tick();
  expect(eRow().querySelector("form.member-edit") !== formBefore && eSel("reports").value === "agt-d" && eIn()[0].value === "docs/, web/tools/, docs/" && eIn()[1].checked,
    "members: unsaved edits survive a redraw");
  expect(pauseIn().value === "quota, half typed", "members: a half-typed pause reason survives a redraw too");
  await submitEdit();
  expect(JSON.stringify(eWrites[0]) === JSON.stringify(["/projects/maintainer/maity/members/agt-r",
    { reports_to: "agt-d", areas: ["docs/", "web/tools/"], capabilities: ["tag"] }])
    && text(main).includes("Saved for Reviewer: reports to, areas, capabilities."), "members: one PATCH with exactly what changed");
  // A circle is refused before sending: Agent D would report to the Reviewer, who reports to Agent D.
  btn(mRow("Reviewer"), "Done").click(); await tick();
  btn(mRow("Agent D"), "Manage").click(); await tick();
  eSel("reports").value = "agt-r";
  await submitEdit();
  expect(eWrites.length === 1 && text(main).includes("Not saved: That would close a circle") && eSel("reports").getAttribute("aria-invalid") === "true"
    && text(byId("member-reports-agt-d-error")).includes("close a circle") && eSel("reports").getAttribute("aria-describedby") === "member-reports-agt-d-error", "members: a reports-to circle is refused before sending, at its field");
  eSel("reports").value = "";
  eIn()[0].value = "../secret";
  await submitEdit();
  expect(eWrites.length === 1 && text(main).includes("Not saved: An area is a repository path"), "members: an area with .. is refused before sending");
  btn(mRow("Agent D"), "Done").click(); await tick();
  // The hub's own cycle refusal reads the same.
  win.Maity.api.patch = (p, b) => Promise.reject(new win.Maity.api.ApiError("cycle", 400, p, "invalid", { fields: { reports_to: "cycle" } }));
  btn(mRow("Agent C"), "Manage").click(); await tick();
  eSel("reports").value = "agt-d";
  await submitEdit();
  expect(text(main).includes("Saving failed: That would close a circle"), "members: the hub's cycle refusal in the same words");
  btn(mRow("Agent C"), "Done").click(); await tick();
  win.Maity.api.patch = mPatch;
  // The organisation follows at once.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 4; k++) await tick();
  const orgNode = (name) => main.querySelectorAll(".org-tree li").find((li) => li.querySelector(".org-node strong").textContent === name);
  expect(orgNode("Agent D").querySelector("ul") && text(orgNode("Agent D").querySelector("ul")).includes("Reviewer"), "members: the organisation shows the Reviewer under Agent D");
  // The mock refuses a circle as the hub does (docs/api.md §6.2, #118); a removal clearing reports_to is checked with the removal below.
  let circle = null;
  try { await mPatch("/projects/maintainer/maity/members/agt-d", { reports_to: "agt-r" }); } catch (err) { circle = err; }
  expect(circle && circle.details.fields.reports_to === "cycle", "members: the mock refuses a circle with cycle");
  // Atomic as the hub: one bad field, nothing written, every bad field named.
  let atomic = null;
  try { await mPatch("/projects/maintainer/maity/members/agt-r", { trust: "member", role: "coder", areas: ["../x"], capabilities: ["fly"] }); } catch (err) { atomic = err; }
  const afterBad = (await win.Maity.api.getAll("/projects/maintainer/maity/members")).items.find((x) => x.id === "agt-r");
  expect(atomic && atomic.details.fields.areas === "invalid_path" && atomic.details.fields.capabilities === "unknown" && afterBad.role !== "member",
    "members: the mock checks every field before it writes anything");
  await mPatch("/projects/maintainer/maity/members/agt-r", { reports_to: "agt-a", areas: [], capabilities: [] });
  // A boss not in the list read stays chosen (and is not sent as nobody).
  const nlGet = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => nlGet(p).then((r) => (p !== "/projects/maintainer/maity/members" ? r
    : { items: r.items.map((x) => (x.id === "agt-r" ? Object.assign({}, x, { reports_to: "agt-gone" }) : x)), next_cursor: null }));
  await go("#/maintainer/maity/members");
  await fireIntervals(); await tick(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const nlSent = [];
  win.Maity.api.patch = (p, b) => { nlSent.push(b); return Promise.resolve(Object.assign({ id: "agt-r", kind: "agent" }, b)); };
  expect(eSel("reports").value === "agt-gone" && text(eSel("reports")).includes("(not in this list)"), "members: a boss not in the list stays chosen");
  eSel("role").value = "coder"; eSel("role").dispatch("change");
  await submitEdit();
  expect(nlSent.length === 1 && !("reports_to" in nlSent[0]), "members: saving the role leaves an unlisted boss alone");
  win.Maity.api.patch = mPatch; win.Maity.api.getAll = nlGet;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // A change that waits for a human's go (202, the consent request) is no "Saved".
  const consents = [];
  win.Maity.api.patch = (p, b) => { consents.push(b); return Promise.resolve({ id: "req-c009", class: "consent", status: "open", to: "owner", title: "Change reviewer to member" }); };
  await go("#/maintainer/maity/members");
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel("role").value = "coder"; eSel("role").dispatch("change");
  await submitEdit();
  expect(text(main).includes("Not changed yet: waiting for the owner's consent (req-c009, Change reviewer to member).") && !text(main).includes("Saved for Reviewer"),
    "members: a change waiting for consent says so, and not that it was saved");
  // The form shows the member as it is again, so a second Save asks nothing twice.
  expect(eSel("role").value === "reviewer", "members: after a consent request the form shows the hub's state, not the draft");
  await submitEdit();
  expect(consents.length === 1 && text(main).includes("Nothing changed."), "members: saving again after a consent request files no second one");
  win.Maity.api.patch = mPatch;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // Done drops a row's unsaved edits.
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel("role").value = "coder"; eSel("role").dispatch("change");
  btn(mRow("Reviewer"), "Done").click(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  expect(eSel("role").value === "reviewer", "members: Done drops the row's unsaved edits");
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // A drafted boss who has left since is dropped and said, never sent as nobody.
  const goneSent = [];
  win.Maity.api.patch = (p, b) => { goneSent.push(b); return mPatch(p, b); };
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel("reports").value = "agt-c"; eSel("reports").dispatch("change");
  const gGet = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => gGet(p).then((r) => (p !== "/projects/maintainer/maity/members" ? r : { items: r.items.filter((x) => x.id !== "agt-c"), next_cursor: null }));
  await fireIntervals(); await tick(); await tick();
  expect(eSel("reports").value === "agt-a" && text(eRow()).includes("whom you picked, is no longer a member"), "members: a drafted boss who left is dropped, and said");
  eIn()[0].value = "docs/"; eIn()[0].dispatch("input");
  await submitEdit();
  expect(goneSent.length === 1 && !("reports_to" in goneSent[0]), "members: saving then leaves the boss as it is");
  win.Maity.api.getAll = gGet;
  await mPatch("/projects/maintainer/maity/members/agt-r", { areas: [] });
  win.Maity.api.patch = mPatch;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  await go("#/maintainer/maity/members");
  // A write that went through is said as done when the re-read fails.
  win.Maity.api.patch = mPatch; win.Maity.api.del = mDel;
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const rAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? Promise.reject(new win.Maity.api.ApiError("down", 0, p)) : rAll(p));
  byId("member-role-agt-r").value = "tester";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Saved for Reviewer: role. Could not refresh: down") && !text(main).includes("Saving failed"),
    "members: a failed re-read after a write is no failed write");
  win.Maity.api.getAll = rAll;
  await win.Maity.api.patch("/projects/maintainer/maity/members/agt-r", { trust: "member", role: "reviewer" });
  // The mock as the hub: removal revokes, releases claims, and answers again as it is.
  const credsBefore = (await win.Maity.api.getAll("/projects/maintainer/sample/members/agt-s1/credentials")).items.filter((c) => !c.revoked_at).length;
  await win.Maity.api.patch("/projects/maintainer/sample/members/hum-maintainer", { reports_to: "agt-s1" });
  const removedS = await win.Maity.api.del("/projects/maintainer/sample/members/agt-s1");
  const sampleOwner = (await win.Maity.api.getAll("/projects/maintainer/sample/members")).items.find((x) => x.id === "hum-maintainer");
  expect(sampleOwner.reports_to === null, "members: the mock's removal clears reports_to on whoever reported to the removed member");
  const removedAgain = await win.Maity.api.del("/projects/maintainer/sample/members/agt-s1");
  const tasksAfter = (await win.Maity.api.getAll("/projects/maintainer/sample/tasks?status=all")).items;
  const credsAfter = (await win.Maity.api.getAll("/projects/maintainer/sample/members/agt-s1/credentials")).items;
  expect(credsBefore > 0 && removedS.removed_at && removedAgain.removed_at === removedS.removed_at
    && credsAfter.every((c) => c.revoked_at) && !tasksAfter.some((t) => t.claim && t.claim.holder === "agt-s1"),
    "members: the mock's DELETE revokes, releases, and answers a second time as it is");
  // A plain member: no actions, no owner or credentials from the hub.
  const mGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? mGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "member"; return x; })
    : p === "/projects/maintainer/maity/members" ? mGet(p).then((x) => ({ items: x.items.map((y) => { const o = Object.assign({}, y); delete o.owner; delete o.credentials; return o; }), next_cursor: null }))
      : mGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members");
  const ths2 = main.querySelectorAll("table.members")[1].querySelector("thead").querySelectorAll("th").map((t) => t.textContent);
  expect(!btn(main, "Manage") && !ths2.includes("Credentials") && text(mRow("Agent A")).includes("Maintainer"),
    "members: a member reads the list without managing; the owner from the members");
  // A human's own agents are on Agents: the credentials and the owner's preferences switch, nothing that changes the membership.
  expect(!btn(mRow("Agent A"), "Details") && !btn(mRow("Agent A"), "Manage") && chatOf("Agent A"), "members: without members:admin a row has its Chat only");
  await go("#/maintainer/maity/agents"); for (let k = 0; k < 6; k++) await tick();
  // agt-c carries the team's rulebook in the fixture.
  const ownCard = main.querySelectorAll("li.agent-card").find((li) => li.getAttribute("data-agent") === "agt-c");
  expect(ownCard && ownCard.querySelector(".agent-here .member-credentials") && ownCard.querySelector("form.member-team") && !ownCard.querySelector(".member-pause")
    && !btn(ownCard, "Remove from the project") && !main.querySelectorAll("li.agent-card").some((li) => li.getAttribute("data-agent") === "agt-x"),
    "agents: without members:admin one's own card holds the rulebook and the credentials, no pause or removal ");
  // Bringing one's own agent (§3.1, tsk-zd2ch05rk7s1): a member adds agents of their own on Agents, within the project's limit.
  for (let k = 0; k < 4; k++) await tick();
  const byoButton = () => main.querySelector("button.join-open");
  const byoNote = () => main.querySelector(".member-agents-limit");
  // At the limit (§3.1) the panel still makes an instance of one already in the project; a new one is refused before sending.
  expect(byoButton() && text(byoButton()) === "+ Add my agent" && !byoButton().disabled && /^\d+ of 3 agents of yours/.test(text(byoNote()))
    && text(byoNote()).includes("no new one; another instance or a replacement still"), "own agents: at the project's limit Add my agent stays for an instance, and says why " + (byoNote() && text(byoNote())));
  const byoFullPosts = [];
  const byoFullPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p.endsWith("/joins")) { byoFullPosts.push(b); return Promise.reject(new win.Maity.api.ApiError("x", 400, p, "invalid", {})); } return byoFullPost(p, b); };
  byoButton().click(); await tick();
  byId("join-agent").value = ""; byId("join-agent").dispatch("change");
  byId("join-handle").value = "one-more"; byId("join-display").value = "One more";
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(!byoFullPosts.length && text(main.querySelector(".join-panel")).includes("you hold as many agents in this project as it allows; choose one of yours"),
    "own agents: at the limit a new agent is refused before sending");
  byId("join-agent").value = "agt-a"; byId("join-agent").dispatch("change");
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(byoFullPosts.length === 1 && byoFullPosts[0].agent.id === "agt-a" && (byoFullPosts[0].new_instance || byoFullPosts[0].replaces),
    "own agents: at the limit an instance of one's member agent is still sent " + JSON.stringify(byoFullPosts[0]));
  win.Maity.api.post = byoFullPost;
  const byoGet = win.Maity.api.get;
  // A hub whose policy has no member_agents does not know members' own agents: no button that would get 403.
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? byoGet(p).then((x) => { const pol = Object.assign({}, x.policy); delete pol.member_agents; return Object.assign({}, x, { policy: pol }); }) : byoGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 6; k++) await tick();
  expect(!byoButton() || byoButton().hidden || text(byoButton()) !== "+ Add my agent", "own agents: no Add my agent where the hub sends no member_agents");
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? byoGet(p).then((x) => Object.assign({}, x, { policy: Object.assign({}, x.policy, { member_agents_max: 10 }) })) : byoGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 6; k++) await tick();
  expect(byoButton() && !byoButton().disabled && /^\d+ of 10 agents of yours$/.test(text(byoNote())), "own agents: below the limit, Add my agent is on");
  byoButton().click(); await tick();
  expect(byId("join-trust") && byId("join-trust").querySelectorAll("option").map((o) => o.getAttribute("value")).join() === "member,guest"
    && byId("join-role").querySelectorAll("option").map((o) => o.getAttribute("value")).join() === "coder,reviewer,tester,designer"
    && !byId("join-reports") && !byId("join-areas") && text(main.querySelector(".join-panel")).includes("Add my agent"),
    "own agents: the panel offers only member or guest, the four roles, no reports to and no areas");
  const byoPosts = [];
  const byoPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p.endsWith("/joins")) byoPosts.push(b); return Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: "member_join_limit", field: "role" })); };
  byId("join-agent").value = ""; byId("join-agent").dispatch("change");
  byId("join-handle").value = "my-helper"; byId("join-display").value = "My helper"; byId("join-role").value = "tester"; byId("join-trust").value = "guest"; byId("join-ttl").value = "900";
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(byoPosts[0]) === JSON.stringify({ agent: { handle: "my-helper", display_name: "My helper" }, trust: "guest", role: "tester", ttl_seconds: 900 })
    && text(main.querySelector(".join-panel")).includes("a member may not set this for their own agent: the role"),
    "own agents: the join carries trust and role only, and the hub's limit is said with its field " + JSON.stringify(byoPosts[0]));
  win.Maity.api.post = (p, b) => Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: "member_agents_max", max: 10 }));
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector(".join-panel")).includes("you hold as many agents in this project as it allows (10)"), "own agents: the hub's count limit in words");
  win.Maity.api.post = byoPost; win.Maity.api.get = byoGet;
  win.Maity.api.get = mGet;
  // Agents whose profiles cannot be read say so, never "none of your agents".
  const aeAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/agents" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal")) : aeAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("Your agents could not be read: down") && !text(main).includes("None of your agents"),
    "agents: a failed read of the profiles is said where the cards go, not as none");
  win.Maity.api.getAll = aeAll;
  // A guest is told of no way to add an agent (§3.1).
  const agGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? agGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "guest"; return x; }) : agGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(main).includes("Adding an agent of yours is on Agents"), "members: a guest is not pointed to adding an agent");
  win.Maity.api.get = agGet;
  // Project settings: whether members add their own agents, and how many each, with a reason (an owner).
  await go("#/maintainer/maity/inbox"); await projectSettings();
  const maPatches = [];
  const maPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { maPatches.push([p, b]); return maPatch(p, b); };
  expect(byId("member-agents-select") && byId("member-agents-select").value === "on" && byId("member-agents-max").value === "3",
    "own agents: Project settings show members' own agents on, three each");
  byId("member-agents-max").value = "5"; byId("member-agents-reason").value = "a bigger team";
  main.querySelector("form.member-agents-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(maPatches.length === 1 && JSON.stringify(maPatches[0][1]) === JSON.stringify({ policy: { member_agents_max: 5 }, reason: "a bigger team" }),
    "own agents: only what changed is sent, with its reason " + JSON.stringify(maPatches[0] && maPatches[0][1]));
  await win.Maity.api.patch("/projects/maintainer/maity", { policy: { member_agents_max: 3 }, reason: "back for the tests" });
  win.Maity.api.patch = maPatch;
  await go("#/maintainer/maity/inbox");

  // Message the project (docs/api.md §8.4): from the Chat tab (tsk-r1adgwp0a5dr), no longer the inbox, no tab of its own.
  await go("#/maintainer/maity/inbox");
  expect(!main.querySelectorAll("a").some((a) => a.textContent === "Message the project"), "message: no longer in the inbox");
  await go("#/maintainer/maity/chat");
  const msgLink = main.querySelector(".chat-list-pane").querySelectorAll("a").find((a) => a.textContent === "Message the project");
  expect(msgLink && msgLink.getAttribute("href") === "#/maintainer/maity/message"
    && !header.querySelectorAll("nav.views a").some((a) => a.textContent === "Message the project"), "message: a link in the Chat tab, no tab");
  const msgPosts = [];
  const mPost0 = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { msgPosts.push([p, b]); return mPost0(p, b); };
  await go("#/maintainer/maity/message");
  const toOpts = byId("message-to").querySelectorAll("option").map((o) => o.attrs.value);
  expect(plainTitle() === "Message the project · Maity · Maity" && toOpts[0] === "all" && toOpts.includes("role:reviewer") && toOpts.includes("agt-b")
    && !toOpts.includes("hum-maintainer") && byId("message-type").value === "notice", "message: to everyone, a role or a member (not oneself); a notice by default");
  main.querySelector("form.message-form").dispatch("submit"); await tick();
  expect(!msgPosts.length && text(main).includes("Not sent: the message is empty"), "message: an empty one is not sent");
  byId("message-to").value = "role:reviewer"; byId("message-type").value = "handover"; byId("message-card").value = "tsk-0006";
  byId("message-body").value = "Please look at the join path, @agent-b; mail x@agent-c is no mention.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(msgPosts[0]) === JSON.stringify(["/projects/maintainer/maity/events", { kind: "message", type: "handover", to: "role:reviewer",
    body: "Please look at the join path, @agent-b; mail x@agent-c is no mention.", task_id: "tsk-0006" }]), "message: the POST as §8.4 has it, no mentions sent");
  expect(text(main).includes("Sent to every reviewer; mentioned and notified: Agent B.") && byId("message-body").value === "",
    "message: sent, with whom the hub's mentions told");
  win.Maity.api.post = (p) => Promise.reject(new win.Maity.api.ApiError("too many", 400, p, "invalid", { fields: { body: "too_many_mentions" } }));
  byId("message-body").value = "@agent-a @agent-b";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 3; k++) await tick();
  expect(text(main).includes("Not sent: too many mentions: at most 10 members"), "message: the hub's mention cap, in words");
  // While it is on its way the fields are held; the confirmation speaks of what was sent, and
  // what was typed meanwhile stays.
  let releasePost = null;
  win.Maity.api.post = (p, b) => new Promise((r) => { releasePost = () => r(mPost0(p, b)); });
  byId("message-to").value = "agt-b"; byId("message-body").value = "First, @agent-b.";
  main.querySelector("form.message-form").dispatch("submit"); await tick();
  expect(byId("message-to").disabled && byId("message-body").disabled && btn(main, "Send").disabled, "message: the fields are held while it is sent");
  byId("message-to").value = "all"; byId("message-body").value = "A second thought";
  releasePost(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Sent to Agent B; mentioned and notified: Agent B.") && byId("message-body").value === "A second thought"
    && !byId("message-body").disabled, "message: the confirmation names what was sent; a draft typed meanwhile is kept");
  win.Maity.api.post = mPost0;
  expect(byId("message-to").querySelectorAll("option").some((o) => o.attrs.value === "trust:owner"), "message: the owners are a trust to write to");
  let badRole = null;
  try { await mPost0("/projects/maintainer/maity/events", { kind: "message", type: "notice", to: "role:wizard", body: "x" }); } catch (err) { badRole = err; }
  let chatNoConv = null;
  try { await mPost0("/projects/maintainer/maity/events", { kind: "message", type: "chat", to: "agt-a", body: "x" }); } catch (err) { chatNoConv = err; }
  expect(badRole && badRole.details.fields.to && chatNoConv && chatNoConv.details.fields.conversation_id === "missing", "message: the mock refuses an unknown role and a chat without its conversation");
  // From a chat: an @name there tells nobody; the hint offers a project message with it.
  await go("#/maintainer/maity/chat/agt-d");
  const chatText = byId("chat-text");
  const hintEl = () => main.querySelector(".mention-hint");
  expect(hintEl() && hintEl().hidden, "message: no hint while the chat has no @name");
  chatText.value = "Ask @agent-c about the join path"; chatText.dispatch("input");
  const hintLink = hintEl().querySelector("a");
  expect(!hintEl().hidden && text(hintEl()).includes("In this chat @agent-c notifies nobody.") && hintLink
    && hintLink.getAttribute("href") === "#/maintainer/maity/message/%40agent-c", "message: a chat's @name is said to notify nobody, with a project message offered");
  chatText.value = "Ask @maintainer/agent-c#k3pa"; chatText.dispatch("input");
  expect(!hintEl().hidden && text(hintEl()).includes("In this chat @maintainer/agent-c#k3pa notifies nobody.")
    && hintEl().querySelector("a").getAttribute("href") === "#/maintainer/maity/message/" + encodeURIComponent("@maintainer/agent-c#k3pa"),
    "message: a chat's instance mention, long or short, gets the hint with the whole mention");
  chatText.value = "mail me@agent-c"; chatText.dispatch("input");
  expect(hintEl().hidden, "message: an @ inside a word gives no hint");
  chatText.value = "run `@agent-c` or\n```\n@agent-c\n```"; chatText.dispatch("input");
  expect(hintEl().hidden, "message: an @name in code gives no hint, as the hub skips code");
  chatText.value = ""; chatText.dispatch("input");
  // Opened from a chat with the @name in it.
  await go("#/maintainer/maity/message/" + encodeURIComponent("@agent-c"));
  expect(byId("message-body").value === "@agent-c ", "message: opened with an @name already written");

  // The swarm statistics (js/swarm.js, docs/api.md §6.22, §6.11): a section of the Overview, no tab, no public page, no switch.
  const swGets = [];
  const swGet = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p.includes("swarm")) swGets.push(p); return swGet(p); };
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 6; k++) await tick();
  const swBox = () => main.querySelector("section.overview-swarm");
  const swLive = () => (swBox().querySelector("ul.swarm-live") || { childNodes: [] }).childNodes;
  const swLi = (id) => swLive().find((li) => li.attrs["data-member"] === id);
  expect(!header.querySelectorAll("nav.views a").some((a) => a.textContent === "Swarm") && swBox() && main.querySelectorAll("section.overview-swarm").length === 1
    && text(swBox().querySelector(".overview-head").childNodes[0]) === "Swarm" && swBox().parentNode.className === "overview-row overview-row-3"
    && swGets[0] === "/projects/maintainer/maity/swarm?days=30" && swLive().length === 4,
    "swarm: a section of the Overview after the facts, no tab; read for 30 days, everyone in the live strip");
  expect(text(swLi("agt-b")).includes("online, 2 instances") && swLi("agt-b").querySelector(".swarm-holding a").getAttribute("href") === "#/maintainer/maity/tasks/tsk-0004"
    && text(swLi("agt-b")).includes("Hub: credential exchange and storage") && text(swLi("agt-c")).includes("last seen") && text(swLi("hum-maintainer")).includes(" online"),
    "swarm: online with its instances, what each holds as links to the cards, last seen for the offline");
  const swRows = swBox().querySelectorAll("table.swarm-table tbody tr");
  const swTotal = swBox().querySelector("table.swarm-table tfoot tr");
  const swRowB = swRows.find((tr) => tr.attrs["data-member"] === "agt-b");
  expect(swRows.length === 4 && JSON.stringify(swRowB.childNodes.slice(1).map((c) => text(c))) === JSON.stringify(["19", "0", "12", "2", "2 h 30 min", "45 min"])
    && text(swRows.find((tr) => tr.attrs["data-member"] === "agt-c")).endsWith("––") && text(swTotal).startsWith("All36132331 h 42 min40 min"),
    "swarm: the window's table per member and in all, medians in words, – below three samples " + JSON.stringify([text(swRowB), text(swTotal)]));
  expect(text(swBox()).includes("36 cards done") && swBox().querySelector(".swarm-per-day").childNodes[1].tagName.toLowerCase() === "svg"
    && text(swBox()).includes("Reviews are counted from 2026-10-20.") && text(swBox()).includes("fewer than three cards")
    && !swBox().querySelectorAll("a").some((a) => /as=public/.test(a.getAttribute("href") || "")), "swarm: cards done per day, the coverage and samples notes, no public page");
  const swPoints = () => swBox().querySelector(".swarm-per-day").childNodes[1].childNodes[0].getAttribute("points").split(" ");
  expect(swPoints().length === 30 && swPoints()[29] === "158.0,6.8", "swarm: the per-day line runs oldest to newest, the newest day at the right " + swPoints().slice(-1));
  const swBefore = swBox();
  let swFeed = [];
  win.Maity.api.get = (p) => {
    if (p.includes("/events?") && swFeed.length) { const items = swFeed; swFeed = []; return Promise.resolve({ items, cursor: items[items.length - 1].seq, superseded: false }); }
    if (p.includes("swarm")) swGets.push(p);
    return swGet(p);
  };
  btn(swBox(), "7 days").click(); for (let k = 0; k < 4; k++) await tick();
  expect(swGets[swGets.length - 1] === "/projects/maintainer/maity/swarm?days=7" && btn(swBox(), "7 days").getAttribute("aria-pressed") === "true" && swPoints().length === 7,
    "swarm: the switch reads 7 days and draws them");
  // A redraw of the counts (a card changed) keeps the section as it is: no new read, the window kept.
  const swReads = swGets.length;
  const swOverview = main.querySelector(".overview-counts");
  swFeed = [{ seq: 9990, kind: "task_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".overview-counts") !== swOverview && swBox() === swBefore && swGets.length === swReads && btn(swBox(), "7 days").getAttribute("aria-pressed") === "true",
    "swarm: the Overview's redraw keeps the section, its window and its read");
  // Project settings have no swarm switch.
  await go("#/maintainer/maity/settings"); for (let k = 0; k < 4; k++) await tick();
  expect(!byId("swarm-public-select") && !main.querySelector("form.swarm-public-form") && !text(main).includes("Public swarm"), "swarm: no public switch in Project settings");
  win.Maity.api.get = swGet; win.Maity.api.forgetRoutes();
  // The contract's section on a contract card (js/contract-panel.js, docs/api.md §6.8): folded until opened,
  // the repository's text untrusted, the hub's code when it cannot resolve it, never an older text.
  const ctGets = [], ctPatches = [];
  const ctGet = win.Maity.api.get, ctPatch = win.Maity.api.patch;
  win.Maity.api.get = (p) => { if (p.endsWith("/contract")) ctGets.push(p); return ctGet(p); };
  win.Maity.api.patch = (p, b) => { if (b && b.contract) ctPatches.push([p, b]); return ctPatch(p, b); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const ctCard = () => main.querySelectorAll("article.card").find((a) => a.attrs["data-card"] === "tsk-0009");
  const ctBox = () => ctCard().querySelector("details.contract-section");
  const ctOpen = async () => { ctBox().open = true; ctBox().dispatch("toggle"); for (let k = 0; k < 4; k++) await tick(); };
  const ctBody = () => ctBox().querySelector(".contract-body");
  const ctSave = async (path, section) => {
    byId("contract-path-tsk-0009").value = path; byId("contract-section-tsk-0009").value = section;
    ctBox().querySelector("form.contract-place").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  };
  expect(ctBox() && text(ctBox().querySelector("summary")) === "Contract section: docs/api.md § 8.2" && !ctGets.length,
    "contract: a contract card names its file and section, folded, nothing read yet");
  await ctOpen();
  const ctLinks = ctBody().querySelectorAll("a");
  expect(ctGets.length === 1 && ctGets[0] === "/projects/maintainer/maity/tasks/tsk-0009/contract"
    && text(ctBody().querySelector(".contract-meta")).startsWith("docs/api.md at 3f9c2a1 · read ")
    && ctLinks.some((a) => text(a) === "the file on the forge" && a.getAttribute("href").startsWith("https://github.com/oliver-zehentleitner/maity/blob/3f9c2a1e"))
    && text(ctBody().querySelector(".contract-text")).includes("Every event has a kind.") && ctBody().querySelector(".contract-text code"),
    "contract: opened, the section as Markdown with the short commit, when it was read, and the file on the forge");
  expect(!ctBody().querySelector("a.mention") && !ctBody().querySelector("a.id-ref") && text(ctBody()).includes("Ask @agent-a about tsk-0123456789ab")
    && ctLinks.length === 2, "contract: the repository's text is untrusted: no mention, no id link, only its own link and the forge's");
  // Refresh is a text button in the line that says what was read; the source's form waits behind Change source.
  const ctChange = btn(ctBox(), "Change source");
  expect(btn(ctBody().querySelector(".contract-meta"), "Refresh") && !ctBox().querySelector(".contract-bar")
    && ctBox().querySelector("form.contract-place").hidden && ctChange && ctChange.getAttribute("aria-expanded") === "false",
    "contract: Refresh in the meta line, the source's form folded behind Change source");
  ctChange.click(); await tick();
  expect(!ctBox().querySelector("form.contract-place").hidden && ctChange.getAttribute("aria-expanded") === "true", "contract: Change source opens the form");
  ctChange.click(); await tick();
  btn(ctBox(), "Refresh").click(); for (let k = 0; k < 4; k++) await tick();
  expect(ctGets.length === 2, "contract: Refresh reads again");
  win.Maity.api.get = (p) => (p.endsWith("/contract") ? Promise.reject(new win.Maity.api.ApiError("the forge did not answer", 503, p, "probe_unavailable")) : ctGet(p));
  btn(ctBox(), "Refresh").click(); for (let k = 0; k < 4; k++) await tick();
  expect(!ctBody().querySelector(".contract-text") && text(ctBody()) === "docs/api.md § 8.2 is not shown: the forge did not answer (probe_unavailable). Refresh",
    "contract: a failed read shows the place and the hub's code, never the older text");
  win.Maity.api.get = (p) => { if (p.endsWith("/contract")) ctGets.push(p); return ctGet(p); };
  const ctBeforeSave = ctGets.length;
  await ctSave("docs/api.md", "4.1");
  expect(ctPatches.length === 1 && JSON.stringify(ctPatches[0][1]) === JSON.stringify({ contract: { path: "docs/api.md", section: "4.1" } })
    && text(ctBox().querySelector("summary")) === "Contract section: docs/api.md § 4.1", "contract: the section changed by one PATCH, the card drawn anew");
  expect(ctBox().open && ctGets.length === ctBeforeSave + 1, "contract: after a save the panel stays open and reads the new section once");
  expect(text(ctBody()) === "docs/api.md § 4.1 is not shown: the file has two headings with this number; the hub shows neither (ambiguous_in_file). Refresh",
    "contract: ambiguous_in_file said with its code");
  await ctSave("docs/api.md", "9.99"); await ctOpen();
  expect(text(ctBody()).endsWith("the file has no heading with this number (not_found_in_file). Refresh"), "contract: not_found_in_file said with its code");
  await ctSave("docs/runner.md", "1"); await ctOpen();
  expect(text(ctBody()) === "docs/runner.md § 1 is not shown: the hub has no forge token for this repository (probe_not_configured). Refresh",
    "contract: probe_not_configured said with its code");
  await ctSave("docs/api.md", "9.1"); await ctOpen();
  expect(text(ctBody()).includes("Cut at 64 KiB; the whole section is in the file (open it)."), "contract: a cut section says so and links the file");
  const ctBefore = ctGets.length;
  await ctSave("docs/api.md", ""); await ctOpen();
  expect(ctPatches[ctPatches.length - 1][1].contract.section === null && ctGets.length === ctBefore
    && text(ctBody()) === "The card names no section yet.", "contract: no section, nothing read, said so");
  await ctSave("/etc/passwd", "1");
  expect(text(ctBox().querySelector(".send-status")).startsWith("Not saved: contract.path: not_a_path"), "contract: the hub's refusal of a path is said");
  win.Maity.api.get = ctGet; win.Maity.api.patch = ctPatch;
  // Where the agents run (js/placements.js, docs/api.md §15.5–§15.7): one row per placement in Agents,
  // with Stop, Start and Restart for whoever may; a refusal as the hub words it; placement events read again.
  const plPosts = [], plPatches = [];
  const plPost = win.Maity.api.post, plPatch = win.Maity.api.patch, plGet = win.Maity.api.get, plGetAll = win.Maity.api.getAll;
  let plFeed = [], plReads = 0;
  win.Maity.api.post = (p, b) => { if (p.includes("/placements/")) plPosts.push([p, b]); return plPost(p, b); };
  win.Maity.api.patch = (p, b) => { if (p.includes("/placements/")) plPatches.push([p, b]); return plPatch(p, b); };
  win.Maity.api.get = (p) => (p.includes("/events?")
    ? (() => { const items = plFeed; plFeed = []; return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 30000, superseded: false }); })()
    : plGet(p));
  win.Maity.api.getAll = (p) => { if (p === "/projects/maintainer/maity/placements") plReads += 1; return plGetAll(p); };
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  const plBox = () => main.querySelector("section.placements");
  const plRow = (id) => plBox().querySelectorAll("li.placement").find((li) => li.attrs["data-placement"] === id);
  const plFacts = (id) => text(plRow(id).querySelector("dl.facts"));
  expect(plBox() && text(plBox().childNodes[0]) === "Where they run" && plBox().querySelectorAll("li.placement").length === 4
    && (() => { const slot = plBox().parentNode; const kids = slot.parentNode.childNodes; return kids[kids.indexOf(slot) + 1] === main.querySelector(".earlier-box"); })(),
    "placements: a section on Agents after the cards, before the earlier joins, one row per placement");
  expect(text(plRow("plc-0001")).includes("on home-laptop") && plFacts("plc-0001").includes("claude-code · opus · interactive")
    && plFacts("plc-0001").includes("Wantedrunning") && plFacts("plc-0001").includes("running · since") && plFacts("plc-0001").includes("· generation 4")
    && plRow("plc-0001").querySelector(".placement-state").classList.contains("pill-ok")
    && btn(plRow("plc-0001"), "Stop") && btn(plRow("plc-0001"), "Restart") && !btn(plRow("plc-0001"), "Restart with a new join"),
    "placements: a running one — runner, harness, model, mode, wanted, reported, generation; Stop and Restart");
  expect(plFacts("plc-0002").includes("stopped: stopped as asked") && btn(plRow("plc-0002"), "Start") && btn(plRow("plc-0002"), "Restart with a new join"),
    "placements: a stopped one offers Start, and a new join where its credential was revoked");
  expect(plFacts("plc-0003").includes("failed: crash loop (5 quick exits within 30 min)") && plRow("plc-0003").querySelector(".placement-state").classList.contains("flag-inline"),
    "placements: a crash loop is flagged with its count");
  const plConsent = plRow("plc-0004").querySelector(".placement-consent a");
  expect(plFacts("plc-0004").includes("Waits for consent to start") && plConsent && plConsent.getAttribute("href") === "#/maintainer/maity/inbox/req-0012"
    && !plRow("plc-0004").querySelectorAll("button").length, "placements: pending consent links to its request in the inbox, and offers nothing else here");
  expect(text(plRow("plc-0001")).includes("Session: tmux -S /var/lib/maity-runner/tmux.sock attach") && text(plRow("plc-0001")).includes("Logs: maity runner logs plc-0001")
    && plRow("plc-0001").querySelectorAll(".placement-command").length === 2 && plRow("plc-0001").querySelectorAll(".placement-command button").every((b) => b.textContent === "Copy")
    && !text(plRow("plc-0002")).includes("Session:"), "placements: the runner's owner sees how to look at it, each command in its box with Copy");
  expect(plRow("plc-0003").querySelector(".placement-state").classList.contains("pill-bad") && plRow("plc-0004").querySelector(".placement-consent").classList.contains("pill-warn"),
    "placements: the state is a pill, a failure red, a consent waiting amber");
  const plStop = btn(plRow("plc-0001"), "Stop");
  plStop.click(); plStop.click(); for (let k = 0; k < 6; k++) await tick();
  expect(plPatches.length === 1 && plPatches[0][0] === "/projects/maintainer/maity/placements/plc-0001" && JSON.stringify(plPatches[0][1]) === JSON.stringify({ desired: "stopped" })
    && plFacts("plc-0001").includes("Wantedstopped") && btn(plRow("plc-0001"), "Start"),
    "placements: Stop is one PATCH of desired, unconfirmed; the row reads again");
  btn(plRow("plc-0001"), "Restart").click(); await tick();
  expect(!plPosts.length && text(plRow("plc-0001")).includes("Restart Agent B? Its session ends and starts again.") && btn(plRow("plc-0001"), "Yes, restart"),
    "placements: Restart asks once more first");
  btn(plRow("plc-0001"), "Yes, restart").click(); for (let k = 0; k < 6; k++) await tick();
  expect(plPosts.length === 1 && plPosts[0][0] === "/projects/maintainer/maity/placements/plc-0001/restart" && JSON.stringify(plPosts[0][1]) === "{}"
    && plFacts("plc-0001").includes("Waiting for the runner to act on generation 5 (last: running)") && plFacts("plc-0001").includes("Wantedrunning"),
    "placements: the confirmed restart is one POST; pending until the runner reports the new generation");
  btn(plRow("plc-0002"), "Restart with a new join").click(); await tick();
  btn(plRow("plc-0002"), "Yes, restart with a new join").click(); for (let k = 0; k < 6; k++) await tick();
  expect(plPosts.length === 2 && JSON.stringify(plPosts[1][1]) === JSON.stringify({ rejoin: true }), "placements: a new join is a restart with rejoin");
  win.Maity.api.patch = (p, b) => (p.includes("/placements/") ? Promise.reject(new win.Maity.api.ApiError("the project is closed", 409, p, "project_closed")) : plPatch(p, b));
  btn(plRow("plc-0001"), "Stop").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(plBox().querySelector(".send-status")) === "Not stopped: the project is closed (project_closed)", "placements: a refusal is the hub's message and code");
  const plBefore = plReads;
  plFeed = [{ seq: 30001, kind: "placement_reported", at: "2026-10-22T14:10:00Z", actor: { kind: "runner", id: "rnr-0002" }, payload: { placement_id: "plc-0001", state: "running" } }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(plReads === plBefore + 1, "placements: a placement event reads the list again");
  // A runner listed for a project one administers but owned by someone else gives no rights over it.
  const plRunner = (owner) => Promise.resolve({ items: [{ id: "rnr-0002", name: "home-laptop", owner_id: owner }], next_cursor: null });
  win.Maity.api.getAll = (p) => (p === "/runners" ? plRunner("hum-other")
    : p === "/projects/maintainer/maity/members" ? plGetAll(p).then((r) => ({ items: r.items.map((x) => Object.assign({}, x, x.kind === "agent" ? { owner_id: "hum-other" } : {})), next_cursor: null })) : plGetAll(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? plGet(p).then((r) => Object.assign({}, r, { items: r.items.map((x) => Object.assign({}, x, x.kind === "agent" ? { owner_id: "hum-other" } : {})) })) : plGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  // Copy beside a runner command is no action on the placement.
  const plActs = () => plBox().querySelectorAll("button").filter((b) => !b.getAttribute("aria-label") || !b.getAttribute("aria-label").startsWith("Copy the "));
  expect(plBox() && !plActs().length, "placements: a runner someone else owns gives a project admin no actions");
  // One's own runner gives the rights, also over agents someone else owns.
  win.Maity.api.getAll = (p) => (p === "/runners" ? plRunner("hum-maintainer")
    : p === "/projects/maintainer/maity/members" ? plGetAll(p).then((r) => ({ items: r.items.map((x) => Object.assign({}, x, x.kind === "agent" ? { owner_id: "hum-other" } : {})), next_cursor: null })) : plGetAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  expect(plBox() && btn(plRow("plc-0003"), "Restart"), "placements: one's own runner gives a project admin the actions, also over another owner's agent");
  // No agent yet: the section is still there for a placement that creates its profile.
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? plGet(p).then((r) => Object.assign({}, r, { items: r.items.filter((x) => x.kind !== "agent") })) : plGet(p));
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? plGetAll(p).then((r) => ({ items: r.items.filter((x) => x.kind !== "agent"), next_cursor: null })) : plGetAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  expect(text(main).includes("None of your agents is in this project yet") && plBox() && plBox().querySelectorAll("li.placement").length === 4,
    "placements: with no agent yet, where they run is still shown");
  // While the placements are read the join panel is open already: the button never shows to vanish.
  let plRelease = null;
  const plGetAll2 = win.Maity.api.getAll;
  const plGet2 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? plGet2(p).then((r) => Object.assign({}, r, { items: r.items.filter((x) => x.kind !== "agent") })) : plGet2(p));
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/placements" ? new Promise((r) => { plRelease = () => r(plGetAll2(p)); })
    : p === "/projects/maintainer/maity/members" ? plGetAll2(p).then((r) => ({ items: r.items.filter((x) => x.kind !== "agent"), next_cursor: null })) : plGetAll2(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  expect(main.querySelector(".join-panel") && !main.querySelector(".join-panel").hidden && main.querySelector("button.join-open").hidden,
    "placements: while they are read, the view is there and a project without agents shows its join panel");
  if (plRelease) plRelease();
  for (let k = 0; k < 4; k++) await tick();
  win.Maity.api.getAll = plGetAll2; win.Maity.api.get = plGet2;
  // Neither the runner's owner nor the agents' owner: the rows without actions.
  const othersOwn = (r) => Object.assign({}, r, { items: r.items.map((x) => Object.assign({}, x, x.kind === "agent" ? { owner_id: "hum-other" } : {})) });
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? plGet(p).then(othersOwn) : plGet(p));
  win.Maity.api.getAll = (p) => (p === "/runners" ? Promise.resolve({ items: [], next_cursor: null })
    : p === "/projects/maintainer/maity/members" ? plGetAll(p).then(othersOwn) : plGetAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 8; k++) await tick();
  expect(plBox() && plBox().querySelectorAll("li.placement").length === 4 && !plActs().length,
    "placements: neither the runner's nor the agent's owner sees no actions");
  win.Maity.api.post = plPost; win.Maity.api.patch = plPatch; win.Maity.api.get = plGet; win.Maity.api.getAll = plGetAll;
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox");

  // The board's column filter (the maintainer's request): one column or the closed ones, remembered per project.
  const cfStore = {};
  const cfLs = win.localStorage;
  win.localStorage = { getItem: (k) => (k in cfStore ? cfStore[k] : null), setItem: (k, v) => { cfStore[k] = String(v); }, removeItem: (k) => { delete cfStore[k]; } };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const cfCols = () => main.querySelectorAll("section.column").map((c) => c.getAttribute("aria-label"));
  const cfCards = () => main.querySelectorAll("article.card").map((a) => a.attrs["data-card"]);
  const cfAll = cfCols().length;
  expect(byId("board-column") && byId("board-column").value === "" && cfAll >= 7, "board: the column filter shows every column by default " + JSON.stringify(cfCols()));
  byId("board-column").value = "closed"; byId("board-column").dispatch("change"); await tick();
  expect(JSON.stringify(cfCols()) === JSON.stringify(["Done", "Cancelled"]) && cfCards().includes("tsk-0003") && cfCards().includes("tsk-0002") && !cfCards().includes("tsk-0006")
    && cfStore["maity.board.column.maintainer/maity"] === "closed", "board: Closed shows the done and cancelled columns only, and is remembered " + JSON.stringify([cfCols(), cfCards()]));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("board-column").value === "closed" && JSON.stringify(cfCols()) === JSON.stringify(["Done", "Cancelled"]), "board: the column filter is there again on the next visit");
  byId("board-column").value = "in_progress"; byId("board-column").dispatch("change"); await tick();
  byId("board-member").value = "agt-a"; byId("board-member").dispatch("change"); await tick();
  expect(JSON.stringify(cfCols()) === JSON.stringify(["In progress"]) && cfCards().includes("tsk-0001") && !cfCards().includes("tsk-0007"),
    "board: the column filter works with the member filter " + JSON.stringify(cfCards()));
  await go("#/maintainer/maity/tasks/tsk-0003"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll("article.card.wanted").length === 1 && cfCols().length === cfAll, "board: a card asked for by its link is shown whatever the column filter says");
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  byId("board-column").value = ""; byId("board-column").dispatch("change"); await tick();
  expect(cfCols().length === cfAll && !("maity.board.column.maity" in cfStore), "board: every column again, nothing remembered");
  win.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  byId("board-column").value = "review"; byId("board-column").dispatch("change"); await tick();
  expect(JSON.stringify(cfCols()) === JSON.stringify(["Review"]), "board: with storage blocked the filter still works");
  win.localStorage = cfLs;
  await go("#/maintainer/maity/inbox");

  // Markdown in a chat (js/markdown.js): text nodes only, https links only.
  const MD = (src) => { const box = document.createElement("div"); win.Maity.dom.append(box, win.Maity.markdown(src)); return box; };
  const tagsOf = (box) => box.childNodes.filter((n) => n.tagName).map((n) => n.tagName.toLowerCase());
  const mdP = MD("First line\nsecond line\n\nNext paragraph with `a <b>` code, **strong**, *em* and _em_.");
  expect(JSON.stringify(tagsOf(mdP)) === '["p","p"]' && mdP.childNodes[0].querySelector("br") && mdP.querySelector("code").textContent === "a <b>"
    && mdP.querySelector("strong").textContent === "strong" && mdP.querySelectorAll("em").length === 2, "markdown: paragraphs, line breaks, code, strong and em");
  const mdHtml = MD("<script>alert(1)</script> and <b>bold</b>");
  expect(!mdHtml.querySelector("script") && !mdHtml.querySelector("b") && text(mdHtml).includes("<script>alert(1)</script>"), "markdown: raw HTML stays visible as text");
  const mdLinks = MD("[ok](https://example.org/a) [no](javascript:alert(1)) see https://maity.dev/x, and http://plain.example");
  const mdA = mdLinks.querySelectorAll("a");
  expect(mdA.length === 2 && mdA[0].getAttribute("href") === "https://example.org/a" && mdA[0].getAttribute("rel") === "noopener noreferrer"
    && mdA[1].getAttribute("href") === "https://maity.dev/x" && text(mdLinks).includes("[no](javascript:alert(1))") && text(mdLinks).includes("http://plain.example"),
    "markdown: links only when plain https, the rest as written");
  const mdBlock = MD("# Title\n- one\n- two\n1. first\n> quoted\n> more\n\n```js\nconst a = `x`;\n```");
  expect(JSON.stringify(tagsOf(mdBlock)) === '["p","ul","ol","blockquote","div"]' && mdBlock.childNodes[0].querySelector("strong") && mdBlock.querySelectorAll("ul li").length === 2
    && text(mdBlock.querySelector("blockquote")).includes("quoted") && mdBlock.querySelector("pre code").textContent === "const a = `x`;"
    && text(mdBlock.querySelector(".md-lang")) === "js" && btn(mdBlock, "Copy"), "markdown: a heading kept small, lists, a quote, a fenced block with its language and Copy");
  btn(mdBlock, "Copy").click(); await tick();
  expect(ctx.copied === "const a = `x`;", "markdown: Copy puts the code on the clipboard");
  const mdPre = mdBlock.querySelector("pre");
  expect(mdPre.getAttribute("role") === "region" && /^Code \(js\), block \d+$/.test(mdPre.getAttribute("aria-label"))
    && btn(mdBlock, "Copied").getAttribute("aria-label") === "Copy " + mdPre.getAttribute("aria-label")
    && mdBlock.querySelector(".md-code-bar .md-lang"), "markdown: a code block is a named region, its Copy names it, language and Copy in the block's corner");
  expect(thCss.includes(".md-code { margin: 0; padding: 36px 10px 8px;"), "markdown: the code block keeps a row of its own for language and Copy, no line runs under them");
  // Inline code copies on a click or Enter (tsk-rdx6gaqveygx), "Copied" said beside it.
  const mdInline = MD("Run `maity wait --batch` now");
  const mdCode = mdInline.querySelector("code.md-inline-copy");
  expect(mdCode && mdCode.getAttribute("role") === "button" && mdCode.getAttribute("tabindex") === "0" && mdCode.getAttribute("aria-label") === "Copy maity wait --batch"
    && mdCode.textContent === "maity wait --batch", "markdown: inline code is a button that names what it copies");
  ctx.copied = null;
  mdCode.click(); await tick();
  expect(ctx.copied === "maity wait --batch" && text(mdInline.querySelector(".md-copied")) === "Copied", "markdown: a click on inline code copies it and says Copied");
  ctx.copied = null;
  mdCode.dispatch("keydown", { key: "Enter" }); await tick();
  expect(ctx.copied === "maity wait --batch", "markdown: Enter on inline code copies it too");
  ctx.copied = null;
  mdCode.dispatch("keydown", { key: " " }); await tick();
  expect(ctx.copied === "maity wait --batch", "markdown: Space on inline code copies it too");
  // A selection elsewhere on the page swallows neither a key nor a click; one inside the code stops the click only.
  const mdSel = win.getSelection;
  win.getSelection = () => ({ isCollapsed: false, toString: () => "other text", containsNode: () => false });
  ctx.copied = null;
  mdCode.dispatch("keydown", { key: "Enter" }); await tick();
  mdCode.click(); await tick();
  const mdElsewhere = ctx.copied;
  win.getSelection = () => ({ isCollapsed: false, toString: () => "wait", containsNode: (n) => n === mdCode });
  ctx.copied = null;
  mdCode.click(); await tick();
  const mdInside = ctx.copied;
  mdCode.dispatch("keydown", { key: "Enter" }); await tick();
  expect(mdElsewhere === "maity wait --batch" && mdInside === null && ctx.copied === "maity wait --batch",
    "markdown: only a selection inside the code stops a click's copy; Enter copies regardless");
  win.getSelection = mdSel;

  // Ids in text become links (js/ids.js, tsk-dcj6qwjxc9cq): by shape only, the id as the link's text.
  const IDS = win.Maity.ids;
  const idAt = { slug: "maintainer/maity", repository: "https://github.com/oliver-zehentleitner/maity" };
  const idBox = (nodes) => { const box = document.createElement("div"); win.Maity.dom.append(box, nodes); return box; };
  const idHrefs = (box) => box.querySelectorAll("a.id-ref").map((a) => text(a) + "=" + a.getAttribute("href")).join(" ");
  const idAll = idBox(IDS.link("See tsk-0123456789ab, req-abcdefghjkmn; ask agt-mbf0gthrsash or hum-mebxvnc20qeg about #340.", idAt));
  expect(idHrefs(idAll) === "tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab req-abcdefghjkmn=#/maintainer/maity/inbox/req-abcdefghjkmn "
    + "agt-mbf0gthrsash=#/maintainer/maity/members/agt-mbf0gthrsash hum-mebxvnc20qeg=#/maintainer/maity/members/hum-mebxvnc20qeg #340=https://github.com/oliver-zehentleitner/maity/issues/340"
    && text(idAll) === "See tsk-0123456789ab, req-abcdefghjkmn; ask agt-mbf0gthrsash or hum-mebxvnc20qeg about #340.",
    "ids: card, request, agent, human and #n become links, the text unchanged " + idHrefs(idAll));
  const idForge = idAll.querySelectorAll("a.id-ref").find((a) => text(a) === "#340");
  expect(idForge.getAttribute("target") === "_blank" && idForge.getAttribute("rel") === "noopener noreferrer"
    && !idAll.querySelectorAll("a.id-ref").find((a) => text(a) === "tsk-0123456789ab").getAttribute("target"),
    "ids: a forge number opens the forge in a new tab, an id stays in the dashboard");
  const idNone = idBox(IDS.link("tsk-0001 tsk-0123456789abc xtsk-0123456789ab tsk-0123456789ab_x tsk-0123456789aI prj-0123456789ab "
    + "https://x.example/tsk-0123456789ab page#12 #0 #12345678 a.tsk-0123456789ab", idAt));
  expect(!idNone.querySelector("a"), "ids: not well-formed, part of a word, a URL or a path, or another prefix: plain text");
  expect(!idBox(IDS.link("tsk-0123456789ab #12", { slug: null, repository: null })).querySelector("a")
    && idHrefs(idBox(IDS.link("tsk-0123456789ab #12", { slug: "maintainer/maity", repository: "https://gitlab.com/o/r" }))) === "tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab"
    && idHrefs(idBox(IDS.link("tsk-0123456789ab #12", { slug: null, repository: "https://github.com/o/r.git" }))) === "#12=https://github.com/o/r/issues/12",
    "ids: without a project no id links, without a GitHub repository no number does");
  // An id is one unit, linked or not (the designer's pass part 3): an unlinked one in the code face too.
  const idPlain = idBox(IDS.link("see tsk-0123456789ab and #12", { slug: null, repository: "https://github.com/o/r" }));
  expect(text(idPlain) === "see tsk-0123456789ab and #12" && idPlain.querySelectorAll("span.id-ref").map((x) => text(x)).join() === "tsk-0123456789ab"
    && idHrefs(idPlain) === "#12=https://github.com/o/r/issues/12",
    "ids: an id that links nowhere still reads as one (span.id-ref) beside the links");
  expect(thCss.includes(".id-ref { font-family: var(--mono); font-size: 0.9em; white-space: nowrap; }") && thCss.includes("a.id-ref { text-decoration: none; }"),
    "ids: never broken across lines, underlined only on hover");
  const mdIds = idBox(win.Maity.markdown("Do tsk-0123456789ab **after #12**, not `tsk-0123456789ab`; [tsk-0123456789ab](https://example.org/x)\n\n```\nreq-abcdefghjkmn\n```", idAt));
  expect(idHrefs(mdIds) === "tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab #12=https://github.com/oliver-zehentleitner/maity/issues/12"
    && mdIds.querySelector("strong a.id-ref") && mdIds.querySelector("code").textContent === "tsk-0123456789ab" && !mdIds.querySelector("pre a"),
    "ids: in Markdown linked in text and emphasis, plain in code spans, fenced code and a link's own text " + idHrefs(mdIds));
  expect(!MD("tsk-0123456789ab").querySelector("a"), "ids: Markdown without the text's project links no id");
  const idOut = IDS.where({ slug: "maintainer/maity", outsider: true, project: { repository: { url: "https://github.com/o/r" } } });
  expect(idOut.slug === null && idOut.repository === null && !idBox(win.Maity.markdown("See tsk-0123456789ab and #4", idOut)).querySelector("a.id-ref"),
    "ids: read along from outside a project, nothing links");
  expect(IDS.forgeBase("https://github.com/o/r/tree/main") === "https://github.com/o/r" && IDS.forgeBase("https://GitHub.com/o/r") === "https://github.com/o/r"
    && IDS.forgeBase("https://github.com/o/r.git") === "https://github.com/o/r" && IDS.forgeBase("https://gitlab.com/o/r") === null && IDS.forgeBase("https://github.com/o") === null,
    "ids: the repository read as the hub reads it — any case of github.com, owner and name the first two segments");
  const wmIds = idBox(win.Maity.dom.withMentions("@agent-b see tsk-0123456789ab", [{ field: "body", offset: 0, length: 8, handle: "agent-b", member_id: "agt-b" }],
    "body", (id) => "/m/" + id, idAt));
  expect(wmIds.querySelector("a.mention").getAttribute("href") === "#/m/agt-b" && idHrefs(wmIds) === "tsk-0123456789ab=#/maintainer/maity/tasks/tsk-0123456789ab",
    "ids: between mentions the text's ids are links, the mention stays the hub's");
  // An id's pages: #/<owner>/<slug>/tasks/<id> is the board with the card marked and focused, its tab the
  // board's; #/<owner>/<slug>/inbox/<id> opens the request. An id neither holds is said.
  const idProto = Object.getPrototypeOf(main);
  const idFocus = idProto.focus;
  idProto.focus = function () { document.activeElement = this; };
  await go("#/maintainer/maity/tasks/tsk-0004"); for (let k = 0; k < 4; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const idCard = main.querySelectorAll("article.card").find((a) => a.attrs["data-card"] === "tsk-0004");
  const boardTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent.startsWith("Board"));
  const cpPanel = () => main.querySelector("aside.card-panel");
  expect(idCard && idCard.classList.contains("wanted") && main.querySelectorAll("article.card.wanted").length === 1
    && cpPanel() && document.activeElement === byId("card-panel-title") && text(byId("card-panel-title")) === idCard.getAttribute("aria-label")
    && text(cpPanel().querySelector(".card-panel-head .card-id")) === "tsk-0004"
    && boardTab().getAttribute("aria-current") === "page" && main.querySelector("section.view-board"),
    "ids: a card's link opens the card's panel on the board, the card marked there, the Board tab current");
  // The designer's pass part 2: the panel is the card (one id, in the bar; the title its heading), the controls right
  // under the claim line, one style of section heading, and on a phone the panel alone.
  const dpCard = cpPanel().querySelector(".card-panel-card article.card");
  const dpKids = dpCard.childNodes.map((x) => x.className || x.tagName);
  const dpClaim = dpKids.findIndex((k) => /claim/.test(String(k)));
  expect(dpKids.indexOf("card-actions") > -1 && (dpClaim < 0 || dpKids.indexOf("card-actions") === dpClaim + 1)
    && thCss.includes(".card-panel .card > header .card-id, .card-panel .card > h3 { display: none; }")
    && thCss.includes(".card-panel h3, .card-panel h4 { font-size: 0.85rem; text-transform: uppercase;")
    && /@media \(max-width: 600px\) \{\s*\.board-body\.has-panel > \.columns \{ display: none; \}/.test(thCss),
    "card panel: one id and one title, the controls right under the claim, one heading style, the panel alone on a phone " + JSON.stringify(dpKids));
  // A refresh that brings a new title brings it to the panel's heading too (H on #461).
  const rtCard = (title) => { const a = document.createElement("article"); a.setAttribute("aria-label", title); return a; };
  const rtPanel = win.Maity.cardPanel.render({ slug: "maintainer/maity", project: { state: "build", repository: null }, base: "/projects/maintainer/maity", link: (v, id) => "/maintainer/maity/" + v + "/" + id, me: { id: "hum-maintainer", kind: "human" }, members: [], memberById: {} }, { id: "tsk-0004", title: "Old title", links: [] }, rtCard("Old title"), () => {});
  rtPanel.update(rtCard("New title"));
  expect(text(rtPanel.el.querySelector(".panel-title")) === "New title", "card panel: a refresh's new title reaches the heading");
  // The opened card (js/card-panel.js): the card with its controls, the body, the open notes with a form, the history.
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const cpCard = () => main.querySelector(".columns").querySelectorAll("article.card").find((a) => a.attrs["data-card"] === "tsk-0001");
  expect(!cpPanel() && main.querySelectorAll("article.card.wanted").length === 1 && document.activeElement === main.querySelectorAll("article.card.wanted")[0].querySelector("a.card-open"),
    "card panel: back on the board, the card that was open is marked and its title focused");
  const cpLink = cpCard().querySelector("a.card-open");
  expect(cpLink && cpLink.getAttribute("href") === "#/maintainer/maity/tasks/tsk-0001" && text(cpLink) === "API contract: docs/api.md", "card panel: a card's title is the link that opens it");
  const cpGets = [], cpPosts = [];
  const cpGet = win.Maity.api.get, cpGetAll = win.Maity.api.getAll, cpPost = win.Maity.api.post;
  win.Maity.api.get = (p) => { if (p.includes("/tasks/tsk-0001/")) cpGets.push(p); return cpGet(p); };
  win.Maity.api.getAll = (p) => { if (p.includes("/tasks/tsk-0001/")) cpGets.push(p); return cpGetAll(p); };
  win.Maity.api.post = (p, b) => { if (p.includes("/notes")) cpPosts.push([p, b]); return cpPost(p, b); };
  await go(cpLink.getAttribute("href")); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const cpNotes = () => cpPanel().querySelectorAll(".card-note-list li").map((li) => text(li));
  expect(cpPanel() && cpPanel().querySelector(".card-panel-card article.card") && cpPanel().querySelector(".card-panel-card article.card .card-actions")
    && !cpPanel().querySelector(".card-panel-card a.card-open") && !cpPanel().querySelector(".card-panel-card article.card").getAttribute("draggable")
    && text(cpPanel().querySelector(".card-body")) === "The REST contract hub, CLI and dashboard build against."
    && JSON.stringify(cpNotes()) === JSON.stringify(["@agent-c · " + win.Maity.dom.formatTime("2026-10-21T10:30:00Z") + "The CLI needs --no-code here too."])
    && cpGets.includes("/projects/maintainer/maity/tasks/tsk-0001/notes?state=open"),
    "card panel: the card with its controls (no link to itself, not dragged), the body as Markdown, the open notes only " + JSON.stringify(cpNotes()));
  const cpHist = cpPanel().querySelectorAll(".card-history-list li").map((li) => text(li));
  expect(cpHist.length === 3 && cpHist[0].startsWith("@maintainer changed the description") && cpPanel().querySelector("pre.history-diff").textContent.includes("+The REST contract hub")
    && cpHist[1].startsWith("@maintainer changed the label: fix → feature") && cpHist[2].startsWith("@agent-a created the card"),
    "card panel: the history, newest first, a description's change as its diff " + JSON.stringify(cpHist));
  byId("card-note-body").value = "  "; cpPanel().querySelector("form.card-note-form").dispatch("submit"); await tick();
  expect(!cpPosts.length, "card panel: an empty note is not sent");
  byId("card-note-body").value = "Check §6.16 too."; cpPanel().querySelector("form.card-note-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(cpPosts[0]) === JSON.stringify(["/projects/maintainer/maity/tasks/tsk-0001/notes", { body: "Check §6.16 too." }])
    && cpNotes().length === 2 && cpNotes()[1].startsWith("@maintainer") && document.activeElement === byId("card-note-body") && byId("card-note-body").value === "",
    "card panel: a note is posted and listed, the form ready for the next");
  // A second submit while the first post is on its way sends nothing; a refusal lets it be sent again.
  let cpRelease = null;
  win.Maity.api.post = (p, b) => {
    if (!p.includes("/notes")) return cpPost(p, b);
    cpPosts.push([p, b]);
    return new Promise((resolve, reject) => { cpRelease = () => reject(new win.Maity.api.ApiError("busy", 503, p, "unavailable")); });
  };
  const cpBefore = cpPosts.length;
  byId("card-note-body").value = "Twice?";
  const cpForm = () => cpPanel().querySelector("form.card-note-form");
  cpForm().dispatch("submit"); cpForm().dispatch("submit"); await tick();
  expect(cpPosts.length === cpBefore + 1 && btn(cpForm(), "Post the note").disabled, "card panel: a note is posted once while the first post is pending, its button disabled");
  cpRelease(); for (let k = 0; k < 3; k++) await tick();
  expect(!btn(cpForm(), "Post the note").disabled && byId("card-note-body").value === "Twice?" && text(cpForm()).includes("Not posted"),
    "card panel: a refused post keeps the text and the button usable again");
  win.Maity.api.post = (p, b) => { if (p.includes("/notes")) cpPosts.push([p, b]); return cpPost(p, b); };
  cpForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(cpPosts.length === cpBefore + 2 && cpNotes().length === 3, "card panel: the note is sent again after the refusal");
  // Escape closes, as Close does: the board again, the card marked, its title focused.
  cpPanel().dispatch("keydown", { key: "Escape" }); for (let k = 0; k < 4; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  expect(win.location.hash === "#/maintainer/maity/board" && !cpPanel() && cpCard().classList.contains("wanted") && document.activeElement === cpCard().querySelector("a.card-open"),
    "card panel: Escape goes back to the board, the card marked and its title focused");
  await go("#/maintainer/maity/tasks/tsk-0001"); for (let k = 0; k < 6; k++) await tick();
  btn(cpPanel(), "Close").click(); for (let k = 0; k < 4; k++) await tick();
  expect(win.location.hash === "#/maintainer/maity/board" && !cpPanel(), "card panel: Close goes back to the board");
  // Opened from a filtered, searched board: the filters and the search stay, opening and going back.
  byId("board-column").value = "in_progress"; byId("board-column").dispatch("change"); await tick();
  byId("board-search").value = "API contract"; byId("board-search").dispatch("input"); await tick();
  const cpLink2 = cpCard().querySelector("a.card-open");
  cpLink2.click(); await go(cpLink2.getAttribute("href")); for (let k = 0; k < 6; k++) await tick();
  expect(cpPanel() && byId("board-column").value === "in_progress" && byId("board-search").value === "API contract"
    && main.querySelector(".columns").querySelectorAll("article.card").length === 1,
    "card panel: a title opens its card on the board as it was, filter and search kept");
  cpPanel().dispatch("keydown", { key: "Escape" }); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  expect(!cpPanel() && byId("board-column").value === "in_progress" && byId("board-search").value === "API contract"
    && cpCard() && cpCard().classList.contains("wanted") && document.activeElement === cpCard().querySelector("a.card-open"),
    "card panel: back on the board, the filter and the search as they were, the card marked and its title focused");
  // A link from elsewhere still reveals its card whatever the filter says.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/tasks/tsk-0004"); for (let k = 0; k < 6; k++) await tick();
  expect(cpPanel() && byId("board-column").value === "" && byId("board-search").value === "", "card panel: a link from elsewhere opens its card with every column shown");
  // An action in the panel keeps the focus in the panel, on its redrawn control.
  const cpMove = () => cpPanel().querySelector(".card-move .menu-button");
  const cpPick = async (label) => {
    cpMove().click(); await tick();
    const item = cpPanel().querySelectorAll(".card-move .menu-item").find((el) => el.textContent === label);
    if (item) { item.click(); for (let k = 0; k < 6; k++) await tick(); }
    return !!item;
  };
  await go("#/maintainer/maity/tasks/tsk-0006"); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const cpMoved = await cpPick("Move to Proposed");
  expect(cpMoved && cpPanel() && cpPanel().contains(document.activeElement) && document.activeElement === cpMove()
    && text(cpMove()).startsWith("Proposed"),
    "card panel: a move from the panel redraws its card there and keeps the focus on its menu");
  // A move that leaves no control to return to (done: no menu) keeps the focus in the panel, on its heading.
  await go("#/maintainer/maity/tasks/tsk-0005"); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const cpDone = await cpPick("Move to Done");
  expect(cpDone && !cpMove() && document.activeElement === byId("card-panel-title"),
    "card panel: a move to done, its menu gone, leaves the focus on the panel's heading");
  cpPanel().dispatch("keydown", { key: "Escape" }); for (let k = 0; k < 4; k++) await tick();
  expect(!cpPanel(), "card panel: after an action Escape still closes it");
  // A hub without notes or history says so in the panel, nothing asked.
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ paths: {} }) : cpGet(p));
  win.Maity.api.forgetRoutes(); cpGets.length = 0;
  await go("#/maintainer/maity/tasks/tsk-0001"); for (let k = 0; k < 6; k++) await tick();
  expect(cpPanel() && text(cpPanel()).includes("This hub has no notes yet.") && text(cpPanel()).includes("This hub has no card history yet.") && !cpGets.length,
    "card panel: a hub without notes or history says so and is not asked");
  win.Maity.api.get = cpGet; win.Maity.api.getAll = cpGetAll; win.Maity.api.post = cpPost; win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/tasks/tsk-zzzzzzzzzzzz"); for (let k = 0; k < 4; k++) await tick();
  expect(!main.querySelector("article.card.wanted") && text(main.querySelector(".wanted-note")).startsWith("No card tsk-zzzzzzzzzzzz on the board"),
    "ids: a card the board does not hold is said");
  const idShown = () => (byId("inbox-show").querySelectorAll("option").find((o) => "selected" in o.attrs || o.selected) || { attrs: {} }).attrs.value;
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const idShowBefore = idShown();
  byId("inbox-show").value = "open"; byId("inbox-show").dispatch("change"); await tick();
  await go("#/maintainer/maity/inbox/req-0009"); for (let k = 0; k < 4; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const idEntry = main.querySelector("li.entry.current");
  expect(idEntry && idEntry.attrs["data-request"] === "req-0009" && idEntry.classList.contains("done") && document.activeElement === idEntry.querySelector("button.entry-head"),
    "ids: a request's link opens it, an answered one among the answered, its head focused");
  await go("#/maintainer/maity/inbox/req-0011"); for (let k = 0; k < 4; k++) await tick();
  const idTitle = main.querySelector("li.entry.current .title-refs");
  expect(idTitle && idHrefs(idTitle) === "#2=https://github.com/oliver-zehentleitner/maity/issues/2" && !main.querySelector("li.entry.current button.entry-head a"),
    "ids: the ids of a request's title are links in its body, never inside its button");
  await go("#/maintainer/maity/inbox/req-zzzzzzzzzzzz"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector(".wanted-note")) === "No request req-zzzzzzzzzzzz in this project's inbox.", "ids: a request the inbox does not hold is said");
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  expect(idShown() === "open" && !main.querySelectorAll("li.entry").some((li) => li.attrs["data-request"] === "req-0009"),
    "ids: after a deep link to an answered request the inbox's own choice (open) stands");
  if (idShowBefore === "all") { byId("inbox-show").value = "all"; byId("inbox-show").dispatch("change"); await tick(); }
  idProto.focus = idFocus; document.activeElement = undefined;
  await go("#/maintainer/maity/inbox");
  // A deep quote stops nesting instead of overflowing the stack.
  const mdDeep = MD(">".repeat(5000) + " deep");
  let quoteDepth = 0;
  for (let q = mdDeep.querySelector("blockquote"); q; q = q.querySelector("blockquote")) quoteDepth += 1;
  expect(quoteDepth === 8 && mdDeep.querySelector(".md-deep") && text(mdDeep).includes("deep"), "markdown: quotes nest at most eight deep, the rest as written");
  const mdFences = MD("```python title=x.py\nprint(1)\n```\n  ~~~~\n```\nstill code\n~~~~~\n3. three\n4. four");
  const mdCodes = mdFences.querySelectorAll("pre code");
  expect(mdCodes.length === 2 && mdCodes[0].textContent === "print(1)" && text(mdFences.querySelector(".md-lang")) === "python"
    && mdCodes[1].textContent === "```\nstill code" && mdFences.querySelector("ol").getAttribute("start") === "3",
    "markdown: a fence with an info string, an indented tilde fence closed only by a long enough one, a list starting at 3");
  const mdInfo = MD("``` not `a` fence\ntext");
  expect(!mdInfo.querySelector("pre"), "markdown: a backtick fence whose info string has a backtick is no fence");
  const mdTrick = MD("[https://bank.example](https://evil.example/x) [a](https://bank.example@evil.example) [b](https://ev\u202eil.example)");
  expect(mdTrick.querySelectorAll("a").length === 1 && text(mdTrick).includes("(goes to evil.example)")
    && text(mdTrick).includes("[a](https://bank.example@evil.example)"),
    "markdown: a link text that looks like another address says where it goes; userinfo and bidi characters are no link");
  expect(MD("```\nif (a\u202e) {}\n```").querySelector(".md-invisible"), "markdown: code with invisible characters is flagged");
  const linear = Date.now(); MD("[".repeat(20000) + "x"); expect(Date.now() - linear < 1000, "markdown: unclosed brackets stay linear");

  // A chat's rows are as tall as their message: the list fills the pane, its rows do not.
  expect(/\.messages \{[^}]*display: grid;[^}]*align-content: start;/.test(fs.readFileSync(path.join(WEB, "css/app.css"), "utf8")),
    "chat: the message grid packs its rows at the top instead of stretching them");
  // Chat: the chats left, the open one right (docs/api.md §9).
  await go("#/maintainer/maity/chat");
  const convs = () => main.querySelectorAll(".chat-list a.conv");
  const conv = (name) => convs().find((a) => a.querySelector(".conv-title").textContent === name);
  // Own agents' direct chats and the fixtures' one group chat (§9.3).
  expect(convs().length === 6 && text(main).includes("Pick a conversation.") && !main.querySelector(".chat-pane"), "chat: the list of own agents and group chats, nothing open yet");
  // Unread first (the group chat with a mention, Agent A), then the newest; without messages last.
  const convOrder = () => convs().map((a) => a.querySelector(".conv-title").textContent + (a.classList.contains("unread") ? "*" : ""));
  expect(JSON.stringify(convOrder()) === JSON.stringify(["Release 0.2 go/no-go*", "Agent A*", "Agent D", "Agent B", "Agent C", "Reviewer"]),
    "chat: unread first, then the newest, the ones without messages after " + JSON.stringify(convOrder()));
  const convA = conv("Agent A");
  expect(convA.getAttribute("href") === "#/maintainer/maity/chat/agt-a" && text(convA).includes("Endpoints for join, tasks and requests are drafted.")
    && convA.querySelector(".count") && convA.querySelector(".count").textContent === "1" && convA.classList.contains("unread")
    && text(convA).includes("online") && convA.querySelector(".avatars svg").style["--avatar-h"] === "340",
    "chat: an entry has the agent, the last message, its time, the unread count, presence and an avatar");
  expect(text(conv("Agent D")).includes("You: Keep the inbox usable"), "chat: one's own last message reads You:");
  expect(!conv("Agent B").querySelector(".preview") && text(conv("Agent C")).includes("paused"), "chat: no messages, no preview; presence in words");
  // Names that share their owner's long prefix (Oliver's list: every row read "Oliver Zehentleit…"): whole, wrapped, and told apart.
  const clLong = (r) => ({ items: r.items.map((m) => (m.kind === "agent" && m.owner_id === "hum-maintainer"
    ? Object.assign({}, m, { display_name: "Oliver Zehentleitner " + m.display_name, handle: "oz-" + m.handle }) : m)), next_cursor: null });
  const clGet = win.Maity.api.getAll, clGet1 = win.Maity.api.get;
  win.Maity.api.getAll = (p) => (p.startsWith("/projects/maintainer/maity/members") ? clGet(p).then(clLong) : clGet(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? clGet1(p).then(clLong) : clGet1(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat"); for (let k = 0; k < 4; k++) await tick();
  const clRow = (tail) => convs().find((a) => a.querySelector(".conv-title").textContent === "Oliver Zehentleitner " + tail);
  expect(clRow("Agent A") && clRow("Agent D") && clRow("Agent A").querySelector(".conv-title").getAttribute("title") === "Oliver Zehentleitner Agent A"
    && text(clRow("Agent A").querySelector(".conv-sub")).includes("@oz-agent-a") && text(clRow("Agent D").querySelector(".conv-sub")).includes("@oz-agent-d"),
    "chat list: names with a shared prefix are whole, with the full name as a tooltip, and told apart by their handles");
  expect(clRow("Agent A").querySelector(".conv-time") && !clRow("Agent A").querySelector(".conv-title .conv-time")
    && clRow("Agent A").querySelector(".conv-time").parentNode === clRow("Agent A"),
    "chat list: the time is its own cell beside the name, never inside it");
  expect(text(clRow("Agent A").querySelector(".conv-sub")).startsWith("agent · ") && !text(clRow("Agent A").querySelector(".conv-sub")).includes("online")
    && text(convs().find((a) => a.querySelector(".conv-title").textContent === "Release 0.2 go/no-go").querySelector(".conv-sub")).startsWith("group · "),
    "chat list: an agent and a group are marked as such; presence is the dot, not a line");
  win.Maity.api.getAll = clGet; win.Maity.api.get = clGet1;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat");
  // The header's link rows no longer style every nav: the chat list was a squeezed row of one-line links.
  const clCss = fs.readFileSync(path.join(WEB, "css/app.css"), "utf8");
  expect(!/(^|\n)nav \{/.test(clCss) && !/(^|\n)nav a \{/.test(clCss) && /nav\.switcher, nav\.views \{/.test(clCss)
    && !/\.conv-title \{[^}]*nowrap/.test(clCss) && /@media \(max-width: 720px\) \{\s*\.chat-layout \{ grid-template-columns: minmax\(0, 1fr\); \}/.test(clCss),
    "chat list: no header rule reaches it, its names wrap, and a phone shows it as one column");
  await go("#/maintainer/maity/chat/agt-a");
  expect(main.querySelectorAll(".msg").length === 2, "conversation with A");
  expect(main.querySelector("li.msg.in .md p") && main.querySelector("li.msg.in .md br"), "chat: an agent's message is drawn as Markdown, its line break kept");
  const quoteBtn = main.querySelector("li.msg.in").querySelectorAll("button").find((b) => b.textContent === "Quote");
  quoteBtn.click(); await tick();
  expect(byId("chat-text").value.startsWith("> Agent A:\n> Endpoints for join, tasks and requests are drafted.\n> Messages and presence follow this afternoon.\n\n"),
    "chat: Quote puts the message into the composer as a quote");
  byId("chat-text").value = ""; byId("chat-text").dispatch("input");
  // The history: a day separator, the line before what was unread, the agent's picture.
  const histItems = main.querySelector("ol.messages").childNodes.map((li) => li.className);
  expect(JSON.stringify(histItems) === JSON.stringify(["day", "msg out", "new-line", "msg in"]) && /^(Yesterday|.*2026.*)$/.test(text(main.querySelector("li.day"))),
    "chat: a day separator, then 'New messages' before the agent's unread reply " + JSON.stringify(histItems));
  expect(main.querySelector("li.msg.in .msg-avatar svg") && !main.querySelector("li.msg.out .msg-avatar"), "chat: the agent's messages carry its picture, one's own none");
  expect(main.querySelector(".chat-list-pane") && conv("Agent A").getAttribute("aria-current") === "page" && conv("Agent A").classList.contains("current")
    && !conv("Agent A").querySelector(".count"), "chat: the list stays beside the open chat; the open one is marked, its unread gone");
  // Messages of one sender close together are grouped; a day apart, separated; the empty chat says what happens.
  const hGet = win.Maity.api.get;
  const at = (min) => new Date(Date.parse("2026-10-21T10:00:00Z") + min * 60000).toISOString();
  // A conversation's messages as the hub pages them (docs/api.md §9.1): before= the limit below, after= forward.
  const convStub = (all, reads) => (p) => {
    const q = new URLSearchParams(p.split("?")[1] || "");
    reads.push(p);
    const limit = Number(q.get("limit") || 200);
    const items = q.get("before") !== null ? all.filter((m) => m.seq < Number(q.get("before"))).slice(-limit)
      : all.filter((m) => m.seq > Number(q.get("after") || 0)).slice(0, limit);
    const earlier = items.length && all.some((m) => m.seq < items[0].seq) ? items[0].seq : null;
    return Promise.resolve({ items, earlier, cursor: q.get("before") !== null ? 0 : (items.length ? items[items.length - 1].seq : 0) });
  };
  const shortReads = [];
  const shortConv = convStub([
    { id: "e1", seq: 1, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "one", sent_at: at(0), delivered_at: at(0) },
    { id: "e2", seq: 2, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "two", sent_at: at(2), delivered_at: at(2) },
    { id: "e3", seq: 3, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "later", sent_at: at(20), delivered_at: at(20) },
    { id: "e4", seq: 4, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "next day", sent_at: at(24 * 60), delivered_at: at(24 * 60) },
  ], shortReads);
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/conversations/agt-c/messages?") ? shortConv(p) : hGet(p));
  await go("#/maintainer/maity/chat/agt-c");
  const gl = main.querySelector("ol.messages").childNodes.map((li) => li.className);
  expect(JSON.stringify(gl) === JSON.stringify(["day", "msg in", "msg in grouped", "msg in", "day", "msg in"])
    && !main.querySelectorAll("li.msg")[1].querySelector(".msg-avatar"), "chat: within five minutes grouped without the picture again; a new day separated " + JSON.stringify(gl));
  win.Maity.api.get = hGet;
  // A long history (tsk-r1adgwp0a5dr): opening reads the newest page only, in two requests (back, then forward,
  // which marks it read), whatever the length; older pages come on scroll-up, one at a time, never twice.
  // Measured on 2000 messages: before, 10 requests and 2000 messages drawn; now 2 requests and 50.
  const longMsg = (seq) => ({ id: "l" + seq, seq, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "m" + seq, sent_at: at(seq), delivered_at: at(seq) });
  const longReads = [];
  const longConv = convStub(Array.from({ length: 2000 }, (_, i) => longMsg(i + 1)), longReads);
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/conversations/agt-c/messages?") ? longConv(p) : hGet(p));
  const hAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/conversations?observed=true"
    ? hAll(p).then((r) => ({ items: r.items.map((c) => (c.agent_id === "agt-c" ? Object.assign({}, c, { unread: 3, last_message: { seq: 2000, from: "agt-c", body: "m2000", sent_at: at(2000), redacted: false } }) : c)), next_cursor: null })) : hAll(p));
  await go("#/maintainer/maity/chat/agt-c");
  const histList = main.querySelector("ol.messages");
  const nl = histList.childNodes.findIndex((li) => li.className === "new-line");
  expect(longReads.length === 2 && /before=2001&limit=50$/.test(longReads[0]) && /after=1950&limit=50$/.test(longReads[1])
    && histList.querySelectorAll("li.msg").length === 50 && nl > 0 && histList.childNodes[nl + 1].attrs["data-seq"] === "1998",
    "chat: a 2000-message chat opens with its newest 50 in two requests, the unread line before the first unread " + JSON.stringify(longReads));
  // Near the top, the page before; a second scroll while it is read asks nothing more.
  histList.scrollTop = 0; histList.dispatch("scroll"); histList.dispatch("scroll"); for (let k = 0; k < 4; k++) await tick();
  expect(longReads.length === 3 && /before=1951&limit=50$/.test(longReads[2]) && histList.querySelectorAll("li.msg").length === 100
    && histList.querySelectorAll("li.msg")[0].attrs["data-seq"] === "1901" && main.querySelectorAll(".chat-pane .earlier button").length === 1,
    "chat: scrolled to the top, the 50 before are read once and drawn in front; Show earlier messages stays for a keyboard");
  btn(main.querySelector(".chat-pane .earlier"), "Show earlier messages").click(); for (let k = 0; k < 4; k++) await tick();
  expect(longReads.length === 4 && histList.querySelectorAll("li.msg").length === 150, "chat: Show earlier messages reads the next page before");
  win.Maity.api.get = hGet;
  // The unread count that cannot be read draws no line, and says so.
  win.Maity.api.get = hGet;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/conversations?observed=true" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : hAll(p));
  await go("#/maintainer/maity/chat/agt-a");
  expect(!main.querySelector("li.new-line") && text(main).includes("Which messages are new could not be read: down"), "chat: a failed unread read is said");
  win.Maity.api.getAll = hAll;
  await go("#/maintainer/maity/chat/agt-b");
  expect(text(main.querySelector("ol.messages")).includes("No messages yet.") && text(main.querySelector("ol.messages")).includes("reads what you write here at its next wait or resume"),
    "chat: an empty chat says when the agent reads it");
  await go("#/maintainer/maity/chat/agt-a");
  // A draft per chat survives switching to another chat and back.
  main.querySelector("textarea").value = "half a thought"; main.querySelector("textarea").dispatch("input");
  await go("#/maintainer/maity/chat/agt-d");
  expect(main.querySelector("textarea").value === "" && text(conv("Agent A")).includes("Draft: half a thought"), "chat: switching keeps the draft, shown in the list");
  await go("#/maintainer/maity/chat/agt-a");
  expect(main.querySelector("textarea").value === "half a thought", "chat: the draft is back in its chat");
  expect(!text(conv("Agent A")).includes("Draft:"), "chat: the open chat's draft is in its composer, not in its row");
  expect(!conv("Agent D").getAttribute("aria-label") && /^Agent D, online, .+, agent · @agent-d · Claude Code: You: Keep the inbox/.test(text(conv("Agent D"))),
    "chat: a row's name is its text, its parts apart " + JSON.stringify(text(conv("Agent D"))));
  main.querySelector("textarea").value = ""; main.querySelector("textarea").dispatch("input");
  // A redacted last message.
  const cAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maintainer/maity/conversations?observed=true" ? r : { items: r.items.map((c) => (c.agent_id !== "agt-d" ? c
    : Object.assign({}, c, { last_message: Object.assign({}, c.last_message, { body: null, redacted: true }) }))), next_cursor: null }));
  await go("#/maintainer/maity/chat");
  expect(text(conv("Agent D")).includes("A message was removed.") && !text(conv("Agent D")).includes("null"), "chat: a redacted last message");
  // A hub before last_message: no preview, the rest stays.
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maintainer/maity/conversations?observed=true" ? r
    : { items: r.items.map((c) => { const o = Object.assign({}, c); delete o.last_message; return o; }), next_cursor: null }));
  await go("#/maintainer/maity/chat");
  expect(convs().length === 6 && !main.querySelector(".chat-list .preview"), "chat: a hub without last_message shows no preview");
  // A refresh asked for while a read runs is read once more after it.
  let convReads = 0;
  win.Maity.api.getAll = (p) => {
    if (p !== "/projects/maintainer/maity/conversations?observed=true") return cAll(p);
    convReads += 1;
    return new Promise((r) => setTimeout(r, 40)).then(() => cAll(p));
  };
  await go("#/maintainer/maity/chat"); await new Promise((r) => setTimeout(r, 120));
  convReads = 0;
  await fireIntervals(); await fireIntervals(); await new Promise((r) => setTimeout(r, 150));
  expect(convReads === 2, "chat: two refreshes during one read make one more read, not none " + convReads);
  win.Maity.api.getAll = cAll;
  // Agents appearing later fill an empty list.
  const cGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? cGet(p).then((r) => ({ items: r.items.filter((m) => m.kind === "human"), next_cursor: null })) : cGet(p));
  const cAll2 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/conversations?observed=true" ? cAll2(p).then((r) => ({ items: r.items.filter((c) => c.kind !== "group"), next_cursor: null })) : cAll2(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat");
  expect(text(main).includes("You own no agents in this project, and are in no group chat.") && !convs().length, "chat: no agents and no group chat, said");
  win.Maity.api.get = cGet; win.Maity.api.getAll = cAll2;
  await fireIntervals(); await tick(); await tick();
  expect(convs().length === 6 && main.querySelector(".chat-list-pane p.muted").hidden, "chat: agents that appear fill the list");
  await go("#/maintainer/maity/chat/agt-a");
  main.querySelector("textarea").value = "Thanks.";
  main.querySelector("form").dispatch("submit"); await tick();
  expect(main.querySelectorAll(".msg").length === 3 && text(main).includes("not picked up yet"), "sent message appended");
  // The feed: a chat event of this conversation fetches its new messages.
  const realGet2 = win.Maity.api.get;
  let feed = [];
  const feedPaths = [];
  const chatEvent = { seq: 9999, kind: "message", actor: { member_id: "agt-a" }, payload: { type: "chat", conversation_id: "agt-a", to: "hum-maintainer", body: "On it." } };
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) {
      feedPaths.push(p);
      const items = feed; feed = [];
      return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 0, superseded: false });
    }
    return p.includes("/messages?after=")
      ? Promise.resolve({ items: [{ id: "evt-9999", seq: 9999, conversation_id: "agt-a", from: "agt-a", to: "hum-maintainer", body: "On it.", sent_at: "2026-10-21T14:00:00Z", delivered_at: "2026-10-21T14:00:00Z" }], cursor: 9999 })
      : realGet2(p);
  };
  feed = [chatEvent];
  await fireIntervals(); await tick();
  expect(main.querySelectorAll(".msg").length === 4 && text(main).includes("On it."), "a chat event in the feed shows the agent's reply");
  expect(feedPaths[0] && /after=\d+&wait=0&limit=200$/.test(feedPaths[0]), "the feed reads from the head with wait=0");
  feed = [chatEvent];
  await fireIntervals(); await tick();
  expect(main.querySelectorAll(".msg").length === 4, "a message seen twice is shown once");
  // Delivery: no event says a message reached the session. The agent's next
  // event, or the window's focus, re-reads the human's pending messages.
  const convPath = "/projects/maintainer/maity/conversations/agt-a/messages";
  const feedStub = win.Maity.api.get;
  const thanks = (await realGet2(convPath)).items.find((m) => m.body === "Thanks.");
  const msgReads = [];
  let delivered = false;
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) { const items = feed; feed = []; return Promise.resolve({ items, cursor: 10000, superseded: false }); }
    if (p.startsWith(convPath + "?after=")) {
      msgReads.push(p);
      return Promise.resolve({ items: [Object.assign({}, thanks, { delivered_at: delivered ? "2026-10-21T14:01:00Z" : null })], cursor: thanks.seq });
    }
    return realGet2(p);
  };
  const thanksLine = () => main.querySelectorAll(".msg.out").find((li) => li.textContent.includes("Thanks.")).textContent;
  feed = [{ seq: 10000, kind: "task_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(!msgReads.length && thanksLine().includes("not picked up yet"), "another member's event does not re-read the conversation");
  delivered = true;
  feed = [{ seq: 10001, kind: "session_resumed", actor: { member_id: "agt-a" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(msgReads.length === 1 && msgReads[0] === convPath + "?after=" + (thanks.seq - 1) + "&limit=200"
    && thanksLine().includes("reached a session"), "the agent's next event marks the message as picked up");
  feed = [{ seq: 10002, kind: "session_resumed", actor: { member_id: "agt-a" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(msgReads.length === 1, "nothing pending: no further re-read");
  delivered = false;
  main.querySelector("textarea").value = "One more.";
  main.querySelector("form").dispatch("submit"); await tick();
  const oneMore = (await realGet2(convPath)).items.find((m) => m.body === "One more.");
  win.Maity.api.get = (p) => (p.startsWith(convPath + "?after=")
    ? (msgReads.push(p), Promise.resolve({ items: [Object.assign({}, oneMore, { delivered_at: "2026-10-21T14:02:00Z" })], cursor: oneMore.seq }))
    : realGet2(p));
  win.onfocus(); await tick(); await tick();
  expect(main.querySelectorAll(".msg.out").find((li) => li.textContent.includes("One more.")).textContent.includes("reached a session"),
    "the window's focus marks a pending message as picked up");
  win.Maity.api.get = feedStub;
  // A long chat, scrolled up: arriving messages leave the view where it is (Newest, below).
  const nGet2 = win.Maity.api.get;
  const arrivingAll = Array.from({ length: 203 }, (_, i) => longMsg(i + 1));
  const arrivingConv = convStub(arrivingAll, []);
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/conversations/agt-c/messages?") ? arrivingConv(p) : nGet2(p));
  await go("#/maintainer/maity/chat/agt-c");
  const longList = main.querySelector("ol.messages");
  // Scrolled up (not near the top), two messages arrive: the view stays, both are counted; Newest goes down and keeps the focus in the chat.
  Object.assign(longList, { scrollHeight: 5000, clientHeight: 400, scrollTop: 300 });
  longList.dispatch("scroll");
  arrivingAll.push(longMsg(204), longMsg(205));
  feed = [{ seq: 204, kind: "message", actor: { member_id: "agt-c" }, payload: { type: "chat", conversation_id: "agt-c" } }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  const jumpBtn = main.querySelector(".jump-latest");
  expect(longList.querySelectorAll("li.msg").length === 52 && longList.scrollTop === 300 && !jumpBtn.hidden && jumpBtn.textContent === "2 new · Newest",
    "chat: two messages arriving while scrolled up leave the view where it is and count both " + jumpBtn.textContent);
  const jProto = Object.getPrototypeOf(jumpBtn);
  const jFocus = jProto.focus;
  jProto.focus = function () { document.activeElement = this; };
  jumpBtn.click(); await tick();
  expect(jumpBtn.hidden && longList.scrollTop === 5000 && document.activeElement === byId("chat-text"), "chat: Newest goes to the end and puts the focus in the composer");
  jProto.focus = jFocus; document.activeElement = undefined;
  // At the end, a message that arrives is followed, and so is content that grows after it was drawn (an image loading).
  Object.assign(longList, { scrollHeight: 5200, scrollTop: 4800 }); longList.dispatch("scroll");
  arrivingAll.push(longMsg(206));
  feed = [{ seq: 206, kind: "message", actor: { member_id: "agt-c" }, payload: { type: "chat", conversation_id: "agt-c" } }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(longList.scrollTop === 5200 && main.querySelector(".jump-latest").hidden, "chat: at the end, an arriving message is followed, no pill");
  longList.scrollHeight = 5600; longList.dispatch("load");
  expect(longList.scrollTop === 5600, "chat: at the end, content that grows after it was drawn keeps the reader at the end");
  win.Maity.api.get = nGet2;

  // The feed in other views: someone else's card event offers a reload,
  // one's own does not; a request event re-reads the counts at once.
  await go("#/maintainer/maity/board");
  feed = [{ seq: 10001, kind: "task_updated", actor: { member_id: "hum-maintainer" }, payload: {} }];
  await fireIntervals(); await tick();
  expect(!text(main).includes("The board changed."), "the human's own card event offers nothing");
  feed = [{ seq: 10002, kind: "task_claimed", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick();
  expect(text(main).includes("The board changed.") && btn(main, "Reload"), "an agent's card event offers a reload");
  feed = [{ seq: 10003, kind: "state_changed", actor: { member_id: "hum-other" }, payload: {} }];
  await fireIntervals(); await tick();
  expect(text(main).includes("The board changed.") && text(main).includes("The project changed."), "state change added to the notice");
  btn(main, "Reload").click(); await tick(); await tick();
  expect(!text(main).includes("The board changed."), "reload clears the notice");
  await go("#/maintainer/maity/inbox");
  const before = gets.length;
  feed = [{ seq: 10004, kind: "request_created", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick();
  expect(gets.slice(before).filter((p) => p === "/me").length >= 1, "a request event re-reads /me");
  const realGet4 = win.Maity.api.get;
  // One more open request: in /me and in §18.2's inbox count, which the list's reload follows.
  const bump = (slug) => (p) => (p === "/me"
    ? realGet2(p).then((m) => { m.projects.find((x) => x.slug === slug).open_requests += 1; return m; })
    : p === "/me/notifications?limit=0" ? realGet2(p).then((a) => {
      const by = Object.assign({}, a.by_project), key = "maintainer/" + slug;
      by[key] = Object.assign({}, by[key], { inbox: ((by[key] || {}).inbox || 0) + 1 });
      return Object.assign({}, a, { by_project: by, counts: Object.assign({}, a.counts, { inbox: ((a.counts || {}).inbox || 0) + 1 }) });
    })
    : (p.includes("/events?") ? Promise.resolve({ items: [], cursor: 10004 }) : realGet2(p)));
  // Nothing open on screen: nothing is being read or typed, so the list reloads on its own.
  expect(!main.querySelectorAll("li.entry").some((e) => !e.className.includes("done")), "maity inbox has no open entry here");
  win.Maity.api.get = bump("maity");
  const beforeQuiet = gets.length;
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(!text(main).includes("What waits for you changed") && gets.slice(beforeQuiet).some((p) => p.startsWith("/projects/maintainer/maity/requests")),
    "a changed count reloads an empty list on its own, without a notice");
  expect(main.querySelector(".notice") && main.querySelector(".notice").getAttribute("role") === "status" && text(main.querySelector(".notice")).includes("1 new request."),
    "the quiet reload says \"1 new request.\" in the status notice");
  // The same with the Project settings panel open and typed in: no reload, the offer instead.
  win.Maity.api.get = realGet2; await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox");
  await projectSettings(); await tick();
  byId("state-reason").value = "typed, not sent";
  win.Maity.api.get = bump("maity");
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "typed, not sent" && onSettings(),
    "on the Settings tab a changed count reloads nothing: the page and its text stay");
  await projectSettings(); await tick();
  // An open entry on screen: the change is offered as a reload instead.
  win.Maity.api.get = realGet2;
  await go("#/maintainer/sample/inbox");
  expect(main.querySelector("li.entry.current"), "sample inbox has an open entry");
  win.Maity.api.get = bump("sample");
  await fireIntervals(); await tick(); await tick();
  expect(text(main).includes("What waits for you changed") && btn(main, "Reload the list"), "a changed open count offers to reload the list");
  // A hidden tab asks the hub nothing: no /me, no events; shown again, it catches up once.
  const hidGets = [];
  win.Maity.api.get = (p) => { hidGets.push(p); return realGet2(p); };
  document.visibilityState = "hidden";
  await fireIntervals(); await tick(); await tick();
  expect(!hidGets.length, "load: a hidden tab reads neither /me nor the project's events");
  document.visibilityState = "visible";
  await fireIntervals(); await tick(); await tick();
  expect(hidGets.filter((p) => p === "/me").length === 1 && hidGets.some((p) => p.includes("/events?after=")),
    "load: shown again, the tab reads /me once and the events it missed");
  const hidAll = win.Maity.api.getAll, hidLists = [];
  win.Maity.api.getAll = (p) => { hidLists.push(p); return hidAll(p); };
  await go("#/chats"); for (let k = 0; k < 4; k++) await tick();
  hidLists.length = 0;
  document.visibilityState = "hidden";
  await fireIntervals(); await tick(); await tick();
  expect(!hidLists.some((p) => p.includes("/conversations")), "load: a hidden tab reads no chat lists");
  win.Maity.api.getAll = hidAll;
  delete document.visibilityState;
  win.Maity.api.get = realGet4;
  win.Maity.api.get = realGet2;
  win.Maity.api.get = realGet2;
  await go("#/maintainer/maity/chat/nobody");
  expect(text(main).includes("No conversation of yours"), "unknown conversation id reported");

  // A new profile's handle, free or taken while it is typed (§6.3); a deleted profile frees its handle.
  const hcAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/agents"
    ? hcAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-old", handle: "old-one", display_name: "Old one", owner_id: "hum-maintainer", memberships: [], deleted_at: "2026-10-01T00:00:00Z" }]), next_cursor: null }))
    : hcAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  byId("join-agent").value = ""; byId("join-agent").dispatch("change");
  const hcType = (v) => { byId("join-handle").value = v; byId("join-handle").dispatch("input"); };
  const hcState = () => byId("join-handle-state");
  expect(hcState() && hcState().getAttribute("role") === "status" && byId("join-handle").getAttribute("aria-describedby").includes("join-handle-state")
    && text(hcState()) === "", "handle check: a status line beside the field, empty until something is typed");
  hcType("agent-b");
  expect(text(hcState()).includes("Taken: your agent Agent B has @agent-b") && hcState().className.includes("field-error"), "handle check: one's own profile's handle is taken");
  hcType("agent-zz");
  expect(text(hcState()) === "@agent-zz is free." && hcState().className.includes("ok"), "handle check: an unused handle is free");
  hcType("old-one");
  expect(text(hcState()) === "@old-one is free.", "handle check: a deleted profile does not block its handle");
  hcType("A");
  expect(text(hcState()).startsWith("Not a handle yet: Lowercase letters") && hcState().className.includes("field-error"), "handle check: the pattern is said too");
  // The hub's answer is the final word: its taken is said in words and the list read again.
  const hcPost = win.Maity.api.post;
  let hcReads = 0;
  win.Maity.api.getAll = (p) => (p === "/agents" ? (hcReads++, hcAll(p)) : hcAll(p));
  win.Maity.api.post = (p, b) => (p === "/projects/maintainer/maity/joins"
    ? Promise.reject(new win.Maity.api.ApiError("taken", 400, p, "invalid", { fields: { handle: "taken" } }))
    : hcPost(p, b));
  hcType("agent-zz"); byId("join-display").value = "Agent ZZ";
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("No join created: you already have an agent with the handle @agent-zz") && hcReads === 1,
    "handle check: the hub's taken is said, and the profiles are read again");
  // The hub's taken stands even when the profiles cannot be read again.
  win.Maity.api.getAll = (p) => (p === "/agents" && hcReads++ ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : hcAll(p));
  hcType("agent-yy");
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(hcState()) === "Taken: the hub says you already have an agent with @agent-yy." && hcState().className.includes("field-error"),
    "handle check: the hub's refusal stays when the re-read fails " + JSON.stringify(text(hcState())));
  hcType("agent-yz"); hcType("agent-yy");
  expect(text(hcState()).startsWith("Taken: the hub says"), "handle check: and when the handle is typed again");
  // After a create, the hint is worked out again: the new handle is one's own.
  // Stubbed, so the fixtures' joins stay as the cases below expect them.
  let hcCreated = false;
  win.Maity.api.post = (p, b) => (p === "/projects/maintainer/maity/joins"
    ? (hcCreated = true, Promise.resolve({ id: "join-hc", agent_id: "agt-new1", paste_line: "maity join https://hub.example/j/x", expires_at: "2099-01-01T00:00:00Z", created_at: "2026-10-23T00:00:00Z" }))
    : hcPost(p, b));
  win.Maity.api.getAll = (p) => (p === "/agents" && hcCreated
    ? hcAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-new1", handle: "agent-new1", display_name: "Agent New", owner_id: "hum-maintainer", memberships: [], deleted_at: null }]), next_cursor: null }))
    : hcAll(p));
  hcType("agent-new1"); byId("join-display").value = "Agent New";
  expect(text(hcState()) === "@agent-new1 is free.", "handle check: free before the create");
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 8; k++) await tick();
  // The line takes the form's place; Join another brings the form back, its hint worked out again.
  btn(main.querySelector(".join-result"), "Join another").click(); await tick();
  byId("join-agent").value = ""; byId("join-agent").dispatch("change"); hcType("agent-new1");
  expect(text(hcState()).startsWith("Taken: your agent Agent New has @agent-new1"), "handle check: after the create it is taken, by the new profile " + JSON.stringify(text(hcState())));
  win.Maity.api.post = hcPost; win.Maity.api.getAll = hcAll;
  await go("#/maintainer/maity/inbox");
  await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(!main.querySelector(".error") && text(main).includes("join-0006"), "join view with existing joins");
  // Each join's state from its fields; an open one is a seat at the front of the grid, with Revoke;
  // the others are the folded record at the view's end.
  // A join where it stands: its seat while it is open (or just expired), else its line in the record.
  const joinRow = (id) => main.querySelectorAll("article.seat").find((a) => a.attrs["data-join"] === id)
    || main.querySelectorAll(".closed-joins li").find((li) => li.textContent.includes(id));
  const seatsNow = () => main.querySelectorAll("article.seat");
  const seat = seatsNow()[0];
  expect(seatsNow().length === 1 && seat.attrs["data-join"] === "join-0010" && main.querySelector(".profiles").childNodes[0] === seat
    && text(seat).includes("open seat") && text(seat).includes("open until") && text(seat).includes("Waiting for the agent to run its line.") && btn(seat, "Revoke"),
    "joins: an open join is a seat at the front of the agents' grid, with Revoke");
  const earlierJ = main.querySelector("details.earlier-joins");
  const closedRows = main.querySelector(".closed-joins").querySelectorAll("li");
  expect(earlierJ && text(earlierJ.querySelector("summary")) === "Earlier joins (4): used, expired or revoked" && closedRows.length === 4 && closedRows.every((li) => !btn(li, "Revoke")),
    "joins: used, expired, burned and revoked joins are folded at the end, without Revoke");
  expect(text(main.querySelector(".agents-count")).includes("1 open join"), "joins: the title's count line says how many joins are open");
  expect(text(joinRow("join-0009")).startsWith("expired join-0009") && text(joinRow("join-0009")).includes("· expired ")
    && joinRow("join-0009").classList.contains("join-expired"), "joins: an expired join says expired, not open");
  expect(text(joinRow("join-0008")).startsWith("burned") && text(joinRow("join-0008")).includes("refused after three wrong codes"), "joins: a burned join");
  expect(text(joinRow("join-0007")).startsWith("revoked") && text(joinRow("join-0007")).includes("· revoked "), "joins: a revoked join");
  expect(text(joinRow("join-0006")).startsWith("used") && text(joinRow("join-0006")).includes("· used "), "joins: a used join");
  expect(main.all().some((e) => e.attrs.pattern) && !badPatterns().length, "join: every pattern compiles with the v flag " + badPatterns());
  byId("join-agent").value = "agt-x";
  const joinPosts = [];
  const realPost2 = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { joinPosts.push([p, b]); return realPost2(p, b); };
  byId("join-briefing").value = "x".repeat(16 * 1024 + 1);
  main.querySelector("form.join-form").dispatch("submit"); await tick();
  expect(!joinPosts.length && text(main).includes("the briefing is longer than 16,384 characters"), "a join briefing over 16 KiB is refused before sending");
  byId("join-briefing").value = "  You review hub/.  ";
  main.querySelector("form.join-form").dispatch("submit"); await tick(); await tick();
  expect(joinPosts.length === 1 && joinPosts[0][1].briefing === "You review hub/.", "the join sends the briefing, trimmed");
  win.Maity.api.post = realPost2;
  expect(text(main).includes("maity join https://maity.example/j/FIXTURE") && text(main).includes("shown once"), "paste line shown once");
  expect(text(main).includes("as a message in its clone of the repository") && text(main).includes("follows the join page"), "the paste line says where it goes");
  btn(main, "Copy").click(); await tick();
  expect(ctx.copied && ctx.copied.startsWith("maity join"), "copy puts the line on the clipboard");
  expect(main.querySelector(".join-result") && !main.querySelector("form.join-form"), "the line takes the form's place in the panel");
  expect(!main.querySelector(".instance-note"), "a new agent's line has no note on another instance's state directory");
  btn(main.querySelector("article.seat"), "Revoke").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector("details.earlier-joins")).includes("revoked"), "open join revoked, now in the record");
  // A join for a new profile: Join another brings the form back; the new join is a seat, the select offers it.
  btn(main.querySelector(".join-result"), "Join another").click(); await tick();
  const agentSel = byId("join-agent"); agentSel.value = ""; agentSel.dispatch("change");
  expect(text(main).includes("Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit.") && byId("join-handle").getAttribute("aria-describedby").split(" ").includes("join-handle-rule"),
    "the handle's rule is said up front, tied to its field");
  const joinsBefore = main.querySelectorAll("article.seat").length + main.querySelectorAll(".closed-joins li").length;
  byId("join-handle").value = "Agent_New";
  main.querySelector("form.join-form").dispatch("submit"); await tick(); await tick();
  expect(main.querySelectorAll("article.seat").length + main.querySelectorAll(".closed-joins li").length === joinsBefore && text(main).includes("No join created: the handle: Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit."),
    "a handle against the rule is refused before sending, with the rule");
  byId("join-handle").value = "agent-new"; byId("join-display").value = "Agent New";
  main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 5; k++) await tick();
  btn(main.querySelector(".join-result"), "Join another").click(); await tick();
  const newOpt = byId("join-agent").querySelectorAll("option").find((o) => o.textContent.startsWith("Agent New (@agent-new)"));
  expect(newOpt && byId("join-agent").value === newOpt.attrs.value && /^agt-/.test(newOpt.attrs.value),
    "a new profile is offered and selected after its join is created");
  expect(main.querySelectorAll("article.seat").some((a) => text(a).includes("Agent New")), "the new profile's join is a seat in the grid");
  // An agent that is already a member joins as an instance (docs/api.md §3.1, §6.17): one in place of
  // an instance, or another one; the membership's own fields stay out of the join.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  const inPosts = [];
  const inPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { inPosts.push([p, b]); return inPost(p, b); };
  const inBox = () => main.querySelector("fieldset.join-instance");
  const inPick = (id) => { byId("join-agent").value = id; byId("join-agent").dispatch("change"); };
  const inNew = () => { byId("join-replace").checked = false; byId("join-new-instance").checked = true; };
  const inSubmit = async () => { main.querySelector("form.join-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick(); };
  const inAgain = async () => { btn(main.querySelector(".join-result"), "Join another").click(); await tick(); };
  inPick("agt-x");
  expect(inBox().hidden && !byId("join-role").parentNode.hidden, "join: no instance choice for an agent that is not a member");
  inPick("agt-b");
  const inOpts = byId("join-replaces").querySelectorAll("option");
  expect(!inBox().hidden && byId("join-replace").checked && inOpts.length === 1 && inOpts[0].attrs.value === "wle2"
    && text(inOpts[0]).startsWith("agent-b#wle2 · last seen") && text(inOpts[0]).endsWith(" · 1 card")
    && ["join-role", "join-reports", "join-areas", "join-briefing"].every((id) => byId(id).parentNode.hidden)
    && text(byId("join-quota")) === "1 of 1 instances active; another one is over the team's limit.",
    "join: a member offers Replace instance preselected with its active instances, the membership's fields hidden");
  await inSubmit();
  const inBody = inPosts[0] && inPosts[0][1];
  expect(inPosts.length === 1 && inBody.replaces === "wle2" && !("new_instance" in inBody) && ["role", "reports_to", "areas", "capabilities", "briefing"].every((k) => !(k in inBody))
    && main.querySelector(".join-result"), "join: Replace instance sends replaces and leaves the membership's fields out " + JSON.stringify(inBody));
  // An instance runs with a state directory of its own (tsk-axmb8dsyvrpb): said before the line, with the export to set.
  const inNote = () => main.querySelector(".join-result .instance-note");
  const inResult = main.querySelector(".join-result");
  expect(inNote() && inResult.childNodes.indexOf(inNote()) < inResult.childNodes.indexOf(inResult.querySelector(".paste-row"))
    && text(inNote().querySelector("code")) === 'export MAITY_STATE_DIR="$HOME/.local/state/maity/agent-b-<name>"'
    && text(inNote()).includes("Do not run maity resume there to start it"),
    "join: a replacing instance's line comes after the note on its own state directory, the export named, resume warned off");
  await inAgain(); inPick("agt-b"); inNew(); await inSubmit();
  expect(inPosts.length === 2 && inPosts[1][1].new_instance === true && !("replaces" in inPosts[1][1]) && !main.querySelector(".join-result")
    && text(main).includes("No join created: the team has as many instances as its rulebook allows"),
    "join: another instance beyond the team's limit shows the hub's instance_quota as it is");
  const inQuota = main.querySelector("a.join-quota-link");
  expect(inQuota && inQuota.getAttribute("href") === "#/maintainer/maity/agents/agt-b/rulebook" && text(inQuota) === "Raise it in the team's rulebook",
    "join: the quota refusal links to the agent's row, where its owner sets the rulebook");
  inPick("agt-c");
  expect(byId("join-replaces").querySelectorAll("option").map((o) => o.attrs.value).join() === "k3pa" && text(byId("join-quota")) === "1 of 3 instances active.",
    "join: a member's active instance offered, the team's count against its limit");
  inNew(); await inSubmit();
  expect(inPosts.length === 3 && inPosts[2][1].new_instance === true && main.querySelector(".join-result"), "join: Start another instance sends new_instance within the team's limit");
  expect(inNote() && text(inNote().querySelector("code")).includes("/maity/agent-c-<name>"), "join: another instance's line has the note too, for its handle");
  // The maintainer's incident: the list on screen does not show the agent as a member; the hub's
  // refusal brings the choice, with the instances read again, and the next create carries it.
  await inAgain();
  const inGetAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members"
    ? inGetAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-x", kind: "agent", handle: "spare", display_name: "Spare", trust: "member", role: "coder",
      team: { max_instances: 2 }, instances: [{ id: "q2zz", label: "spare#q2zz", presence: "offline", last_seen_at: null, claims: 2, revoked_at: null }] }]), next_cursor: null }))
    : inGetAll(p));
  win.Maity.api.post = (p, b) => {
    inPosts.push([p, b]);
    return b.agent.id === "agt-x" && !b.replaces && !b.new_instance
      ? Promise.reject(new win.Maity.api.ApiError("the agent is a member: new_instance or replaces", 400, p, "invalid", { fields: { instance: "required" } }))
      : inPost(p, b);
  };
  inPick("agt-x");
  expect(inBox().hidden, "join: the list on screen does not show agt-x as a member");
  const inProto = Object.getPrototypeOf(main);
  const inFocus = inProto.focus;
  inProto.focus = function () { document.activeElement = this; };
  await inSubmit();
  expect(inPosts.length === 4 && !inBox().hidden && byId("join-replace").checked && byId("join-replaces").value === "q2zz"
    && text(byId("join-replaces").querySelector("option")) === "spare#q2zz · last seen never · 2 cards"
    && text(main).includes("No join created: this agent is already a member of the project. Choose whether the line starts another instance or replaces one, then create it.")
    && document.activeElement === byId("join-replaces") && byId("join-role").parentNode.hidden,
    "join: the hub's instance-required refusal offers replace or another instance, the focus on the choice");
  inProto.focus = inFocus; document.activeElement = undefined;
  await inSubmit();
  expect(inPosts.length === 5 && inPosts[4][1].replaces === "q2zz" && !("role" in inPosts[4][1]), "join: after the refusal the join is created as a replacement");
  // The hub checks the membership's fields first: its differs_from_membership says "member" as well.
  // The agent became a member after the panel read the members: the hub lists it from the refusal on.
  let inSpareJoined = false;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" && inSpareJoined
    ? inGetAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-x", kind: "agent", handle: "spare", display_name: "Spare", trust: "member", role: "coder",
      team: { max_instances: 2 }, instances: [{ id: "q2zz", label: "spare#q2zz", presence: "offline", last_seen_at: null, claims: 0, revoked_at: null },
        { id: "r3yy", label: "spare#r3yy", presence: "online", last_seen_at: null, claims: 0, revoked_at: null }] }]), next_cursor: null }))
    : inGetAll(p));
  win.Maity.api.post = (p, b) => {
    inPosts.push([p, b]);
    if (b.agent.id === "agt-x" && "areas" in b) inSpareJoined = true;
    return b.agent.id === "agt-x" && "areas" in b
      ? Promise.reject(new win.Maity.api.ApiError("the agent is a member; change its membership instead", 400, p, "invalid", { fields: { areas: "differs_from_membership" } }))
      : inPost(p, b);
  };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  inPick("agt-x"); byId("join-areas").value = "web/";
  await inSubmit();
  expect(!inBox().hidden && text(main).includes("this agent is already a member of the project") && byId("join-role").parentNode.hidden,
    "join: the hub's differs_from_membership also brings the instance choice");
  inNew();
  byId("join-replaces").value = "r3yy"; byId("join-replaces").dispatch("change");
  expect(byId("join-replace").checked && !byId("join-new-instance").checked, "join: choosing an instance to replace selects Replace");
  win.Maity.api.post = inPost; win.Maity.api.getAll = inGetAll;
  // Joining lives in Agents: no tab of its own; the old route opens the panel there.
  expect(!header.querySelectorAll("nav.views a").some((a) => a.textContent.startsWith("Join an agent")), "join: no tab of its own any more");
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const jpPanel = () => main.querySelector(".join-panel");
  const jpButton = () => main.querySelector("button.join-open");
  expect(jpPanel() && jpPanel().hidden && jpButton() && !jpButton().hidden && text(jpButton()) === "+ Add an agent"
    && main.querySelector(".agents-head") && main.querySelector(".agents-head").querySelector("button.join-open") === jpButton(),
    "join: Agents has + Add an agent at its head, the panel closed");
  const jpProto = Object.getPrototypeOf(main);
  const jpFocus = jpProto.focus;
  jpProto.focus = function () { document.activeElement = this; };
  jpButton().click(); await tick();
  expect(!jpPanel().hidden && jpButton().hidden && document.activeElement === byId("join-agent"), "join: the button opens the panel, the focus on its first field");
  btn(jpPanel(), "Cancel").click(); await tick();
  expect(jpPanel().hidden && !jpButton().hidden && document.activeElement === jpButton(), "join: Cancel closes it, the focus back on the button");
  jpButton().click(); await tick();
  jpPanel().querySelector("button.join-close").click(); await tick();
  expect(jpPanel().hidden && document.activeElement === jpButton() && jpPanel().querySelector("button.join-close").getAttribute("aria-label") === "Close",
    "join: the panel's own Close does the same");
  jpProto.focus = jpFocus; document.activeElement = undefined;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".view-agents") && !jpPanel().hidden && main.querySelector(".profiles"), "join: /agents/join opens Agents with the panel open");
  // A failed read of the joins stays in the panel, with a retry; the agents' cards are drawn all the same.
  const jfAll = win.Maity.api.getAll;
  let jfFail = true;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/joins" && jfFail ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : jfAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll("li.agent-card").length === 5 && !main.querySelector("article.seat"),
    "join: the joins failing to load leave every agent's card on screen");
  main.querySelector("button.join-open").click(); await tick();
  const jfRetry = btn(main.querySelector(".join-panel"), "Try again");
  expect(jfRetry && text(main.querySelector(".join-panel")).includes("The joins could not be read: down"), "join: the panel says so, with Try again");
  jfFail = false;
  jfRetry.click(); for (let k = 0; k < 4; k++) await tick();
  expect(byId("join-agent") && main.querySelector("article.seat"), "join: Try again reads them and draws the form and the seats");
  win.Maity.api.getAll = jfAll;
  // An agent running its line: with the panel closed the view redraws with
  // its card; with the panel open only the joins are read again.
  const mjGet = win.Maity.api.get;
  let mjFeed = [];
  win.Maity.api.get = (p) => (p.includes("/events?")
    ? Promise.resolve({ items: mjFeed.splice(0), cursor: 10100, superseded: false }) : mjGet(p));
  let mjReads = 0;
  let mjMembers = 0;
  win.Maity.api.getAll = (p) => { if (p === "/projects/maintainer/maity/joins") mjReads++; if (p === "/projects/maintainer/maity/members") mjMembers++; return jfAll(p); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const mjBefore = jpPanel();
  const mjMembersBefore = mjMembers;
  mjFeed = [{ seq: 10100, kind: "member_joined", actor: { member_id: "agt-x" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(jpPanel() === mjBefore && mjMembers > mjMembersBefore, "join: an agent joining reads the members again while the panel is closed, the panel kept");
  main.querySelector("button.join-open").click(); await tick();
  const mjOpen = jpPanel();
  mjReads = 0;
  mjFeed = [{ seq: 10101, kind: "member_joined", actor: { member_id: "agt-x" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(jpPanel() === mjOpen && !mjOpen.hidden && mjReads === 1, "join: with the panel open only the joins are read again (" + mjReads + ")");
  win.Maity.api.get = mjGet; win.Maity.api.getAll = jfAll;
  // A join that expires while the view is open moves to the others without a reload.
  const jAll = win.Maity.api.getAll;
  const soon = { id: "join-soon", agent_id: "agt-b", trust: "member", role: "coder", created_by: "hum-maintainer", created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 60).toISOString(), used_at: null, burned: false, revoked_at: null };
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/joins" ? Promise.resolve({ items: [soon], next_cursor: null }) : jAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(joinRow("join-soon") && joinRow("join-soon").tagName === "ARTICLE" && btn(joinRow("join-soon"), "Revoke"), "joins: open while it lasts, as a seat");
  await new Promise((r) => setTimeout(r, 80)); await fireIntervals(); await tick();
  expect(text(joinRow("join-soon").querySelector(".seat-label")) === "expired" && text(main.querySelector(".agents-count")).includes("0 open joins"),
    "joins: expired while the view is open, without a reload");
  expect(btn(joinRow("join-soon"), "Revoke"), "joins: just expired, it keeps Revoke for a minute: the hub decides");
  const jNow = win.Maity.api.now;
  win.Maity.api.now = () => Date.now() + 61000;
  await fireIntervals(); await tick();
  expect(joinRow("join-soon").tagName === "LI" && text(joinRow("join-soon")).startsWith("expired") && !btn(joinRow("join-soon"), "Revoke"),
    "joins: a minute after it expired, no Revoke: it moved to the record");
  // Expiry is judged by the hub's clock (M.api.now; its skew is tested in API mode).
  soon.expires_at = new Date(Date.now() - 5 * 60000).toISOString();
  win.Maity.api.now = () => Date.now() - 10 * 60000;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(joinRow("join-soon").tagName === "ARTICLE" && btn(joinRow("join-soon"), "Revoke"), "joins: a browser ahead of the hub still sees an open join open");
  // A Revoke the hub refuses (expired by its clock): said, kept on screen, the list re-read.
  win.Maity.api.getAll = jAll;
  win.Maity.api.now = () => Date.parse("2026-10-21T08:10:00Z");
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  const jReads = [];
  const jAll2 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => { jReads.push(p); return jAll2(p); };
  btn(joinRow("join-0009"), "Revoke").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Not revoked: the join is expired") && jReads.includes("/projects/maintainer/maity/joins"),
    "joins: a refused Revoke is said and the list re-read");
  win.Maity.api.getAll = jAll2;
  win.Maity.api.now = jNow;
  win.Maity.api.getAll = jAll;
  await go("#/maintainer/maity/inbox");
  expect(!text(main).includes("FIXTURE"), "the line is gone after leaving the view");
  // count polling: a change offers a reload instead of replacing the list
  await fireIntervals(); await tick();
  expect(!main.querySelector(".notice .flag"), "no notice while nothing changed");

  // state and absence
  await projectSettings(); await tick();
  const sel = byId("state-select");
  expect(sel.querySelectorAll("option").map((o) => o.getAttribute("value")).join(" ") === "plan build review launch archived"
    && sel.querySelectorAll("option").find((o) => o.getAttribute("value") === "launch").getAttribute("disabled") == null,
    "state: exactly the five states of §6.1; the owner may move to launch");
  sel.value = "review";
  byId("state-reason").value = "release 0.1.0";
  // The 15-s count re-read replaces the switcher only; the open panel and what is typed stay.
  const switcherBefore = header.querySelector("nav.switcher");
  await fireIntervals(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "release 0.1.0" && byId("state-select").value === "review",
    "the count re-read keeps the open Project settings panel and its input");
  expect(header.querySelector("nav.switcher") !== switcherBefore && header.querySelectorAll("nav.switcher").length === 1,
    "the count re-read replaces the switcher, once");
  byId("state-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header).includes("Review") && onSettings() && text(main).includes("State saved.")
    && header.querySelectorAll("nav.views a").find((a) => a.textContent === "Settings").getAttribute("aria-current") === "page",
    "state changed to review; the save stays on the Settings tab, says so, the tab marked current");
  byId("absence-until").value = "2026-10-25T08:00"; byId("absence-scope").value = "fixes only";
  byId("absence-until").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header.querySelector(".project-state")).includes("Away until") && text(header.querySelector(".absence")).includes("While away: fixes only"), "absence set");
  // An admin who is no owner: launch is offered disabled, until the project is in launch, which they may leave.
  const lnGet = win.Maity.api.get;
  let lnState = "build";
  win.Maity.api.get = (p) => (p === "/me" ? lnGet(p).then((m) => { Object.assign(m.projects.find((x) => x.slug === "maity"), { trust: "admin", state: lnState }); return m; })
    : p === "/projects/maintainer/maity" ? lnGet(p).then((x) => Object.assign({}, x, { state: lnState })) : lnGet(p));
  const launchOption = () => byId("state-select").querySelectorAll("option").find((o) => o.getAttribute("value") === "launch");
  await go("#/maintainer/maity/inbox"); await projectSettings(); await tick();
  const lnBuild = launchOption() && launchOption().getAttribute("disabled") != null;
  lnState = "launch";
  await go("#/maintainer/maity/inbox"); await projectSettings(); await tick();
  expect(lnBuild && launchOption().getAttribute("disabled") == null && launchOption().getAttribute("selected") != null,
    "state: an admin who is no owner sees launch disabled, and selectable once the project is in launch");
  win.Maity.api.get = lnGet;

  // policy.signing: before required, the agents a bearer token would cut off.
  const sigPatches = [];
  const realPatch4 = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { sigPatches.push([p, b]); return realPatch4(p, b); };
  await projectSettings(); await tick();
  const sigSel = byId("signing-select");
  expect(sigSel && sigSel.value === "optional", "signing: the switch shows the project's policy");
  sigSel.value = "required"; sigSel.dispatch("change"); await tick(); await tick(); await tick();
  const impact = main.querySelector(".signing-impact");
  expect(text(impact).includes("This agent calls with a bearer token and would be refused (signature_required) until it signs") && text(impact).includes("Agent B · crd-b-0003")
    && !text(impact).includes("crd-d-0001") && !text(impact).includes("crd-c-0002") && !text(impact).includes("Agent A ·"),
    "signing: the agents last using a bearer token are listed, revoked and signed ones are not");
  expect(text(impact).includes("1 credential has not been used yet (Agent C)"), "signing: unused credentials are named");
  byId("signing-reason").value = "all agents run the CLI now";
  byId("signing-select").parentNode.dispatch("submit"); await tick();
  expect(!sigPatches.length, "signing: required is not sent while bearer agents are listed and not confirmed");
  byId("signing-confirm").checked = true;
  byId("signing-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(sigPatches.length === 1 && sigPatches[0][0] === "/projects/maintainer/maity"
    && JSON.stringify(sigPatches[0][1]) === JSON.stringify({ policy: { signing: "required" }, reason: "all agents run the CLI now" }),
    "signing: confirmed, the PATCH carries the policy field and the reason");
  await projectSettings(); await tick();
  expect(byId("signing-select").value === "required", "signing: the switch reads required after the change");
  byId("signing-select").value = "optional"; byId("signing-select").dispatch("change"); await tick();
  expect(!text(main.querySelector(".signing-impact")).length, "signing: back to optional needs no check");
  byId("signing-reason").value = "back to optional";
  byId("signing-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(sigPatches[1][1]) === JSON.stringify({ policy: { signing: "optional" }, reason: "back to optional" }), "signing: back to optional is sent");
  win.Maity.api.patch = realPatch4;
  await go("#/maintainer/sample/inbox");
  await projectSettings(); await tick();
  expect(byId("state-select") && !byId("signing-select"), "signing: no switch where the hub has no signing policy");
  await projectSettings(); await tick();
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  for (const id of ["agt-a", "agt-b", "agt-c", "agt-d"]) {
    main.querySelectorAll("tr.member").find((tr) => tr.attrs["data-member"] === id).querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click();
    for (let k = 0; k < 4; k++) await tick();
  }
  expect(text(main).includes("(signed)") && text(main).includes("(bearer token)"), "credentials: how each was last used");
  await go("#/maintainer/maity/inbox");
  // Logo in the header, the tab's icon, the banner on the project's inbox.
  const headerMark = header.querySelector(".bar .project-mark");
  const icon = () => head.querySelectorAll("link").find((l) => l.getAttribute("rel") === "icon");
  expect(headerMark && headerMark.tagName === "IMG" && icon() && icon().getAttribute("href") === "fixtures/maity/logo.png",
    "logo: in the header, and as the tab's icon");
  const bannerImg = main.querySelector("img.project-banner");
  expect(bannerImg && bannerImg.getAttribute("src") === "fixtures/maity/banner.png" && bannerImg.getAttribute("alt") === "", "banner: heads the project's inbox");
  await go("#/maintainer/sample/inbox");
  expect(header.querySelector(".bar .project-mark").textContent === "SS" && !icon() && !main.querySelector("img.project-banner"),
    "logo: a project without images has a monogram, no icon and no banner");
  await go("#/maintainer/maity/inbox");
  // Upload and remove, for project:admin, with the type read from the bytes.
  const imgPuts = [];
  const realPut = win.Maity.api.putImage, realDel = win.Maity.api.del;
  win.Maity.api.putImage = (p, blob, type) => { imgPuts.push(["PUT", p, type, blob.size]); return realPut(p, blob, type); };
  win.Maity.api.del = (p) => { imgPuts.push(["DELETE", p]); return realDel(p); };
  const fakeFile = (bytes, size, type) => ({
    size: size || bytes.length, type: type || "image/png",
    slice: (a, b) => ({ arrayBuffer: async () => Uint8Array.from(bytes.slice(a, b)).buffer }),
  });
  const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13];
  const WEBP = [0x52, 0x49, 0x46, 0x46, 1, 2, 3, 4, 0x57, 0x45, 0x42, 0x50];
  const SVG = [0x3c, 0x73, 0x76, 0x67, 0x20, 0x78, 0x6d, 0x6c, 0x6e, 0x73, 0x3d, 0x22];
  const pick = async (id, file) => { const i = byId(id); i.files = [file]; i.dispatch("change"); for (let k = 0; k < 6; k++) await tick(); };
  await projectSettings(); await tick();
  expect(main.querySelector(".images") && text(main.querySelector(".images")).includes("from the repository's forge")
    && text(main.querySelector(".images")).includes("uploaded here") && byId("upload-logo"), "images: what shows now and where it comes from");
  await pick("upload-logo", fakeFile(SVG, 0, "image/svg+xml"));
  expect(!imgPuts.length && text(main).includes("Logo not uploaded: not a PNG, JPEG or WebP image"), "images: an SVG is refused by its bytes, before sending");
  await pick("upload-logo", fakeFile(PNG, 1024 * 1024 + 1));
  expect(!imgPuts.length && text(main).includes("Logo not uploaded: larger than 1 MiB"), "images: over 1 MiB is refused before sending");
  await pick("upload-logo", fakeFile(WEBP, 2000, "image/png"));
  expect(JSON.stringify(imgPuts[0]) === JSON.stringify(["PUT", "/projects/maintainer/maity/logo", "image/webp", 2000]),
    "images: the upload is a PUT of the raw file, typed by its bytes (WebP, whatever the file claims)");
  // The panel opens again by itself and says what happened.
  const removeLogo = btn(main, "Remove the uploaded logo");
  expect(removeLogo && text(main.querySelector(".images")).includes("Logo uploaded.") && text(main.querySelector(".images")).includes("uploaded here"),
    "images: after an upload the panel says so, and the logo can be removed");
  removeLogo.click(); await tick(); await tick(); await tick();
  expect(JSON.stringify(imgPuts[1]) === JSON.stringify(["DELETE", "/projects/maintainer/maity/logo"]) && header.querySelector(".bar .project-mark").getAttribute("src") === "fixtures/maity/logo.png",
    "images: removed, the forge's logo applies again");
  expect(text(main).includes("Uploaded logo removed; the forge's logo, or a monogram, shows again."), "images: the removal is said too");
  await projectSettings(); await tick();
  // A hub before /me's logo: the switcher falls back to GET /projects.
  const realGet7 = win.Maity.api.get;
  const fallbackGets = [];
  win.Maity.api.get = (p) => { fallbackGets.push(p); return p === "/me" ? realGet7(p).then((m) => { m.projects.forEach((x) => { delete x.logo; }); return m; }) : realGet7(p); };
  await go("#/all"); await go("#/maintainer/maity/inbox");
  expect(fallbackGets.includes("/projects") && chip("Maity").querySelector(".project-mark").tagName === "IMG",
    "logo: without logos on /me, the project views are read and the logo still shows");
  win.Maity.api.get = realGet7;
  win.Maity.api.putImage = realPut; win.Maity.api.del = realDel;
  // The repository in Project settings (docs/api.md §6.1): https only here, the hub checks the forge.
  const repoPatches = [];
  const repoRealPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { if ("repository" in b) repoPatches.push(b); return repoRealPatch(p, b); };
  await go("#/maintainer/maity/inbox"); await projectSettings();
  const repoIn = () => byId("repo-url");
  const repoSave = async () => { main.querySelector("form.repository-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick(); };
  expect(repoIn() && repoIn().value === "https://github.com/oliver-zehentleitner/maity", "repository: Project settings shows the project's repository");
  repoIn().value = "http://github.com/a/b"; await repoSave();
  expect(!repoPatches.length && text(byId("repo-url-error")).startsWith("Must be https://") && repoIn().getAttribute("aria-invalid") === "true",
    "repository: anything but an https forge URL is refused at its field, nothing sent");
  repoIn().value = "https://gitlab.com/a/b"; await repoSave();
  expect(repoPatches.length === 1 && text(byId("repo-url-error")).startsWith("Must be https://"), "repository: the hub's not_a_configured_forge is said at the field");
  let repoAsked = null;
  win.confirm = (q) => { repoAsked = q; return true; };
  repoIn().value = "https://github.com/acme/widget/"; await repoSave();
  const repoNow = (await win.Maity.api.get("/projects/maintainer/maity")).repository;
  expect(JSON.stringify(repoPatches[1]) === JSON.stringify({ repository: { url: "https://github.com/acme/widget" } }) && repoNow.url === "https://github.com/acme/widget"
    && /^Change the repository to https:\/\/github\.com\/acme\/widget\?/.test(repoAsked), "repository: a change asks first, then is sent without the trailing slash");
  await projectSettings();
  repoIn().value = ""; await repoSave();
  expect(JSON.stringify(repoPatches[2]) === JSON.stringify({ repository: null }) && (await win.Maity.api.get("/projects/maintainer/maity")).repository === null
    && repoAsked.startsWith("Remove the repository?"), "repository: emptied, it is removed after asking");
  win.confirm = () => true;
  await repoRealPatch("/projects/maintainer/maity", { repository: { url: "https://github.com/oliver-zehentleitner/maity" } });
  win.Maity.api.patch = repoRealPatch;
  // Account: change the password (docs/api.md §2.1).
  // The profile menu: the avatar, the account, what is still to come, signing out (js/menu.js).
  const profileButton = () => header.querySelectorAll("button").find((b) => (b.getAttribute("aria-label") || "").startsWith("Your profile: "));
  const pb = profileButton();
  expect(pb && pb.attrs["aria-haspopup"] === "menu" && pb.attrs["aria-expanded"] === "false" && pb.querySelector("svg") && text(pb).includes("Maintainer"),
    "header: the profile is a menu button with the avatar and the name");
  const mProto = Object.getPrototypeOf(main);
  const mFocus = mProto.focus;
  mProto.focus = function () { document.activeElement = this; };
  pb.click(); await tick();
  const pMenu = header.querySelector(".profile-menu").parentNode.querySelector("ul.menu");
  const pItems = pMenu.querySelectorAll(".menu-item").map((el) => text(el));
  expect(!pMenu.hidden && pb.attrs["aria-expanded"] === "true" && JSON.stringify(pItems) === JSON.stringify(["Profile", "Picture", "Preferences", "Theme", "Organisations", "Sign in another device", "Change password", "Linked accounts · later", "Sign out"])
    && document.activeElement === pMenu.querySelectorAll(".menu-item")[0], "header: the profile menu opens with its items, the first focused");
  pMenu.dispatch("keydown", { key: "ArrowDown" });
  expect(document.activeElement === pMenu.querySelectorAll(".menu-item")[1] && pMenu.querySelectorAll(".menu-item")[1].getAttribute("href") === "#/account/picture",
    "header: arrows move through the items; Picture goes to the account's picture");
  for (let k = 0; k < 6; k++) pMenu.dispatch("keydown", { key: "ArrowDown" });
  expect(pMenu.querySelectorAll(".menu-item")[7].attrs["aria-disabled"] === "true" && document.activeElement === pMenu.querySelectorAll(".menu-item")[7],
    "header: one still to come is disabled and still reached");
  pMenu.dispatch("keydown", { key: "End" });
  expect(text(document.activeElement) === "Sign out", "header: End goes to the last item");
  pMenu.dispatch("keydown", { key: "Escape" });
  expect(pMenu.hidden && pb.attrs["aria-expanded"] === "false" && document.activeElement === pb, "header: Escape closes the menu and gives the focus back to its button");
  pb.dispatch("keydown", { key: "ArrowUp" });
  expect(!pMenu.hidden && text(document.activeElement) === "Sign out", "header: ArrowUp on the button opens the menu at its last item");
  pMenu.dispatch("keydown", { key: "Escape" });
  mProto.focus = mFocus; document.activeElement = undefined;
  pb.click(); await tick();
  const accountLink = pMenu.querySelectorAll("a.menu-item").find((a) => a.textContent === "Profile");
  expect(accountLink && accountLink.getAttribute("href") === "#/account", "the profile menu links to the account");
  pb.click(); await tick();
  await go("#/account");
  expect(plainTitle() === "Your account · Maity" && text(main).includes("@maintainer") && byId("password-current"), "the account view");
  const pwPosts = [];
  const realPost5 = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { pwPosts.push([p, b]); return realPost5(p, b); };
  const pwSubmit = () => main.querySelector("form.project-form").dispatch("submit");
  byId("password-current").value = "initial-generated"; byId("password-new").value = "short"; byId("password-repeat").value = "short";
  pwSubmit(); await tick();
  expect(!pwPosts.length && text(byId("password-new-error")) === "At least 12 characters.", "password: under 12 characters is refused locally");
  byId("password-new").value = "a long new password"; byId("password-repeat").value = "a long new passw0rd";
  pwSubmit(); await tick();
  expect(!pwPosts.length && text(byId("password-repeat-error")) === "The two new passwords differ.", "password: a repeat that differs is refused locally");
  byId("password-repeat").value = "a long new password";
  pwSubmit(); await tick(); await tick();
  expect(pwPosts.length === 1 && pwPosts[0][0] === "/auth/password"
    && JSON.stringify(pwPosts[0][1]) === JSON.stringify({ current: "initial-generated", new: "a long new password" })
    && text(main).includes("Password changed. Every other session of yours was signed out") && byId("password-current").value === "",
    "password: changed, the fields cleared, the other sessions named");
  byId("password-current").value = "not the current one"; byId("password-new").value = "another long password"; byId("password-repeat").value = "another long password";
  pwSubmit(); await tick(); await tick();
  expect(text(byId("password-current-error")) === "This is not your current password." && byId("password-current").getAttribute("aria-invalid") === "true",
    "password: a wrong current one is put next to its field");
  win.Maity.api.post = realPost5;

  // Meat proxy (docs/api.md §5.2): the human's own switch on the account, PATCH /me; the page says the one sentence agents read.
  const mpPatch = win.Maity.api.patch, mpSent = [];
  win.Maity.api.patch = (p, b) => { mpSent.push([p, b]); return mpPatch(p, b); };
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("meat-proxy") && !byId("meat-proxy").checked && text(byId("meat-proxy-note")) === "This person says: I am a meat proxy. "
    + "Lead me step by step rather than expecting me to explain; and when you need a human's hands, come to me first.",
    "meat proxy: the account offers the switch, off, and shows exactly the note agents read (§5.2)");
  byId("meat-proxy").checked = true; byId("meat-proxy").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mpSent[0]) === JSON.stringify(["/me", { meat_proxy: true }]) && byId("meat-proxy").checked
    && text(main).includes("Saved: your agents and the agents of your projects are told"), "meat proxy: switched on with PATCH /me, said so");
  win.Maity.api.patch = () => Promise.reject(new win.Maity.api.ApiError("x", 500, "/me", "internal"));
  byId("meat-proxy").checked = false; byId("meat-proxy").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("meat-proxy").checked && text(main).includes("Not saved"), "meat proxy: a failed change is said and the switch goes back");
  win.Maity.api.patch = mpPatch;
  await mpPatch("/me", { meat_proxy: false });
  const mpBody = win.Maity.api.hubBody;
  win.Maity.api.hubBody = () => Promise.resolve(new Set());
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(!byId("meat-proxy"), "meat proxy: no switch on a hub whose machine form does not name it");
  win.Maity.api.hubBody = mpBody;
  // The note is the hub's (/me member.meat_proxy_note), never a copy: a hub that does not send it shows none.
  const mpGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? mpGet(p).then((m) => { m.member.meat_proxy_note = "This person says: a newer note."; return m; }) : mpGet(p));
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(text(byId("meat-proxy-note")) === "This person says: a newer note.", "meat proxy: the note shown is the one /me carries");
  win.Maity.api.get = (p) => (p === "/me" ? mpGet(p).then((m) => { delete m.member.meat_proxy_note; return m; }) : mpGet(p));
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("meat-proxy") && !byId("meat-proxy-note") && !text(main).includes("This person says"), "meat proxy: a hub without the note shows the switch and no note of the page's own");
  win.Maity.api.get = mpGet;
  // Your data (docs/api.md §2.9): the export and the deletion request, each a sensitive call (§2.8): the page asks for the
  // password or a code where the hub says so, proves it and makes the call again.
  const ydGet = win.Maity.api.get, ydPost = win.Maity.api.post, ydSave = win.Maity.yourData.save;
  const ydSaved = [], ydProofs = [];
  win.Maity.yourData.save = (name, textOf) => { ydSaved.push([name, textOf]); };
  let ydNeed = "step_up_required";
  win.Maity.api.get = (p) => {
    if (p === "/me/export" && ydNeed) { const r = ydNeed; return Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: r })); }
    return ydGet(p);
  };
  win.Maity.api.post = (p, b) => {
    if (p === "/auth/second-factor/verify" || p === "/auth/reauthenticate") ydProofs.push([p, b]);
    if ((p === "/auth/second-factor/verify" && b.code === "123456") || (p === "/auth/reauthenticate" && b.password === "correct horse")) ydNeed = null;
    if (p === "/me/deletion" && ydNeed) { const r = ydNeed; return Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: r })); }
    return ydPost(p, b);
  };
  await go("#/account/data"); for (let k = 0; k < 4; k++) await tick();
  const ydBox = () => main.querySelector("section.your-data");
  expect(ydBox() && btn(ydBox(), "Export my data") && text(ydBox()).includes("Delete my account"), "your data: the account has the export and the deletion");
  btn(ydBox(), "Export my data").click(); for (let k = 0; k < 4; k++) await tick();
  const ydForm = () => ydBox().querySelector("form.step-up");
  expect(ydForm() && text(ydForm()).includes("Exporting your data needs your second factor") && !ydSaved.length,
    "your data: the export asks for a code where the hub wants the step-up, naming the action");
  byId("step-up-step_up_required").value = "000000"; ydForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(ydForm() && text(ydForm()).includes("That code is not valid.") && !ydSaved.length, "your data: a wrong code is said, nothing exported");
  byId("step-up-step_up_required").value = "123456"; ydForm().dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(!ydForm() && ydSaved.length === 1 && /^maity-export-maintainer-\d{4}-\d{2}-\d{2}\.json$/.test(ydSaved[0][0]) && JSON.parse(ydSaved[0][1]).format === 1
    && text(ydBox()).includes("Your export was saved."), "your data: proven, the call is made again and the file saved under the hub's name");
  ydNeed = "step_up_required";
  btn(ydBox(), "Export my data").click(); for (let k = 0; k < 4; k++) await tick();
  btn(ydForm(), "Cancel").click(); for (let k = 0; k < 4; k++) await tick();
  expect(!ydForm() && ydSaved.length === 1 && !text(ydBox()).includes("Not exported"), "your data: Cancel exports nothing and says no failure");
  // The deletion: confirmed by the handle, the password asked where the hub wants it, then pending until the mail's link.
  ydNeed = "reauthentication_required";
  const ydDel = () => btn(ydBox(), "Delete my account");
  expect(ydDel() && ydDel().disabled, "your data: Delete my account is off until the handle is typed");
  byId("delete-account-confirm").value = "@maintainer"; byId("delete-account-confirm").dispatch("input");
  ydBox().querySelector("form.account-delete").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(ydForm() && text(ydForm()).includes("password"), "your data: the deletion asks for the password where the hub wants it");
  expect(byId("delete-account-confirm").disabled && ydDel().disabled, "your data: while it is asked, the handle is locked and the button off");
  byId("step-up-reauthentication_required").value = "wrong"; ydForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(ydForm()).includes("That is not your password."), "your data: a wrong password is said");
  byId("step-up-reauthentication_required").value = "correct horse"; ydForm().dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(ydBox()).includes("We sent a mail to your verified address") && btn(ydBox(), "Withdraw the deletion") && text(ydBox()).includes("follow the link in the mail"),
    "your data: requested, the page says it waits for the mail's link and offers to withdraw");
  btn(ydBox(), "Withdraw the deletion").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(ydBox()).includes("The deletion was withdrawn") && ydDel(), "your data: withdrawn, the account stays");
  win.Maity.api.post = (p, b) => (p === "/me/deletion" ? Promise.reject(new win.Maity.api.ApiError("x", 409, p, "namespace_owner", {})) : ydPost(p, b));
  byId("delete-account-confirm").value = "maintainer"; byId("delete-account-confirm").dispatch("input");
  ydBox().querySelector("form.account-delete").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(ydBox()).includes("Not asked: a project in your namespace is still open"), "your data: the hub's refusal in words");
  win.Maity.api.post = (p, b) => (p === "/me/deletion" ? Promise.reject(new win.Maity.api.ApiError("x", 409, p, "org_last_owner", { orgs: ["oz-team", "guild"] })) : ydPost(p, b));
  byId("delete-account-confirm").value = "maintainer"; byId("delete-account-confirm").dispatch("input");
  ydBox().querySelector("form.account-delete").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(ydBox()).includes("Not asked: you are the last owner of @oz-team, @guild: make someone else an owner, or delete the organisation, first"),
    "your data: the last owner of organisations is told which ones");
  // One slot, one question: a second question cancels the first, whose call then does not hang (the deletion's field free again).
  win.Maity.api.post = (p, b) => {
    if (p === "/auth/second-factor/verify" || p === "/auth/reauthenticate") ydProofs.push([p, b]);
    if (p === "/me/deletion") return Promise.reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: "reauthentication_required" }));
    return ydPost(p, b);
  };
  ydNeed = "step_up_required";
  byId("delete-account-confirm").value = "@maintainer"; byId("delete-account-confirm").dispatch("input");
  ydBox().querySelector("form.account-delete").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("step-up-reauthentication_required") && byId("delete-account-confirm").disabled, "your data: the deletion's password is asked, its field locked");
  btn(ydBox(), "Export my data").click(); for (let k = 0; k < 4; k++) await tick();
  expect(byId("step-up-step_up_required") && !byId("step-up-reauthentication_required") && !byId("delete-account-confirm").disabled
    && !ydDel().disabled && !text(ydBox()).includes("Not asked"), "your data: a second question cancels the first; the deletion is free again, no failure said");
  // A password goes as typed, spaces included; a code typed with a space is a code.
  btn(ydForm(), "Cancel").click(); for (let k = 0; k < 4; k++) await tick();
  ydBox().querySelector("form.account-delete").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  ydProofs.length = 0;
  byId("step-up-reauthentication_required").value = "  spaced pass  "; ydForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(ydProofs[0]) === JSON.stringify(["/auth/reauthenticate", { password: "  spaced pass  " }]), "your data: a password is sent as typed, not trimmed");
  btn(ydForm(), "Cancel").click(); for (let k = 0; k < 4; k++) await tick();
  btn(ydBox(), "Export my data").click(); for (let k = 0; k < 4; k++) await tick();
  ydProofs.length = 0;
  byId("step-up-step_up_required").value = "482 913"; ydForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(ydProofs[0]) === JSON.stringify(["/auth/second-factor/verify", { code: "482913" }]), "your data: a code typed with a space goes as a code");
  if (ydForm()) { btn(ydForm(), "Cancel").click(); for (let k = 0; k < 4; k++) await tick(); }
  win.Maity.api.get = ydGet; win.Maity.api.post = ydPost; win.Maity.yourData.save = ydSave;
  // A hub whose machine form lists neither route (§2.9 not deployed yet): said quietly, nothing offered.
  const ydHas = win.Maity.api.hubHas;
  win.Maity.api.hubHas = (m, p) => (p === "/me/export" || p === "/me/deletion" ? Promise.resolve(false) : ydHas(m, p));
  await go("#/account/data"); for (let k = 0; k < 4; k++) await tick();
  expect(ydBox() && !btn(ydBox(), "Export my data") && !btn(ydBox(), "Delete my account") && text(ydBox()).includes("This hub cannot export your data yet.")
    && text(ydBox()).includes("This hub cannot delete an account yet."), "your data: a hub without the routes offers neither, said quietly");
  win.Maity.api.hubHas = () => Promise.reject(new Error("unreadable"));
  await go("#/account/data"); for (let k = 0; k < 4; k++) await tick();
  expect(btn(ydBox(), "Export my data") && btn(ydBox(), "Delete my account"), "your data: a machine form that cannot be read keeps both");
  win.Maity.api.hubHas = ydHas;
  // Organisations (docs/api.md §6.26) under the account: the list and a new one, then one organisation's
  // members, invitations, settings and deletion, each refusal of the hub in words.
  await go("#/account/orgs"); for (let k = 0; k < 4; k++) await tick();
  expect(plainTitle() === "Organisations · Maity" && main.querySelector('ul.org-list a[href="#/account/orgs/oz-team"]') && text(main).includes("@oz-team · owner")
    && byId("org-new-handle"), "orgs: #/account/orgs lists the human's organisations with their role and offers a new one");
  const orgCreate = () => main.querySelector("form.org-create");
  byId("org-new-handle").value = "Bad Handle"; byId("org-new-name").value = "Bad"; orgCreate().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(orgCreate()).includes("Not created: handle: 2 to 31 lowercase letters"), "orgs: a handle the hub refuses is said with its rule");
  byId("org-new-handle").value = "@acme"; byId("org-new-name").value = " Acme "; orgCreate().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(win.location.hash === "#/account/orgs/acme", "orgs: created (the @ dropped), the page goes to the new organisation");
  await go("#/account/orgs/acme"); for (let k = 0; k < 6; k++) await tick();
  expect(plainTitle() === "@acme · Organisations · Maity" && text(main).includes("Acme") && text(main).includes("@acme · you are owner")
    && main.querySelectorAll("li.org-member").length === 1, "orgs: the new organisation has its creator as the one owner");
  await go("#/account/orgs/oz-team"); for (let k = 0; k < 6; k++) await tick();
  const orgMembers = () => main.querySelector("section.org-members");
  expect(orgMembers() && byId("org-role-hum-maintainer") && byId("org-role-hum-anna") && text(orgMembers()).includes("@maintainer (you)")
    && btn(orgMembers(), "Leave") && btn(orgMembers(), "Remove"), "orgs: an owner may change every role, remove others and leave");
  byId("org-role-hum-maintainer").value = "admin"; byId("org-role-hum-maintainer").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(text(orgMembers()).includes("Not changed: the organisation would have no owner left") && byId("org-role-hum-maintainer").value === "owner",
    "orgs: the last owner's demotion is refused in words and the role shown again");
  const orgInvites = () => main.querySelector("section.org-invitations");
  expect(orgInvites() && text(orgInvites()).includes("@ben as member") && btn(orgInvites(), "Withdraw"), "orgs: the open invitations, each with Withdraw");
  byId("org-invite-handle").value = "anna"; main.querySelector("form.org-invite").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(orgInvites()).includes("Not invited: handle: already a member"), "orgs: inviting a member is said");
  byId("org-invite-handle").value = "@carl"; byId("org-invite-role").value = "admin"; main.querySelector("form.org-invite").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("Invited @carl as admin.") && text(orgInvites()).includes("@carl as admin"), "orgs: an invitation is listed at once");
  btn(orgInvites(), "Withdraw").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("The invitation of @ben was withdrawn.") && !text(orgInvites()).includes("@ben as"), "orgs: a withdrawn invitation leaves the list");
  // An admin sees no Withdraw on an invitation for the role owner, and the fixture hub refuses it (§6.26).
  const orgGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/orgs/oz-team" ? orgGet(p).then((o) => Object.assign(o, { my_role: "admin" }))
    : p === "/orgs/oz-team/members/invitations" ? orgGet(p).then((r) => ({ items: r.items.concat([{ id: "oinv-own", handle: "dora", role: "owner",
      invited_by: { id: "hum-maintainer", handle: "maintainer" }, created_at: "2026-10-29T10:00:00Z", expires_at: "2026-11-12T10:00:00Z" }]) })) : orgGet(p));
  await go("#/account/orgs/oz-team"); for (let k = 0; k < 6; k++) await tick();
  const orgOwnRow = main.querySelectorAll("li.org-invitation").find((li) => text(li).includes("@dora as owner"));
  expect(orgOwnRow && !btn(orgOwnRow, "Withdraw") && main.querySelectorAll("li.org-invitation").some((li) => btn(li, "Withdraw")) && !main.querySelector("form.org-settings"),
    "orgs: an admin may withdraw invitations for member and admin, not for owner, and has no settings");
  win.Maity.api.get = orgGet;
  // Suspended (§6.26): no rename and no public page turned on from the form.
  win.Maity.api.get = (p) => (p === "/orgs/oz-team" ? orgGet(p).then((o) => Object.assign(o, { moderation: { action: "suspend", report_id: "rpt-1", at: "2026-10-29T10:00:00Z" } })) : orgGet(p));
  await go("#/account/orgs/oz-team"); for (let k = 0; k < 6; k++) await tick();
  expect(byId("org-handle").disabled && byId("org-public-page").disabled && !byId("org-name").disabled
    && text(main).includes("its handle cannot change and its public page cannot be turned on"), "orgs: while suspended, the handle and turning the page on are off");
  win.Maity.api.get = orgGet;
  // The handle in the address is read as a typed one: decoded, without @, in lowercase.
  await go("#/account/orgs/%40OZ-Team"); for (let k = 0; k < 6; k++) await tick();
  expect(plainTitle() === "@oz-team · Organisations · Maity" && text(main).includes("@oz-team · you are owner"),
    "orgs: an address with @ and capitals opens the organisation, the title as its handle");
  const orgOwnInv = await win.Maity.api.post("/orgs/oz-team/members/invitations", { handle: "dora", role: "owner" });
  expect(!("request_id" in orgOwnInv) && orgOwnInv.handle === "dora", "orgs: an invitation item carries no request id (§6.26)");
  await win.Maity.api.del("/orgs/oz-team/members/invitations/" + orgOwnInv.id);
  const orgSaid = win.Maity.orgs.said;
  expect(orgSaid({ code: "alias_limit", details: { limit: 8 } }).message.includes("8 earlier handles")
    && orgSaid({ code: "invalid", details: { fields: { confirm: "mismatch" } } }).message === "confirm: not the organisation's handle; read the page again",
    "orgs: the alias limit and a confirmation that no longer matches in words");
  await go("#/account/orgs/oz-team"); for (let k = 0; k < 6; k++) await tick();
  byId("org-role-hum-anna").value = "member"; byId("org-role-hum-anna").dispatch("change"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("@anna is member now.") && byId("org-role-hum-anna").value === "member", "orgs: a role changed");
  byId("org-handle").value = "oz-crew"; byId("org-members-create").checked = true; main.querySelector("form.org-settings").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(win.location.hash === "#/account/orgs/oz-crew", "orgs: renamed, the page follows the new handle");
  await go("#/account/orgs/oz-team"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("@oz-crew · you are owner · also known as @oz-team") && byId("org-members-create").checked,
    "orgs: the old handle still leads to it, named as an alias; the setting kept");
  const orgDel = () => btn(main.querySelector("section.org-delete-part"), "Delete the organisation");
  expect(orgDel() && orgDel().disabled, "orgs: Delete is off until the handle is typed");
  byId("org-delete-confirm").value = "@oz-crew"; byId("org-delete-confirm").dispatch("input");
  main.querySelector("form.org-delete").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(win.location.hash === "#/account/orgs", "orgs: deleted with its handle typed, the page goes back to the list");
  await go("#/account/orgs/oz-crew"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("You are in no organisation @oz-crew."), "orgs: one that is gone, or not one's own, is said as not found");
  win.Maity.api.hubHas = (m, p) => (p === "/orgs" ? Promise.resolve(false) : ydHas(m, p));
  await go("#/account/orgs"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("This hub has no organisations yet.") && !byId("org-new-handle"), "orgs: a hub without them says so quietly");
  win.Maity.api.hubHas = ydHas;
  // Pictures (docs/api.md §6.10): one's own on the account, an agent's in its row on Members;
  // the account keeps only the agents no project of one's own shows (tsk-th1yq0jtk3yf).
  const avCalls = [];
  win.Maity.api.putImage = (p, blob, type) => { avCalls.push(["PUT", p, type]); return realPut(p, blob, type); };
  win.Maity.api.del = (p) => { avCalls.push(["DELETE", p]); return realDel(p); };
  await go("#/account/picture");
  const avHeading = main.querySelector(".picture-heading");
  expect(avHeading && avHeading.getAttribute("tabindex") === "-1" && byId("avatar-file-hum-maintainer") && text(main).includes("Generated from the member id")
    && !btn(main, "Remove the upload"), "picture: the account shows the picture, where it comes from and an upload; nothing to remove yet");
  // The agents' pictures are on /agents now (tsk-hn82893h9sdh): the account only points there.
  expect(!main.querySelector(".picture-list") && !byId("avatar-file-agt-x") && main.querySelectorAll("a").some((a) => a.getAttribute("href") === "#/agents" && text(a) === "Your agents"),
    "picture: the account has no agents of its own any more, a link to Your agents instead");
  // Your agents (/agents): every profile across projects, its memberships with instances, Add to a project.
  await go("#/agents"); for (let k = 0; k < 6; k++) await tick();
  const agCards = () => main.querySelectorAll("li.agent-card");
  const agCard = (id) => agCards().find((li) => li.getAttribute("data-agent") === id);
  expect(plainTitle() === "Your agents · Maity" && agCard("agt-x") && agCard("agt-b") && text(agCard("agt-x")).includes("Spare @maintainer/spare")
    && text(agCard("agt-x")).includes("guest/guestlab") && byId("avatar-file-agt-x") && byId("avatar-file-agt-b"),
    "agents page: every profile of one's own, by global name, its memberships, each with its picture");
  expect(text(agCard("agt-b")).includes("maintainer/maity · member · coder") && text(agCard("agt-b")).includes("1 of 1 instance active")
    && agCard("agt-b").querySelectorAll("a").some((a) => a.getAttribute("href") === "#/maintainer/maity/agents/agt-b/rulebook"),
    "agents page: a membership with trust and role, the instances against the team's limit, the rulebook linked: " + text(agCard("agt-b")).slice(0, 200));
  byId("agent-add-agt-b").value = "maintainer/maity"; agCard("agt-b").querySelector("form.agent-add").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(win.location.hash === "#/maintainer/maity/agents/join?agent=agt-b", "agents page: Add to a project opens that project's join panel for the profile");
  await go(win.location.hash); for (let k = 0; k < 8; k++) await tick();
  expect(main.querySelector(".join-panel") && !main.querySelector(".join-panel").hidden && byId("join-agent").value === "agt-b"
    && !main.querySelector("fieldset.join-instance").hidden, "agents page: there the panel is open with the profile chosen, as an instance where it is a member");
  btn(main.querySelector(".join-panel"), "Cancel").click(); await tick();
  // A new profile, a refused handle, then a rename that keeps the old handle as an earlier one.
  await go("#/agents"); for (let k = 0; k < 6; k++) await tick();
  byId("agent-new-handle").value = "Bad Handle"; byId("agent-new-name").value = "Bad"; main.querySelector("form.agent-new").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector("form.agent-new")).includes("Not created: handle:"), "agents page: a handle the hub refuses is said at the form");
  byId("agent-new-handle").value = "@helper"; byId("agent-new-name").value = " Helper "; main.querySelector("form.agent-new").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  const agHelper = agCards().find((li) => text(li).includes("Helper @maintainer/helper"));
  expect(agHelper && text(main).includes("The profile @helper was created") && text(agHelper).includes("In no project yet."), "agents page: a new profile, in no project yet");
  const agHelperId = agHelper.getAttribute("data-agent");
  byId("agent-handle-" + agHelperId).value = "agent-b"; agHelper.querySelector("form.agent-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(agHelper.querySelector("form.agent-edit")).includes("Not saved: handle: you have a profile with this handle already"), "agents page: a handle one's other profile has is refused");
  byId("agent-handle-" + agHelperId).value = "helper-2"; byId("agent-git-name-" + agHelperId).value = "Helper";
  byId("agent-git-email-" + agHelperId).value = "helper@example.org"; agHelper.querySelector("form.agent-edit").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main).includes("Saved. The old handle @helper still names it as an earlier one.") && text(agCard(agHelperId)).includes("@maintainer/helper-2"),
    "agents page: renamed with a git identity, the old handle kept as an earlier one");
  // A hub whose machine form does not name handle on PATCH /agents/{id} (before #523) is offered no rename.
  const agBody = win.Maity.api.hubBody;
  win.Maity.api.hubBody = (m, p) => (m === "PATCH" && p === "/agents/{agent_id}" ? Promise.resolve(new Set(["display_name", "git_identity"])) : agBody(m, p));
  await go("#/all"); await go("#/agents"); for (let k = 0; k < 6; k++) await tick();
  expect(agCard("agt-b") && byId("agent-name-agt-b") && !byId("agent-handle-agt-b"), "agents page: a hub without renames offers no handle field");
  win.Maity.api.hubBody = agBody;
  // A failed first read of the joins: Try again opens the panel with the profile asked for still chosen.
  const agAll = win.Maity.api.getAll;
  let agFail = true;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/joins" && agFail ? (agFail = false, Promise.reject(new win.Maity.api.ApiError("down", 503, p, "unavailable", {}))) : agAll(p));
  await go("#/all"); await go("#/maintainer/maity/agents/join?agent=agt-b"); for (let k = 0; k < 8; k++) await tick();
  btn(main.querySelector(".join-panel"), "Try again").click(); for (let k = 0; k < 8; k++) await tick();
  expect(!main.querySelector(".join-panel").hidden && byId("join-agent") && byId("join-agent").value === "agt-b", "agents page: Try again keeps the profile asked for");
  btn(main.querySelector(".join-panel"), "Cancel").click(); await tick();
  win.Maity.api.getAll = agAll;
  await go("#/account/picture"); for (let k = 0; k < 4; k++) await tick();
  await pick("avatar-file-hum-maintainer", fakeFile(SVG, 0, "image/svg+xml"));
  expect(!avCalls.length && text(main).includes("Not uploaded: not a PNG, JPEG or WebP image"), "picture: an SVG is refused by its bytes, before sending");
  await pick("avatar-file-hum-maintainer", fakeFile(PNG, 1024 * 1024 + 1));
  expect(!avCalls.length && text(main).includes("Not uploaded: larger than 1 MiB"), "picture: over 1 MiB is refused before sending");
  await pick("avatar-file-hum-maintainer", fakeFile(WEBP, 2000, "image/png"));
  await tick(); await tick();
  const meAfter = await win.Maity.api.get("/me");
  const memberAfter = (await win.Maity.api.getAll("/projects/maintainer/maity/members")).items.find((x) => x.id === "hum-maintainer");
  expect(JSON.stringify(avCalls[0]) === JSON.stringify(["PUT", "/me/avatar", "image/webp"]) && meAfter.member.avatar_source === "uploaded"
    && memberAfter.avatar_source === "uploaded" && memberAfter.avatar_url === meAfter.member.avatar_url,
    "picture: uploaded with the sniffed type; the member is the same everywhere");
  expect(text(main).includes("Picture uploaded.") && text(main).includes("Uploaded.") && btn(main, "Remove the upload"), "picture: the page says so and offers Remove");
  btn(main, "Remove the upload").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(avCalls[1]) === JSON.stringify(["DELETE", "/me/avatar"]) && text(main).includes("Uploaded picture removed; the generated one shows again.")
    && !btn(main, "Remove the upload"), "picture: Remove deletes the upload; the generated picture applies again");
  // An agent in one's project: its picture in its row on Members, opened with Manage.
  await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick(); await agOpen("agt-b");
  const avRow = () => main.querySelectorAll("tr.member-manage").find((r) => r.id === "member-manage-agt-b");
  expect(avRow() && avRow().querySelector(".member-picture-title") && text(avRow().querySelector(".member-picture-title")) === "Picture" && byId("avatar-file-agt-b"),
    "picture: an own agent's row on Members, managed, holds its picture and upload");
  await pick("avatar-file-agt-b", fakeFile(PNG, 3000));
  for (let k = 0; k < 6; k++) await tick();
  const bAfter = (await win.Maity.api.getAll("/projects/maintainer/maity/members")).items.find((x) => x.id === "agt-b");
  expect(JSON.stringify(avCalls[2]) === JSON.stringify(["PUT", "/agents/agt-b/avatar", "image/png"]) && bAfter.avatar_source === "uploaded",
    "picture: an owner sets an agent's picture, which its member view carries");
  expect(avRow() && text(main).includes("Picture uploaded.") && btn(avRow(), "Remove the upload"),
    "picture: the row stays open, says so and offers Remove");
  await go("#/account/picture");
  // The hub's refusals in words.
  const refuse = (code, details) => () => Promise.reject(new win.Maity.api.ApiError("x", code === "invalid" ? 400 : 429, "/me/avatar", code, details));
  win.Maity.api.putImage = refuse("invalid", { fields: { body: "dimensions" } });
  await pick("avatar-file-hum-maintainer", fakeFile(PNG, 3000));
  expect(text(main).includes("Not uploaded: more than 4096 pixels on a side"), "picture: the hub's dimensions refusal in words");
  win.Maity.api.putImage = refuse("rate_limited", {});
  await pick("avatar-file-hum-maintainer", fakeFile(PNG, 3000));
  expect(text(main).includes("Not uploaded: too many changes of this picture in the last hour"), "picture: the rate limit in words");
  win.Maity.api.putImage = () => Promise.reject(new win.Maity.api.ApiError("Not found", 404, "/me/avatar", "not_found", {}));
  await pick("avatar-file-hum-maintainer", fakeFile(PNG, 3000));
  expect(text(main).includes("Not uploaded: this hub does not take pictures yet"), "picture: a hub without the endpoint is said as such");
  win.Maity.api.putImage = realPut; win.Maity.api.del = realDel;
  // The mock as the hub: someone else's profile is not_found; ten changes an hour.
  let notMine = null;
  try { await win.Maity.api.del("/agents/agt-zz/avatar"); } catch (err) { notMine = err; }
  let limited = null;
  try { for (let k = 0; k < 12; k++) await win.Maity.api.del("/agents/agt-c/avatar"); } catch (err) { limited = err; }
  expect(notMine && notMine.code === "not_found" && limited && limited.code === "rate_limited", "picture: the mock answers not_found for another's profile and limits ten changes an hour");
  // An avatar is loaded only from the hub's own path, and one that fails to load gives way to the generated one.
  let foreign = null;
  try { win.Maity.dom.h("img", { src: "https://evil.example/api/v1/avatars/agt-a?v=1" }); } catch (err) { foreign = err; }
  const avBox = document.createElement("div");
  const avImg = win.Maity.avatar({ id: "agt-a", avatar_url: "/api/v1/avatars/agt-a?v=abc" }, 24);
  avBox.appendChild(avImg);
  const loaded = avBox.querySelector("img");
  avImg.dispatch("error");
  expect(foreign && loaded && avBox.querySelector("svg") && !avBox.querySelector("img"), "picture: only the hub's avatar path loads; a failed load shows the generated picture");

  // sign out, sign in
  profileButton().click(); await tick();
  header.querySelectorAll("button.menu-item").find((b) => b.textContent === "Sign out").click(); await tick(); await tick();
  expect(byId("login-handle"), "sign out shows the login");
  // Signed out, the theme is a menu in the header, beside nothing else.
  expect(thButton() && thButton().getAttribute("aria-label") === "Theme: System", "theme: signed out, a theme switch in the header, System by default");
  const thPick = async (label) => {
    thButton().click(); await tick();
    header.querySelectorAll(".menu-item").find((el) => el.textContent === label && el.getAttribute("role") === "menuitemradio").click(); await tick();
  };
  thButton().click(); await tick();
  expect(JSON.stringify(header.querySelectorAll(".menu-item").filter((el) => el.getAttribute("role") === "menuitemradio").map((el) => el.textContent + ":" + el.getAttribute("aria-checked")))
    === JSON.stringify(["System:true", "Light:false", "Dark:false"]), "theme: signed out, three choices, the current one checked");
  thButton().click(); await tick();
  win.localStorage = { getItem: (k) => (k in thStore ? thStore[k] : null), setItem: (k, v) => { thStore[k] = String(v); }, removeItem: (k) => { delete thStore[k]; } };
  await thPick("Dark");
  expect(thHtml.attrs["data-theme"] === "dark" && thStore["maity.theme"] === "dark" && thButton().getAttribute("aria-label") === "Theme: Dark", "theme: signed out, Dark sets data-theme=dark and is kept");
  expect(byId(thButton().getAttribute("aria-controls")).getAttribute("aria-label") === "Theme",
    "theme: the menu's name stays Theme when the pick changes");
  await thPick("System");
  expect(thHtml.attrs["data-theme"] === undefined && !("maity.theme" in thStore), "theme: signed out, System removes both");
  delete win.localStorage;
  // At the root without a session the dashboard draws the login page: the landing page is the hub's own static
  // page (§16.7), which the dashboard never asks for. The legal pages that are set are linked (§16.7.1).
  const lpGet = win.Maity.api.get, lpReads = [];
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => { if (p === "/landing" || p === "/legal") lpReads.push(p); return lpGet(p); };
  await go("#/all"); await go(""); for (let k = 0; k < 6; k++) await tick();
  const lpLegal = main.querySelector(".legal-links");
  expect(byId("login-handle") && !main.querySelector("article.landing") && !lpReads.includes("/landing") && lpReads.includes("/legal")
    && lpLegal && lpLegal.querySelectorAll("a").map((a) => a.getAttribute("href") + "=" + text(a)).join() === "/impressum=Imprint",
    "landing: the root without a session is the login page, the landing never read here; the legal pages set are linked");
  win.Maity.api.get = lpGet; win.Maity.api.forgetRoutes();
  // An invitation (docs/api.md §3.4) without a session: who invites to what, and the ways in this hub offers.
  const ivPage = () => main.querySelector("article.invite");
  await go("#/invite/open-xxxxxxxxxxxxxxxx1"); for (let k = 0; k < 4; k++) await tick();
  const ivSignIn = ivPage() && ivPage().querySelectorAll("a").find((a) => text(a) === "Sign in to accept");
  const ivRegister = ivPage() && ivPage().querySelectorAll("a").find((a) => text(a) === "Create one");
  expect(ivPage() && text(ivPage()).includes("Maintainer invites you to join Maity as member · coder.") && text(ivPage().querySelector(".invite-note")) === "You review the web side; D will brief you."
    && ivSignIn && ivSignIn.getAttribute("href") === "#/login?next=%2Finvite%2Fopen-xxxxxxxxxxxxxxxx1"
    && ivRegister && ivRegister.getAttribute("href") === "#/register?next=%2Finvite%2Fopen-xxxxxxxxxxxxxxxx1"
    && header.querySelector(".theme-menu") && plainTitle() === "Join Maity · Maity",
    "invite: signed out, the invitation and both ways in, each returning to it");
  // The door (the designer's pass part 2): one centred card; the role in bold, the note a quote with who wrote it,
  // the logo or its monogram, the action full width.
  expect(ivPage().classList.contains("door") && text(ivPage().querySelector(".invite-lead strong")) === "member · coder"
    && text(ivPage().querySelector(".invite-note-by")) === "— Maintainer" && ivPage().querySelector(".invite-project .invite-logo")
    && ivSignIn.classList.contains("door-action") && thCss.includes(".door { max-width: 28rem; margin: 10vh auto;"),
    "invite: one centred card, the role in bold, the note a quote signed, the logo, the action full width");
  await go("#/invite/only-xxxxxxxxxxxxxxxx2"); for (let k = 0; k < 4; k++) await tick();
  expect(!ivPage().querySelectorAll("a").some((a) => text(a) === "Create one") && text(ivPage()).includes("This hub does not create new accounts")
    && ivPage().querySelectorAll("a").some((a) => text(a) === "Sign in to accept"), "invite: where the hub does not register, only signing in");
  await go("#/invite/nothing-here-at-all-000"); for (let k = 0; k < 4; k++) await tick();
  expect(text(ivPage()).includes("This invitation cannot be used") && text(ivPage()).includes("expired, been used or been withdrawn"),
    "invite: an unknown, used, expired or revoked link is one answer");
  // Registration (§2.7.1): from an invitation that admits, though the hub does not register on request.
  const rgPosts = [];
  const rgPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p === "/auth/register") rgPosts.push(b); return rgPost(p, b); };
  await go("#/register?next=%2Finvite%2Fbound-xxxxxxxxxxxxxxx3"); for (let k = 0; k < 6; k++) await tick();
  const rgForm = () => main.querySelector("form.register-form");
  expect(rgForm() && text(rgForm()).includes("Use the address the invitation was sent to"), "register: from an invitation that admits, the form, bound to its address");
  byId("register-address").value = "anna@example.org"; byId("register-password").value = "short"; byId("register-repeat").value = "short";
  rgForm().dispatch("submit"); await tick();
  expect(!rgPosts.length && text(rgForm()).includes("at least 12 characters"), "register: a short password is said before anything is sent");
  byId("register-password").value = "a long enough password"; byId("register-repeat").value = "a long enough password";
  rgForm().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(rgPosts[0]) === JSON.stringify({ address: "anna@example.org", password: "a long enough password", next: "/invite/bound-xxxxxxxxxxxxxxx3" })
    && text(main).includes("Check your mail") && text(main).includes("works for 24 hours") && text(main).includes("come back to where you were"),
    "register: sent with the invitation as next, then 'check your mail' for every address alike");
  win.Maity.api.post = rgPost;
  await go("#/register"); for (let k = 0; k < 6; k++) await tick();
  expect(!rgForm() && text(main).includes("This hub does not create new accounts on request."), "register: a hub that does not register says so, with the way to sign in");
  // A hub that registers on request (§2.7, GET /auth/methods): the form, and its terms named with their version.
  const rgGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/auth/methods"
    ? Promise.resolve({ password: true, device_code: true, email_link: true, registration: true, terms: { url: "https://example.org/terms", version: "2026-10" } }) : rgGet(p));
  await go("#/login"); await go("#/register"); for (let k = 0; k < 6; k++) await tick();
  const rgTerms = main.querySelector(".register-terms");
  expect(rgForm() && rgTerms && text(rgTerms) === "When you complete your account you accept this hub's terms (version 2026-10)."
    && rgTerms.querySelector("a").getAttribute("href") === "https://example.org/terms" && rgTerms.querySelector("a").getAttribute("rel") === "noopener noreferrer",
    "register: where the hub registers, the form names its terms and their version, as a link");
  win.Maity.api.get = (p) => (p === "/auth/methods"
    ? Promise.resolve({ password: true, device_code: true, email_link: true, registration: true, terms: { url: "javascript:alert(1)", version: "1" } }) : rgGet(p));
  await go("#/login"); await go("#/register"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".register-terms") && !main.querySelector(".register-terms a"), "register: terms whose address is not plain https are named, not linked");
  win.Maity.api.get = rgGet;
  // Signing in from the invitation returns to it, now with the button to join.
  await go("#/login?next=%2Finvite%2Fonly-xxxxxxxxxxxxxxxx2"); for (let k = 0; k < 4; k++) await tick();
  byId("login-handle").value = "maintainer"; byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); for (let k = 0; k < 8; k++) await tick();
  expect(win.location.hash === "#/invite/only-xxxxxxxxxxxxxxxx2" && ivPage() && btn(ivPage(), "Join Maity as Maintainer"),
    "invite: signing in with the invitation as next comes back to it, signed in");
  await win.Maity.api.post("/auth/logout");
  await go(""); await tick(); await tick();
  byId("login-handle").value = "maintainer"; byId("login-password").value = "initial-generated";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(byId("login-handle") && text(main).includes("wrong"), "password: the old password no longer signs in");
  byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(!byId("login-handle") && !main.querySelector(".error"), "sign in with the new password returns to the dashboard");

  // Sign-in without a password (§2.6): the code, its QR, the approval by number; the code on the new device; a link by mail.
  const ds = win.Maity.deviceSignIn;
  expect(ds.normalCode("k7qm-4xpr-9d2f") === "K7QM4XPR9D2F" && ds.normalCode("K7QM 4XPR 9D2I") === "K7QM4XPR9D21" && ds.normalCode("oooo-llll-oooo") === "000011110000"
    && ds.normalCode("K7QM-4XPR-9D2") === null && ds.normalCode("K7QM-4XPR-9D2U") === null && ds.normalCode("K7QM-4XPR") === null,
    "device code: twelve characters, read as the hub reads it (I and L as 1, O as 0), else refused; the eight of before no longer");
  const qrRows = win.Maity.qr.matrix("https://hub.example.org/#/sign-in/code?c=K7QM4XPR").map((r) => r.map((b) => (b ? 1 : 0)).join("")).join("\n");
  expect(qrRows.split("\n").length === 33 && require("crypto").createHash("sha256").update(qrRows).digest("hex") === "1b941096a98468ba07ea7d475e887cdb49a0aa655d2ec0e0e6cee3b208447dba",
    "qr: the sign-in URL as a version 4 symbol, bit for bit the one checked against an independent encoder");
  const dsSettle = async () => { for (let k = 0; k < 6; k++) await tick(); };
  const dsFocus = Object.getPrototypeOf(main).focus;
  Object.getPrototypeOf(main).focus = function () { document.activeElement = this; };
  await go("#/maintainer/maity/inbox"); await go("#/account/sign-in-device"); await dsSettle();
  const dsCode = main.querySelector(".device-code");
  expect(dsCode && text(dsCode).includes("K7QM-4XPR-9D2F") && dsCode.querySelectorAll("svg").some((sv) => sv.attrs.class === "qr") && text(dsCode).includes("Expires in ") && btn(dsCode, "Cancel"),
    "device code: Sign in another device shows the code in three groups, its QR and the time left");
  // Any public URL fits a QR (up to 2331 bytes); past that the code and Cancel still stand.
  expect(win.Maity.qr.matrix("https://" + ["a".repeat(63), "b".repeat(63), "c".repeat(63)].join(".") + ".example.com/#/sign-in/code?c=K7QM4XPR9D2F").length === 61,
    "qr: a long public URL (three 63-character labels) still fits, as a version 11 symbol");
  const dsPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => (p === "/auth/device-codes"
    ? dsPost(p, b).then((r) => Object.assign({}, r, { url: "https://hub.example.org/" + "x".repeat(2400) })) : dsPost(p, b));
  await go("#/maintainer/maity/inbox"); await go("#/account/sign-in-device"); await dsSettle();
  const dsLong = main.querySelector(".device-code");
  expect(dsLong && text(dsLong).includes("K7QM-4XPR-9D2F") && btn(dsLong, "Cancel") && text(dsLong).includes("No QR code for this hub's address"),
    "device code: without a QR the code and Cancel are still shown");
  win.Maity.api.post = dsPost;
  await go("#/maintainer/maity/inbox"); await go("#/account/sign-in-device"); await dsSettle();
  await fireIntervals(); await dsSettle(); await fireIntervals(); await dsSettle();
  let dsDialog = main.querySelector(".device-approval");
  expect(dsDialog && text(dsDialog).includes("Approve this device?") && text(dsDialog).includes("203.0.113.24") && text(dsDialog).includes("Says it is Safari on iOS")
    && text(dsDialog).includes("First sign-in from this browser.") && text(dsDialog).includes("Only approve a device you are holding now.")
    && JSON.stringify(dsDialog.querySelectorAll(".match-choice").map((b) => text(b))) === JSON.stringify(["18", "47", "83"]) && !btn(dsDialog, "Approve"),
    "device code: the approval leads with what the hub saw, labels the claim, and offers three numbers and no plain Approve");
  expect(document.activeElement === btn(dsDialog, "Deny"), "device code: Deny is the default");
  btn(dsDialog, "18").click(); await dsSettle();
  expect(text(main.querySelector(".device-stage")).includes("That was not the number it shows, so the code is denied.") && btn(main.querySelector(".device-stage"), "New code"),
    "device code: a wrong number denies the code; a new one is offered");
  btn(main.querySelector(".device-stage"), "New code").click(); await dsSettle();
  await fireIntervals(); await dsSettle(); await fireIntervals(); await dsSettle();
  btn(main.querySelector(".device-approval"), "47").click(); await dsSettle();
  expect(text(main.querySelector(".device-stage")).includes("Approved: the other device is signing in."), "device code: the right number approves it");
  // The new device: the QR's URL fills the code in, a tap sends it, the number shows, and after the approval the account.
  const dsMade = await win.Maity.api.post("/auth/device-codes", {});
  profileButton().click(); await tick();
  header.querySelectorAll("button.menu-item").find((b) => b.textContent === "Sign out").click(); await dsSettle();
  win.location.hash = "#/sign-in/code?c=k7qm4xpr9d2f"; win.onhashchange(); await dsSettle();
  expect(byId("device-code") && byId("device-code").value === "K7QM-4XPR-9D2F" && byId("login-handle"), "device code: the QR's URL opens the login with the code filled in, not sent");
  // Over https (§16.11) the code is in the fragment, /sign-in/code#c=…: read once, then gone from the address.
  const dsRoute = win.Maity.route;
  let dsFragment = "c=k7qm4xpr9d2f";
  win.Maity.route = Object.assign({}, dsRoute, { fixture: false,
    current: () => ({ path: "/sign-in/code", query: new URLSearchParams(""), fragment: dsFragment }),
    dropFragment: () => { dsFragment = ""; } });
  const dsHttps = win.Maity.deviceSignIn.loginOptions(() => {}, () => {}); await dsSettle();
  const dsAgain = win.Maity.deviceSignIn.loginOptions(() => {}, () => {}); await dsSettle();
  win.Maity.route = dsRoute;
  const dsField = (box) => box.querySelectorAll("input").find((i) => i.id === "device-code");
  expect(dsField(dsHttps) && dsField(dsHttps).value === "K7QM-4XPR-9D2F" && dsFragment === ""
    && text(dsAgain).includes("Have a code?") && !(dsField(dsAgain) && dsField(dsAgain).value),
    "device code: over https the code comes from the fragment and fills the field, the fragment is gone after; a second drawing finds none and folds the entry");
  main.querySelector(".sign-in-code form").dispatch("submit"); await dsSettle();
  const dsWait = main.querySelector(".device-waiting");
  expect(dsWait && text(dsWait).includes("Waiting for approval on your other device") && text(dsWait.querySelector(".match-number")) === "47" && !text(dsWait).includes("Maintainer"),
    "device code: the new device shows the number to pick and nothing of the account");
  // Simulate the signed-in approving device in this single-session fixture.
  await win.Maity.api.post("/auth/login", { handle: "maintainer", password: "a long new password" });
  await win.Maity.api.get("/auth/session");
  await win.Maity.api.post("/auth/device-codes/" + dsMade.id + "/approve", { number: 47 });
  await win.Maity.api.post("/auth/logout");
  await fireIntervals(); await dsSettle(); await dsSettle();
  expect(!byId("login-handle") && !main.querySelector(".error") && win.location.hash !== "#/sign-in/code?c=k7qm4xpr", "device code: approved, the new device is signed in and leaves the code's URL");
  // A link by mail, and its six-digit code.
  profileButton().click(); await tick();
  header.querySelectorAll("button.menu-item").find((b) => b.textContent === "Sign out").click(); await dsSettle();
  btn(main.querySelector(".sign-in-mail"), "Email me a sign-in link").click(); await tick();
  byId("sign-in-address").value = "maintainer@example.org";
  main.querySelector(".sign-in-mail form").dispatch("submit"); await dsSettle();
  expect(text(main.querySelector(".sign-in-mail")).includes("If this address belongs to an account, a link is on its way.") && byId("sign-in-mail-code"),
    "sign-in link: the same answer for any address, with a field for the code");
  byId("sign-in-mail-code").value = "000 000";
  main.querySelector(".sign-in-mail form").dispatch("submit"); await dsSettle();
  expect(text(main.querySelector(".sign-in-mail")).includes("that code does not match") && byId("login-handle"), "sign-in link: a wrong code is said and signs nobody in");
  byId("sign-in-mail-code").value = "482 913";
  main.querySelector(".sign-in-mail form").dispatch("submit"); await dsSettle();
  expect(!byId("login-handle") && !main.querySelector(".error"), "sign-in link: the code signs this browser in");
  // A hub whose machine form has no /auth/methods is not asked: the password alone.
  profileButton().click(); await tick();
  header.querySelectorAll("button.menu-item").find((b) => b.textContent === "Sign out").click(); await dsSettle();
  const dsGet = win.Maity.api.get;
  const dsAsked = [];
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => { dsAsked.push(p); return p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : dsGet(p); };
  await go("#/"); await dsSettle();
  expect(byId("login-handle") && !dsAsked.includes("/auth/methods") && !main.querySelector(".sign-in-code") && !main.querySelector(".sign-in-mail"),
    "sign-in: a hub without the methods is not asked for them and offers the password alone");
  // Listed, but the call fails (404, 5xx): the same, and no error on the page.
  for (const status of [404, 503]) {
    win.Maity.api.forgetRoutes();
    win.Maity.api.get = (p) => (p === "/auth/methods" ? Promise.reject(new win.Maity.api.ApiError("x", status, p, status === 404 ? "not_found" : "unavailable", {})) : dsGet(p));
    await go("#/maintainer/maity/inbox"); await go("#/"); await dsSettle();
    expect(byId("login-handle") && !main.querySelector(".sign-in-code") && !main.querySelector(".sign-in-mail") && !main.querySelector(".error") && !main.querySelector(".send-status.failed"),
      "sign-in: a methods call that answers " + status + " leaves the password form alone, with no error");
  }
  win.Maity.api.get = dsGet; win.Maity.api.forgetRoutes();
  byId("login-handle").value = "maintainer"; byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); await dsSettle();
  expect(!byId("login-handle"), "sign-in: and the password signs in as before");
  Object.getPrototypeOf(main).focus = dsFocus; document.activeElement = undefined;

  // No memberships: the empty state, then creating a project.
  let noProjects = true;
  win.Maity.api.get = (p) => {
    gets.push(p);
    return p === "/me" && noProjects
      ? realGet(p).then((m) => Object.assign({}, m, { projects: [] }))
      : realGet(p);
  };
  await go("");
  expect(win.location.hash === "#/all", "no project: the empty hash lands on #/all");
  await tick();
  expect(text(main).includes("No projects yet") && !main.querySelector(".error"), "no project: empty state, no error");
  // A personal request reaches its human without a membership (§7): it comes first, the empty state after it.
  expect(main.querySelectorAll(".project-label.personal").length === 2
    && text(main).indexOf("proposes a change to its soul") < text(main).indexOf("No projects yet"),
    "no project: a personal request is still shown, before the empty state");
  // A truly empty account: the empty state alone.
  const npGetAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/requests" ? Promise.resolve({ items: [], next_cursor: null }) : npGetAll(p));
  await go("#/new"); await go("#/all"); await tick();
  expect(text(main).includes("No projects yet") && !main.querySelector("li.entry") && !text(main).includes("Nothing waits for you")
    && !text(main).includes("Waiting for you") && win.Maity.notify.state.available !== false,
    "no project and nothing personal: only the empty state");
  win.Maity.api.getAll = npGetAll;
  const createLink = main.querySelectorAll("a").find((a) => a.textContent === "Create a project");
  expect(createLink && createLink.getAttribute("href") === "#/new", "empty state offers Create a project");
  expect(chip("+ New project") && chip("+ New project").getAttribute("href") === "#/new", "switcher links to #/new");
  await go("#/new"); await tick();
  const fieldError0 = (id) => text(byId(id + "-error"));
  expect(plainTitle() === "New project · Maity" && byId("project-slug"), "create-project view");
  expect(byId("project-slug").attrs.pattern && !badPatterns().length, "create: every pattern compiles with the v flag " + badPatterns());
  // §6.26: the owner, the human or an organisation they may create projects in (acme, made under Organisations above).
  expect(byId("project-owner") && byId("project-owner").value === "" && byId("project-owner").querySelectorAll("option").map((o) => o.getAttribute("value") + "=" + text(o)).join()
    === "=@maintainer (you),crew=@crew · Crew,acme=@acme · Acme", "create: the owner is the human, or an organisation of theirs");
  const owPost = win.Maity.api.post, owBodies = [];
  win.Maity.api.post = (p, b) => {
    if (p !== "/projects") return owPost(p, b);
    owBodies.push(b);
    return Promise.reject(owBodies.length === 1 ? new win.Maity.api.ApiError("x", 403, p, "forbidden", { reason: "org_role" })
      : new win.Maity.api.ApiError("x", 400, p, "invalid", { fields: { owner: "unknown" } }));
  };
  byId("project-owner").value = "acme"; byId("project-name").value = "Shop"; byId("project-slug").value = "shop";
  main.querySelector("form").dispatch("submit"); for (let k = 0; k < 3; k++) await tick();
  expect(owBodies[0] && owBodies[0].owner === "acme" && text(main).includes("Not created: this organisation lets only its owners and admins create projects"),
    "create: the chosen organisation goes as owner; its role refusal in words");
  main.querySelector("form").dispatch("submit"); for (let k = 0; k < 3; k++) await tick();
  expect(fieldError0("project-owner") === "Not an organisation you are in." && byId("project-owner").getAttribute("aria-invalid") === "true",
    "create: an owner the hub does not know is said at the field");
  win.Maity.api.post = owPost;
  // A suspended organisation takes no new project: not offered (§6.26).
  const owGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/orgs" ? owGet(p).then((r) => ({ items: r.items.map((o) => Object.assign({}, o, { moderation: { action: "suspend", report_id: "rpt-1", at: "2026-10-29T10:00:00Z" } })) })) : owGet(p));
  await go("#/all"); await go("#/new"); await tick(); await tick();
  expect(!byId("project-owner") || !byId("project-owner").querySelectorAll("option").some((o) => o.getAttribute("value") === "acme"),
    "create: a suspended organisation is not offered as owner");
  win.Maity.api.get = owGet;
  await go("#/new");
  byId("project-name").value = "Dogfood Hub"; byId("project-name").dispatch("input");
  expect(byId("project-slug").value === "dogfood-hub", "slug proposed from the name");
  const posts = [];
  const realPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { posts.push([p, b]); return realPost(p, b); };
  const fieldError = fieldError0;
  byId("project-slug").value = "-Bad"; byId("project-slug").dispatch("input");
  main.querySelector("form").dispatch("submit"); await tick();
  expect(text(main).includes("Lowercase letters, digits and -, 2–63 characters, starting with a letter or digit. Used in links") && byId("project-slug").getAttribute("aria-describedby") === "project-slug-hint project-slug-error",
    "create: the slug's rule is said up front, tied to its field");
  expect(!posts.length && fieldError("project-slug") === "Lowercase letters, digits and -, 2–63 characters, starting with a letter or digit." && byId("project-slug").getAttribute("aria-invalid") === "true",
    "a malformed slug is refused next to the field, nothing sent");
  byId("project-slug").value = "maity";
  byId("project-repository").value = "https://gitlab.example/a/b";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(fieldError("project-slug").includes("already") && fieldError("project-repository").includes("forge"),
    "the hub's invalid fields shown next to slug and repository");
  byId("project-slug").value = "dogfood"; byId("project-repository").value = "https://github.com/example/dogfood";
  // Project memory (§6.1, §6.21): Keep the Why preselected, its three setup options ticked beneath it.
  const setupRow = (key) => byId("setup-" + key).parentNode;
  const setupKeys = ["keep_the_why_init", "keep_the_why_badge", "maity_badge"];
  expect(byId("project-memory").value === "keep-the-why" && byId("project-memory").querySelectorAll("option").map((o) => text(o)).join() === "Keep the Why,None"
    && setupKeys.every((k) => byId("setup-" + k).checked && !setupRow(k).hidden)
    && setupKeys.map((k) => text(setupRow(k)).trim()).join("|") === "Set up Keep the Why in the repository|Add the Keep the Why badge to the README|Add the Maity badge to the README"
    && text(main).includes("an agent sets it up in the repository, through the setup cards below"),
    "create: Project memory with Keep the Why preselected, the three setup options ticked, the setup's agent said");
  const cpNote = byId("setup-maity_badge-note");
  expect(cpNote && byId("setup-maity_badge").getAttribute("aria-describedby") === "setup-maity_badge-note" && text(cpNote).includes("how many humans and agents")
    && cpNote.parentNode === setupRow("maity_badge").parentNode && !text(byId("project-setup-hint")).includes("badge")
    && main.querySelectorAll("button").find((b) => b.textContent === "Create project").classList.contains("primary"),
    "create: the Maity badge's consequence right under its checkbox; Create project is primary");
  // The policy select names the presets; what one means is the hint under it, following the choice.
  expect(byId("project-preset").querySelectorAll("option").map((o) => text(o)).join() === "Hierarchical,Solo"
    && text(byId("project-preset-hint")).startsWith("Reviewers move cards to done"),
    "create: the policy options are the presets' names, the hint says what the chosen one means");
  byId("project-preset").value = "solo"; byId("project-preset").dispatch("change");
  expect(text(byId("project-preset-hint")).startsWith("The holder moves its own card"), "create: the hint follows the chosen preset");
  byId("project-preset").value = "hierarchical"; byId("project-preset").dispatch("change");
  // The hub's refusal of an option is said at the options.
  const spPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => (p === "/projects" ? Promise.reject(new win.Maity.api.ApiError("does not validate", 400, p, "invalid", { fields: { "setup.maity_badge": "not_a_boolean" } })) : spPost(p, b));
  byId("project-slug").value = "dogfood"; byId("project-repository").value = "https://github.com/example/dogfood";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(text(byId("project-setup-error")) === "Add the Maity badge to the README: Must be ticked or not.", "create: the hub's refusal of a setup option is said at the options");
  win.Maity.api.post = spPost;
  byId("project-preset").value = "solo";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  const sent = posts[posts.length - 1];
  expect(sent[0] === "/projects" && JSON.stringify(sent[1]) === JSON.stringify({
    slug: "dogfood", name: "Dogfood Hub", repository: { url: "https://github.com/example/dogfood" },
    memory: { provider: "keep-the-why" }, setup: { keep_the_why_init: true, keep_the_why_badge: true, maity_badge: true }, policy: { preset: "solo" },
  }) && !("keep_the_why" in sent[1]), "POST /projects with memory and every setup option sent explicitly " + JSON.stringify(sent[1]));
  expect(!fieldError("project-slug") && !byId("project-slug").getAttribute("aria-invalid"), "errors cleared on resubmit");
  noProjects = false;
  win.onhashchange(); await tick(); await tick();
  expect(win.location.hash === "#/maintainer/dogfood/agents" && text(header).includes("Dogfood Hub") && text(header).includes("Build"),
    "on 201 the page switches into the new project's Agents, where agents are added");
  for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("None of your agents is in this project yet") && main.querySelector(".join-panel") && !main.querySelector(".join-panel").hidden && byId("join-agent"),
    "the new project opens Join an agent at once");
  expect(chip("Dogfood Hub") && chip("Dogfood Hub").getAttribute("aria-current") === "page", "the new project is in the switcher");
  // With a repository the hub makes the setup cards at once; the Maity badge is on from the start.
  await go("#/maintainer/dogfood/board"); for (let k = 0; k < 4; k++) await tick();
  const setupCards = main.querySelectorAll("article.card.card-setup");
  expect(setupCards.map((c) => c.attrs["aria-label"]).sort().join("|") === "Add the Keep the Why badge to the README|Add the Maity badge to the README|Set up Keep the Why in the repository"
    && setupCards.every((c) => text(c).includes("Setup") && text(c).includes("Unclaimed")),
    "create: the three setup cards on the new project's board, open, marked Setup");
  await projectSettings();
  const memPanel = main.querySelector("section.memory-panel");
  expect(memPanel && text(memPanel).includes("Keep the Why: joining agents load the Keep the Why skill") && memPanel.querySelectorAll("a.id-ref").length === 3
    && memPanel.querySelectorAll("a.id-ref").every((a) => /^#\/maintainer\/dogfood\/tasks\/tsk-/.test(a.getAttribute("href"))) && !memPanel.querySelector("select, input"),
    "settings: the memory provider read only, with links to its setup cards");
  expect(byId("badge-select").value === "members" && text(main.querySelector("form.badge-form .paste-line")).endsWith("/badge/maintainer/dogfood.svg)](" + (win.location.origin && win.location.origin !== "null" ? win.location.origin : "https://<hub>") + "/maintainer/dogfood/overview)")
    && text(main.querySelector("form.badge-form .paste-line")).startsWith("[![maity]("),
    "settings: the badge is on (members) after the Maity badge was chosen, its README snippet shown");
  const bgPatches = [];
  const bgPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { bgPatches.push([p, b]); return bgPatch(p, b); };
  expect(!byId("badge-reason"), "settings: the badge form asks for no reason (§6.20)");
  byId("badge-select").value = "agents_online";
  main.querySelector("form.badge-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(bgPatches.length === 1 && JSON.stringify(bgPatches[0][1]) === JSON.stringify({ policy: { badge: "agents_online" } }),
    "settings: the badge changed as a policy change without a reason");
  expect(onSettings() && main.querySelector("form.badge-form") && byId("badge-select").value === "agents_online",
    "settings: after the save the page stays on Settings and shows the new badge (the maintainer's report)");
  win.Maity.api.patch = bgPatch;
  if (main.querySelector("section.memory-panel")) await projectSettings();
  // None: only the Maity badge is offered; without a repository the cards wait for one.
  await go("#/new");
  byId("project-name").value = "Plain"; byId("project-name").dispatch("input");
  byId("project-memory").value = "none"; byId("project-memory").dispatch("change");
  expect(setupRow("keep_the_why_init").hidden && setupRow("keep_the_why_badge").hidden && !setupRow("maity_badge").hidden,
    "create: under None only the Maity badge is offered");
  byId("setup-maity_badge").checked = false; byId("project-preset").value = "hierarchical";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(posts[posts.length - 1][1]) === JSON.stringify({ slug: "plain", name: "Plain", memory: { provider: "none" },
    setup: { keep_the_why_init: false, keep_the_why_badge: false, maity_badge: false }, policy: { preset: "hierarchical" } }),
    "create: None sends the Keep the Why options false and the unticked Maity badge false " + JSON.stringify(posts[posts.length - 1]));
  win.onhashchange(); for (let k = 0; k < 4; k++) await tick();
  await projectSettings();
  expect(text(main.querySelector("section.memory-panel")).includes("None: the project works without a memory provider.")
    && text(main.querySelector("section.memory-panel")).includes("No setup option was chosen.") && byId("badge-select").value === "off"
    && text(main.querySelector("form.badge-form")).includes("While the badge is off, its address answers not found."),
    "settings: None, nothing chosen, the badge off");
  await projectSettings();
  // Keep the Why without a repository: the options are kept, the cards wait for the repository.
  await go("#/new");
  byId("project-name").value = "Later"; byId("project-name").dispatch("input");
  byId("setup-keep_the_why_badge").checked = false; byId("project-preset").value = "hierarchical";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  win.onhashchange(); for (let k = 0; k < 4; k++) await tick();
  await projectSettings();
  expect(text(main.querySelector("section.memory-panel")).includes("Chosen: Set up Keep the Why in the repository; Add the Maity badge to the README.")
    && text(main.querySelector("section.memory-panel")).includes("The cards are made when the project gets a repository."),
    "settings: options chosen without a repository wait for it");
  await projectSettings();
  // The boolean keep_the_why alias of memory.provider is gone from the hub (#606): the mock refuses it too.
  const akGet = win.Maity.api.get;
  const akRefused = await win.Maity.api.post("/projects", { slug: "alias-hub", name: "Alias Hub", keep_the_why: true }).catch((err) => err);
  const akPatched = await win.Maity.api.patch("/projects/maintainer/maity", { keep_the_why: false }).catch((err) => err);
  const akView = await win.Maity.api.get("/projects/maintainer/maity");
  expect(akRefused.code === "invalid" && akRefused.details.fields.keep_the_why === "extra_forbidden"
    && akPatched.code === "invalid" && akPatched.details.fields.keep_the_why === "extra_forbidden" && !("keep_the_why" in akView),
    "create: the mock refuses the old keep_the_why alias in POST and PATCH, and the project view has none");
  // A machine form that cannot be read: no choice offered, and the form says the hub's defaults apply.
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.reject(new win.Maity.api.ApiError("bad gateway", 502, p, "unavailable")) : akGet(p));
  win.Maity.api.forgetRoutes();
  await go("#/new"); await tick();
  expect(!byId("project-memory") && text(main).includes("Project memory: this hub's machine form could not be read, so its defaults apply."),
    "create: an unreadable machine form is said, not silent");
  win.Maity.api.get = akGet; win.Maity.api.forgetRoutes();
  // A hub whose machine form does not name memory and setup refuses them: they are not offered nor sent.
  const omGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ paths: { "/api/v1/projects": { post: {} } } }) : omGet(p));
  win.Maity.api.forgetRoutes();
  await go("#/new"); await tick();
  byId("project-name").value = "Old Hub"; byId("project-name").dispatch("input"); byId("project-preset").value = "hierarchical";
  expect(!byId("project-memory") && !main.querySelector("fieldset.project-setup"), "create: a hub without memory and setup offers neither");
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(posts[posts.length - 1][1]) === JSON.stringify({ slug: "old-hub", name: "Old Hub", policy: { preset: "hierarchical" } }),
    "create: and sends neither");
  win.Maity.api.get = omGet; win.Maity.api.forgetRoutes();
  win.onhashchange(); for (let k = 0; k < 4; k++) await tick();
  // The settings view of a project with None, its setup processed with nothing chosen, and its badge on.
  await go("#/maintainer/sample/inbox"); await projectSettings();
  expect(text(main.querySelector("section.memory-panel")).includes("None") && text(main.querySelector("section.memory-panel")).includes("No setup option was chosen.")
    && byId("badge-select").value === "members" && !main.querySelector("img.badge-preview")
    && text(main.querySelector("form.badge-form .paste-line")).includes("/badge/maintainer/sample.svg"),
    "settings: a project with None and its badge on; no preview without a hub to serve it");
  await projectSettings();
  // A first-time human: the empty board and inbox say where their content comes from.
  await go("#/maintainer/plain/board");
  expect(text(main).includes("Every open card, and the done and cancelled ones of the last 14 days.")
    && main.querySelector(".first-hint") && text(main).includes("No cards yet. Your agents put the work here"), "empty board: subtitle and first hint");
  await go("#/maintainer/plain/inbox");
  expect(text(main).includes("No open requests.") && text(main).includes("Your agents ask here when they need you"), "empty inbox: first hint");
  win.Maity.api.get = (p) => { gets.push(p); return realGet(p); };
  win.Maity.api.post = realPost;

  // Group chats (docs/api.md §9.2): in the list, open, write, manage, remove, read along.
  await go("#/maintainer/maity/chat");
  const gcConv = () => main.querySelectorAll(".chat-list a.conv").find((a) => a.getAttribute("href") === "#/maintainer/maity/chat/cnv-0007");
  expect(gcConv() && text(gcConv()).includes("Release 0.2 go/no-go") && gcConv().querySelector(".count").textContent === "1"
    && gcConv().querySelector(".mention-count") && text(gcConv()).includes("Agent A, Agent B"),
    "group chat: listed with its title, its unread, that it mentions you, and who is in it");
  // Both counters share one cell, side by side, and the @ is drawn light on its badge (not accent on accent).
  const gcCounts = gcConv().querySelector(".conv-counts");
  const gcCss = fs.readFileSync(path.join(WEB, "css/app.css"), "utf8");
  expect(gcCounts && gcCounts.querySelectorAll(".count").some((c) => !c.classList.contains("mention-count")) && gcCounts.querySelector(".mention-count")
    && gcCss.indexOf(".conv .mention-count { color: var(--accent-text); }") > gcCss.indexOf(".conv .count { color: var(--accent); }")
    && !/\.conv \.count \{[^}]*grid-area/.test(gcCss),
    "chat list: the unread count and the @ sit together in one cell, the @ readable on its badge");
  expect(main.querySelector(".chat-list-pane a.new-group") && main.querySelector(".chat-list-pane a.new-group").getAttribute("href") === "#/maintainer/maity/chat/new",
    "group chat: New group chat beside the list");
  const gcWrites = [];
  const gcPost = win.Maity.api.post, gcPatch = win.Maity.api.patch, gcDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { gcWrites.push(["POST", p, b]); return gcPost(p, b); };
  win.Maity.api.patch = (p, b) => { gcWrites.push(["PATCH", p, b]); return gcPatch(p, b); };
  win.Maity.api.del = (p) => { gcWrites.push(["DELETE", p]); return gcDel(p); };
  // It opens at the first unread message, as a direct chat does.
  const gfReal = win.Maity.chatParts.follower;
  const gfOpened = [];
  win.Maity.chatParts.follower = (m, onEnd) => {
    const f = gfReal(m, onEnd);
    const o = f.open;
    f.open = (marker) => { gfOpened.push(marker); o(marker); };
    return f;
  };
  await go("#/maintainer/maity/chat/cnv-0007");
  win.Maity.chatParts.follower = gfReal;
  expect(gfOpened.length === 1 && gfOpened[0] && gfOpened[0].className === "new-line", "group chat: it opens at the first unread message");
  // Newest puts the focus in the composer, not on the page.
  const gfProto = Object.getPrototypeOf(main);
  const gfFocus = gfProto.focus;
  gfProto.focus = function () { document.activeElement = this; };
  main.querySelector(".group-chat .jump-latest").click(); await tick();
  expect(document.activeElement === byId("chat-text"), "group chat: Newest leaves the focus in the composer");
  gfProto.focus = gfFocus; document.activeElement = undefined;
  expect(main.querySelector(".group-chat ol.messages") && main.querySelector(".group-chat .jump-latest") && main.querySelector(".group-chat .jump-latest").hidden,
    "group chat: it has the same Newest pill, hidden at the end");
  const gcList = () => main.querySelector(".group-chat ol.messages");
  expect(main.querySelector(".group-chat") && text(main.querySelector(".group-chat .group-title")) === "Release 0.2 go/no-go"
    && text(main.querySelector(".group-people-line")) === "In it: Maintainer, Agent A (agent), Agent B (agent)" && !main.querySelector(".group-observers")
    && gcList().querySelectorAll("li.msg").length === 3, "group chat: opens with its title, its people and its messages");
  const gcNew = gcList().childNodes.findIndex((li) => li.className === "new-line");
  expect(gcNew > 0 && gcList().childNodes[gcNew + 1].attrs["data-seq"] === "5020" && !main.querySelector(".earlier button"),
    "group chat: the unread line before the first unread; no earlier part for someone there from the start");
  expect(text(gcList().querySelectorAll("li.msg")[1]).includes("Agent A") && !text(main).includes("not picked up yet"), "group chat: senders named, no delivery line (several recipients)");
  // Writing, with mentions that reach only someone in the chat.
  byId("chat-text").value = "@agent-c look"; byId("chat-text").dispatch("input");
  expect(!main.querySelector(".group-chat .mention-hint").hidden && text(main.querySelector(".group-chat .mention-hint")) === "@agent-c is not in this chat: it reaches nobody.",
    "group chat: a mention of someone not in it is said to reach nobody");
  byId("chat-text").value = "@agent-a go ahead"; byId("chat-text").dispatch("input");
  expect(main.querySelector(".group-chat .mention-hint").hidden, "group chat: a mention of a participant gives no hint");
  main.querySelector(".group-chat form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gcWrites[0]) === JSON.stringify(["POST", "/projects/maintainer/maity/conversations/cnv-0007/messages", { body: "@agent-a go ahead" }])
    && gcList().querySelectorAll("li.msg").length === 4 && byId("chat-text").value === "", "group chat: a message is sent and shown");
  // Removing a message for everyone (§8.5).
  const gcPrompt = win.prompt;
  win.prompt = () => "pasted a token";
  btn(gcList().querySelectorAll("li.msg")[0], "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gcWrites[1]) === JSON.stringify(["POST", "/projects/maintainer/maity/events/5010/redact", { reason: "pasted a token" }])
    && text(gcList().querySelectorAll("li.msg")[0]).includes("This message was removed by Maintainer: pasted a token.")
    && !btn(gcList().querySelectorAll("li.msg")[0], "Remove"), "group chat: a human in it removes a message, its tombstone says by whom and why");
  const gcHub = (await win.Maity.api.get("/projects/maintainer/maity/conversations/cnv-0007/messages?before=5011&limit=5")).items[0];
  const gcKept = (await win.Maity.api.get("/projects/maintainer/maity/conversations/cnv-0007/messages?before=5016&limit=5")).items.find((m) => m.seq === 5015);
  expect(gcHub.body === null && gcHub.redacted === true && gcHub.redaction.by === "hum-maintainer" && gcHub.redaction.reason === "pasted a token" && gcHub.redaction.at
    && gcKept.redacted === false && gcKept.redaction === null, "group chat: the mock gives redacted and redaction on every message item (§9, #206)");
  win.prompt = () => null;
  btn(gcList().querySelectorAll("li.msg")[1], "Remove").click(); await tick();
  expect(gcWrites.length === 2, "group chat: a cancelled removal sends nothing");
  const gcAsks = [];
  win.prompt = (q) => { gcAsks.push(q); return gcAsks.length === 1 ? "   " : null; };
  btn(gcList().querySelectorAll("li.msg")[1], "Remove").click(); await tick();
  expect(gcAsks.length === 2 && gcAsks[1].startsWith("A reason is needed") && gcWrites.length === 2, "group chat: an empty reason is asked again, never sent (§8.5 needs one)");
  let gcNoReason = null;
  try { await gcPost("/projects/maintainer/maity/events/5015/redact", {}); } catch (err) { gcNoReason = err; }
  expect(gcNoReason && gcNoReason.code === "invalid", "group chat: the mock refuses a removal without a reason");
  win.prompt = gcPrompt;
  const gcComposer = byId("chat-text");
  // Managing: rename, add (the latecomer's history said), remove.
  byId("group-rename").value = "Release 0.2"; header.querySelector && main.querySelector(".group-manage form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(gcWrites[2]) === JSON.stringify(["PATCH", "/projects/maintainer/maity/conversations/cnv-0007", { title: "Release 0.2" }])
    && text(main.querySelector(".group-chat .group-title")) === "Release 0.2", "group chat: the creator renames it");
  expect(byId("chat-text") === gcComposer && main.querySelectorAll(".group-chat .send-status").some((el) => text(el).includes("Renamed.")),
    "group chat: a rename is drawn in place, the composer kept and the result said");
  expect(text(main.querySelector(".group-manage")).includes("can read what came before with Show earlier messages"), "group chat: adding says what a latecomer reads");
  byId("group-rename").value = "Release 0.2, half typed"; byId("group-rename").dispatch("input");
  byId("group-add").value = "agt-c";
  main.querySelectorAll(".group-manage form")[1].dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(byId("group-rename").value === "Release 0.2, half typed", "group chat: a title being typed survives a change of the chat drawn in place");
  byId("chat-text").value = "@agent-c welcome"; byId("chat-text").dispatch("input");
  expect(main.querySelector(".group-chat .mention-hint").hidden, "group chat: someone just added is reachable by mention at once");
  byId("chat-text").value = ""; byId("chat-text").dispatch("input");
  expect(JSON.stringify(gcWrites[3]) === JSON.stringify(["POST", "/projects/maintainer/maity/conversations/cnv-0007/participants", { member_id: "agt-c" }])
    && text(main.querySelector(".group-people-line")).includes("Agent C (agent)"), "group chat: a participant added");
  const gcConfirm = win.confirm;
  win.confirm = () => true;
  btn(main.querySelectorAll(".group-members li").find((li) => text(li).startsWith("Agent C")), "Remove").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(gcWrites[4]) === JSON.stringify(["DELETE", "/projects/maintainer/maity/conversations/cnv-0007/participants/agt-c"])
    && !text(main.querySelector(".group-people-line")).includes("Agent C"), "group chat: a participant removed");
  expect(main.querySelectorAll(".group-members button").every((b) => /^Remove .+ from the chat$/.test(b.getAttribute("aria-label") || "")),
    "group chat: each participant's Remove names whom it removes");
  // Someone else's removal and someone else's rename reach the open chat in place.
  const gcEvGet = win.Maity.api.get;
  let gcFeed = [];
  let gcRenamed = false;
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) { const items = gcFeed; gcFeed = []; return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 9000, superseded: false }); }
    if (p === "/projects/maintainer/maity/conversations/cnv-0007" && gcRenamed) return gcEvGet(p).then((v) => Object.assign({}, v, { title: "Renamed by Ops" }));
    return gcEvGet(p);
  };
  const gcTyping = byId("chat-text");
  gcFeed = [{ seq: 9101, kind: "event_redacted", actor: { member_id: "hum-maintainer" }, payload: { seq: 5015, reason: "a key" } }];
  await fireIntervals(); await tick(); await tick();
  const gcMsg5015 = gcList().querySelectorAll("li.msg").find((li) => li.getAttribute("data-seq") === "5015");
  expect(text(gcMsg5015).includes("This message was removed by Maintainer: a key.") && !btn(gcMsg5015, "Quote"), "group chat: a removal by someone else takes the text out at once");
  gcRenamed = true;
  gcFeed = [{ seq: 9102, kind: "conversation_updated", subject: { type: "conversation", id: "cnv-0007" }, actor: { member_id: "hum-ops" }, payload: { id: "cnv-0007" } }];
  await fireIntervals(); await tick(); await tick();
  expect(text(main.querySelector(".group-chat .group-title")) === "Renamed by Ops" && byId("chat-text") === gcTyping,
    "group chat: someone else's rename is drawn in place, the composer untouched");
  // A direct chat takes a removal the same way.
  await go("#/maintainer/maity/chat/agt-a");
  gcFeed = [{ seq: 9103, kind: "event_redacted", actor: { member_id: "hum-maintainer" }, payload: { seq: 4202, reason: "pasted" } }];
  await fireIntervals(); await tick(); await tick();
  const gcDirect = main.querySelectorAll("li.msg").find((li) => li.getAttribute("data-seq") === "4202");
  expect(gcDirect && text(gcDirect).includes("This message was removed by Maintainer: pasted.") && !btn(gcDirect, "Quote"), "direct chat: a removal reaches the open chat too");
  win.Maity.api.get = gcEvGet;
  // A removed message as the hub gives it: body null, with or without redacted.
  let gcNullSeq = null;
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/conversations/cnv-0007/messages?")
    ? gcEvGet(p).then((r) => { if (gcNullSeq === null && r.items.length > 1) gcNullSeq = r.items[1].seq;
      return Object.assign({}, r, { items: r.items.map((m) => (m.seq === gcNullSeq ? Object.assign({}, m, { body: null }) : m)) }); }) : gcEvGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007");
  const gcNull = gcList().querySelectorAll("li.msg")[1];
  expect(text(gcNull).includes("This message was removed.") && !btn(gcNull, "Quote") && !btn(gcNull, "Remove"), "group chat: body null reads as removed, nothing to quote or remove");
  // A latecomer with nothing new: said, with the earlier part a button away.
  // Before one joined there is history (before= finds it), in the window nothing (after= reads none).
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/conversations/cnv-0007/messages?before=")
    ? Promise.resolve({ items: [{ id: "evt-5020", seq: 5020, conversation_id: "cnv-0007", from: "agt-a", to: "cnv-0007", body: "before you came", sent_at: "2026-10-21T10:00:00Z", mentions: [], attachments: [], redacted: false, redaction: null }], cursor: 0, earlier: null })
    : p.startsWith("/projects/maintainer/maity/conversations/cnv-0007/messages?after=") ? Promise.resolve({ items: [], cursor: 5021, earlier: null }) : gcEvGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007");
  expect(text(gcList()).includes("Nothing new since you joined.") && btn(main.querySelector(".earlier"), "Show earlier messages"), "group chat: a latecomer with nothing new is told the earlier part is there");
  win.Maity.api.get = gcEvGet;
  // The earlier part, on demand.
  const gcGet = win.Maity.api.get;
  win.Maity.api.get = (p) => {
    // The window begins after the chat's first message: that one lies before it.
    if (p.startsWith("/projects/maintainer/maity/conversations/cnv-0007/messages?after=")) return gcGet(p).then((r) => Object.assign({}, r, { items: r.items.slice(1) }));
    if (p.startsWith("/projects/maintainer/maity/conversations/cnv-0007/messages?before=") && !p.includes("before=" + Number.MAX_SAFE_INTEGER)) {
      return Promise.resolve({ items: [{ id: "evt-5001", seq: 5001, conversation_id: "cnv-0007", from: "agt-a", to: "cnv-0007", body: "before you came", sent_at: "2026-10-21T12:00:00Z", mentions: [] }], cursor: 0, earlier: null });
    }
    return gcGet(p);
  };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007");
  const gcBefore = gcList().querySelectorAll("li.msg").length;
  btn(main.querySelector(".earlier"), "Show earlier messages").click(); for (let k = 0; k < 4; k++) await tick();
  expect(gcList().querySelectorAll("li.msg").length === gcBefore + 1 && text(gcList().querySelectorAll("li.msg")[0]).includes("before you came")
    && !main.querySelector(".earlier button"), "group chat: the earlier part is read on demand and put before");
  // Reading along as an agent's owner: no writing, no managing, no removing; the observers named.
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/conversations/cnv-0007"
    ? gcGet(p).then((v) => Object.assign({}, v, { access: "observer", observers: ["hum-maintainer", "hum-outside"],
      participants: v.participants.filter((x) => x.member_id !== "hum-maintainer").concat([{ member_id: "hum-ops", kind: "human", handle: "ops", owner_id: null, joined_at: v.created_at }]) }))
    : gcGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007");
  expect(!byId("chat-text") && text(main).includes("You read along as the owner of an agent in this chat") && !main.querySelector(".group-manage")
    && !gcList().querySelectorAll("button").some((b) => b.textContent === "Remove" || b.textContent === "Quote")
    && text(main.querySelector(".group-observers")).includes("Also read by: you (owner of Agent A, Agent B), an owner outside the project"),
    "group chat: an owner reads along, writes and manages nothing, and is named as reading along");
  // A closed chat stays readable and takes nothing.
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/conversations/cnv-0007" ? gcGet(p).then((v) => Object.assign({}, v, { closed_at: "2026-10-22T10:00:00Z", closed_reason: "no_human" })) : gcGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007");
  expect(!byId("chat-text") && text(main).includes("This chat is closed") && !main.querySelector(".group-manage") && gcList().querySelectorAll("li.msg").length >= 4,
    "group chat: a closed chat is read only");
  win.Maity.api.get = gcGet;
  // Creating: at least one other, not one's own agent alone, then the chat opens.
  await go("#/maintainer/maity/chat/new");
  const gcBox = (id) => byId("group-member-" + id);
  main.querySelector("form.group-form").dispatch("submit"); await tick();
  expect(text(byId("group-people-error")) === "Choose at least one other participant." && gcWrites.length === 5, "group chat: none chosen, said, nothing sent");
  gcBox("agt-a").checked = true;
  main.querySelector("form.group-form").dispatch("submit"); await tick();
  expect(text(byId("group-people-error")).startsWith("That is your direct chat with Agent A") && byId("group-people-error").querySelector("a").getAttribute("href") === "#/maintainer/maity/chat/agt-a",
    "group chat: one's own agent alone is the direct chat, and it says so");
  gcBox("agt-b").checked = true; byId("group-title").value = "Hub and CLI";
  main.querySelector("form.group-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const gcMade = gcWrites[5];
  expect(gcMade[0] === "POST" && gcMade[1] === "/projects/maintainer/maity/conversations" && JSON.stringify(gcMade[2]) === JSON.stringify({ title: "Hub and CLI", participants: ["agt-a", "agt-b"] })
    && /^#\/maintainer\/maity\/chat\/cnv-/.test(win.location.hash), "group chat: created with its title and participants, and opened");
  await go(win.location.hash);
  expect(text(main.querySelector(".group-chat .group-title")) === "Hub and CLI" && text(main).includes("No messages yet."), "group chat: the new chat is empty and open");
  // Leaving as the last human closes it; it is gone from one's list.
  win.confirm = (q) => { gcWrites.push(["CONFIRM", q]); return true; };
  btn(main.querySelector(".group-manage"), "Leave the chat").click(); for (let k = 0; k < 6; k++) await tick();
  const gcLeft = gcWrites.filter((w) => w[0] === "DELETE").pop();
  expect(gcWrites.some((w) => w[0] === "CONFIRM" && w[1].includes("You are its last human: it closes")) && /\/participants\/hum-maintainer$/.test(gcLeft[1])
    && win.location.hash === "#/maintainer/maity/chat", "group chat: leaving as its last human says it closes, and goes back to the list");
  win.confirm = gcConfirm;
  win.Maity.api.post = gcPost; win.Maity.api.patch = gcPatch; win.Maity.api.del = gcDel;
  // The mock as the hub: its refusals (§9.2).
  const gcErr = async (call) => { try { await call(); return null; } catch (err) { return err; } };
  const tooMany = await gcErr(() => gcPost("/projects/maintainer/maity/conversations", { participants: Array.from({ length: 12 }, (_, i) => "agt-" + i) }));
  const direct = await gcErr(() => gcPost("/projects/maintainer/maity/conversations", { participants: ["agt-a"] }));
  const both = await gcErr(() => win.Maity.api.get("/projects/maintainer/maity/conversations/cnv-0007/messages?after=1&before=9"));
  expect(tooMany && tooMany.details.fields.participants === "not_a_member" && direct && direct.details.fields.participants === "use_direct"
    && both && both.code === "invalid", "group chat: the mock refuses a non-member, one's own agent alone, and after with before");
  // Removing a message in a direct chat: the human party, with a reason (§8.5).
  const gcPost2 = win.Maity.api.post;
  const gcRemoves = [];
  win.Maity.api.post = (p, b) => { if (p.includes("/redact")) gcRemoves.push([p, b]); return gcPost2(p, b); };
  await go("#/maintainer/maity/chat/agt-a");
  win.prompt = () => "wrong chat";
  const gcDirectMsg = main.querySelectorAll("li.msg")[0];
  btn(gcDirectMsg, "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(gcRemoves.length === 1 && /\/projects\/maintainer\/maity\/events\/\d+\/redact$/.test(gcRemoves[0][0]) && gcRemoves[0][1].reason === "wrong chat"
    && text(main.querySelectorAll("li.msg")[0]).includes("This message was removed by Maintainer: wrong chat.") && !btn(main.querySelectorAll("li.msg")[0], "Remove"),
    "direct chat: the human party removes a message with a reason");
  win.prompt = gcPrompt;
  // Blind removal (§8.5, #206): a closed group chat's message the admin was never in, by its number.
  await go("#/maintainer/maity/inbox"); await projectSettings();
  byId("remove-seq").value = "x1";
  main.querySelector("form.remove-reported").dispatch("submit"); await tick();
  expect(text(main).includes("Not removed: the message number is a whole number") && gcRemoves.length === 1, "blind removal: the number is checked before sending");
  let gcAsked = "";
  win.confirm = (q) => { gcAsked = q; return true; };
  byId("remove-seq").value = "5020"; byId("remove-reason").value = "typo";
  main.querySelector("form.remove-reported").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const gc5010 = (await win.Maity.api.get("/projects/maintainer/maity/conversations/cnv-0007/messages?before=5021&limit=1")).items[0];
  expect(gcRemoves[1][1].expect === "closed_chat_message" && text(main).includes("number 5020 is no message of a closed group chat in this project; nothing was removed")
    && gc5010.body !== null, "blind removal: always sends expect, so a number that is no closed chat's message removes nothing");
  byId("remove-seq").value = "4990"; byId("remove-reason").value = "reported by a reviewer";
  main.querySelector("form.remove-reported").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gcRemoves[2]) === JSON.stringify(["/projects/maintainer/maity/events/4990/redact", { reason: "reported by a reviewer", expect: "closed_chat_message" }])
    && text(main).includes("Message 4990 is removed.") && gcAsked.startsWith("Remove the closed group chat's message with number 4990"),
    "blind removal: an admin removes a closed chat's message it was never in, by its number, without reading it");
  win.confirm = gcConfirm;
  win.Maity.api.post = gcPost2;
  await projectSettings();
  // Without events:admin a direct chat offers no Remove (§8.5).
  const gcRole = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? gcRole(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "member"; return x; }) : gcRole(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-a");
  expect(main.querySelectorAll("li.msg").length && !main.querySelectorAll("li.msg button").some((b) => b.textContent === "Remove"), "direct chat: a member without events:admin gets no Remove");
  win.Maity.api.get = gcRole;
  // Reading along outside one's projects (§9.2): Spare is in guestlab, its owner is not.
  const gcOutGets = [];
  const gcOutGet = win.Maity.api.get, gcOutAll = win.Maity.api.getAll;
  win.Maity.api.get = (p) => { gcOutGets.push(p); return gcOutGet(p); };
  win.Maity.api.getAll = (p) => { gcOutGets.push(p); return gcOutAll(p); };
  await go("#/all");
  const gcNote = main.querySelector(".observe-note");
  expect(gcNote && gcNote.querySelector("a").getAttribute("href") === "#/observe/guest/guestlab" && text(gcNote).includes("through Spare"),
    "read along: everything waiting names the projects one's agents are in and one is not");
  await go("#/observe/guest/guestlab");
  expect(text(main).includes("Read along in guest/guestlab") && main.querySelectorAll(".chat-list a.conv").length === 1
    && main.querySelector(".chat-list a.conv").getAttribute("href") === "#/observe/guest/guestlab/cnv-0301" && !main.querySelector("a.new-group")
    && !gcOutGets.some((p) => p.startsWith("/projects/guest/guestlab/members") || p === "/projects/guest/guestlab" || p.startsWith("/projects/guest/guestlab/events")),
    "read along: the chats one's agent is in, nothing else of the project read");
  await go("#/observe/guest/guestlab/cnv-0301");
  expect(!byId("chat-text") && text(main).includes("You read along as the owner of an agent in this chat") && text(main.querySelector(".group-observers")).includes("you (owner of Spare)")
    && main.querySelector(".group-chat a.chat-back").getAttribute("href") === "#/observe/guest/guestlab" && main.querySelectorAll(".group-chat li.msg").length === 1
    && text(main.querySelector(".group-chat li.msg")).includes("@guest"), "read along: the chat read only, its people by handle");
  // From outside: other observers neutrally, someone who left as a former participant, the access ending said.
  win.Maity.api.get = (p) => {
    gcOutGets.push(p);
    if (p === "/projects/guest/guestlab/conversations/cnv-0301") return gcOutGet(p).then((v) => Object.assign({}, v, { observers: v.observers.concat(["hum-other"]) }));
    if (p.startsWith("/projects/guest/guestlab/conversations/cnv-0301/messages?")) {
      return gcOutGet(p).then((r) => Object.assign({}, r, { items: r.items.filter((m) => m.seq !== 7002).concat([{ id: "evt-7002", seq: 7002, conversation_id: "cnv-0301", from: "hum-gone", to: "cnv-0301", body: "bye", sent_at: "2026-10-22T09:05:00Z", mentions: [], redacted: false, redaction: null }]) }));
    }
    return gcOutGet(p);
  };
  await go("#/observe/guest/guestlab/cnv-0301");
  expect(text(main.querySelector(".group-observers")).includes("another agent's owner") && !text(main.querySelector(".group-observers")).includes("outside the project")
    && text(main.querySelectorAll(".group-chat li.msg")[1]).includes("someone not in the chat"), "read along: other observers and someone not in the chat named neutrally");
  // The 30-second re-read reads the newest page only, never the whole history (tsk-r1adgwp0a5dr), and draws again only on a change.
  const gcLong = (seq) => ({ id: "evt-" + seq, seq, conversation_id: "cnv-0301", from: "hum-guest", to: "cnv-0301", body: "m" + seq, sent_at: "2026-10-22T10:00:00Z", mentions: [], redacted: false, redaction: null });
  let gcLongN = 2000;
  const gcPages = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/projects/guest/guestlab/conversations/cnv-0301/messages?")) {
      gcPages.push(p);
      const all = Array.from({ length: gcLongN }, (_, i) => gcLong(8001 + i));
      const q = new URLSearchParams(p.split("?")[1]);
      const items = q.get("before") !== null ? all.filter((m) => m.seq < Number(q.get("before"))).slice(-Number(q.get("limit")))
        : all.filter((m) => m.seq > Number(q.get("after") || 0)).slice(0, Number(q.get("limit") || 200));
      return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 0, earlier: items.length ? items[0].seq : null });
    }
    return gcOutGet(p);
  };
  const gcLast = () => { const lis = main.querySelectorAll(".group-chat li.msg"); return lis[lis.length - 1].attrs["data-seq"]; };
  await fireIntervals(); await tick(); await tick(); await tick();
  const gcFirstLi = main.querySelector(".group-chat li.msg");
  expect(gcPages.length === 1 && gcPages[0] === "/projects/guest/guestlab/conversations/cnv-0301/messages?before=" + Number.MAX_SAFE_INTEGER + "&limit=50"
    && gcLast() === "10000" && main.querySelectorAll(".group-chat li.msg").length <= 60,
    "read along: the re-read of a 2000-message chat is one request for its newest 50 " + JSON.stringify(gcPages));
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(main.querySelector(".group-chat li.msg") === gcFirstLi && gcPages.length === 2, "read along: nothing new, nothing drawn again (the list is a live region)");
  gcLongN = 2001;
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(gcLast() === "10001", "read along: a new message shows");
  // More than a page between two re-reads (H on #452): what is shown is let go, the gap read on scroll-up in order.
  gcLongN = 2101;
  await fireIntervals(); await tick(); await tick(); await tick();
  const gcSeqs = () => main.querySelectorAll(".group-chat li.msg").map((li) => Number(li.attrs["data-seq"]));
  expect(gcSeqs().length === 50 && gcSeqs()[0] === 10052 && gcLast() === "10101" && btn(main.querySelector(".group-chat .earlier"), "Show earlier messages"),
    "read along: more than a page between re-reads drops what no longer meets it; the gap comes on scroll-up");
  btn(main.querySelector(".group-chat .earlier"), "Show earlier messages").click(); for (let k = 0; k < 4; k++) await tick();
  expect(gcSeqs().length === 100 && gcSeqs()[0] === 10002 && gcSeqs().every((x, i, a) => !i || x === a[i - 1] + 1), "read along: the gap is read back in order, nothing missing");
  // A long tail drawn and the reader at the newest: the re-read lets the oldest go, as an arrival does.
  for (let n = 0; n < 5; n++) { btn(main.querySelector(".group-chat .earlier"), "Show earlier messages").click(); for (let k = 0; k < 4; k++) await tick(); }
  const gcList2 = main.querySelector(".group-chat ol.messages");
  Object.assign(gcList2, { scrollHeight: 9000, clientHeight: 400, scrollTop: 8600 });
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(gcSeqs().length === 100 && gcLast() === "10101", "read along: at the newest, a long tail is let go on the re-read too " + gcSeqs().length);
  win.Maity.api.get = (p) => (p.startsWith("/projects/guest/guestlab/conversations/cnv-0301/messages") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : gcOutGet(p));
  await fireIntervals(); await tick(); await tick();
  expect(text(main).includes("You no longer read this chat: your agent left it, or left the project"), "read along: an access that ended is said on the next re-read");
  win.Maity.api.get = gcOutGet;
  await go("#/observe/someone/nowhere");
  expect(text(main).includes("None of your agents is in a project someone/nowhere"), "read along: a project none of one's agents is in is said");
  win.Maity.api.get = gcOutGet; win.Maity.api.getAll = gcOutAll;
  // Without a project of one's own the landing still names where one reads along.
  win.Maity.api.get = (p) => (p === "/me" ? gcOutGet(p).then((x) => Object.assign({}, x, { projects: [] })) : gcOutGet(p));
  await go("#/all");
  expect(main.querySelector(".observe-note") && main.querySelector(".observe-note a").getAttribute("href") === "#/observe/guest/guestlab", "read along: the empty landing names it too");
  win.Maity.api.get = gcOutGet;

  // A closed project: no new group chat.
  const gcMe = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? gcMe(p).then((x) => Object.assign({}, x, { state: "archived" })) : gcMe(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat");
  expect(!main.querySelector("a.new-group"), "group chat: a closed project offers no new group chat");
  await go("#/maintainer/maity/chat/new");
  expect(text(main).includes("The project is closed: it takes no new group chat.") && !main.querySelector("form.group-form"), "group chat: nor its form");
  win.Maity.api.get = gcMe;
  await go("#/maintainer/maity/inbox");

  // Per hub, from its machine form (GET /openapi.json): what it does not serve is not offered.
  const hgGet = win.Maity.api.get;
  const hgPaths = (paths) => {
    win.Maity.api.forgetRoutes();
    win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths }) : hgGet(p));
  };
  const hgSettle = async () => { for (let k = 0; k < 6; k++) await tick(); };
  hgPaths({ "/api/v1/projects/{owner}/{slug}/conversations": { get: {} } });
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat"); await hgSettle();
  expect(!main.querySelector("a.new-group") && text(main).includes("This hub has no group chats yet."),
    "hub without group chats: no New group chat, and that is said instead of an empty-looking list");
  await go("#/maintainer/maity/chat/new"); await hgSettle();
  expect(!main.querySelector("form.group-form") && text(main).includes("there is none to create"), "hub without group chats: nor the form");
  await go("#/maintainer/maity/inbox"); await projectSettings(); await hgSettle();
  expect(main.querySelector(".attach-admin") && !main.querySelector("form.remove-reported"), "hub without group chats: no removal of a closed group chat's message");
  await projectSettings();
  await go("#/all"); await hgSettle();
  expect(!main.querySelector(".observe-note"), "hub without group chats: nothing to read along in is named");
  await go("#/observe/guest/guestlab"); await hgSettle();
  expect(text(main).includes("there is nothing to read along in") && !main.querySelector(".chat-list"), "hub without group chats: the read-along view says so");
  await go("#/maintainer/maity/chat/agt-b"); await hgSettle();
  // The whole attachments part is hidden, so no file field is left without its label.
  const hgChooser = () => main.querySelector(".attach");
  expect(hgChooser() && hgChooser().hidden && byId("chat-files").disabled, "hub without attachments: no Attach files");
  expect(/\.attach\[hidden\] \{ display: none; \}/.test(fs.readFileSync(path.join(WEB, "css/app.css"), "utf8")),
    "hub without attachments: the part's own display does not beat its hidden attribute");
  // With both: offered (the route's parameter name and prefix do not matter).
  hgPaths({ "/projects/{owner}/{slug}/conversations": { get: {}, post: {} }, "/api/v1/projects/{who}/{project}/attachments": { post: {} } });
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat"); await hgSettle();
  expect(main.querySelector("a.new-group") && !text(main).includes("This hub has no group chats yet."), "hub with group chats: New group chat is offered");
  await go("#/maintainer/maity/inbox"); await projectSettings(); await hgSettle();
  expect(main.querySelector("form.remove-reported"), "hub with group chats: the removal of a closed group chat's message is offered");
  await projectSettings();
  await go("#/maintainer/maity/chat/agt-b"); await hgSettle();
  expect(hgChooser() && !hgChooser().hidden, "hub with attachments: Attach files is offered");
  // A machine form that cannot be read keeps the controls.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : hgGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat"); await hgSettle();
  expect(main.querySelector("a.new-group"), "an unreadable machine form keeps New group chat");
  win.Maity.api.get = hgGet;
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox");

  // A personal request without a project (§6.26: an organisation's invitation, a transfer into one) is listed without one.
  const oiGetAll = win.Maity.api.getAll;
  const oiReq = (id, title, org) => ({ id, class: "consent", title, summary: "", options: [], replies: [{ id: "go", label: "Go" }, { id: "no", label: "No" }],
    priority: "normal", to: "human:hum-maintainer", asked_by: { member_id: "hum-anna", display_name: "Anna" }, task_id: null, task: null,
    while_open: "wait", personal: true, status: "open", answer: null, project: null, org, created_at: "2026-10-29T10:00:00Z" });
  win.Maity.api.getAll = (p) => (p === "/requests" ? oiGetAll(p).then((r) => Object.assign({}, r, { items: r.items.concat([
    oiReq("req-oi01", "Join @oz-team as admin", undefined),
    Object.assign(oiReq("req-oi02", "Take over anna/shop into @guild as guild/shop", { id: "org-oz00guild001", handle: "guild" }), { project: { full_name: "anna/shop", name: "Anna's shop" } })]) })) : oiGetAll(p));
  await go("#/all"); await hgSettle();
  const oiLabels = main.querySelectorAll(".project-label.personal").map((el) => text(el));
  expect(text(main).includes("Join @oz-team as admin") && oiLabels.includes("Personal") && oiLabels.includes("Personal · Anna's shop") && !text(main).includes("undefined"),
    "personal request: one without a project reads as Personal, a transfer into an organisation names its project");
  const oiHead = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("into @guild"));
  if (oiHead.attrs["aria-expanded"] !== "true") { oiHead.click(); await tick(); }
  expect(text(main.querySelector(".current")).includes("ProjectAnna's shop — a personal request: for you as an owner of @guild")
    && text(main.querySelector(".current")).includes("Into@guild") && !text(main.querySelector(".current")).includes("not for a project")
    && oiHead.textContent.includes("Anna's shop, into @guild: "), "personal request: a transfer into an organisation shows the project and where it goes");
  const oiInvite = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("Join @oz-team"));
  if (oiInvite.attrs["aria-expanded"] !== "true") { oiInvite.click(); await tick(); }
  expect(!text(main.querySelector(".current")).includes("Project"), "personal request: an invitation without org or project names no project");
  win.Maity.api.getAll = oiGetAll;
  // Personal requests (§7): in the cross-project inbox only, answered and withdrawn on /requests/{id}.
  const psCalls = [];
  const psPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { psCalls.push([p, b]); return psPost(p, b); };
  await go("#/maintainer/maity/inbox"); await hgSettle();
  expect(!text(main).includes("proposes a change to its soul"), "personal request: never in a project's inbox");
  await go("#/all"); await hgSettle();
  const psHead = () => main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("proposes a change to its soul"));
  expect(psHead() && main.querySelectorAll(".project-label.personal").length === 2
    && !main.querySelectorAll("a.project-label").some((a) => a.getAttribute("href").includes("elsewhere")),
    "personal request: listed as Personal, with no link into its project");
  if (psHead().attrs["aria-expanded"] !== "true") { psHead().click(); await tick(); }
  const psEntry = () => main.querySelector(".current");
  expect(!psEntry().querySelectorAll("a").some((a) => (a.getAttribute("href") || "").includes("elsewhere")) && btn(psEntry(), "Withdraw"),
    "personal request: no links into a project one may not be in, and Withdraw is offered");
  // Withdraw: confirmed, then sent on /requests/{id}/withdraw with the free text as its reason (here refused, so it stays open).
  const psConfirm = win.confirm;
  win.confirm = () => true;
  win.Maity.api.post = (p, b) => { psCalls.push([p, b]); return p.endsWith("/withdraw") ? Promise.reject(new win.Maity.api.ApiError("no", 409, p, "request_not_open", {})) : psPost(p, b); };
  const psText = psEntry().querySelector(".free-text textarea");
  psText.value = "not needed any more";
  btn(psEntry(), "Withdraw").click(); await hgSettle();
  win.confirm = psConfirm;
  expect(psCalls.length === 1 && psCalls[0][0] === "/requests/req-p001/withdraw" && psCalls[0][1].reason === "not needed any more"
    && text(psEntry()).includes("Not sent"), "personal request: withdrawn through /requests/{id}/withdraw, its reason from the free text");
  psCalls.length = 0;
  psText.value = "";
  win.Maity.api.post = (p, b) => { psCalls.push([p, b]); return psPost(p, b); };
  btn(psEntry(), "Go").click(); await hgSettle();
  expect(psCalls.length === 1 && psCalls[0][0] === "/requests/req-p001/answer" && psCalls[0][1].reply_id === "go",
    "personal request: answered through /requests/{id}/answer");
  win.Maity.api.post = psPost;

  // Attachments (docs/api.md §8.7): upload when chosen, name when sent, images inline, files as downloads.
  const atCalls = [];
  const atRaw = win.Maity.api.postRaw, atPost = win.Maity.api.post, atDel = win.Maity.api.del, atUrl = win.Maity.api.attachmentUrl;
  win.Maity.api.postRaw = (p, b, t) => { atCalls.push(["RAW", p, t, b.size]); return atRaw(p, b, t); };
  win.Maity.api.post = (p, b) => { atCalls.push(["POST", p, b]); return atPost(p, b); };
  win.Maity.api.del = (p) => { atCalls.push(["DELETE", p]); return atDel(p); };
  // Fixture mode serves an object URL; the test's stand-in files have none, so a path stands in.
  win.Maity.api.attachmentUrl = (slug, id, download) => "/api/v1/projects/" + win.Maity.api.projectPath(slug) + "/attachments/" + id + "/content" + (download ? "?download=1" : "");
  const atPick = async (id, files) => { const i = byId(id); i.files = files; i.dispatch("change"); for (let k = 0; k < 8; k++) await tick(); };
  const atFile = (name, bytes, size, type) => Object.assign(fakeFile(bytes, size, type), { name });
  await go("#/maintainer/maity/chat/agt-b");
  expect(byId("chat-files") && main.querySelector("label.attach-button").getAttribute("for") === "chat-files", "attachments: the composer offers Attach files");
  await atPick("chat-files", [atFile("big.bin", [1, 2, 3], 10 * 1024 * 1024 + 1, "application/octet-stream")]);
  expect(!atCalls.length && text(main).includes("big.bin is larger than 10 MiB"), "attachments: over 10 MiB refused before uploading");
  await atPick("chat-files", [atFile("shot.png", PNG, 2048, "image/png"), atFile("notes.txt", [0x68, 0x69], 2, "text/plain")]);
  expect(atCalls[0][0] === "RAW" && atCalls[0][1] === "/projects/maintainer/maity/attachments?name=shot.png" && atCalls[0][2] === "image/png"
    && atCalls[1][1] === "/projects/maintainer/maity/attachments?name=notes.txt" && atCalls[1][2] === "text/plain"
    && main.querySelectorAll(".attach-pending li").length === 2 && text(main.querySelector(".attach-pending")).includes("shot.png"),
    "attachments: each file is uploaded raw, an image with its sniffed type, and shown as pending");
  btn(main.querySelectorAll(".attach-pending li")[1], "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(atCalls[2][0] === "DELETE" && /\/projects\/maintainer\/maity\/attachments\/att-/.test(atCalls[2][1]) && main.querySelectorAll(".attach-pending li").length === 1,
    "attachments: a pending one removed is deleted");
  main.querySelector("form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const atSent = atCalls.find((c) => c[0] === "POST" && c[1] === "/projects/maintainer/maity/conversations/agt-b/messages");
  const atMsg = main.querySelectorAll("li.msg").pop();
  expect(atSent && atSent[2].body === "" && atSent[2].attachments.length === 1 && atMsg.querySelector("img.attach-image")
    && atMsg.querySelector("img.attach-image").getAttribute("alt") === "shot.png" && !main.querySelectorAll(".attach-pending li").length,
    "attachments: a message of only a file is sent and shows the image inline");
  // A file that is no image: its name, size and type, a download link, nothing rendered.
  await atPick("chat-files", [atFile("build.log", [0x6c, 0x6f, 0x67], 300, "text/plain")]);
  byId("chat-text").value = "the log"; main.querySelector("form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const atLog = main.querySelectorAll("li.msg").pop();
  expect(!atLog.querySelector("img") && atLog.querySelector("a.attach-link").getAttribute("download") === "build.log"
    && /\/content\?download=1$/.test(atLog.querySelector("a.attach-link").getAttribute("href")) && text(atLog).includes("300 B · text/plain"),
    "attachments: any other file is only a download, with its name, size and type");
  // Deleting a file of the chat (§8.7: the human party), and someone else's deletion arriving.
  const atConfirm = win.confirm;
  win.confirm = () => true;
  btn(atLog, "Delete").click(); for (let k = 0; k < 4; k++) await tick();
  expect(atCalls.slice(-1)[0][0] === "DELETE" && text(atLog).includes("build.log: removed."), "attachments: a file of the chat deleted, said in place");
  win.confirm = atConfirm;
  // The hub's refusals, in words.
  win.Maity.api.postRaw = () => Promise.reject(new win.Maity.api.ApiError("q", 409, "/x", "attachment_quota", { scope: "pending" }));
  await atPick("chat-files", [atFile("more.png", PNG, 100, "image/png")]);
  expect(text(main).includes("Not attached: more.png: you have 20 files, or 100 MiB, waiting to be sent"), "attachments: the pending quota in words");
  win.Maity.api.postRaw = () => Promise.reject(new win.Maity.api.ApiError("d", 400, "/x", "invalid", { fields: { body: "dimensions" } }));
  await atPick("chat-files", [atFile("huge.png", PNG, 100, "image/png")]);
  expect(text(main).includes("the image is larger than 8192 pixels"), "attachments: an image too large in pixels in words");
  // A 300 KB picture refused by a hub's 64 KiB body cap (no upload route yet): its own words and the real size, no 10 MiB.
  win.Maity.api.postRaw = () => Promise.reject(new win.Maity.api.ApiError("the body is over 64 KiB", 413, "/x", "payload_too_large", {}));
  await atPick("chat-files", [atFile("shot300.png", PNG, 300 * 1024, "image/png")]);
  expect(text(main).includes("Not attached: shot300.png: the hub refused it as too large (the file is 300 KB): the body is over 64 KiB")
    && !text(main.querySelector(".attach")).includes("10 MiB"), "attachments: a size refusal says the hub's limit and the file's size, not a fixed one");
  // A message that is no string (a hub answering an object) is left out, never "[object Object]".
  win.Maity.api.postRaw = () => Promise.reject(Object.assign(new win.Maity.api.ApiError("x", 413, "/x", "payload_too_large", {}), { message: { too: "big" } }));
  await atPick("chat-files", [atFile("odd.png", PNG, 2048, "image/png")]);
  expect(text(main).includes("Not attached: odd.png: the hub refused it as too large (the file is 2.0 KB)") && !text(main).includes("[object Object]"),
    "attachments: a non-string message is left out of the refusal");
  win.Maity.api.postRaw = (p, b, t) => { atCalls.push(["RAW", p, t, b.size]); return atRaw(p, b, t); };
  // A group chat: the participant attaches; a project message too.
  await go("#/maintainer/maity/chat/cnv-0007");
  expect(byId("group-files"), "attachments: a group chat's composer offers files");
  await go("#/maintainer/maity/message");
  await atPick("message-files", [atFile("plan.pdf", [0x25, 0x50, 0x44, 0x46], 900, "application/pdf")]);
  byId("message-body").value = "the plan"; main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  const atEvent = atCalls.filter((c) => c[0] === "POST" && c[1] === "/projects/maintainer/maity/events").pop();
  expect(atEvent && atEvent[2].attachments.length === 1 && atEvent[2].body === "the plan", "attachments: a project message names its file");
  // The mock as the hub: an id that is no pending upload of the poster is refused.
  let atBad = null;
  try { await atPost("/projects/maintainer/maity/events", { kind: "message", type: "notice", to: "all", body: "x", attachments: ["att-9999"] }); } catch (err) { atBad = err; }
  expect(atBad && atBad.details.fields.attachments["att-9999"] === "unknown", "attachments: the mock refuses an id that is no pending upload of the poster");
  // Project settings: everyone's pending uploads, another member's without name or type.
  await atRaw("/projects/maintainer/maity/attachments?name=draft.png", fakeFile(PNG, 64), "image/png");
  const atAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/attachments?status=pending"
    ? atAll(p).then((r) => ({ items: r.items.concat([{ id: "att-other", uploaded_by: "agt-b", size: 4096, uploaded_at: "2026-10-23T00:00:00Z", expires_at: "2026-10-24T00:00:00Z",
      name: null, type: null, kind: null, sha256: null, width: null, height: null, message_seq: null }]), next_cursor: null }))
    : atAll(p));
  await go("#/maintainer/maity/inbox"); await projectSettings(); for (let k = 0; k < 4; k++) await tick();
  const atAdmin = main.querySelector(".attach-admin");
  expect(atAdmin && text(atAdmin).includes("draft.png") && text(atAdmin).includes("4.0 KB · Agent B") && !text(atAdmin).includes("null"),
    "attachments: the admin sees everyone's pending uploads, another member's by size and uploader only");
  win.Maity.api.getAll = atAll;
  await projectSettings();
  // The mock never reuses an id after a deletion.
  const atX = await atRaw("/projects/maintainer/maity/attachments?name=x.txt", fakeFile([0x78], 1, "text/plain"), "text/plain");
  const atY = await atRaw("/projects/maintainer/maity/attachments?name=y.txt", fakeFile([0x79], 1, "text/plain"), "text/plain");
  await atDel("/projects/maintainer/maity/attachments/" + atX.id);
  const atZ = await atRaw("/projects/maintainer/maity/attachments?name=z.txt", fakeFile([0x7a], 1, "text/plain"), "text/plain");
  expect(atZ.id !== atY.id && atZ.id !== atX.id, "attachments: the mock gives a new id after a deletion");
  // One's own uploads no message names yet, offered in the composer to attach or remove.
  await go("#/maintainer/maity/chat/agt-b");
  const atEarlier = () => main.querySelector(".attach-earlier-box");
  const atEarlierItem = (name) => main.querySelectorAll(".attach-earlier li").find((li) => text(li).includes(name));
  expect(!atEarlier().hidden && atEarlierItem("draft.png") && atEarlierItem("y.txt") && atEarlierItem("z.txt") && !atEarlierItem("x.txt"),
    "attachments: one's files waiting from before are offered");
  btn(atEarlierItem("z.txt"), "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(atCalls.slice(-1)[0][0] === "DELETE" && atCalls.slice(-1)[0][1].endsWith("/" + atZ.id) && !atEarlierItem("z.txt"), "attachments: one waiting from before removed");
  btn(atEarlierItem("y.txt"), "Attach").click(); await tick();
  expect(text(main.querySelector(".attach-pending")).includes("y.txt") && !atEarlierItem("y.txt"), "attachments: one waiting from before attached");
  // Attached, then removed: deleted on the hub, so no longer offered as waiting.
  btn(atEarlierItem("draft.png"), "Attach").click(); await tick();
  btn(main.querySelectorAll(".attach-pending li").find((li) => text(li).includes("draft.png")), "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(!atEarlierItem("draft.png") && !text(main.querySelector(".attach-pending")).includes("draft.png"), "attachments: one attached from before and removed is gone from both lists");
  byId("chat-text").value = "the rest"; main.querySelector("form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const atRest = atCalls.filter((c) => c[0] === "POST" && c[1] === "/projects/maintainer/maity/conversations/agt-b/messages").pop();
  expect(atRest[2].attachments.length === 1 && atRest[2].attachments[0] === atY.id && !main.querySelectorAll(".attach-pending li").length,
    "attachments: it is sent with the message");
  // An image that fails to load: said, its download link kept.
  const atImg = main.querySelectorAll("li.msg").find((li) => li.querySelector("img.attach-image"));
  atImg.querySelector("img.attach-image").dispatch("error");
  expect(!atImg.querySelector("img.attach-image") && text(atImg).includes("shot.png: could not be shown.") && atImg.querySelector("a.attach-link") && btn(atImg, "Delete"),
    "attachments: an image that did not load is said, not called removed");
  // Inline only a raster type the hub produced; any id the hub gives.
  const atSvg = win.Maity.attachments.render({ slug: "maintainer/maity" }, { body: "", attachments: [{ id: "f1", name: "a.svg", size: 10, type: "image/svg+xml", kind: "image" }] }, null);
  expect(!atSvg.querySelector("img") && atSvg.querySelector("a.attach-link"), "attachments: an image of another type is only a download");
  expect(win.Maity.dom.h("img", { src: "/api/v1/projects/maintainer/maity/attachments/file_7Q/content" }), "attachments: the id is the hub's, not parsed");
  // A closed project takes no new files.
  const atState = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? atState(p).then((x) => Object.assign({}, x, { state: "archived" })) : atState(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-b");
  expect(!byId("chat-files") && main.querySelector("img.attach-image"), "attachments: a closed project offers no new file, and still shows the ones there");
  win.Maity.api.get = atState;
  // Only the hub's own attachment path is a link or an image source.
  let atForeign = null;
  try { win.Maity.dom.h("a", { href: "/api/v1/projects/maintainer/maity/attachments/../../me" }); } catch (err) { atForeign = err; }
  expect(atForeign && win.Maity.dom.h("img", { src: "/api/v1/projects/maintainer/maity/attachments/att-1/content" }), "attachments: only the attachment path itself is allowed");
  // A hub with attachments off (409) is asked for the waiting uploads once per page load.
  const atAll2 = win.Maity.api.getAll;
  let atAsked = 0;
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending&uploaded_by=/.test(p)
    ? (atAsked++, Promise.reject(new win.Maity.api.ApiError("n", 409, p, "attachments_not_configured", {}))) : atAll2(p));
  await go("#/maintainer/maity/chat/agt-b"); await go("#/maintainer/maity/message"); await go("#/maintainer/maity/chat/agt-b");
  expect(atAsked === 1 && !main.querySelectorAll(".attach-earlier li").length, "attachments: a hub with them off is asked once, nothing offered");
  // Project settings then asks no more either.
  let atAskedAll = 0;
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending/.test(p) ? (atAskedAll++, atAll2(p)) : atAll2(p));
  await go("#/maintainer/maity/inbox"); await projectSettings(); for (let k = 0; k < 4; k++) await tick();
  expect(atAskedAll === 0 && text(main.querySelector(".attach-admin")).includes("Attachments are not set up on this instance."), "attachments: settings ask a hub with them off no more");
  await projectSettings();
  win.Maity.api.getAll = atAll2;
  win.Maity.api.postRaw = atRaw; win.Maity.api.post = atPost; win.Maity.api.del = atDel; win.Maity.api.attachmentUrl = atUrl;
  await go("#/maintainer/maity/chat/agt-b"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".attach") && main.querySelector(".attach").hidden, "attachments: once the hub answered 409, the composer offers no Attach files");
  await go("#/maintainer/maity/inbox");

  // Attachments off (§8.7, #477): 409 attachments_not_configured hides upload and delete, files stay as links.
  win.Maity.attachments.forget();
  win.location.search = "?attachments=off";
  win.Maity.api.postRaw = (p, b, t) => { atCalls.push(["RAW", p, t, b.size]); return atRaw(p, b, t); };
  win.Maity.api.attachmentUrl = (slug, id, download) => "/api/v1/projects/" + slug + "/attachments/" + id + "/content" + (download ? "?download=1" : "");
  // Before the hub said so (its waiting uploads read as none), an upload is tried: refused in words, the chooser gone.
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending&uploaded_by=/.test(p) ? Promise.resolve({ items: [], next_cursor: null }) : atAll2(p));
  await go("#/maintainer/maity/chat/agt-b"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".attach").hidden && !main.querySelector("label.attach-button").hidden, "attachments off: before the hub said so, Attach files is offered");
  await atPick("chat-files", [atFile("late.txt", [0x6c], 1, "text/plain")]);
  expect(text(main.querySelector(".attach")).includes("Not attached: late.txt: attachments are not set up on this instance")
    && main.querySelector("label.attach-button").hidden && byId("chat-files").hidden && !main.querySelectorAll(".attach-pending li").length,
    "attachments off: an upload refused with 409 says so and Attach files goes");
  win.Maity.api.getAll = atAll2;
  // One's upload from before, removed after the hub turned them off: said, the list and the chooser gone.
  win.Maity.attachments.forget();
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending&uploaded_by=/.test(p)
    ? Promise.resolve({ items: [{ id: "att-old", name: "old.txt", size: 3, type: "text/plain", kind: "file", uploaded_by: "hum-maintainer", message_seq: null }], next_cursor: null })
    : atAll2(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-b"); for (let k = 0; k < 6; k++) await tick();
  const aoOld = main.querySelectorAll(".attach-earlier li").find((li) => text(li).includes("old.txt"));
  if (aoOld) {
    btn(aoOld, "Remove").click(); for (let k = 0; k < 4; k++) await tick();
    expect(text(main.querySelector(".attach")).includes("Not removed: attachments are not set up on this instance")
      && main.querySelector(".attach-earlier-box").hidden && main.querySelector("label.attach-button").hidden,
      "attachments off: removing an upload from before says so; the list and Attach files go");
  } else expect(false, "attachments off: one's upload from before is offered");
  win.Maity.api.getAll = atAll2;
  // A Delete drawn before the hub said so: refused calmly, the button gone.
  win.Maity.attachments.forget();
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-b");
  const aoDel = main.querySelectorAll("li.attach-item").find((li) => btn(li, "Delete"));
  if (aoDel) {
    btn(aoDel, "Delete").click(); for (let k = 0; k < 4; k++) await tick();
    expect(!btn(aoDel, "Delete") && text(aoDel).includes("Not deleted: attachments are not set up on this instance.") && !aoDel.querySelector(".failed"),
      "attachments off: a delete refused with 409 is said calmly and offered no more");
  }
  for (let k = 0; k < 6; k++) await tick();
  // Known off: the composer offers no files, a message's files stay as links without Delete.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-b"); for (let k = 0; k < 6; k++) await tick();
  const aoLinks = main.querySelectorAll("li.attach-item").filter((li) => li.querySelector("a.attach-link"));
  expect(main.querySelector(".attach").hidden && aoLinks.length && !aoLinks.some((li) => btn(li, "Delete")),
    "attachments off: no Attach files, files stay as links, no Delete");
  // Project settings: said in words, the storage line kept.
  const aoGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? aoGet(p).then((x) => Object.assign({}, x, { attachments: { used: 0, quota: 1024 * 1024 * 1024 } })) : aoGet(p));
  win.Maity.attachments.forget();
  await go("#/maintainer/maity/inbox"); await projectSettings(); for (let k = 0; k < 4; k++) await tick();
  const aoAdmin = main.querySelector(".attach-admin-box");
  expect(aoAdmin && text(aoAdmin).includes("Attachments are not set up on this instance.") && text(aoAdmin).includes("Stored: 0 B of 1024.0 MB.")
    && !btn(aoAdmin, "Delete"), "attachments off: settings say so in words and keep the storage line");
  await projectSettings();
  win.Maity.api.get = aoGet;
  win.Maity.api.postRaw = atRaw; win.Maity.api.attachmentUrl = atUrl;
  win.location.search = "";
  win.Maity.attachments.forget();
  await go("#/maintainer/maity/inbox");

  // Messages (§8.4): the project's messages, newest first, by type, with mentions, files and removal.
  // A hub that keeps files again: the earlier 404 case left this page thinking it has none.
  if (win.Maity.attachments.forget) win.Maity.attachments.forget();
  await go("#/maintainer/maity/messages");
  const pmTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Messages");
  const pmItems = () => main.querySelectorAll("ol.project-messages li.pmsg");
  const pmSeq = (seq) => pmItems().find((li) => li.attrs["data-seq"] === String(seq));
  expect(pmTab && pmTab.getAttribute("aria-current") === "page" && pmItems().map((li) => li.attrs["data-seq"]).filter((x) => x < "9000").join() === "6009,6005,6001"
    && Number(pmItems()[0].attrs["data-seq"]) > 9000, "messages: a tab with the project's messages, newest first");
  // While the view reads /events a removed message is never shown: a removed chat message looks the same there (§8.5, §8.8).
  expect(!pmSeq(6003) && !pmSeq(6012) && !text(main).includes("a token"), "messages: no removed message, a chat's or a project's");
  const pmHand = pmSeq(6005);
  expect(text(pmHand).includes("Handover") && text(pmHand).includes("Agent B to Maintainer") && pmHand.querySelectorAll("a").find((a) => !a.classList.contains("member-ref")).getAttribute("href") === "#/maintainer/maity/tasks/tsk-0004"
    && pmHand.querySelector("li.attach-item") && text(pmHand.querySelector(".attach-meta")).includes("exchange.log · 4.1 KB · text/plain") && btn(pmHand, "Delete"),
    "messages: type, sender, addressee, card and its file; an admin deletes the file");
  expect(pmSeq(6001).querySelector(".pmsg-mentions a").getAttribute("href") === "#/maintainer/maity/members/hum-maintainer", "messages: the members it mentions, as links");
  byId("messages-type").value = "blocker"; byId("messages-type").dispatch("change");
  expect(pmItems().length === 1 && text(pmItems()[0]).includes("waits for the PyPI token"), "messages: filtered by type");
  byId("messages-type").value = ""; byId("messages-type").dispatch("change");
  // A file deleted by someone else arrives with the feed and stays removed on a redraw.
  await win.Maity.api.del("/projects/maintainer/maity/attachments/att-0901");
  await fireIntervals(); await tick(); await tick();
  expect(text(pmSeq(6005)).includes("exchange.log: removed.") && !pmSeq(6005).querySelector(".attach-meta"), "messages: a file deleted elsewhere is said removed");
  byId("messages-type").value = "handover"; byId("messages-type").dispatch("change");
  byId("messages-type").value = ""; byId("messages-type").dispatch("change");
  expect(text(pmSeq(6005)).includes("exchange.log: removed.") && !btn(pmSeq(6005), "Delete"), "messages: a deleted file does not come back on a redraw");
  // A new message arrives in place, at the top; the list is not rebuilt.
  const pmKeep = pmSeq(6001);
  await win.Maity.api.post("/projects/maintainer/maity/events", { kind: "message", type: "notice", to: "all", body: "new from the composer" });
  await fireIntervals(); await tick(); await tick();
  expect(text(pmItems()[0]).includes("new from the composer") && pmSeq(6001) === pmKeep && text(main.querySelector(".view-messages .send-status")).includes("1 new message."),
    "messages: a new message arrives with the feed, at the top, the rest kept in place");
  // Removing one (§8.5, events:admin): it leaves the list.
  const pmPrompt = win.prompt;
  win.prompt = () => "wrong project";
  btn(pmSeq(6009), "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(!pmSeq(6009) && text(main.querySelector(".view-messages .send-status")).includes("Removed.") && pmSeq(6001) === pmKeep, "messages: an admin removes a message with a reason; it leaves the list");
  win.prompt = pmPrompt;
  // A removal elsewhere arrives with the feed (event_redacted) and takes the message out.
  await win.Maity.api.post("/projects/maintainer/maity/events/6001/redact", { reason: "outdated" });
  await fireIntervals(); await tick(); await tick();
  expect(!pmSeq(6001) && pmSeq(6005), "messages: a removal elsewhere takes it out");
  // The scan reads the latest window and says so; a cursor that does not move fails loud.
  const pmGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/events?after=latest&wait=0" ? Promise.resolve({ items: [], cursor: 20000 }) : pmGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/messages");
  expect(text(main).includes("Only messages within the hub's latest 5000 events (all projects counted) are shown") && text(main).includes("No project messages yet."),
    "messages: a long log is read from its latest events, and that is said");
  let pmCalls = 0;
  win.Maity.api.get = (p) => (/\/events\?after=\d+&wait=0&limit=200$/.test(p)
    ? (pmCalls++, Promise.resolve({ items: Array.from({ length: 200 }, () => ({ seq: 5, kind: "member_joined", payload: {} })), cursor: 5 })) : pmGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/messages"); for (let k = 0; k < 4; k++) await tick();
  expect(pmCalls === 1 && text(main).includes("did not move"), "messages: a cursor that does not move stops the scan, said");
  // A member without events:admin: only what it may read, no Remove, Delete only on what it sent.
  win.Maity.api.get = (p) => (p === "/me" ? pmGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "member"; return x; }) : pmGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/messages");
  expect(!pmSeq(6009) && pmSeq(6005) && !main.querySelectorAll("ol.project-messages button").some((b) => b.textContent === "Remove"),
    "messages: a member reads only what is addressed to it, and removes nothing");
  win.Maity.api.get = pmGet;
  await go("#/maintainer/maity/inbox");

  // Ticker (docs/api.md §17): for me / everything, filters, why in words, follow and mute, a manual post.
  await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  const tkItems = () => main.querySelectorAll("ol.ticker-list li.ticker-item");
  const tkSeqs = () => tkItems().map((li) => li.attrs["data-seq"]).join();
  const tkSeq = (seq) => tkItems().find((li) => li.attrs["data-seq"] === String(seq));
  const tkTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Ticker");
  const tkStatus = () => main.querySelector(".view-ticker .send-status");
  expect(tkTab && tkTab.getAttribute("aria-current") === "page" && tkSeqs() === "4330,4310",
    "ticker: a tab; For me lists the items with a reason for the viewer, newest first");
  expect(text(tkSeq(4310)).includes("For you: you own the whole repository, you follow web/.") && text(tkSeq(4310)).includes("Contract change")
    && tkSeq(4310).querySelectorAll("a").find((a) => !a.classList.contains("id-ref")).getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/pull/214"
    && !tkSeq(4310).querySelector("a.id-ref") && tkSeq(4310).querySelectorAll("a").length === 1,
    "ticker: why in words, a contract change marked, its link");
  expect(text(tkSeq(4330)).includes("(muted: it woke no one here)"), "ticker: a muted one says so");
  btn(main.querySelector(".ticker-tabs"), "Everything").click(); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4330,4325,4320,4315,4310,4305,4302" && !text(tkSeq(4320)).includes("For you")
    && btn(main.querySelector(".ticker-tabs"), "Everything").getAttribute("aria-pressed") === "true", "ticker: Everything lists every item one may read");
  expect(text(tkSeq(4315)).includes("Decided: Keep the order — Dashboard view order") && !text(tkSeq(4315)).includes("For you"),
    "ticker: a decision with the chosen reply and the request's title, read at read time");
  expect(text(tkSeq(4325)).includes("This item was removed.") && !tkSeq(4305).querySelectorAll("a").some((a) => !a.classList.contains("member-ref")) && text(tkSeq(4305)).includes("The old wiki moved."),
    "ticker: a removed item says so; an http link is not a link");
  byId("ticker-type").value = "contract"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4310,4302", "ticker: by type, contract meaning a merge that touched the contract");
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  byId("ticker-area").value = "hub/"; main.querySelector("form.board-filter").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4302", "ticker: by area");
  byId("ticker-area").value = ""; main.querySelector("form.board-filter").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  // Text only; a link only when it is https, whatever the case or the trick.
  const tkGet = win.Maity.api.get;
  const tkBad = ["JaVaScRiPt:alert(1)", " https://evil.example", "data:text/html,x", "http://plain.example", "https://user@evil.example/x"];
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => ({ items: tkBad.map((u, i) => Object.assign({}, r.items[0], { seq: 9990 + i, text: i ? "x" : "<b>bold</b>", url: u })), next_cursor: null })) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkItems().length === 5 && tkItems().every((li) => !li.querySelectorAll("a").some((a) => !a.classList.contains("member-ref"))) && text(tkSeq(9990)).includes("<b>bold</b>") && !tkSeq(9990).querySelector("b"),
    "ticker: text as text; javascript:, data:, http:, a leading space or a user in the URL is no link");
  // A decision answered in words has no reply label.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => ({ items: [Object.assign({}, r.items.find((x) => x.type === "merge"), { seq: 9995, type: "decision", contract: null,
    detail: { request_title: "Which hash?", reply_label: null } })], next_cursor: null })) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkSeq(9995)).includes("Decided: answered in writing — Which hash?") && !text(tkSeq(9995)).includes("null"), "ticker: a decision answered in words");
  win.Maity.api.get = tkGet;
  // Older follows the hub's cursor; a quick second click reads nothing twice; a filter change drops an answer still on its way.
  const tkCalls = [];
  let tkHold = null;
  win.Maity.api.get = (p) => {
    if (!p.startsWith("/projects/maintainer/maity/ticker?")) return tkGet(p);
    tkCalls.push(p);
    const r = tkGet(p.replace("limit=50", "limit=2"));
    return tkHold && p.includes("cursor=") ? new Promise((done) => { tkHold = () => r.then(done); }) : r;
  };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  btn(main.querySelector(".ticker-tabs"), "Everything").click(); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4330,4325" && btn(main, "Older"), "ticker: a page, and Older");
  tkHold = true;
  btn(main, "Older").click(); await tick();
  const tkOlderCalls = tkCalls.filter((c) => c.includes("cursor=")).length;
  expect(btn(main, "Older").attrs.disabled !== undefined, "ticker: Older is off while it reads");
  btn(main, "Older").click(); await tick();
  expect(tkCalls.filter((c) => c.includes("cursor=")).length === tkOlderCalls, "ticker: a second click reads nothing more");
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  const tkLate = tkHold; tkHold = null; tkLate(); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4320", "ticker: an older page of the previous filter, answering late, is dropped");
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  btn(main, "Older").click(); for (let k = 0; k < 4; k++) await tick();
  expect(tkSeqs() === "4330,4325,4320,4315" && new Set(tkSeqs().split(",")).size === 4, "ticker: Older appends the next page by the cursor, each item once");
  win.Maity.api.get = tkGet;
  // Follow and mute (§17.8): what is added or removed, nothing replaced.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  const tkSub = () => main.querySelector("section.ticker-sub");
  expect(text(tkSub()).includes("web/") && text(tkSub()).includes("Releases") && text(tkSub()).includes("Notes"), "ticker: one's own follow and mute");
  const tkPatches = [];
  const tkPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { tkPatches.push([p, b]); return tkPatch(p, b); };
  btn(tkSub(), "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(tkPatches[0]) === JSON.stringify(["/projects/maintainer/maity/ticker/subscription", { remove: { follow: { areas: ["web/"] } } }]) && text(tkSub()).includes("No longer following web/."),
    "ticker: stop following an area");
  byId("ticker-sub-list").value = "mute"; byId("ticker-sub-kind").value = "areas"; byId("ticker-sub-value").value = "cli/";
  tkSub().querySelector("form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(tkPatches[1][1]) === JSON.stringify({ add: { mute: { areas: ["cli/"] } } }) && text(tkSub()).includes("Muting cli/.") && byId("ticker-sub-value").value === "",
    "ticker: mute an area");
  win.Maity.api.patch = () => Promise.reject(new win.Maity.api.ApiError("x", 400, "/x", "invalid", { fields: { "follow.areas": "too_many" } }));
  byId("ticker-sub-list").value = "follow"; byId("ticker-sub-value").value = "docs/"; tkSub().querySelector("form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkSub()).includes("Not saved: The areas you follow may hold at most 20") && byId("ticker-sub-value").value === "docs/", "ticker: the hub's refusal in words; the value is kept");
  win.Maity.api.patch = () => Promise.reject(new win.Maity.api.ApiError("x", 429, "/x", "rate_limited", {}));
  tkSub().querySelector("form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkSub()).includes("too many changes in a short time"), "ticker: too many changes, said as changes");
  win.Maity.api.patch = tkPatch;
  // A manual post (§17.6), owners and admins: never a merge or a decision.
  const tkPost = () => main.querySelector("form.ticker-post");
  // Ctrl+Enter posts, as everywhere a multi-line field is (the other forms: further down).
  const tkCe = [];
  const tkCePost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { tkCe.push(p); return new Promise(() => {}); };
  byId("ticker-post-text").value = "from the keyboard";
  byId("ticker-post-text").dispatch("keydown", { key: "Enter" }); await tick();
  const tkCeSend = tkPost().querySelectorAll("button").find((b) => b.getAttribute("type") === "submit");
  tkCeSend.disabled = true; byId("ticker-post-text").dispatch("keydown", { key: "Enter", ctrlKey: true }); await tick();
  tkCeSend.disabled = false;
  expect(!tkCe.length, "Ctrl+Enter: the ticker post: plain Enter and a disabled Post send nothing");
  byId("ticker-post-text").dispatch("keydown", { key: "Enter", ctrlKey: true }); for (let k = 0; k < 3; k++) await tick();
  byId("ticker-post-text").dispatch("keydown", { key: "Enter", ctrlKey: true }); for (let k = 0; k < 3; k++) await tick();
  expect(JSON.stringify(tkCe) === JSON.stringify(["/projects/maintainer/maity/ticker"])
    && main.querySelectorAll("label").find((l) => l.getAttribute("for") === "ticker-post-text").textContent.includes("Ctrl+Enter posts"),
    "Ctrl+Enter: the ticker post is posted, and its label says so");
  win.Maity.api.post = tkCePost;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkPost() && Array.from(byId("ticker-post-type").childNodes).map((o) => o.attrs.value).join() === "note,deploy,release", "ticker: an admin posts a note, a deploy or a release");
  byId("ticker-post-text").value = "Staging is down for an hour.";
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("Not posted: The areas is missing"), "ticker: a note to whom it concerns needs its areas, said");
  byId("ticker-post-areas").value = "hub/ cli/";
  tkPost().dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  btn(main.querySelector(".ticker-tabs"), "Everything").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("Posted.") && text(tkItems()[0]).includes("Staging is down for an hour."), "ticker: posted, and listed");
  byId("ticker-post-text").value = "x".repeat(281);
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("longer than 280 characters"), "ticker: more than 280 characters is refused before sending");
  byId("ticker-post-type").value = "release"; byId("ticker-post-type").dispatch("change");
  byId("ticker-post-text").value = "Released 0.1.0"; byId("ticker-post-release").value = "rel-0001";
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("The release card must name a release card that is done"), "ticker: a release card not done, in words");
  // A deploy: a sha told from a version.
  const tkPosts = [];
  const tkPostFn = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p.endsWith("/ticker")) tkPosts.push(b); return tkPostFn(p, b); };
  byId("ticker-post-type").value = "deploy"; byId("ticker-post-type").dispatch("change");
  byId("ticker-post-text").value = "Deployed 1CDDC4D to production"; byId("ticker-post-env").value = "production"; byId("ticker-post-version").value = "1CDDC4D";
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(tkPosts[0].deploy.sha === "1cddc4d" && !("version" in tkPosts[0].deploy) && text(tkPost()).includes("this was posted already (item 4320)"),
    "ticker: a sha, any case, is sent as sha; a deploy already announced is a duplicate, said");
  byId("ticker-post-version").value = "1234567"; byId("ticker-post-text").value = "Deployed 1234567";
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(tkPosts[1].deploy.version === "1234567" && !("sha" in tkPosts[1].deploy), "ticker: digits only are a version");
  win.Maity.api.post = (p, b) => (p.endsWith("/ticker") ? Promise.reject(new win.Maity.api.ApiError("x", 429, p, "rate_limited", {})) : tkPostFn(p, b));
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("too many posts in the last hour"), "ticker: the hourly limit in words");
  win.Maity.api.post = (p, b) => (p.endsWith("/ticker") ? Promise.reject(new win.Maity.api.ApiError("x", 400, p, "invalid", { fields: { deploy: "not_for_type" } })) : tkPostFn(p, b));
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("does not go with this type"), "ticker: a field not for its type, in words");
  win.Maity.api.post = tkPostFn;
  // To everyone asks first; declined, nothing is sent.
  const tkConfirm = win.confirm;
  let tkAskedAll = 0;
  win.confirm = () => { tkAskedAll += 1; return false; };
  const tkBefore = tkPosts.length;
  win.Maity.api.post = (p, b) => { if (p.endsWith("/ticker")) tkPosts.push(b); return tkPostFn(p, b); };
  byId("ticker-post-type").value = "note"; byId("ticker-post-type").dispatch("change");
  byId("ticker-post-to").value = "all"; byId("ticker-post-to").dispatch("change"); byId("ticker-post-text").value = "Everyone, read this";
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(tkAskedAll === 1 && tkPosts.length === tkBefore, "ticker: a post to everyone asks first; declined, it is not sent");
  win.confirm = tkConfirm;
  win.Maity.api.post = tkPostFn;
  byId("ticker-post-to").value = "computed"; byId("ticker-post-to").dispatch("change");
  // From the feed: the view reads its own listing after the newest shown, in its filters, and keeps the rest.
  const tkKeep = tkSeq(4320);
  const tkLive = [];
  win.Maity.api.get = (p) => { if (p.includes("/ticker?") && p.includes("after=")) tkLive.push(p); return tkGet(p); };
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "from the feed", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkItems()[0]).includes("from the feed") && tkSeq(4320) === tkKeep && text(tkStatus()).includes("1 new item.") && /for=all/.test(tkLive[0]) && /after=\d+/.test(tkLive[0]),
    "ticker: a new item arrives with the feed, read with after=, on top, the rest kept");
  // The feed's event is only the signal: the listing's text is what shows.
  const tkSeen = tkItems().length;
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? tkGet(p).then((r) => ({ items: r.items.map((x) => Object.assign({}, x, { text: "as the listing says" })), next_cursor: null })) : tkGet(p));
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "raw event text", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkItems()[0]).includes("as the listing says") && !text(main).includes("raw event text") && tkItems().length === tkSeen + 1, "ticker: items are the listing's, not built from the raw event");
  // In a filter that does not take it, a new item stays out.
  win.Maity.api.get = tkGet;
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "not a deploy", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(!text(main).includes("not a deploy") && tkItems().every((li) => li.className.includes("type-deploy")), "ticker: a new item outside the filter stays out");
  // More new items than one page: every one arrives.
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  const tkMany = tkItems().length;
  for (let i = 0; i < 60; i++) await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "burst " + i, to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(tkItems().length === tkMany + 60 && text(tkItems()[0]).includes("burst 59"), "ticker: more than a page of new items, every one arrives");
  // A failed live read is said.
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "lost?", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the new items: down"), "ticker: a failed live read is said");
  win.Maity.api.get = tkGet;
  // An item that comes twice in a page is shown once; a reason by role reads with its article.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => {
    const x = Object.assign({}, r.items[0], { seq: 9980, for_me: true, why: ["trust:owner", "trust:admin"] });
    return { items: [x, x], next_cursor: null };
  }) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkItems().length === 1 && text(tkSeq(9980)).includes("you are an owner, you are an admin"), "ticker: one item once; role reasons with their article");
  win.Maity.api.get = tkGet;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  btn(main.querySelector(".ticker-tabs"), "Everything").click(); for (let k = 0; k < 4; k++) await tick();
  // The hub's other refusals of a post, in words.
  win.Maity.api.post = (p, b) => (p.endsWith("/ticker") ? Promise.reject(new win.Maity.api.ApiError("f", 403, p, "forbidden", {})) : tkPostFn(p, b));
  byId("ticker-post-text").value = "x"; byId("ticker-post-areas").value = "/"; tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("only an owner or admin may post to the ticker"), "ticker: forbidden, in words");
  win.Maity.api.post = (p, b) => (p.endsWith("/ticker") ? Promise.reject(new win.Maity.api.ApiError("d", 409, p, "ticker_duplicate", {})) : tkPostFn(p, b));
  tkPost().dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkPost()).includes("this was posted already") && !text(tkPost()).includes("(item"), "ticker: a duplicate without its item number, in words");
  win.Maity.api.post = tkPostFn;
  // A live answer that comes after the filters changed is dropped.
  let tkRelease = null;
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") && !tkRelease
    ? new Promise((done) => { tkRelease = () => tkGet(p).then(done); }) : tkGet(p));
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "late live", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  tkRelease(); for (let k = 0; k < 6; k++) await tick();
  expect(!text(main).includes("late live") && tkItems().every((li) => li.className.includes("type-deploy")), "ticker: a live answer for the previous filters is dropped");
  win.Maity.api.get = tkGet;
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  // A signal while the first page of a filter set is on its way: no read from the start, one read after it.
  let tkFirst = null;
  const tkAfters = [];
  win.Maity.api.get = (p) => {
    if (p.includes("/ticker?") && p.includes("after=")) { tkAfters.push(p); return tkGet(p); }
    if (p.startsWith("/projects/maintainer/maity/ticker?") && tkFirst === true) return new Promise((done) => { tkFirst = () => tkGet(p).then(done); });
    return tkGet(p);
  };
  tkFirst = true;
  byId("ticker-type").value = "note"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 2; k++) await tick();
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "during the reset", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(!tkAfters.length, "ticker: no live read while the first page is on its way");
  const tkRun = tkFirst; tkFirst = null; tkRun(); for (let k = 0; k < 8; k++) await tick();
  expect(tkAfters.length >= 1 && tkAfters.every((p) => !/after=0(&|$)/.test(p)) && tkItems().filter((li) => text(li).includes("during the reset")).length === 1,
    "ticker: after it, one live read from its newest item; the item once");
  win.Maity.api.get = tkGet;
  // A signal while a live read runs is kept: the read runs once more.
  let tkHeld = null;
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") && tkHeld === true
    ? (() => { const r = tkGet(p); return new Promise((done) => { tkHeld = () => r.then(done); }); })() : tkGet(p));
  tkHeld = true;
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "first signal", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  const tkGo = tkHeld; tkHeld = null;
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "second signal", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  tkGo(); for (let k = 0; k < 10; k++) await tick();
  expect(text(main).includes("first signal") && text(main).includes("second signal"), "ticker: a signal during a live read is not lost");
  win.Maity.api.get = tkGet;
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  // A first page that failed: a signal reads that page again, never everything from the start.
  let tkFailFirst = true;
  const tkReads = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/projects/maintainer/maity/ticker?")) tkReads.push(p);
    if (p.startsWith("/projects/maintainer/maity/ticker?") && !p.includes("after=") && tkFailFirst) { tkFailFirst = false; return Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})); }
    return tkGet(p);
  };
  byId("ticker-type").value = "note"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the ticker: down") && !tkItems().length, "ticker: a failed first page is said");
  tkReads.length = 0;
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "after a failed page", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(tkReads.length >= 1 && tkReads.every((p) => !p.includes("after=")) && text(main).includes("after a failed page") && tkItems().length > 1,
    "ticker: the next signal reads the first page again, not after=0");
  expect(!text(tkStatus()).includes("Could not read the ticker"), "ticker: the page read again clears the failure");
  // After that, signals read after= again, and the new item goes on top.
  tkReads.length = 0;
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "after the re-read", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(tkReads.some((p) => /after=\d+/.test(p) && !/after=0(&|$)/.test(p)) && text(tkItems()[0]).includes("after the re-read"),
    "ticker: once the page is in, a signal reads after= and puts the item on top");
  win.Maity.api.get = tkGet;
  // A live read with nothing new ends a failure said before.
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "fails", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the new items"), "ticker: a failed live read is said");
  win.Maity.api.get = tkGet;
  await win.Maity.api.post("/projects/maintainer/maity/ticker", { type: "note", text: "not for this filter", to: ["trust:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(!text(tkStatus()).includes("Could not read"), "ticker: the next live read with nothing new clears it");
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  // A member: no post form.
  win.Maity.api.get = (p) => (p === "/me" ? tkGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").trust = "member"; return x; }) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!tkPost() && tkSub(), "ticker: a member follows and mutes, and posts nothing");
  win.Maity.api.get = tkGet;
  // A 404 that the hub's machine form does not explain is an error, not "no ticker"; another failure too.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/ticker?") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(main).includes("This hub has no ticker yet.") && main.querySelector(".error"), "ticker: a 404 while the hub lists the ticker is an error");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maintainer/maity/ticker?") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(main).includes("This hub has no ticker yet.") && main.querySelector(".error"), "ticker: a 500 is an error, not no ticker");
  // A hub whose machine form has no ticker: said, decided once per page load.
  let tkAsked = 0;
  win.Maity.api.get = (p) => {
    if (p === "/openapi.json") return Promise.resolve({ openapi: "3.1.0", paths: {} });
    if (p.startsWith("/projects/maintainer/maity/ticker?")) { tkAsked += 1; return Promise.reject(new win.Maity.api.ApiError("n", 404, p, "not_found", {})); }
    return tkGet(p);
  };
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkAsked === 1 && text(main).includes("This hub has no ticker yet."), "ticker: a hub without it in its machine form is asked once, and that is said");
  win.Maity.api.get = tkGet;
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox");

  // The overview (docs/api.md §6.11): the project at a glance, every count a link.
  const ovGets = [];
  const ovGet = win.Maity.api.get;
  // Its own feed: the events the test hands over, then none.
  let ovFeed = [];
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) { const items = ovFeed; ovFeed = []; return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 10099, superseded: false }); }
    if (p.includes("/overview")) ovGets.push(p);
    return ovGet(p);
  };
  await go("#/maintainer/maity/overview");
  const ovTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Overview");
  expect(ovTab() && ovTab().getAttribute("href") === "#/maintainer/maity/overview" && header.querySelectorAll("nav.views a")[1] === ovTab()
    && ovTab().getAttribute("aria-current") === "page", "overview: a tab, next to the inbox, marked while open");
  const ov = await ovGet(ovGets[0]);
  expect(ovGets.length === 1 && /^\/projects\/maintainer\/maity\/overview\?closed_after=\d{4}-\d\d-\d\dT[\d:]+Z$/.test(decodeURIComponent(ovGets[0]))
    && Math.abs(Date.parse(decodeURIComponent(ovGets[0].split("=")[1])) - (Date.now() - 14 * 86400000)) < 60000,
    "overview: read once, with the board's 14-day window");
  const ovPart = (id) => main.querySelector("section.overview-part[aria-labelledby=\"" + id + "\"]");
  const repoLink = ovPart("overview-links").querySelectorAll("a")[0];
  expect(repoLink.getAttribute("href") === "https://github.com/oliver-zehentleitner/maity" && repoLink.getAttribute("rel") === "noopener noreferrer"
    && repoLink.getAttribute("target") === "_blank", "overview: the repository, linked in a new tab without an opener");
  const whyItems = ovPart("overview-links").querySelectorAll(".overview-why li");
  expect(whyItems.length >= 2 && whyItems[0].querySelector("a").getAttribute("href") === "https://maity.dev/keep-the-why-dashboard/"
    && text(whyItems[0]).includes("the project · 1 entry needs attention") && text(whyItems[1]).startsWith("hub")
    && text(ovPart("overview-links")).includes("hierarchical"), "overview: each Keep the Why dashboard with its attention, and the policy preset");
  const ovContract = ovPart("overview-links").querySelectorAll("a").find((a) => text(a) === "docs/api.md");
  expect(ovContract && ovContract.getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/blob/main/docs/api.md" && ovContract.getAttribute("target") === "_blank",
    "overview: the contract on the forge at the default branch, beside Keep the Why");
  // The README badge as it stands: off here, said so, the snippet with Copy; an owner is sent to Settings to change it.
  const ovBadge = ovPart("overview-badge");
  expect(ovBadge && text(ovBadge).includes("Off: the badge address answers 'not found'.") && !ovBadge.querySelector("img.badge-preview")
    && ovBadge.querySelector(".overview-badge-states li[aria-current=\"true\"]") && text(ovBadge.querySelector(".overview-badge-states li[aria-current=\"true\"]")) === "Off"
    && text(ovBadge.querySelector(".overview-snippet code")).includes("/badge/maintainer/maity.svg") && btn(ovBadge, "Copy")
    && ovBadge.querySelector(".overview-snippet code").getAttribute("tabindex") === "0" && ovBadge.querySelector(".overview-snippet code").getAttribute("aria-label")
    && ovBadge.querySelectorAll("a").some((a) => a.getAttribute("href") === "#/maintainer/maity/settings"),
    "overview: the README badge's state, its snippet with Copy, and for an owner the way to change it");
  // The team: per role, member chips (the designer's layout); All members at the head's end.
  const ovChips = ovPart("overview-members").querySelectorAll("a.member-chip");
  const ovOwner = ovChips.find((a) => a.getAttribute("data-member") === "hum-maintainer");
  expect(text(ovPart("overview-members")).includes("owner") && ovOwner && text(ovOwner).includes("@maintainer")
    && ovOwner.getAttribute("title").startsWith("Maintainer · owner · coder · human · ")
    && ovOwner.getAttribute("href") === "#/maintainer/maity/members/hum-maintainer" && ovOwner.querySelector(".chip-avatar.human .chip-dot")
    && ovChips.some((a) => a.querySelector(".chip-avatar.agent"))
    && ovPart("overview-members").querySelector("a").getAttribute("href") === "#/maintainer/maity/members" && text(ovPart("overview-members").querySelector("a")) === "All members",
    "overview: the team per role as member chips (name, role, kind and presence in the tooltip), All members at the head's end");
  const ovCounts = ovPart("overview-board").querySelectorAll(".overview-counts li");
  expect(ovCounts.length === 7 && ovCounts.every((li) => li.querySelector("a").getAttribute("href") === "#/maintainer/maity/board")
    && text(ovCounts.find((li) => li.attrs["data-status"] === "in_progress")).startsWith(String(ov.board.counts.in_progress)),
    "overview: every column's count, each linking to the board");
  // The fixtures' requests are answered by now: the count and its empty state.
  expect((!ov.requests.open || text(ovPart("overview-requests")).includes(String(ov.requests.open)))
    && (ov.requests.open ? text(ovPart("overview-requests")).includes(" for you") : text(ovPart("overview-requests")).includes("Nothing waits for an answer."))
    && (!ov.requests.open || ovPart("overview-requests").querySelector("a").getAttribute("href") === "#/maintainer/maity/inbox")
    && text(byId("overview-requests")) === "Waiting for you" && main.querySelector(".overview-row-1").childNodes[0] === ovPart("overview-requests"),
    "overview: what waits for the reader comes first, linking to the inbox when anything does");
  const ovReport = ovPart("overview-reports").querySelector("li");
  expect(ovReport && text(ovReport).includes("@agent-b") && text(ovReport).includes("tsk-0005")
    && ovReport.querySelectorAll("a").some((a) => a.getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/pull/3") && text(ovReport).includes("PR #3 open"),
    "overview: the latest report with its card, its author and its pull request as the probe saw it");
  // The layout: the designer's order, with Project and README badge under Team, beside and before Latest reports
  // (tsk-b67chbx96n29: below the long list they were out of sight); the board as a stacked bar with an accessible name.
  const ovRows = main.querySelectorAll(".overview-row").map((row) => row.querySelectorAll(".overview-part").map((x) => x.getAttribute("aria-labelledby")).join("+"));
  const ovStack = main.querySelector(".overview-row-2 .overview-stack");
  const ovBar = ovPart("overview-board").querySelector(".overview-bar");
  expect(JSON.stringify(ovRows) === JSON.stringify(["overview-requests+overview-board", "overview-members+overview-links+overview-badge+overview-reports", "overview-swarm", "overview-org"])
    && ovStack && ovStack.childNodes.map((x) => x.getAttribute("aria-labelledby")).join("+") === "overview-members+overview-links+overview-badge"
    && ovStack.parentNode.childNodes[1] === ovPart("overview-reports")
    && ovBar && ovBar.getAttribute("role") === "img" && ovBar.getAttribute("aria-label").includes(ov.board.counts.in_progress + " in progress")
    && main.querySelectorAll(".overview-head").every((hd) => !hd.childNodes[0].querySelector("a")),
    "overview: four rows, what needs you first, Project and README badge under Team before Latest reports, then the swarm, the organisation last; the board's bar named for a screen reader; no heading is a link " + JSON.stringify(ovRows));
  // Re-read on a card, a request or the probe; not on anything else; no Reload offered.
  ovFeed = [{ seq: 10100, kind: "member_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(ovGets.length === 1 && !btn(main, "Reload"), "overview: a member event does not re-read the counts, and offers no Reload");
  ovFeed = [{ seq: 10101, kind: "probe_observed", actor: null, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(ovGets.length === 2 && !btn(main, "Reload"), "overview: probe_observed re-reads it in place, no Reload offered");
  ovFeed = [{ seq: 10102, kind: "task_reported", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(ovGets.length === 3, "overview: a card event re-reads it");
  // Empty states, and a value from data that is no https link stays text.
  win.Maity.api.get = (p) => (p.includes("/overview")
    ? Promise.resolve({ server_time: "2026-10-22T14:00:00Z", board: { counts: { proposed: 0, open: 0, in_progress: 0, blocked: 0, review: 0, done: 0, cancelled: 0 }, closed_after: null },
      requests: { open: 0, to_me: 0, by_priority: { urgent: 0, high: 0, normal: 0, low: 0 }, oldest_open_at: null },
      reports: [{ task: { id: "tsk-x", title: "X", status: "done", kind: "task", label: null }, reported_by: { member_id: "agt-b", handle: "agent-b", display_name: "Agent B", avatar_url: null },
        reported_at: "2026-10-22T13:10:00Z", code: true, verification: "signed", pr: { number: 9, url: "javascript:alert(1)" }, pr_state: "merged", observed_at: null, mismatch: true }] })
    : p === "/projects/maintainer/maity" ? ovGet(p).then((x) => Object.assign({}, x, { repository: null, keep_the_why_export: null })) : ovGet(p));
  await go("#/maintainer/maity/overview");
  expect(text(ovPart("overview-board")).includes("No cards yet.") && text(ovPart("overview-requests")).includes("Nothing waits for an answer.")
    && text(ovPart("overview-links")).includes("No repository.") && text(ovPart("overview-links")).includes("No Keep the Why dashboard is published.")
    && text(ovPart("overview-links")).includes("dashboard-state line"), "overview: empty states, and for an owner where the Keep the Why link comes from");
  const badPr = ovPart("overview-reports").querySelector("li");
  expect(!badPr.querySelectorAll("a").some((a) => (a.getAttribute("href") || "").startsWith("javascript")) && text(badPr).includes("PR #9 merged")
    && text(badPr).includes("does not match what was reported"), "overview: a pull request URL that is no https link stays text; a mismatch is said");
  btn(ovPart("overview-links"), "Set the repository").click(); win.onhashchange(); for (let k = 0; k < 6; k++) await tick();
  expect(onSettings() && main.all().some((e) => e.id === "project-panel") && byId("repo-url"), "overview: Set the repository opens the Settings tab at the repository");
  // A hub without the endpoint: links and members still, the counts said missing.
  win.Maity.api.get = (p) => (p.includes("/overview") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : ovGet(p));
  await go("#/maintainer/maity/overview");
  expect(!main.querySelector(".error") && ovPart("overview-links") && ovPart("overview-members") && !ovPart("overview-board")
    && main.querySelector(".overview-missing") && text(main).includes("This hub has no overview yet") && !main.querySelector(".send-status.failed"),
    "overview: without the endpoint the rest stays, the counts said missing quietly, never as an error");
  // A refresh that meets the 404 again stays quiet too; any other failure is an error.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p.includes("/overview") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : ovGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview");
  expect(main.querySelector(".send-status.failed") && text(main).includes("The counts could not be read: down") && !main.querySelector(".overview-missing"),
    "overview: a 500 is still said as an error");
  win.Maity.api.get = ovGet;
  // An owner gets no timer: the events reach them. A redraw keeps the focus on the same link.
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) { const items = ovFeed; ovFeed = []; return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 10199, superseded: false }); }
    if (p.includes("/overview")) ovGets.push(p);
    return ovGet(p);
  };
  const ovReads = () => ovGets.length;
  await go("#/maintainer/maity/overview");
  let ovBefore = ovReads();
  await fireIntervals(); await tick(); await tick();
  expect(ovReads() === ovBefore && !docListeners.visibilitychange, "overview: an owner's view has no 60-second re-read and no tab-focus re-read");
  const ovProto = Object.getPrototypeOf(main);
  const ovFocus = ovProto.focus;
  ovProto.focus = function () { document.activeElement = this; };
  const openCount = () => main.querySelector(".overview-counts li[data-status=\"open\"] a");
  const firstOpen = openCount();
  firstOpen.focus();
  ovFeed = [{ seq: 10200, kind: "task_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(openCount() !== firstOpen && document.activeElement === openCount(), "overview: a redraw puts the focus back on the same count");
  ovProto.focus = ovFocus; document.activeElement = undefined;
  // A member (neither owner nor admin): every 60 seconds and on the tab's return, one follow-up for a burst.
  const ovMe = win.Maity.api.get;
  let ovSlow = null;
  win.Maity.api.get = (p) => {
    if (p === "/me") return ovMe(p).then((m) => { m.projects.find((x) => x.slug === "maity").trust = "member"; return m; });
    if (p.includes("/overview") && ovSlow) { ovGets.push(p); return new Promise((done) => { ovSlow.push(() => ovGet(p).then(done)); }); }
    return ovMe(p);
  };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview");
  expect(!btn(main, "Set the repository") && !text(main).includes("dashboard-state line"), "overview: a member sees neither Set the repository nor where the link comes from");
  ovBefore = ovReads();
  await fireIntervals(); await tick(); await tick();
  expect(ovReads() === ovBefore + 1, "overview: a member's view re-reads every 60 seconds");
  document.visibilityState = "visible";
  docListeners.visibilitychange(); await tick(); await tick();
  expect(ovReads() === ovBefore + 2, "overview: and when the tab comes back");
  win.onfocus(); await tick(); await tick();
  expect(ovReads() === ovBefore + 3, "overview: and when its window gets the focus back");
  ovSlow = [];
  ovBefore = ovReads();
  docListeners.visibilitychange(); docListeners.visibilitychange(); docListeners.visibilitychange(); await tick();
  ovSlow.shift()(); await tick(); await tick();
  ovSlow.length && ovSlow.shift()(); await tick(); await tick();
  expect(ovReads() === ovBefore + 2, "overview: triggers during a read give one more read, not none and not one each");
  ovSlow = null;
  win.Maity.api.get = ovMe;
  // A mismatch the probe has not looked at yet (null) is no warning.
  const ovGet2 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p.includes("/overview") ? ovGet2(p).then((o) => Object.assign({}, o, { reports: o.reports.map((r) => Object.assign({}, r, { mismatch: null })) })) : ovGet2(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview");
  expect(!text(ovPart("overview-reports")).includes("does not match"), "overview: mismatch null is no warning");
  win.Maity.api.get = ovGet;
  await go("#/maintainer/maity/inbox");

  // The mock as the hub: closed cards counted after closed_after only; a bad limit is invalid.
  const allTime = await ovGet("/projects/maintainer/maity/overview");
  const recent = await ovGet("/projects/maintainer/maity/overview?closed_after=2030-01-01T00:00:00Z");
  let badLimit = null;
  try { await ovGet("/projects/maintainer/maity/overview?limit=0"); } catch (err) { badLimit = err; }
  expect(allTime.board.closed_after === null && recent.board.counts.done === 0 && recent.board.counts.open === allTime.board.counts.open
    && badLimit && badLimit.details.fields.limit, "overview: the mock counts closed cards in the window, open ones in full, and refuses a bad limit");

  // The mock as the hub answers an admin agent (?as=agt-a, docs/api.md §2.3 ᵃ).
  win.location.search = "?as=agt-a";
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  const asAgent = async (call) => { try { return await call(); } catch (err) { return err; } };
  const aRole = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-r", { trust: "member", role: "coder" }));
  const aPause = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-r", { paused: { reason: "quota" } }));
  const aRemove = await asAgent(() => win.Maity.api.del("/projects/maintainer/maity/members/agt-b"));
  const aMember = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-b", { areas: ["web/"], paused: { reason: "quota" } }));
  const aCaps = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-b", { capabilities: ["tag"] }));
  const aProxy = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-b", { trust: "admin", role: "proxy" }));
  const aHuman = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/hum-maintainer", { areas: ["x/"] }));
  const aSelf = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity/members/agt-a", { areas: ["x/"] }));
  const aLaunch = await asAgent(() => win.Maity.api.patch("/projects/maintainer/maity", { state: "launch", reason: "go" }));
  const aAfter = (await win.Maity.api.getAll("/projects/maintainer/maity/members")).items;
  const humansOnly = (e) => e && e.code === "forbidden" && e.details.reason === "humans_only";
  expect(aRole.class === "consent" && aRole.to === "owner" && aRole.title === "Change reviewer to member · coder"
    && aPause.title === "Pause reviewer" && aRemove.title === "Remove agent-b"
    && aAfter.find((x) => x.id === "agt-r").role === "reviewer" && !aAfter.find((x) => x.id === "agt-r").paused && aAfter.some((x) => x.id === "agt-b"),
    "mock as an admin agent: a reviewer's role or pause and any removal wait for the owner's consent (202), nothing changed yet");
  expect(aMember.id === "agt-b" && aMember.paused && aMember.areas.join() === "web/", "mock as an admin agent: a member agent's areas and pause apply at once");
  expect(humansOnly(aCaps) && humansOnly(aProxy) && humansOnly(aHuman) && humansOnly(aSelf),
    "mock as an admin agent: capabilities, proxy, a human's and its own membership are a human's");
  expect(aLaunch && aLaunch.status === 403 && aLaunch.code === "forbidden", "mock as an admin agent: moving to launch is the owner's go (403)");
  win.location.search = "";

  // The Keep the Why commitment (docs/api.md §6.23): the policy in Settings, the Members mark, the why on a report,
  // the notification's way to the agent. Quiet on a hub without the fields.
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  const ktRow = (name) => main.querySelectorAll("tr.member").find((tr) => tr.querySelector(".member-name").textContent === name);
  expect(ktRow("Agent B").querySelector(".ktw-unconfirmed") && text(ktRow("Agent B")).includes("agent-b#wle2: to confirm by " + win.Maity.dom.formatTime("2026-10-21T10:42:00Z"))
    && !ktRow("Agent C").querySelector(".ktw-unconfirmed") && text(ktRow("Agent C")).includes("agent-c#k3pa: confirmed")
    && !main.querySelector(".error"), "keep the why: an agent past its deadline is marked with it, a confirmed one says when, per instance");
  const ktGetAll = win.Maity.api.getAll;
  const ktStrip = (m) => { const x = Object.assign({}, m); delete x.keep_the_why_unconfirmed; return x; };
  const ktGet0 = win.Maity.api.get;
  win.Maity.api.getAll = (p) => (p.endsWith("/members") ? ktGetAll(p).then((r) => ({ ...r, items: r.items.map(ktStrip) })) : ktGetAll(p));
  win.Maity.api.get = (p) => (p.endsWith("/members") ? ktGet0(p).then((r) => ({ ...r, items: r.items.map(ktStrip) })) : ktGet0(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick();
  expect(!main.querySelectorAll("th").some((t) => t.textContent === "Keep the Why") && !main.querySelector(".ktw-unconfirmed"),
    "keep the why: without the hub's fields (optional, or an older hub) no column and no mark");
  win.Maity.api.getAll = ktGetAll; win.Maity.api.get = ktGet0;
  // Settings: required or optional, with a reason; disabled under no memory provider; absent where the hub has no such policy.
  const ktPatches = [];
  const ktPatch = win.Maity.api.patch, ktGet = win.Maity.api.get;
  win.Maity.api.patch = (p, b) => { if (b && b.policy && "keep_the_why" in b.policy) ktPatches.push(b); return ktPatch(p, b); };
  await go("#/maintainer/maity/settings"); for (let k = 0; k < 6; k++) await tick();
  const ktForm = () => main.querySelector("form.ktw-policy-form");
  expect(ktForm() && byId("ktw-policy-select").value === "required" && !byId("ktw-policy-select").disabled, "keep the why: Settings offer the commitment, required here");
  byId("ktw-policy-select").value = "optional"; ktForm().dispatch("submit"); await tick();
  expect(!ktPatches.length, "keep the why: a change needs a reason");
  byId("ktw-policy-select").value = "optional"; byId("ktw-policy-reason").value = "A trial project";
  ktForm().dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(ktPatches[0]) === JSON.stringify({ policy: { keep_the_why: "optional" }, reason: "A trial project" }) && byId("ktw-policy-select").value === "optional",
    "keep the why: switched to optional as a policy change with its reason");
  await ktPatch("/projects/maintainer/maity", { policy: { keep_the_why: "required" }, reason: "back" });
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? ktGet(p).then((x) => ({ ...x, memory: { provider: "none" }, policy: { ...x.policy, keep_the_why: "optional" } })) : ktGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/settings"); for (let k = 0; k < 6; k++) await tick();
  expect(ktForm() && byId("ktw-policy-select").getAttribute("disabled") !== null && byId("ktw-policy-reason").getAttribute("disabled") !== null
    && btn(ktForm(), "Change").getAttribute("disabled") !== null && text(ktForm()).includes("no memory provider"),
    "keep the why: under no memory provider the choice is disabled and says why");
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity" ? ktGet(p).then((x) => { const pol = { ...x.policy }; delete pol.keep_the_why; return { ...x, policy: pol }; }) : ktGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/settings"); for (let k = 0; k < 6; k++) await tick();
  expect(!ktForm() && !main.querySelector(".error"), "keep the why: a hub without the policy shows no form");
  win.Maity.api.get = ktGet; win.Maity.api.patch = ktPatch;
  // The why on a code report: a link to the entry's file at the report's head; a reason when there is none; a bad path stays text.
  const ktHead = "d91e294c" + "0".repeat(32);
  const ktReport = (why) => ({ summary: "Done.", mentions: [], reported_at: "2026-10-22T13:10:00Z", verification: "signed", code: true, head: ktHead,
    pr: null, pr_status: "none", observed: null, mismatch: false, why });
  const ktWhys = { "tsk-0005": { ref: "context/cards.md#2280ced7-c51f-48f5-aab7-3bdacc7de21e" }, "tsk-0006": { none: "a mechanical rename" }, "tsk-0007": { ref: "../secret.md#x" } };
  win.Maity.api.getAll = (p) => (p.includes("/tasks?") ? ktGetAll(p).then((r) => ({ ...r, items: r.items.map((c) => (ktWhys[c.id] ? { ...c, report: ktReport(ktWhys[c.id]) } : c)) })) : ktGetAll(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 6; k++) await tick();
  const ktCard = (id) => main.querySelectorAll("article.card").find((a) => a.attrs["data-card"] === id);
  const ktLink = ktCard("tsk-0005").querySelector(".report-why a");
  expect(ktLink && ktLink.getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/blob/" + ktHead + "/context/cards.md"
    && ktLink.getAttribute("rel") === "noopener noreferrer" && text(ktCard("tsk-0005").querySelector(".report-why")).endsWith("#2280ced7-c51f-48f5-aab7-3bdacc7de21e"),
    "keep the why: a report's why links its entry's file at the reported head, the entry's id beside it");
  expect(text(ktCard("tsk-0006").querySelector(".report-why")) === "No why: a mechanical rename"
    && !ktCard("tsk-0007").querySelector(".report-why a") && text(ktCard("tsk-0007").querySelector(".report-why")).includes("../secret.md"),
    "keep the why: no why says the reason; a path out of the repository stays text");
  win.Maity.api.getAll = ktGetAll;
  // Since 2026-10-26 the owner's notice is a personal request in the inbox (§6.23, §18.1): no kind of its own.
  expect(!("keep_the_why" in win.Maity.notify.KIND_WORDS), "keep the why: the owner's notice is a request in the inbox, no notification kind of its own");
  const ktProto = Object.getPrototypeOf(main), ktFocus = ktProto.focus;
  ktProto.focus = function () { document.activeElement = this; };
  // /agents/<id>: one profile marked, its title focused, its settings open.
  await go("#/agents/agt-x"); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const ktAgent = main.querySelectorAll("li.agent-card.wanted");
  expect(ktAgent.length === 1 && ktAgent[0].getAttribute("data-agent") === "agt-x" && document.activeElement === ktAgent[0].querySelector(".agent-card-title")
    && ktAgent[0].querySelector("details.agent-settings").attrs.open !== undefined, "agents page: /agents/<id> marks that profile, its title focused, its settings open");
  ktProto.focus = ktFocus; document.activeElement = undefined;

  // Subtasks (docs/api.md §6.4): children folded under their parent with the hub's counts, a child whose parent
  // is not shown standing on its own, parent and related in the opened card, a new subtask, the hub's refusals.
  const stProto = Object.getPrototypeOf(main), stFocus = stProto.focus;
  stProto.focus = function () { document.activeElement = this; };
  try { win.localStorage && win.localStorage.removeItem && win.localStorage.removeItem("maity.board.column.maity"); } catch (err) { /* none */ }
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/board"); for (let k = 0; k < 6; k++) await tick();
  const stCard = (id) => main.querySelector(".columns").querySelectorAll("article.card").find((a) => a.attrs["data-card"] === id);
  const stToggle = (id) => stCard(id).querySelector("button.subtask-toggle");
  const stRows = (id) => stCard(id).querySelectorAll("li.subtask").map((li) => li.getAttribute("data-card"));
  expect(!stCard("tsk-0011") && !stCard("tsk-0012") && !stCard("tsk-0014") && stToggle("tsk-0010") && text(stToggle("tsk-0010")) === "Subtasks · 1 of 2 open"
    && stToggle("tsk-0010").getAttribute("aria-expanded") === "false" && stCard("tsk-0010").querySelector("ul.subtask-list").hidden,
    "subtasks: children stand folded under their parent, the hub's open and total on the toggle");
  stToggle("tsk-0010").click(); await tick();
  expect(stToggle("tsk-0010").getAttribute("aria-expanded") === "true" && !stCard("tsk-0010").querySelector("ul.subtask-list").hidden
    && JSON.stringify(stRows("tsk-0010").sort()) === JSON.stringify(["tsk-0011", "tsk-0012"])
    && stCard("tsk-0010").querySelectorAll("li.subtask a").some((a) => a.getAttribute("href") === "#/maintainer/maity/tasks/tsk-0011"),
    "subtasks: unfolded, each child with its status, linked to open it");
  expect(stToggle("tsk-0013") && text(stToggle("tsk-0013")) === "Subtasks · 1 of 1 open" && (stToggle("tsk-0013").click(), JSON.stringify(stRows("tsk-0013"))) === JSON.stringify(["tsk-0014"]),
    "subtasks: a cancelled parent keeps its open child under it");
  // Only open cards: the parent (in review) is not shown, so its open child stands with the parent's id.
  byId("board-column").value = "open"; byId("board-column").dispatch("change"); await tick();
  expect(stCard("tsk-0011") && text(stCard("tsk-0011").querySelector(".card-parent")) === "Subtask of tsk-0010"
    && stCard("tsk-0011").querySelector(".card-parent a").getAttribute("href") === "#/maintainer/maity/tasks/tsk-0010",
    "subtasks: a child whose parent is not shown stands on its own with the parent's id");
  byId("board-column").value = ""; byId("board-column").dispatch("change"); await tick();
  // A folded child opened by its link: its parent unfolds, the child's row is marked, the panel shows the parent.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/tasks/tsk-0011"); for (let k = 0; k < 6; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const stPanel = () => main.querySelector("aside.card-panel");
  const stMarked = main.querySelector(".columns").querySelectorAll("li.subtask").find((li) => li.getAttribute("data-card") === "tsk-0011");
  expect(stPanel() && stMarked && stMarked.className.includes("wanted") && !stMarked.parentNode.hidden
    && stPanel().querySelector(".card-parent a").getAttribute("href") === "#/maintainer/maity/tasks/tsk-0010" && byId("card-parent-tsk-0011").value === "tsk-0010",
    "subtasks: a folded child's link unfolds its parent and marks it; its card names the parent");
  // The parent's card: its children and its related card, as links.
  await go("#/maintainer/maity/tasks/tsk-0010"); for (let k = 0; k < 6; k++) await tick();
  expect(stPanel().querySelectorAll(".card-panel-card li.subtask").length === 2 && stPanel().querySelector(".related a").getAttribute("href") === "#/maintainer/maity/tasks/tsk-0006"
    && !byId("card-parent-tsk-0010") && text(stPanel()).includes("It has subtasks of its own, so it is no subtask."),
    "subtasks: the parent's card lists its children and related cards; a parent takes no parent");
  // Editing: a parent and related cards are one PATCH; the hub's refusal is said in its own words.
  const stPatches = [];
  const stPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { if (b && ("parent" in b || "related" in b)) stPatches.push([p, b]); return stPatch(p, b); };
  await go("#/maintainer/maity/tasks/tsk-0006"); for (let k = 0; k < 6; k++) await tick();
  const stOptions = byId("card-parent-tsk-0006").querySelectorAll("option").map((o) => o.getAttribute("value"));
  expect(!stOptions.includes("tsk-0013") && !stOptions.includes("tsk-0011") && !stOptions.some((v) => v.startsWith("rel-")) && stOptions.includes("tsk-0001"),
    "subtasks: a parent is chosen among open cards that are no subtask and no release");
  // tsk-0006 depends on tsk-0001: as its parent that would wait forever, and the hub says so.
  byId("card-parent-tsk-0006").value = "tsk-0001";
  stPanel().querySelector("form.card-family-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(stPatches[0]) === JSON.stringify(["/projects/maintainer/maity/tasks/tsk-0006", { parent: "tsk-0001" }]) && stCard("tsk-0006")
    && text(stPanel().querySelector("form.card-family-form .send-status")) === "Not saved: the request does not validate (parent: cycle)",
    "subtasks: a parent that would make a cycle is refused in the hub's words");
  byId("card-parent-tsk-0006").value = "tsk-0007";
  stPanel().querySelector("form.card-family-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(stPatches[1]) === JSON.stringify(["/projects/maintainer/maity/tasks/tsk-0006", { parent: "tsk-0007" }]) && !stCard("tsk-0006")
    && stRows("tsk-0007").includes("tsk-0006") && document.activeElement && document.activeElement.getAttribute("data-focus") === "family:tsk-0006",
    "subtasks: a parent set, the card folds under it and the focus stays on Save");
  win.Maity.api.patch = (p, b) => (b && "parent" in b ? Promise.reject(new win.Maity.api.ApiError("the request does not validate", 400, p, "invalid", { fields: { parent: "too_deep", related: "unknown_task" } })) : stPatch(p, b));
  byId("card-parent-tsk-0006").value = "";
  stPanel().querySelector("form.card-family-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(stPanel().querySelector("form.card-family-form .send-status")) === "Not saved: the request does not validate (parent: too_deep; related: unknown_task)",
    "subtasks: a refusal is said as the hub words it, with its reason");
  // Every reason of §6.4 in the hub's words; anything else as the board says it elsewhere.
  const stRefuse = async (err) => {
    win.Maity.api.patch = (p, b) => (b && ("parent" in b || "related" in b) ? Promise.reject(err) : stPatch(p, b));
    byId("card-related-tsk-0006").querySelectorAll("option")[0].selected = true;
    stPanel().querySelector("form.card-family-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
    const said = text(stPanel().querySelector("form.card-family-form .send-status"));
    byId("card-related-tsk-0006").querySelectorAll("option")[0].selected = false;
    return said;
  };
  const stApiErr = (status, code, details, message) => new win.Maity.api.ApiError(message || "the request does not validate", status, "/x", code, details);
  const stSaid = [];
  for (const why of ["has_children", "parent_closed", "self", "release_card"]) stSaid.push(await stRefuse(stApiErr(400, "invalid", { fields: { parent: why } })));
  stSaid.push(await stRefuse(stApiErr(403, "forbidden", { reason: "subtasks_proposed" }, "under this project's subtask policy a subtask starts as proposed")));
  stSaid.push(await stRefuse(stApiErr(404, "unknown_task", { fields: { parent: "unknown_task" } }, "no such card")));
  stSaid.push(await stRefuse(stApiErr(503, "unavailable", {}, "the hub is busy")));
  expect(JSON.stringify(stSaid) === JSON.stringify([
    "Not saved: the request does not validate (parent: has_children)", "Not saved: the request does not validate (parent: parent_closed)",
    "Not saved: the request does not validate (parent: self)", "Not saved: the request does not validate (parent: release_card)",
    "Not saved: under this project's subtask policy a subtask starts as proposed (subtasks_proposed)",
    "Not saved: no such card (parent: unknown_task)", "Not saved: the hub is busy"]),
    "subtasks: each refusal said in the hub's words with its reason, another one as elsewhere " + JSON.stringify(stSaid));
  win.Maity.api.patch = stPatch;
  await stPatch("/projects/maintainer/maity/tasks/tsk-0006", { parent: null });
  // A parent waiting for its subtasks says which.
  expect(win.Maity.boardEdit.said(stApiErr(409, "dependencies_open", { open: ["tsk-0001", "tsk-0011"], children: ["tsk-0011"] }, "dependencies or children are not done")).message
    === "Not done yet: its subtask tsk-0011 still open, and tsk-0001 it depends on.", "subtasks: a parent not done for its open subtask names it");
  // Edges the board did not load stay as they are: a parent and a related card outside the window are shown and kept.
  const stGetAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p.includes("/tasks?") ? stGetAll(p).then((r) => ({ ...r, items: r.items.filter((t) => t.id !== "tsk-0010")
    .map((t) => (t.id === "tsk-0011" ? { ...t, related: ["tsk-0099"] } : t)) })) : stGetAll(p));
  stPatches.length = 0;
  win.Maity.api.patch = (p, b) => { if (b && ("parent" in b || "related" in b)) stPatches.push([p, b]); return Promise.resolve({}); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/tasks/tsk-0011"); for (let k = 0; k < 6; k++) await tick();
  const stRel = byId("card-related-tsk-0011").querySelectorAll("option");
  expect(byId("card-parent-tsk-0011").value === "tsk-0010" && text(byId("card-parent-tsk-0011").querySelectorAll("option").find((o) => o.getAttribute("value") === "tsk-0010")) === "tsk-0010 (not on the board)"
    && stRel.find((o) => o.getAttribute("value") === "tsk-0099").selected, "subtasks: a parent and a related card the board did not load are shown, chosen");
  stRel.find((o) => o.getAttribute("value") === "tsk-0006").selected = true;
  stPanel().querySelector("form.card-family-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(stPatches.length === 1 && !("parent" in stPatches[0][1]) && JSON.stringify(stPatches[0][1].related.slice().sort()) === JSON.stringify(["tsk-0006", "tsk-0099"]),
    "subtasks: changing only the related cards sends them alone, keeping the one not loaded " + JSON.stringify(stPatches));
  win.Maity.api.getAll = stGetAll; win.Maity.api.patch = stPatch;
  // Folding is no redraw: the column filter, the search and the scroll stay.
  await go("#/maintainer/maity/board"); for (let k = 0; k < 6; k++) await tick();
  byId("board-column").value = "review"; byId("board-column").dispatch("change"); await tick();
  byId("board-search").value = "subtasks"; byId("board-search").dispatch("input"); await tick();
  win.scrollY = 240;
  const stWasOpen = stToggle("tsk-0010").getAttribute("aria-expanded");
  stToggle("tsk-0010").click(); await tick();
  stToggle("tsk-0010").click(); await tick();
  expect(byId("board-column").value === "review" && byId("board-search").value === "subtasks" && win.scrollY === 240
    && stToggle("tsk-0010").getAttribute("aria-expanded") === stWasOpen && main.querySelector(".columns").querySelectorAll("article.card").length === 1,
    "subtasks: folding and unfolding keep the column filter, the search and the scroll");
  byId("board-column").value = ""; byId("board-column").dispatch("change"); await tick();
  byId("board-search").value = ""; byId("board-search").dispatch("input"); await tick(); win.scrollY = 0;
  // A hub without subtasks (no parent on its cards): no editor and no New subtask.
  await go("#/maintainer/sample/tasks/tsk-0021"); for (let k = 0; k < 6; k++) await tick();
  expect(stPanel() && !stPanel().querySelector("form.card-family-form") && !btn(stPanel(), "New subtask"), "subtasks: a hub without them offers no editor and no New subtask");
  // A new subtask from the opened card: the parent preset; under the proposed policy a member's starts as proposed.
  const stPosts = [];
  const stPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p === "/projects/maintainer/maity/tasks") stPosts.push(b); return stPost(p, b); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/tasks/tsk-0010"); for (let k = 0; k < 6; k++) await tick();
  btn(stPanel(), "New subtask").click(); await tick();
  expect(stPanel().querySelector("form.new-subtask") && text(stPanel().querySelector(".new-card-parent")) === "A subtask of tsk-0010 · Board: subtasks"
    && !byId("new-subtask-status").disabled, "subtasks: New subtask opens the form with its parent; an admin may open it at once");
  byId("new-subtask-title").value = "Subtasks: the designer's pass";
  stPanel().querySelector("form.new-subtask").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(stPosts.length === 1 && stPosts[0].parent === "tsk-0010" && stPosts[0].status === "proposed"
    && text(stPanel().querySelector(".card-panel-card .subtasks")).includes("Subtasks · 2 of 3 open"),
    "subtasks: the subtask is created under its parent and the parent's counts follow");
  win.Maity.api.post = stPost;
  expect(win.Maity.boardEdit.childProposed({ trust: "member", role: "coder", project: { policy: {} } }) && !win.Maity.boardEdit.childProposed({ trust: "member", role: "coder", project: { policy: { subtasks: "direct" } } })
    && !win.Maity.boardEdit.childProposed({ trust: "owner", role: "coder", project: { policy: {} } }), "subtasks: a member's subtask starts as proposed unless the policy is direct");
  const stMemberBodies = [];
  const stMemberForm = win.Maity.boardEdit.newCardForm({ trust: "member", role: "coder", me: { id: "agt-x" }, members: [], project: { policy: {}, state: "build" } }, [],
    async (body) => { stMemberBodies.push(body); }, () => {}, { id: "tsk-0010", title: "Board: subtasks" });
  const stMemberStatus = stMemberForm.form.all().find((e) => e.id === "new-subtask-status");
  expect(stMemberStatus.disabled && stMemberStatus.value === "proposed" && text(stMemberForm.form).includes("Starts as proposed"),
    "subtasks: for such a member the status is fixed to proposed and says why");
  stMemberForm.form.all().find((e) => e.id === "new-subtask-title").value = "As a member";
  stMemberStatus.value = "open"; // a disabled select a script changed still sends what it may
  stMemberForm.form.dispatch("submit"); await tick();
  expect(JSON.stringify(stMemberBodies) === JSON.stringify([{ title: "As a member", kind: "task", status: "proposed", parent: "tsk-0010" }]),
    "subtasks: such a member's subtask is sent as proposed under its parent, whatever the select says");
  // And the mock answers such a member (?as=agt-c, no tasks:admin) as the hub does: an explicit open is refused, the form's body is taken.
  const stSearch = win.location.search;
  win.location.search = "?as=agt-c";
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  const stOpenTry = await win.Maity.api.post("/projects/maintainer/maity/tasks", { title: "As a member, open", parent: "tsk-0010", status: "open" }).catch((err) => err);
  const stAsForm = await win.Maity.api.post("/projects/maintainer/maity/tasks", stMemberBodies[0]).catch((err) => err);
  const stNoStatus = await win.Maity.api.post("/projects/maintainer/maity/tasks", { title: "As a member, no status", parent: "tsk-0010" }).catch((err) => err);
  const stUnknown = await win.Maity.api.post("/projects/maintainer/maity/tasks", { title: "Under nothing", parent: "tsk-zzzz", status: "proposed" }).catch((err) => err);
  win.location.search = stSearch;
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  expect(stOpenTry.code === "forbidden" && stOpenTry.details.reason === "subtasks_proposed" && stAsForm.status === "proposed" && stAsForm.parent === "tsk-0010"
    && stNoStatus.status === "proposed" && stUnknown.status === 400 && stUnknown.code === "invalid" && stUnknown.details.fields.parent === "unknown_task",
    "subtasks: the mock refuses a member's open subtask, takes the form's proposed one, starts one without a status as proposed, and refuses an unknown parent as the hub does");
  stProto.focus = stFocus; document.activeElement = undefined;
  await go("#/maintainer/maity/inbox");

  // Inviting a person (docs/api.md §3.4): on Members for a human with members:admin; the link once; the list; revoking.
  const ivPosts = [], ivDels = [];
  const ivPost = win.Maity.api.post, ivDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { if (p.includes("invitation")) ivPosts.push([p, b]); return ivPost(p, b); };
  win.Maity.api.del = (p) => { if (p.includes("/invitations/")) ivDels.push(p); return ivDel(p); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick();
  const ivBox = () => main.querySelector("section.invitations");
  const ivItems = () => ivBox().querySelectorAll("li.invite-item").map((li) => li.getAttribute("data-invitation") + ":" + text(li.querySelector(".invite-state")));
  expect(ivBox() && JSON.stringify(byId("invite-trust").querySelectorAll("option").map((o) => o.getAttribute("value"))) === JSON.stringify(["owner", "admin", "member", "guest"])
    && JSON.stringify(ivItems()) === JSON.stringify(["inv-0003:open", "inv-0004:voided", "inv-0002:used", "inv-0001:revoked"])
    && !text(ivBox()).includes("#/invite/"), "invite: Members offers inviting, every trust for an owner; the list with each state, never a link");
  byId("invite-role").value = "reviewer"; byId("invite-address").value = "ben@example.org"; byId("invite-ttl").value = "604800"; byId("invite-note").value = "Welcome.";
  ivBox().querySelector("form.invite-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(byId("invite-via-join") && byId("invite-via-join").checked && text(ivBox()).includes("Link via join.example.org"),
    "invite: where the hub names a join host, Link via <join host> is offered, on by default (§3.4)");
  expect(JSON.stringify(ivPosts[0]) === JSON.stringify(["/projects/maintainer/maity/invitations", { trust: "member", role: "reviewer", ttl_seconds: 604800, address: "ben@example.org", note: "Welcome.", via: "join" }])
    && /^https:\/\/join\.example\.org\/i\/fx\d{20}$/.test(byId("invite-url").value) && text(ivBox().querySelector(".invite-issued")).includes("This link is shown only now")
    && btn(ivBox(), "Copy") && ivItems().length === 5 && ivItems()[0].endsWith(":open") && text(ivBox().querySelectorAll("li.invite-item")[0]).includes("via join.example.org"),
    "invite: created via the join host, the link shown once with Copy, the list grows and says which link went out");
  // Off: the link on this hub's own address.
  byId("invite-via-join").checked = false;
  ivBox().querySelector("form.invite-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(ivPosts[1] && ivPosts[1][1].via === "public" && /#\/invite\/fx\d{20}$/.test(byId("invite-url").value)
    && text(ivBox().querySelectorAll("li.invite-item")[0]).includes("on this hub's address"),
    "invite: Link via unticked sends via public, and the link is on the hub's own address");
  byId("invite-via-join").checked = true;
  // A hub without a join host (join_url null): no choice, no via sent.
  // The form takes the session the page read already (M.api.session), no new read of it.
  const ivSessionGets = [], ivGetAll = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p === "/auth/session") ivSessionGets.push(p); return ivGetAll(p); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick();
  // The app reads the session once per page drawn (two here); the form adds none.
  expect(byId("invite-via-join") && ivSessionGets.length === 2, "invite: the form uses the session the page read, without reading it again (" + ivSessionGets.length + ")");
  win.Maity.api.get = ivGetAll;
  const ivSession = win.Maity.api.session;
  win.Maity.api.session = () => Object.assign({}, ivSession(), { join_url: null });
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick();
  const ivNoHost = ivPosts.length;
  ivBox().querySelector("form.invite-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(!byId("invite-via-join") && ivPosts[ivNoHost] && !("via" in ivPosts[ivNoHost][1]) && byId("invite-url"),
    "invite: without a join host there is no choice and no via; the hub picks the link");
  win.Maity.api.session = ivSession;
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick();
  // The note's limit is 1 KiB of UTF-8, not 1024 characters: 400 three-byte characters are too long.
  byId("invite-note").value = "€".repeat(400);
  const ivBefore = ivPosts.length;
  ivBox().querySelector("form.invite-form").dispatch("submit"); await tick();
  expect(ivPosts.length === ivBefore && text(ivBox()).includes("the note is longer than 1 KiB"), "invite: a note over 1 KiB in bytes is said before sending");
  byId("invite-note").value = "";
  btn(ivBox().querySelectorAll("li.invite-item").find((li) => li.getAttribute("data-invitation") === "inv-0003"), "Revoke").click(); for (let k = 0; k < 6; k++) await tick();
  expect(ivDels[0] === "/projects/maintainer/maity/invitations/inv-0003" && ivItems().includes("inv-0003:revoked") && text(ivBox()).includes("Revoked; the link no longer works."),
    "invite: an open invitation revoked, said so");
  // A member without members:admin sees no inviting.
  const ivGet = win.Maity.api.get;
  win.Maity.api.get = (p) => ivGet(p).then((v) => (p === "/me" ? Object.assign({}, v, { projects: v.projects.map((x) => Object.assign({}, x, { trust: "member", role: "coder" })) }) : v));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 6; k++) await tick();
  expect(!ivBox(), "invite: no inviting for a member without members:admin");
  win.Maity.api.get = ivGet;
  // The invitation page signed in: one button; accepted, the way into the project; the hub's refusals in its words.
  await go("#/invite/open-xxxxxxxxxxxxxxxx1"); for (let k = 0; k < 6; k++) await tick();
  const ivArticle = () => main.querySelector("article.invite");
  btn(ivArticle(), "Join Maity as Maintainer").click(); for (let k = 0; k < 6; k++) await tick();
  expect(ivPosts.some(([p]) => p === "/invitations/open-xxxxxxxxxxxxxxxx1/accept") && text(ivArticle()).includes("You are a member of Maity now.")
    && ivArticle().querySelectorAll("a").some((a) => a.getAttribute("href") === "#/maintainer/maity/inbox"), "invite: accepted, the project opens from here");
  const ivSaid = [];
  for (const tok of ["mismatch-xxxxxxxxxxxx4", "member-xxxxxxxxxxxxxx5", "void-xxxxxxxxxxxxxxxx6", "closed-xxxxxxxxxxxxxx7", "pending-xxxxxxxxxxxxx8"]) {
    await go("#/invite/" + tok); for (let k = 0; k < 6; k++) await tick();
    ivArticle().querySelectorAll("button").find((b) => text(b).startsWith("Join ")).click(); for (let k = 0; k < 4; k++) await tick();
    ivSaid.push(text(ivArticle().querySelector(".send-status")));
  }
  expect(JSON.stringify(ivSaid) === JSON.stringify([
    "Not joined: this invitation is for another address (invitation_address_mismatch)", "Not joined: the request does not validate (already_member)",
    "Not joined: the person who invited you can no longer give this role (invitation_void)", "Not joined: the project is closed (project_closed)",
    "Not joined: your account waits for approval (account_pending)"]), "invite: each refusal said in the hub's words with its reason " + JSON.stringify(ivSaid));
  // Not you? Sign out (H on #461): signed out, the same invitation again, with its ways in; never the root.
  const soPost = win.Maity.api.post, soEnd = win.Maity.api.endSession, soGet = win.Maity.api.get;
  let soOut = false;
  win.Maity.api.post = (p, b) => (p === "/auth/logout" ? (soOut = true, Promise.resolve({})) : soPost(p, b));
  win.Maity.api.endSession = () => {};
  win.Maity.api.get = (p) => (soOut && (p === "/auth/session" || p === "/me") ? Promise.reject(new win.Maity.api.ApiError("signed out", 401, p, "unauthenticated")) : soGet(p));
  await go("#/invite/void-xxxxxxxxxxxxxxxx6"); for (let k = 0; k < 6; k++) await tick();
  btn(ivArticle(), "Not you? Sign out").click(); for (let k = 0; k < 8; k++) await tick();
  expect(soOut && win.location.hash === "#/invite/void-xxxxxxxxxxxxxxxx6" && ivArticle()
    && ivArticle().querySelectorAll("a").some((a) => text(a) === "Sign in to accept") && !btn(ivArticle(), "Not you? Sign out"),
    "invite: Not you? Sign out signs out and shows the same invitation, signed out " + win.location.hash);
  win.Maity.api.post = soPost; win.Maity.api.endSession = soEnd; win.Maity.api.get = soGet;
  if (win.Maity.notify && win.Maity.notify.resume) win.Maity.notify.resume();
  win.Maity.api.post = ivPost; win.Maity.api.del = ivDel;
  // A next that is no dashboard route of this page is no next (§2.6.5): signed in, #/login goes to the start instead.
  const nxStart = (await win.Maity.api.get("/me")).projects.length === 1 ? "#/maintainer/maity/inbox" : "#/all";
  const nxLanded = [];
  // A hub path (§16.11) is no next either: /api/…, /assets/…, /join/…
  for (const bad of ["//evil.example/x", "javascript:alert(1)", "/..//x", "//evil", "/a#b", "https://evil.example/x", "/ space", "/api/v1/me", "/assets/js/app.js", "/join/abc"]) {
    await go("#/login?next=" + encodeURIComponent(bad)); for (let k = 0; k < 4; k++) await tick();
    nxLanded.push(win.location.hash);
  }
  await go("#/login?next=" + encodeURIComponent("/maintainer/maity/board")); for (let k = 0; k < 4; k++) await tick();
  expect(nxLanded.every((x) => x === nxStart) && win.location.hash === "#/maintainer/maity/board",
    "sign-in: a next that is not a dashboard route of this page is ignored, a good one is followed " + JSON.stringify(nxLanded));
  // Signed in, #/register goes on to its next: there is nothing to register.
  await go("#/register?next=" + encodeURIComponent("/maintainer/maity/members")); for (let k = 0; k < 4; k++) await tick();
  expect(win.location.hash === "#/maintainer/maity/members", "register: signed in, it goes on to its next");
  // An account waiting for approval (§2.7.5) sees that page and nothing else.
  win.Maity.api.get = (p) => ivGet(p).then((v) => (p === "/me" ? Object.assign({}, v, { member: Object.assign({}, v.member, { account_status: "pending" }), projects: [] }) : v));
  await go("#/all"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Your account waits for the operator's approval") && btn(main, "Sign out") && !header.querySelector("nav.switcher")
    && win.location.hash === "#/account/pending", "pending: an account waiting for approval sees that at /account/pending, and can sign out");
  // The invitation page for such an account: no Join, the invitation waits.
  await go("#/invite/only-xxxxxxxxxxxxxxxx2"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector("article.invite") && !main.querySelector("article.invite").querySelectorAll("button").some((b) => text(b).startsWith("Join "))
    && text(main.querySelector("article.invite")).includes("Your account waits for the operator's approval. The invitation waits for you"),
    "invite: an account waiting for approval sees the invitation wait, no Join");
  win.Maity.api.get = ivGet;
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();

  // A session that ends under the page (expired, revoked, ended elsewhere): the first 401 on a call that
  // needs it stops the background and shows sign-in with a note; nothing is asked after that; signing in returns.
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const seGet = win.Maity.api.get, seGetAll = win.Maity.api.getAll;
  const seCalls = [];
  // The fixture hub forgets the session, as an expiry or a revocation elsewhere would.
  await win.Maity.api.post("/auth/logout");
  const sePost = win.Maity.api.post, seDel = win.Maity.api.del;
  const seEpoch = win.Maity.sessionEpoch || 0;
  win.Maity.notify.state.settings = { browser: { enabled: true, kinds: { chat: true }, content: { chat: true } } };
  win.Maity.api.get = (p) => { seCalls.push(p); return seGet(p); };
  win.Maity.api.getAll = (p) => { seCalls.push(p); return seGetAll(p); };
  win.Maity.api.post = (p, b) => { seCalls.push("POST " + p); return sePost(p, b); };
  win.Maity.api.del = (p) => { seCalls.push("DELETE " + p); return seDel(p); };
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(byId("login-handle") && main.querySelector(".session-ended") && text(main.querySelector(".session-ended")).includes("Your session has ended")
    && win.location.hash === "#/maintainer/maity/board" && win.Maity.notify.state.settings === null && !win.Maity.notify.running(),
    "session: the first 401 under the page shows sign-in with a note, the route kept; the browser notifications' settings go with it");
  const seAfter = seCalls.length;
  await fireIntervals(); await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(seCalls.length === seAfter, "session: after it ended nothing more is asked " + JSON.stringify(seCalls.slice(seAfter)));
  byId("login-handle").value = "maintainer"; byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); for (let k = 0; k < 8; k++) await tick();
  expect(!byId("login-handle") && main.querySelector("section.view-board") && win.location.hash === "#/maintainer/maity/board" && !main.querySelector(".session-ended"),
    "session: signing in again returns to the same route");
  // A late 401 of the old session ends the new one not; a 401 on a session's own /auth/ call ends it.
  win.Maity.onSessionEnded("/me", seEpoch); for (let k = 0; k < 4; k++) await tick();
  expect(!byId("login-handle") && main.querySelector("section.view-board"), "session: a late 401 from the session before ends nothing");
  win.Maity.api.post = sePost; win.Maity.api.del = seDel;
  await win.Maity.api.post("/auth/logout");
  await win.Maity.api.get("/auth/sessions").catch(() => null); for (let k = 0; k < 4; k++) await tick();
  expect(byId("login-handle") && main.querySelector(".session-ended"), "session: a 401 on the session's own /auth/sessions ends it too");
  byId("login-handle").value = "maintainer"; byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); for (let k = 0; k < 8; k++) await tick();
  win.Maity.api.get = seGet; win.Maity.api.getAll = seGetAll;

  // Which 401s say a session ended: the visitor's calls, with or without a query, never; the session's own always.
  const ppPublic = ["/auth/session", "/auth/login", "/auth/device-login?wait=0", "/auth/device-login/complete", "/auth/email-code", "/auth/methods",
    "/legal", "/openapi.json", "/invitations/open-xxxxxxxxxxxxxxxx1"];
  const ppSession = ["/auth/sessions", "/auth/sessions?ended=true", "/auth/password", "/auth/device-codes", "/auth/second-factor", "/me", "/me/notifications?limit=0",
    "/legal/x", "/auth/login-other", "/invitations/abc/accept", "/projects/maintainer/maity/members", "/swarm/maintainer/maity?days=30"];
  const ppWrong = ppPublic.filter((p) => !win.Maity.api.isPublicPath(p)).concat(ppSession.filter((p) => win.Maity.api.isPublicPath(p)));
  expect(!ppWrong.length, "session: a visitor's call is public with any query, a session's own call never " + JSON.stringify(ppWrong));

  // Notifications (docs/api.md §18): the bell, the counts, browser notifications.
  await go("#/maintainer/maity/inbox");
  const bellBtn = () => header.querySelector("button.bell");
  const tabCountOf = (name) => { const a = header.querySelectorAll("nav.views a").find((x) => x.textContent.startsWith(name)); const c = a && a.querySelector(".count"); return c ? c.textContent : null; };
  // Unread on the bell: every kind but the open requests (the inbox shows those); a sign-in alert counts.
  expect(bellBtn() && bellBtn().getAttribute("aria-label") === "3 new notifications" && text(bellBtn()).includes("3")
    && tabCountOf("Chat") === "1", "notifications: the bell says how many are new; the chat tab its unread chats");
  // The header's right block: Chat, Notifications, the gear, the profile; the Chat badge is the hub's unread chat messages.
  const chatBtn = () => header.querySelector("a.chat-button");
  const meOrder = header.querySelector(".me").childNodes.map((el) => (el.getAttribute("class") || "").split(" ").concat(el.tagName ? [el.tagName.toLowerCase()] : []).join(" "));
  expect(chatBtn() && chatBtn().getAttribute("href") === "#/chats" && chatBtn().getAttribute("aria-label") === "1 unread chat message"
    && text(chatBtn().querySelector(".count")) === "1" && chatBtn().querySelector(".count").getAttribute("aria-hidden") === "true"
    && /chat-button/.test(meOrder[0]) && /lead-button/.test(meOrder[1]) && /bell-box/.test(meOrder[2]) && header.querySelector(".me").childNodes.length === 5,
    "header: Chat, Lead, then Notifications, the gear and the profile; the chat badge a number, its words in the label " + JSON.stringify(meOrder));
  // The Lead button (the maintainer's decision, req-4rpd7vqb6xe3): Chat stays the way to every chat; Lead reaches
  // the one lead at once (here the owner's own admin agent, on a hub without coordinator data).
  const leadBtn = () => header.querySelector(".lead-button");
  expect(leadBtn() && leadBtn().tagName === "A" && leadBtn().getAttribute("href") === "#/maintainer/maity/chat/agt-a"
    && leadBtn().getAttribute("aria-label") === "Talk to the lead: Agent A" && !header.querySelector(".lead-chat") && !main.querySelector(".lead-chat"),
    "header: one lead, the Lead button opens that chat; no lead strip anywhere");
  // The counts' refresh redraws Chat on the same route: 1 to 0 drops the badge, 0 to 3 brings it back.
  const rcGet = win.Maity.api.get;
  let rcChat = 0;
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications?limit=0")
    ? rcGet(p).then((r) => ({ ...r, counts: { ...r.counts, chat: rcChat } })) : rcGet(p));
  await fireIntervals(); for (let k = 0; k < 3; k++) await tick();
  expect(chatBtn().getAttribute("aria-label") === "Chats" && !chatBtn().querySelector(".count"), "header: a refresh to no unread chat messages drops Chat's badge on the same route");
  rcChat = 3;
  await fireIntervals(); for (let k = 0; k < 3; k++) await tick();
  expect(chatBtn().getAttribute("aria-label") === "3 unread chat messages" && text(chatBtn().querySelector(".count")) === "3"
    && header.querySelectorAll("a.chat-button").length === 1, "header: a refresh to new chat messages brings Chat's badge back, one button");
  win.Maity.api.get = rcGet;
  await fireIntervals(); for (let k = 0; k < 3; k++) await tick();
  await go("#/chats"); for (let k = 0; k < 4; k++) await tick();
  const chLinks = main.querySelectorAll(".chat-list a.conv");
  expect(plainTitle() === "Chats · Maity" && main.querySelector(".chat-layout") && !main.querySelector(".chat-layout.open")
    && chLinks.length === 7 && chLinks.slice(0, 2).every((a) => a.className === "conv unread with-project") && !chLinks.slice(2).some((a) => a.className.includes("unread"))
    && chLinks[0].getAttribute("href") === "#/chats/maintainer/maity/cnv-0007" && text(chLinks[0]).endsWith("in Maity")
    && chLinks[1].getAttribute("href") === "#/chats/maintainer/maity/agt-a" && text(chLinks[1]).includes("1 unread")
    && chLinks[6].getAttribute("href") === "#/chats/maintainer/sample/agt-s1" && text(chLinks[6]).endsWith("in Sample shop")
    && text(main).includes("Pick a conversation.") && header.querySelector("a.chat-button").getAttribute("aria-current") === "page",
    "chats: the Chat tab's layout with every project's chats, unread first, then the newest, each with its project");
  // The project as a mark after the who line, its name on hover (no line of its own).
  const chMark = (a) => a.querySelector(".conv-sub .conv-project");
  expect(chLinks.every((a) => chMark(a) && chMark(a).querySelector(".project-mark")) && chMark(chLinks[0]).getAttribute("title") === "Maity"
    && chMark(chLinks[6]).getAttribute("title") === "Sample shop",
    "chats: each row's project is a mark after the who line, its name on hover");
  // One read across projects (§9.3, GET /me/conversations), not one per project; a hub without it is read project by project.
  const mcReads = [];
  const mcGetAll = win.Maity.api.getAll, mcMissing = win.Maity.api.missingRoute;
  win.Maity.api.getAll = (p) => { mcReads.push(p); return mcGetAll(p); };
  await go("#/all"); await go("#/chats"); for (let k = 0; k < 4; k++) await tick();
  expect(mcReads.filter((p) => p === "/me/conversations?observed=true").length === 1 && !mcReads.some((p) => /^\/projects\/.+\/conversations\?/.test(p))
    && main.querySelectorAll(".chat-list a.conv").length === 7,
    "chats: one read across projects lists every project's chats");
  mcReads.length = 0;
  win.Maity.api.getAll = (p) => { mcReads.push(p); return p.startsWith("/me/conversations") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found")) : mcGetAll(p); };
  win.Maity.api.missingRoute = (err, method, path) => Promise.resolve(path === "/me/conversations" || mcMissing(err, method, path));
  await go("#/all"); await go("#/chats"); for (let k = 0; k < 6; k++) await tick();
  expect(mcReads.filter((p) => /^\/projects\/.+\/conversations\?observed=true$/.test(p)).length === 2 && main.querySelectorAll(".chat-list a.conv").length === 7
    && !main.querySelector(".chat-list-pane .send-status.failed"),
    "chats: a hub without the list across projects is read project by project");
  win.Maity.api.getAll = mcGetAll; win.Maity.api.missingRoute = mcMissing; win.Maity.api.forgetRoutes();
  await go("#/all"); await go("#/chats"); for (let k = 0; k < 4; k++) await tick();
  // Opening one keeps the global view: its messages and composer in place, the list beside it, its unread gone.
  const gxGets = [], gxPosts = [];
  const gxGet = win.Maity.api.get, gxGetAll = win.Maity.api.getAll, gxPost = win.Maity.api.post, gxPatch = win.Maity.api.patch;
  win.Maity.api.get = (p) => { gxGets.push(p); return gxGet(p); };
  win.Maity.api.getAll = (p) => { gxGets.push(p); return gxGetAll(p); };
  win.Maity.api.post = (p, b) => { if (p.includes("/conversations/")) gxPosts.push([p, b]); return gxPost(p, b); };
  await go(chLinks[1].getAttribute("href")); for (let k = 0; k < 8; k++) await tick(); await new Promise((r) => setTimeout(r, 5));
  const gxConv = (href) => main.querySelectorAll(".chat-list a.conv").find((a) => a.getAttribute("href") === href);
  expect(win.location.hash === "#/chats/maintainer/maity/agt-a" && main.querySelector(".chat-layout.open") && main.querySelector("section.chat-pane")
    && byId("chat-text") && main.querySelectorAll(".chat-list a.conv").length === 7 && gxConv("#/chats/maintainer/maity/agt-a").getAttribute("aria-current") === "page"
    && !gxConv("#/chats/maintainer/maity/agt-a").className.includes("unread") && main.querySelector(".chat-back").getAttribute("href") === "#/chats"
    && !gxGets.some((p) => p.includes("/events")), "chats: a conversation opens in the global view, the list beside it, read, and no project feed is opened");
  byId("chat-text").value = "Across projects"; main.querySelector("form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gxPosts[0]) === JSON.stringify(["/projects/maintainer/maity/conversations/agt-a/messages", { body: "Across projects" }])
    && text(main.querySelector("ol.messages")).includes("Across projects"), "chats: sending from the global view posts to the conversation's project");
  // The notifications stream drives it: a burst is one re-read of the lists and one fetch of the open conversation.
  const gxBefore = gxGets.length;
  for (let k = 0; k < 4; k++) win.Maity.notify.changed();
  await tick();
  expect(gxGets.length === gxBefore, "chats: stream events wait to settle");
  await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 6; k++) await tick();
  const gxAfter = gxGets.slice(gxBefore);
  // (The open chat reads the list once more after its fetch, as in a project; a message still being delivered is checked.)
  const gxLists = gxAfter.filter((p) => p.endsWith("/conversations?observed=true"));
  expect(gxLists.length <= 4 && ["maity", "sample"].every((sl) => gxLists.filter((p) => p.includes("/projects/maintainer/" + sl + "/")).length <= 2)
    && gxAfter.filter((p) => /\/conversations\/agt-a\/messages\?after=\d+$/.test(p)).length === 1
    && !gxAfter.some((p) => p.includes("/events")), "chats: a burst of stream events is one round of list reads and one fetch of the open chat " + JSON.stringify(gxAfter));
  // What the stream cannot say is read again on its nudge: a removal shows as removed in the open chat.
  const gxLastSeq = Number(main.querySelectorAll("ol.messages li.msg").map((li) => li.getAttribute("data-seq")).filter(Boolean).sort((a, b) => a - b)[0]);
  await gxPost("/projects/maintainer/maity/events/" + gxLastSeq + "/redact", { reason: "wrong chat" });
  win.Maity.notify.changed(); await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 6; k++) await tick();
  const gxRemoved = main.querySelectorAll("ol.messages li.msg").find((li) => li.getAttribute("data-seq") === String(gxLastSeq));
  expect(gxRemoved && gxRemoved.querySelector(".msg-redacted") && !gxRemoved.querySelector(".md"),
    "chats: a message removed elsewhere shows as removed in the open chat after the stream's nudge");
  // Bounded: each nudge reads one page of what is shown, walking back page by page, one delivery page at most,
  // and never a second update alongside a slow one.
  const gxCalls = [];
  let gxInflight = 0, gxMaxInflight = 0;
  const gxHold = [];
  win.Maity.api.get = (p) => {
    gxCalls.push(p);
    if (/\/conversations\/agt-a\/messages\?before=/.test(p) && !p.includes("before=5000")) {
      return Promise.resolve({ items: Array.from({ length: 200 }, (_, i) => ({ seq: 5000 + i, from: "agt-a", body: "x", sent_at: "2026-10-21T13:00:00Z", attachments: [] })), cursor: 5199 });
    }
    if (/\/conversations\/agt-a\/messages\?after=\d+$/.test(p)) {
      gxInflight++; gxMaxInflight = Math.max(gxMaxInflight, gxInflight);
      return new Promise((resolve) => gxHold.push(() => { gxInflight--; resolve(gxGet(p)); }));
    }
    return gxGet(p);
  };
  win.Maity.api.getAll = (p) => {
    gxCalls.push(p);
    if (!p.endsWith("/conversations?observed=true")) return gxGetAll(p);
    gxInflight++; gxMaxInflight = Math.max(gxMaxInflight, gxInflight);
    return new Promise((resolve) => gxHold.push(() => { gxInflight--; resolve(gxGetAll(p)); }));
  };
  const gxStart = gxCalls.length;
  win.Maity.notify.changed(); await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 4; k++) await tick();
  win.Maity.notify.changed(); await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 4; k++) await tick();
  win.Maity.notify.changed(); await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 4; k++) await tick();
  const gxTick = fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(gxMaxInflight <= 1, "chats: slow reads never overlap: one update in flight, the rest waits for it (" + gxMaxInflight + " held reads at once)");
  for (let round = 0; round < 12 && gxHold.length; round++) { gxHold.splice(0).forEach((f) => f()); for (let k = 0; k < 6; k++) await tick(); }
  win.Maity.api.getAll = (p) => { gxCalls.push(p); return gxGetAll(p); };
  gxHold.splice(0).forEach((f) => f());
  await gxTick;
  const gxBefores = gxCalls.slice(gxStart).filter((p) => p.includes("/conversations/agt-a/messages?before=")).map((p) => /before=(\d+)/.exec(p)[1]);
  const gxDelivery = gxCalls.slice(gxStart).filter((p) => /\/conversations\/agt-a\/messages\?after=\d+&limit=200$/.test(p));
  expect(gxBefores.length >= 2 && gxBefores[1] === "5000" && gxBefores.length <= 3,
    "chats: the open chat's re-read walks back one page per pass, from where it stopped " + JSON.stringify(gxBefores));
  expect(gxDelivery.length <= gxBefores.length, "chats: at most one delivery page per pass " + gxDelivery.length);
  win.Maity.api.get = (p) => { gxGets.push(p); return gxGet(p); };
  win.Maity.api.getAll = (p) => { gxGets.push(p); return gxGetAll(p); };
  // Every 30 seconds the members are read too: a new name shows in the list.
  const gxMembers = gxGetAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members"
    ? gxMembers(p).then((r) => ({ ...r, items: r.items.map((m) => (m.id === "agt-b" ? { ...m, display_name: "Agent B renamed" } : m)) })) : gxMembers(p));
  byId("chat-text").value = "a draft that stays";
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(main.querySelector(".chat-list")).includes("Agent B renamed") && byId("chat-text").value === "a draft that stays",
    "chats: the 30-second refresh reads the members again, the draft stays");
  win.Maity.api.getAll = (p) => { gxGets.push(p); return gxGetAll(p); };
  byId("chat-text").value = "";
  // A group chat of another project opens the same way, in its project's context.
  await go("#/chats/maintainer/maity/cnv-0007"); for (let k = 0; k < 8; k++) await tick();
  expect(main.querySelector(".chat-layout.open") && main.querySelectorAll(".chat-list a.conv").length === 7 && text(main).includes("Release 0.2 go/no-go")
    && main.querySelector(".chat-back") && main.querySelector(".chat-back").getAttribute("href") === "#/chats", "chats: a group chat opens in the global view too");
  // A rename elsewhere reaches its open pane on the stream's nudge.
  await gxPatch("/projects/maintainer/maity/conversations/cnv-0007", { title: "Release 0.2: go" });
  win.Maity.notify.changed(); await new Promise((r) => setTimeout(r, 450)); for (let k = 0; k < 8; k++) await tick();
  expect(text(main.querySelector("section.group-chat")).includes("Release 0.2: go"), "chats: a group chat renamed elsewhere shows its new title after the stream's nudge");
  await go("#/chats/someone/nowhere/agt-a"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("No project of yours named someone/nowhere."), "chats: an unknown project is said");
  // In the global chat an agent's message names the projects it is in, by logo with the name on
  // hover: only the reader's projects whose members name it; a human's message and a project's own chat none.
  const gpIn = () => main.querySelectorAll("li.msg.in").filter((li) => !li.classList.contains("grouped"));
  const gpMarks = (li) => li.querySelectorAll(".msg-project").map((s) => s.getAttribute("title"));
  await go("#/chats/maintainer/maity/agt-a"); for (let k = 0; k < 8; k++) await tick();
  expect(gpIn().length && gpIn().every((li) => JSON.stringify(gpMarks(li)) === JSON.stringify(["Maity"]))
    && gpIn()[0].querySelector(".msg-project .project-mark") && text(gpIn()[0].querySelector(".msg-projects")).includes("in Maity"),
    "global chat: an agent in one of the reader's projects shows that one project's mark, its name on hover");
  win.Maity.api.getAll = (p) => gxGetAll(p).then((r) => (p === "/projects/maintainer/sample/members"
    ? Object.assign({}, r, { items: r.items.concat([{ id: "agt-a", kind: "agent", handle: "agent-a", display_name: "Agent A", trust: "member", role: "coder", presence: "online" }]) }) : r));
  await go("#/chats/maintainer/maity/agt-a"); for (let k = 0; k < 8; k++) await tick();
  expect(gpIn().length && JSON.stringify(gpMarks(gpIn()[0])) === JSON.stringify(["Maity", "Sample shop"]),
    "global chat: an agent in two of the reader's projects shows both, in the switcher's order");
  win.Maity.api.getAll = gxGetAll;
  expect(!main.querySelectorAll("li.msg.out .msg-projects").length, "global chat: the reader's own messages name no project");
  await go("#/maintainer/maity/chat/agt-a"); for (let k = 0; k < 8; k++) await tick();
  expect(main.querySelectorAll("li.msg.in").length && !main.querySelector(".msg-projects"), "global chat: a project's own chat names no projects");
  win.Maity.api.get = gxGet; win.Maity.api.getAll = gxGetAll; win.Maity.api.post = gxPost;

  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 2; k++) await tick();
  const nPosts = [];
  const nPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (p.startsWith("/me/notifications")) nPosts.push([p, b]); return nPost(p, b); };
  const nGets = [];
  const nGet0 = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p.startsWith("/me/notifications")) nGets.push(p); return nGet0(p); };
  bellBtn().click(); await tick(); await tick();
  win.Maity.api.get = nGet0;
  expect(nGets[0] === "/me/notifications?limit=20", "notifications: the bell reads the latest 20 when it opens");
  const bellPanel = () => header.querySelector(".bell-panel");
  const bellItem = (title) => bellPanel().querySelectorAll(".bell-items li").find((li) => text(li).includes(title));
  const bellLinks = bellPanel().querySelectorAll(".bell-items a").map((a) => a.getAttribute("href"));
  expect(!bellPanel().hidden && bellBtn().getAttribute("aria-expanded") === "true"
    && JSON.stringify(bellLinks) === JSON.stringify(["#/admin", "#/account/sessions", "#/maintainer/maity/tasks/tsk-0004", "#/maintainer/maity/chat/agt-a", "#/all", "#/maintainer/sample/inbox/req-s001"])
    && bellPanel().querySelectorAll(".bell-items li.unread").length === 5 && text(bellPanel()).includes("Mentions 1"),
    "notifications: the bell lists the latest, each linking to where it happened by its target, unread ones marked");
  // Escape closes it with the focus still on the bell.
  bellBtn().dispatch("keydown", { key: "Escape" });
  expect(bellPanel().hidden && bellBtn().getAttribute("aria-expanded") === "false", "notifications: Escape on the bell closes the panel");
  bellBtn().click(); await tick(); await tick();
  const maityBefore = Number(chipCount("Maity"));
  bellItem("Agent A in agent-a").querySelector("a").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(nPosts[0]) === JSON.stringify(["/me/notifications/read", { ids: ["ntf-4237"] }]) && bellBtn().getAttribute("aria-label") === "2 new notifications"
    && Number(chipCount("Maity")) === maityBefore - 1, "notifications: opening an item marks it read, and the counts follow");
  // A sign-in alert is never confirmed by opening it (§2.6.5, §18.3).
  bellBtn().click(); await tick(); await tick();
  expect(text(bellPanel()).includes("stays unread: opening it here does not confirm it") && text(bellPanel()).includes("This was me under Sessions"),
    "notifications: the panel says a sign-in alert stays unread until This was me under Sessions");
  bellItem("New sign-in").querySelector("a").click(); for (let k = 0; k < 4; k++) await tick();
  expect(nPosts.length === 1 && bellBtn().getAttribute("aria-label") === "2 new notifications", "notifications: opening a sign-in alert marks nothing");
  bellBtn().click(); await tick(); await tick();
  btn(bellPanel(), "Mark all read").click(); for (let k = 0; k < 4; k++) await tick();
  const maityOpen = (await win.Maity.api.get("/me")).projects.find((x) => x.slug === "maity").open_requests;
  expect(JSON.stringify(nPosts[1]) === JSON.stringify(["/me/notifications/read", { up_to: "4239.8" }]) && bellBtn().getAttribute("aria-label") === "1 new notification"
    && Number(chipCount("Maity")) === maityOpen,
    "notifications: Mark all read marks up to the bell's position, never the sign-in alert; the project's count is its open requests again");
  bellBtn().click(); await tick(); await tick();
  expect(!btn(bellPanel(), "Mark all read") && bellItem("New sign-in").className === "unread", "notifications: with only a sign-in alert left, no Mark all read");
  bellBtn().dispatch("keydown", { key: "Escape" });
  win.Maity.api.post = nPost;
  // A hub without notifications: no bell, the counts from /me as before.
  const nGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : nGet(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox");
  const bellLink = header.querySelectorAll("a.bell").find((a) => a.getAttribute("href") === "#/all");
  expect(!bellBtn() && bellLink && bellLink.getAttribute("aria-label") === "Notifications" && !bellLink.querySelector(".count")
    && chatBtn() && chatBtn().getAttribute("aria-label") === "Chats" && !chatBtn().querySelector(".count")
    && !text(main).includes("Could not read your notifications") && !tabCountOf("Chat"),
    "notifications: a hub without them keeps the bell as a link to everything waiting and Chat, both without a count, and no error");
  // Refreshes on such a hub replace the bell in place: one bell, the order kept.
  for (let k = 0; k < 3; k++) { await fireIntervals(); await tick(); }
  const fbOrder = header.querySelector(".me").childNodes.map((el) => el.getAttribute("class") || "");
  expect(header.querySelectorAll("a.bell").filter((a) => a.getAttribute("href") === "#/all").length === 1
    && /chat-button/.test(fbOrder[0]) && fbOrder.filter((c) => c === "bell-box").length === 1 && header.querySelectorAll(".lead-button").length <= 1,
    "notifications: refreshes without them keep one bell, one Lead, Chat first " + JSON.stringify(fbOrder));
  const nSettingsAsked = [];
  const nGetNone = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p === "/me/notification-settings") nSettingsAsked.push(p); return nGetNone(p); };
  win.Notification = function () {};
  win.Notification.permission = "default";
  await go("#/account/notifications");
  expect(text(main).includes("This hub has no notification settings yet.") && !nSettingsAsked.length, "notifications: the account page does not ask such a hub for settings");
  delete win.Notification;
  win.Maity.api.get = nGetNone;
  // A hub that has them again: this page had noted them as absent and asked no more.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : nGet(p));
  await go("#/maintainer/maity/board");
  expect(text(main).includes("Could not read your notifications: down") && !main.querySelector(".error"), "notifications: a failed read is said, the page stays");
  win.Maity.api.get = nGet;
  // Browser notifications: asked only on the human's click, shown per kind, never for one's own.
  const shownNotes = [];
  let asked = 0;
  win.Notification = function (title, opts) { shownNotes.push([title, opts]); this.close = () => {}; };
  win.Notification.permission = "default";
  win.Notification.requestPermission = async () => { asked += 1; win.Notification.permission = "granted"; return "granted"; };
  await go("#/account/notifications");
  expect(byId("notify-browser") && !byId("notify-browser").checked && asked === 0 && text(main).includes("has not been asked yet")
    && byId("notify-kind-chat").attrs.disabled !== undefined, "notifications: the settings, off, the browser not asked on opening them");
  const ksKinds = () => main.querySelectorAll("input").filter((i) => (i.getAttribute("id") || "").startsWith("notify-kind-")).map((i) => i.getAttribute("id").slice(12));
  expect(JSON.stringify(ksKinds()) === JSON.stringify(["inbox", "chat", "mention", "security"]),
    "notifications: the switches are the four kinds a human reacts to " + JSON.stringify(ksKinds()));
  // Settings stored before 2026-10-26 may still name removed kinds (§18.4): no switch for them; a kind the hub does not list, none either.
  const ksGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me/notification-settings"
    ? ksGet(p).then((x) => ({ ...x, kinds: ["inbox", "chat", "mention", "card", "ticker"], browser: { ...x.browser, kinds: { ...x.browser.kinds, card: true, ticker: false } } })) : ksGet(p));
  win.Maity.notify.state.settings = null;
  await go("#/all"); await go("#/account/notifications");
  expect(JSON.stringify(ksKinds()) === JSON.stringify(["inbox", "chat", "mention"]), "notifications: old kinds in stored settings get no switch, an unlisted kind none " + JSON.stringify(ksKinds()));
  win.Maity.api.get = ksGet; win.Maity.notify.state.settings = null;
  await go("#/all"); await go("#/account/notifications");
  const fresh = [
    { id: "ntf-5001", seq: 5001, kind: "chat", at: "2026-10-22T15:00:00Z", project: { slug: "maity", full_name: "maintainer/maity", name: "Maity" }, actor: { member_id: "agt-a" }, title: "Agent A in agent-a", target: { type: "conversation", id: "agt-a" }, read: false, redacted: false, content: "secret text" },
    { id: "ntf-5002", seq: 5002, kind: "card", at: "2026-10-22T15:01:00Z", project: { slug: "maity", full_name: "maintainer/maity", name: "Maity" }, actor: { member_id: "agt-b" }, title: "tsk-0004 …: reported", target: { type: "task", id: "tsk-0004" }, read: false, redacted: false },
    { id: "ntf-5003", seq: 5003, kind: "mention", at: "2026-10-22T15:02:00Z", project: { slug: "maity", full_name: "maintainer/maity", name: "Maity" }, actor: { member_id: "hum-maintainer" }, title: "own", target: { type: "task", id: "tsk-0004" }, read: false, redacted: false },
  ];
  const polls = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/me/notifications?after=")) { polls.push(p); const items = fresh.splice(0); return Promise.resolve({ counts: {}, items, next_cursor: null }); }
    return nGet(p);
  };
  byId("notify-browser").checked = true; byId("notify-browser").dispatch("change"); for (let k = 0; k < 8; k++) await tick();
  expect(asked === 1 && byId("notify-browser").checked && text(main).includes("Browser notifications are on.") && text(main).includes("This browser shows them."),
    "notifications: turning them on asks the browser once, and saves the wish");
  expect(polls.length >= 1 && /after=4239\.8&wait=55/.test(polls[0]) && shownNotes.length === 1 && shownNotes[0][0] === "Agent A in agent-a"
    && shownNotes[0][1].tag === "ntf-5001" && !shownNotes[0][1].body.includes("secret text"),
    "notifications: a new chat is shown with its id as tag, without its text; a removed kind (card) and one's own are not");
  shownNotes.length = 0;
  // Something arrives on the hub before the next start: a restart begins at the hub's head then, not at the page's first one.
  const headNow = "4300.7";
  const nPoll = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me/notifications?limit=0" ? nGet(p).then((a) => Object.assign(a, { next_after: headNow })) : nPoll(p));
  polls.length = 0;
  fresh.push(Object.assign({}, { id: "ntf-5004", seq: 5004, kind: "chat", at: "2026-10-22T15:03:00Z", project: { slug: "maity", full_name: "maintainer/maity", name: "Maity" }, actor: { member_id: "agt-a" }, title: "Agent A in agent-a", target: { type: "conversation", id: "agt-a" }, read: false, redacted: false, content: "x".repeat(300) }));
  byId("notify-content-chat").checked = true; byId("notify-content-chat").dispatch("change"); for (let k = 0; k < 8; k++) await tick();
  expect(polls.length >= 1 && /after=4300\.7&wait=55/.test(polls[0]), "notifications: a restart reads from the hub's head of now, nothing replayed");
  expect(shownNotes.length === 1 && shownNotes[0][1].body === "Maity\n" + "x".repeat(120), "notifications: one notification per new item, its text cut at 120 when allowed");
  win.Maity.notify.stopBrowser();
  byId("notify-browser").checked = false; byId("notify-browser").dispatch("change"); for (let k = 0; k < 6; k++) await tick();
  expect(!win.Maity.notify.running() && text(main).includes("Browser notifications are off."), "notifications: turned off, nothing is polled any more");
  win.Maity.api.get = nGet;
  delete win.Notification;

  // Sessions (docs/api.md §2.6.5, §2.6.7): where one is signed in, This was me, End, a held address change.
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  const sesRow = (id) => main.querySelectorAll("li.session").find((li) => li.getAttribute("data-session") === id);
  const sesBox = () => main.querySelector("section.sessions");
  expect(main.querySelectorAll("li.session").map((li) => li.getAttribute("data-session")).join() === "hss-41d2,hss-41c7,hss-41c0"
    && text(sesRow("hss-41c0")).includes("this browser") && !btn(sesRow("hss-41c0"), "End")
    && text(sesRow("hss-41d2")).includes("not confirmed") && text(sesRow("hss-41d2")).includes("a link by mail")
    && text(sesRow("hss-41c7")).includes("approved from Firefox on Linux"),
    "sessions: the active ones, newest first, this browser marked, how each signed in");
  expect(text(sesBox().querySelector("details.sessions-ended")).includes("Chrome on Windows, signed out"), "sessions: the ended ones of the last 30 days");
  expect(text(sesRow("hss-41d2")).includes("Its sign-in alert is not confirmed.") && btn(sesRow("hss-41d2"), "This was me") && !btn(sesRow("hss-41c7"), "This was me"),
    "sessions: This was me on the sign-in whose alert is unread");
  expect(text(main.querySelector(".address-change")).includes("from Firefox on Linux, 192.0.2.80, not confirmed"), "sessions: the held change says which session asked for it");
  // The banner of a mail sign-in, on every page of another session (§2.6.5).
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  const sesBanner = () => main.querySelector(".signin-banner");
  expect(sesBanner() && text(sesBanner()).includes("New sign-in by mail: Firefox on Linux, 192.0.2.80") && btn(sesBanner(), "End this session") && btn(sesBanner(), "This was me"),
    "sessions: a mail sign-in is a banner on every page, with End this session and This was me");
  const sesDel = win.Maity.api.del;
  const sesDels = [];
  win.Maity.api.del = (p) => { sesDels.push(p); return Promise.resolve({ ended: true }); };
  btn(sesBanner(), "End this session").click(); for (let k = 0; k < 4; k++) await tick();
  expect(sesDels[0] === "/auth/sessions/hss-41d2" , "sessions: End this session ends it with one click");
  win.Maity.api.del = sesDel;
  // From a session that is not confirmed and under an hour old: what it may not do is said, not tried (§2.6.5).
  const sesGet = win.Maity.api.get;
  const weak = { id: "hss-new", current: true, method: "email_code", created_at: new Date(Date.now() - 10 * 60000).toISOString(), last_seen_at: new Date().toISOString(),
    browser: "Chrome", os: "Android", ip: "192.0.2.99", approved_by: null, good_standing: false, created: { record: "acr-9", ip: "192.0.2.99", browser: "Chrome", os: "Android" }, ended_at: null, ended_by: null };
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? sesGet(p).then((r) => ({ items: [weak].concat(r.items.map((x) => Object.assign({}, x, { current: false }))) })) : sesGet(p));
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  expect(btn(sesRow("hss-41c0"), "End").attrs.disabled !== undefined && text(sesRow("hss-41c0")).includes("Confirm this session's sign-in from another session first.")
    && btn(sesRow("hss-41d2"), "End").attrs.disabled !== undefined && text(sesRow("hss-41d2")).includes("This session is too new to end older ones.")
    && btn(sesBox(), "End all other sessions").attrs.disabled !== undefined && !btn(sesRow("hss-41d2"), "This was me"),
    "sessions: a new session not confirmed may end no confirmed one, no older one, and confirms nothing");
  const sesApprove = btn(main.querySelector(".address-change"), "Approve");
  expect(sesApprove && sesApprove.attrs.disabled !== undefined && btn(main.querySelector(".address-change"), "Reject").attrs.disabled !== undefined
    && text(main.querySelector(".address-change")).includes("Only a confirmed session can decide it."), "sessions: a held address change, not decided from such a session");
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(btn(sesBanner(), "End this session").attrs.disabled !== undefined && text(sesBanner()).includes("This session is too new to end older ones."),
    "sessions: the banner's End follows the same rules as the list");
  win.Maity.api.get = sesGet;
  // The banner stays while a session the mail sign-in approved is active, though the sign-in itself ended (§2.6.5).
  const approved = { id: "hss-41e0", method: "device_code", created_at: "2026-10-22T13:30:00Z", last_seen_at: "2026-10-22T13:31:00Z", browser: "Edge", os: "Windows",
    ip: "192.0.2.81", approved_by: "hss-41d2", good_standing: false, created: { record: "acr-8", ip: "192.0.2.81", browser: "Edge", os: "Windows" }, ended_at: null, ended_by: null };
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? sesGet(p).then((r) => ({ items: [approved].concat(r.items.map((x) => (x.id === "hss-41d2"
    ? Object.assign({}, x, { ended_at: "2026-10-22T13:40:00Z", ended_by: "logout" }) : x))) })) : sesGet(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(sesBanner() && text(sesBanner()).includes("It has ended, but a session it approved is still active: Edge on Windows"), "sessions: the banner stays while a session it approved is active");
  sesDels.length = 0;
  win.Maity.api.del = (p) => { sesDels.push(p); return Promise.resolve({ ended: true }); };
  btn(sesBanner(), "End this session").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(sesDels) === JSON.stringify(["/auth/sessions/hss-41e0"]), "sessions: End this session ends the one still active");
  win.Maity.api.del = sesDel;
  // An ended session's unread alert is still confirmed from the list.
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  const sesEnded = sesBox().querySelector("details.sessions-ended");
  const sesEndedRow = sesEnded.querySelectorAll("li").find((li) => li.getAttribute("data-session") === "hss-41d2");
  expect(sesEnded.attrs.open !== undefined && sesEndedRow && btn(sesEndedRow, "This was me"), "sessions: an ended session whose alert is unread keeps This was me");
  win.Maity.api.get = sesGet;
  // The banner follows the counts at once, without navigating.
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(sesBanner(), "sessions: the banner is there");
  win.Maity.api.get = (p) => (p === "/me/notifications?limit=0" ? sesGet(p).then((r) => Object.assign({}, r, { counts: Object.assign({}, r.counts, { security: 0 }) })) : sesGet(p));
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(!sesBanner(), "sessions: no alert left in the counts, the banner goes at once");
  win.Maity.api.get = sesGet;
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(sesBanner(), "sessions: an alert in the counts, the banner comes at once");
  // A confirmation the hub skipped (§18.3 answers 200 anyway) is not called confirmed.
  const loose = { id: "ntf-acr-8", record: "acr-8", kind: "security", at: new Date().toISOString(), project: null, actor: null,
    title: "Sign-in address changed", target: { type: "settings", id: "email" }, read: false, redacted: false };
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications?kind=security") ? sesGet(p).then((r) => Object.assign({}, r, { items: r.items.concat([loose]) })) : sesGet(p));
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  const sesLoose = sesBox().querySelectorAll(".session-alerts li").find((li) => li.getAttribute("data-alert") === "ntf-acr-8");
  btn(sesLoose, "This was me").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(sesBox()).includes("The hub did not confirm it from this session.") && !text(sesBox()).includes("Confirmed: Sign-in"), "sessions: a skipped confirmation is said, not claimed");
  win.Maity.api.get = sesGet;
  // The hub's refusals in words.
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  win.Maity.api.del = () => Promise.reject(new win.Maity.api.ApiError("f", 403, "/x", "forbidden", { reason: "not_in_good_standing" }));
  btn(sesRow("hss-41c7"), "End").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(sesBox()).includes("Not done: this session's own sign-in is not confirmed yet"), "sessions: not in good standing, in words");
  win.Maity.api.del = sesDel;
  const sesPost = win.Maity.api.post;
  let replaced = false;
  win.Maity.api.post = (p, b) => (p.includes("address-change") ? (replaced = true, Promise.reject(new win.Maity.api.ApiError("c", 409, p, "conflict", {}))) : sesPost(p, b));
  win.Maity.api.get = (p) => (p === "/me/notification-settings" && replaced ? sesGet(p).then((r) => JSON.parse(JSON.stringify(r, (k, v) => (k === "address_change"
    ? { id: "adc-9b1c", address: "other@example.net", requested_at: "2026-10-22T14:00:00Z", session_id: "hss-41d2" } : v)))) : sesGet(p));
  btn(main.querySelector(".address-change"), "Approve").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(sesBox()).includes("replaced by a newer change") && text(main.querySelector(".address-change")).includes("other@example.net"),
    "sessions: a change replaced meanwhile is not approved; the one that replaced it is shown");
  win.Maity.api.post = sesPost;
  win.Maity.api.get = sesGet;
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  // This was me, from a confirmed older session: the mock confirms the sign-in.
  const sesPosts = [];
  win.Maity.api.post = (p, b) => { sesPosts.push([p, b]); return sesPost(p, b); };
  btn(sesRow("hss-41d2"), "This was me").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(sesPosts[0]) === JSON.stringify(["/me/notifications/read", { ids: ["ntf-acr-7"] }])
    && text(sesRow("hss-41d2")).includes("confirmed") && !text(sesRow("hss-41d2")).includes("not confirmed") && text(sesBox()).includes("Confirmed: Firefox on Linux is yours."),
    "sessions: This was me marks the alert read by its id; the session is confirmed");
  btn(main.querySelector(".address-change"), "Approve").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(sesPosts[1]) === JSON.stringify(["/me/notification-settings/email/address-change/approve", { id: "adc-7f2a", address: "maint@example.net" }])
    && !main.querySelector(".address-change") && text(sesBox()).includes("Approved."), "sessions: the held change approved by its id and address");
  btn(sesRow("hss-41c7"), "End").click(); for (let k = 0; k < 6; k++) await tick();
  expect(!sesRow("hss-41c7") && text(sesBox().querySelector("details.sessions-ended")).includes("Safari on iOS, ended"), "sessions: End ends it; it moves to the ended ones");
  win.Maity.api.post = sesPost;
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".signin-banner"), "sessions: no banner once its alert is confirmed");
  // After This was me, a list that cannot be read again leaves the result unknown, never "Confirmed".
  let sesFailNext = false;
  win.Maity.api.get = (p) => {
    if (p === "/auth/sessions?ended=true" && sesFailNext) return Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {}));
    if (p.startsWith("/me/notifications?kind=security")) return sesGet(p).then((r) => Object.assign({}, r, { items: r.items.concat([loose]) }));
    return sesGet(p);
  };
  const sesPostU = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { sesFailNext = true; return sesPostU(p, b); };
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  btn(sesBox().querySelectorAll(".session-alerts li").find((li) => li.getAttribute("data-alert") === "ntf-acr-8"), "This was me").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(sesBox()).includes("whether it was confirmed is not known") && !text(sesBox()).includes("Confirmed"), "sessions: a list that could not be read again leaves the result unknown");
  win.Maity.api.post = sesPostU;
  // The banner follows each round while an alert is unread: the session ending elsewhere with the count unchanged takes it down.
  const mailX = { id: "hss-41f3", method: "email_code", created_at: "2026-10-22T15:00:00Z", last_seen_at: "2026-10-22T15:01:00Z", browser: "Opera", os: "macOS",
    ip: "192.0.2.90", approved_by: null, good_standing: false, created: { record: "acr-9", ip: "192.0.2.90", browser: "Opera", os: "macOS" }, ended_at: null, ended_by: null };
  const alertX = { id: "ntf-acr-9", record: "acr-9", kind: "security", at: "2026-10-22T15:00:00Z", project: null, actor: null, title: "New sign-in: Opera on macOS (email_code)",
    target: { type: "session", id: "hss-41f3" }, read: false, redacted: false };
  let mailEnded = false;
  win.Maity.api.get = (p) => {
    if (p === "/auth/sessions?ended=true") return sesGet(p).then((r) => ({ items: [Object.assign({}, mailX, mailEnded ? { ended_at: "2026-10-22T15:10:00Z", ended_by: "revoked" } : {})].concat(r.items) }));
    if (p.startsWith("/me/notifications?kind=security")) return Promise.resolve({ items: [alertX], next_cursor: null });
    if (p === "/me/notifications?limit=0") return sesGet(p).then((r) => Object.assign({}, r, { counts: Object.assign({}, r.counts, { security: 1 }) }));
    return sesGet(p);
  };
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(sesBanner() && text(sesBanner()).includes("Opera on macOS"), "sessions: a banner for the new mail sign-in");
  mailEnded = true;
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(!sesBanner(), "sessions: its session ended elsewhere, the count unchanged: the banner goes with the next round");
  win.Maity.api.get = sesGet;
  // Crossing the hour while the section is open: what was too new is offered after the minute's check.
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? sesGet(p).then((r) => ({ items: [weak].concat(r.items.map((x) => Object.assign({}, x, { current: false })).filter((x) => !x.good_standing || x.id === "hss-41c0")) })) : sesGet(p));
  const unconfirmedOld = { id: "hss-41aa", method: "email_link", created_at: new Date(Date.now() - 30 * 60000).toISOString(), last_seen_at: new Date().toISOString(), browser: "Vivaldi", os: "Linux",
    ip: "192.0.2.91", approved_by: null, good_standing: false, created: { record: "acr-10", ip: "192.0.2.91", browser: "Vivaldi", os: "Linux" }, ended_at: null, ended_by: null };
  const sesGetW = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? sesGetW(p).then((r) => ({ items: r.items.concat([unconfirmedOld]) })) : sesGetW(p));
  await go("#/account/sessions"); for (let k = 0; k < 6; k++) await tick();
  expect(btn(sesRow("hss-41aa"), "End").attrs.disabled !== undefined, "sessions: an older unconfirmed one is not ended from a session under an hour old");
  const sesNow = win.Maity.api.now;
  win.Maity.api.now = () => sesNow() + 3600 * 1000;
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(btn(sesRow("hss-41aa"), "End").attrs.disabled === undefined, "sessions: once this session is an hour old, the minute's check offers it");
  win.Maity.api.now = sesNow;
  win.Maity.api.get = sesGet;
  // A hub without the session list: said, and asked once per page load.
  let sesAsked = 0;
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? (sesAsked++, Promise.reject(new win.Maity.api.ApiError("n", 404, p, "not_found", {}))) : sesGet(p));
  await go("#/account/sessions"); for (let k = 0; k < 4; k++) await tick();
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(sesAsked === 2 && text(main.querySelector("section.sessions")).includes("This hub lists no sessions yet."), "sessions: a hub without them is asked once per view, and that is said");
  win.Maity.api.get = sesGet;

  // Ctrl+Enter (Cmd+Enter on a Mac) sends every multi-line form; plain Enter never does, nor a disabled submit button.
  const ceCalls = [];
  const cePost = win.Maity.api.post, cePatch = win.Maity.api.patch;
  // Writes recorded and left hanging: what was sent is all a case looks at, and a view stays as it was.
  win.Maity.api.post = (p, b) => { ceCalls.push(["POST", p, b]); return new Promise(() => {}); };
  win.Maity.api.patch = (p, b) => { ceCalls.push(["PATCH", p, b]); return new Promise(() => {}); };
  const ceKey = async (field, extra) => { field.dispatch("keydown", Object.assign({ key: "Enter" }, extra || {})); for (let k = 0; k < 3; k++) await tick(); };
  const ceCase = async (name, field, value, path, submit) => {
    ceCalls.length = 0;
    field.value = value;
    await ceKey(field);
    await ceKey(field, { shiftKey: true });
    expect(!ceCalls.length, "Ctrl+Enter: " + name + ": plain and Shift+Enter send nothing");
    if (submit) {
      submit.disabled = true;
      await ceKey(field, { ctrlKey: true });
      expect(!ceCalls.length, "Ctrl+Enter: " + name + ": not while its submit button is disabled");
      submit.disabled = false;
    }
    await ceKey(field, { metaKey: true });
    expect(ceCalls.length === 1 && ceCalls[0][1] === path, "Ctrl+Enter: " + name + ": Cmd+Enter sends it " + JSON.stringify(ceCalls));
    // The write is held (it never answers here): pressing again sends nothing more.
    await ceKey(field, { ctrlKey: true });
    expect(ceCalls.length === 1, "Ctrl+Enter: " + name + ": not again while the first is on its way");
    ceCalls.length = 0;
  };
  const ceLabel = (id) => main.querySelectorAll("label").concat(header.querySelectorAll("label")).find((l) => l.getAttribute("for") === id);
  const ceSubmitOf = (field) => { let f = field.parentNode; while (f && f.tagName !== "FORM") f = f.parentNode; return f.querySelectorAll("button").find((b) => b.getAttribute("type") === "submit"); };
  // The inbox's free text.
  await go("#/maintainer/maity/inbox"); await tick();
  const ceFree = main.querySelector(".current .free-text textarea");
  expect(text(ceLabel(ceFree.id)).includes("Ctrl+Enter sends"), "Ctrl+Enter: the inbox's free text says so");
  await ceCase("inbox answer", ceFree, "In my own words", "/projects/maintainer/maity/requests/" + main.querySelector(".current .free-text textarea").id.split("-").slice(3).join("-") + "/answer", btn(main.querySelector(".current .free-text"), "Send"));
  // The chat, the group chat, the project message.
  await go("#/maintainer/maity/chat/agt-b"); await tick();
  expect(text(ceLabel("chat-text")).includes("Ctrl+Enter sends"), "Ctrl+Enter: the chat says so");
  // The keys beside the button that sends, muted, and in its tooltip; named as the keyboard prints them.
  const ceSend = ceSubmitOf(byId("chat-text"));
  const ceGroup = ceSend.parentNode;
  const ceHint = ceGroup.childNodes[0];
  expect(ceGroup.classList.contains("send-with-keys") && ceGroup.childNodes.length === 2 && ceGroup.childNodes[1] === ceSend
    && ceGroup.parentNode.classList.contains("compose-actions") && ceGroup.parentNode.querySelector("label.attach-button")
    && ceHint.classList.contains("send-keys") && ceHint.classList.contains("muted") && text(ceHint) === "Ctrl+Enter"
    && ceHint.getAttribute("aria-hidden") === "true" && ceSend.getAttribute("title") === "Send (Ctrl+Enter)"
    && ceSend.getAttribute("aria-keyshortcuts") === "Control+Enter Meta+Enter" && ceSend.classList.contains("primary"),
    "Ctrl+Enter: the chat's primary Send has the keys right before it and in its tooltip, in one row with Attach");
  // The label says the keys to a screen reader only: the hint by the button is the one seen.
  const ceLabelHidden = ceLabel("chat-text").querySelector(".visually-hidden");
  expect(ceLabelHidden && text(ceLabelHidden).includes("Ctrl+Enter sends") && !text(ceLabel("chat-text")).replace(text(ceLabelHidden), "").includes("Ctrl+Enter"),
    "Ctrl+Enter: the chat's label keeps the keys for a screen reader, not shown twice");
  const ceKeys = win.Maity.dom.sendKeysFor;
  expect(ceKeys("de-AT", "Linux x86_64", "") === "Strg+Enter" && ceKeys("de", "Win32", "") === "Strg+Enter"
    && ceKeys("en-US", "Win32", "") === "Ctrl+Enter" && ceKeys("", "", "") === "Ctrl+Enter" && ceKeys("dev", "Win32", "") === "Ctrl+Enter"
    && ceKeys("de-DE", "MacIntel", "") === "⌘+Enter" && ceKeys("en", "", "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)") === "⌘+Enter",
    "Ctrl+Enter: the keys are Strg+Enter in German, ⌘+Enter on an Apple device, Ctrl+Enter elsewhere");
  // Once per button; none where only touch is, which has no keys to press.
  const ceButton = (label) => { const f = document.createElement("form"); const b = document.createElement("button"); b.textContent = label; f.appendChild(b); return b; };
  const ceTwice = ceButton("Post");
  win.Maity.dom.showSendKeys(ceTwice); win.Maity.dom.showSendKeys(ceTwice);
  const ceMedia = win.matchMedia;
  win.matchMedia = (q) => ({ matches: q.includes("pointer: coarse") });
  const ceTouch = ceButton("Send");
  win.Maity.dom.showSendKeys(ceTouch);
  win.matchMedia = ceMedia;
  expect(ceTwice.parentNode.parentNode.querySelectorAll(".send-keys").length === 1 && ceTwice.getAttribute("title") === "Post (Ctrl+Enter)"
    && !ceTouch.parentNode.querySelectorAll(".send-keys").length && !ceTouch.getAttribute("title"),
    "Ctrl+Enter: the keys are shown once per button, and not on a touch-only device");
  await ceCase("chat", byId("chat-text"), "hello", "/projects/maintainer/maity/conversations/agt-b/messages", ceSubmitOf(byId("chat-text")));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-0007"); for (let k = 0; k < 4; k++) await tick();
  await ceCase("group chat", byId("chat-text"), "hello all", "/projects/maintainer/maity/conversations/cnv-0007/messages", ceSubmitOf(byId("chat-text")));
  await go("#/maintainer/maity/message"); await tick();
  expect(text(ceLabel("message-body")).includes("Ctrl+Enter sends"), "Ctrl+Enter: the project message says so");
  await ceCase("project message", byId("message-body"), "A note to all", "/projects/maintainer/maity/events", ceSubmitOf(byId("message-body")));
  // A new card, a briefing, a join's briefing (the ticker post: in the Ticker's own part).
  await go("#/maintainer/maity/board"); await tick();
  btn(main, "New card").click(); await tick();
  byId("new-card-title").value = "From the keyboard";
  await ceCase("new card", byId("new-card-body"), "Body text", "/projects/maintainer/maity/tasks", ceSubmitOf(byId("new-card-body")));
  await go("#/maintainer/maity/members"); for (let k = 0; k < 4; k++) await tick(); await tick();
  main.querySelectorAll(".members-agents tr.member")[0].querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click();
  for (let k = 0; k < 4; k++) await tick();
  const ceBox = main.querySelectorAll(".briefing")[0];
  (btn(ceBox, "Edit briefing") || btn(ceBox, "Write a briefing")).click(); await tick();
  const ceBrief = main.querySelector("form.briefing-form textarea");
  expect(text(ceLabel(ceBrief.id)).includes("Ctrl+Enter saves"), "Ctrl+Enter: the briefing says so");
  await ceCase("briefing", ceBrief, "Review first.", "/projects/maintainer/maity/members/" + ceBrief.id.slice("briefing-".length), ceSubmitOf(ceBrief));
  await go("#/maintainer/maity/agents/join"); for (let k = 0; k < 4; k++) await tick(); await tick();
  byId("join-agent").value = "agt-x"; byId("join-agent").dispatch("change");
  await ceCase("join", byId("join-briefing"), "Start with the open PRs.", "/projects/maintainer/maity/joins", ceSubmitOf(byId("join-briefing")));
  win.Maity.api.post = cePost; win.Maity.api.patch = cePatch;
  await go("#/maintainer/maity/inbox");

  // A member is always clickable (the maintainer's rule): every view names members through one
  // helper, a link to their view with the full name as tooltip; following it marks their row.
  const mrFollow = async (route, label) => {
    await go("#/maintainer/maity/inbox"); await go(route); for (let k = 0; k < 6; k++) await tick();
    const refs = main.querySelectorAll("a.member-ref");
    const ref = refs[0];
    expect(ref && /^#\/maintainer\/maity\/members\/[^/]+$/.test(ref.getAttribute("href")) && ref.getAttribute("title") && ref.getAttribute("data-member"),
      "member links: " + label + " names members as links with the full name as tooltip (" + refs.length + ")");
    if (!ref) return;
    const id = ref.getAttribute("data-member");
    await go(ref.getAttribute("href")); for (let k = 0; k < 4; k++) await tick();
    const known = win.Maity && main.querySelector(".member-head");
    expect(known && text(main.querySelector(".breadcrumb")).includes("@") && main.querySelector("nav.member-tabs"),
      "member links: from " + label + " the link opens that member's page (" + id + ")");
  };
  await mrFollow("#/maintainer/maity/overview", "the overview");
  await mrFollow("#/maintainer/maity/chat/agt-a", "the chat");
  await mrFollow("#/maintainer/maity/messages", "the project messages");
  await mrFollow("#/maintainer/maity/members", "the members list");
  await mrFollow("#/maintainer/maity/board", "the board");
  // A member's page (the designer's handover #6484, read only since #643): header, pills, line, Chat, Actions that only lead away, tabs.
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members/agt-b"); for (let k = 0; k < 6; k++) await tick();
  const mpBox = () => main.querySelector(".member-head");
  const mpPills = () => mpBox().querySelectorAll(".member-pill").map((x) => text(x));
  expect(mpBox() && text(main.querySelector(".breadcrumb")).replace(/\s+/g, " ").trim() === "Members / @agent-b"
    && mpPills().some((t) => t.startsWith("agent of")) && text(mpBox().querySelector(".member-line")).includes("Claude Code")
    && mpBox().querySelectorAll("a").some((a) => a.classList.contains("member-chat") && a.getAttribute("href") === "#/maintainer/maity/chat/agt-b"),
    "member page: breadcrumb, pills (agent of the owner), the line with the harness, Chat to one's own agent");
  const mpMenu = mpBox().querySelector(".member-actions-menu button");
  mpMenu.click(); await tick();
  const mpItems = mpBox().querySelectorAll(".member-actions-menu a").map((x) => [text(x), x.getAttribute("href")]);
  expect(JSON.stringify(mpItems) === JSON.stringify([["Manage on Members", "#/maintainer/maity/members?manage=agt-b"], ["Manage on Agents", "#/maintainer/maity/agents/agt-b"]]),
    "member page: Actions only leads to where each action is done, Members for an admin, Agents for the owner " + JSON.stringify(mpItems));
  const mpTabs = main.querySelectorAll("nav.member-tabs a");
  // Activity: their events in the window the project's messages read, newest first, the window said.
  expect(text(main.querySelector(".member-section")).startsWith("What they did in this project, newest first"),
    "member page: Activity says what it lists, without a count of the project's events it cannot know");
  expect(mpTabs.map((a) => text(a)).join() === "Activity,Cards,Briefing,Sessions & credentials" && mpTabs[0].getAttribute("aria-current") === "page"
    && mpTabs[1].getAttribute("href") === "#/maintainer/maity/members/agt-b/cards", "member page: four tabs, Activity first and current");
  await go("#/maintainer/maity/members/agt-b/cards"); for (let k = 0; k < 6; k++) await tick();
  expect(text(main.querySelector(".member-section")).includes("Holds (") && text(main.querySelector(".member-section")).includes("Assigned ("),
    "member page: Cards lists what they hold and what is assigned to them");
  await go("#/maintainer/maity/members/agt-b/briefing"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".member-section .member-briefing") && text(main.querySelector(".member-section")).includes("You build the hub"),
    "member page: Briefing shows an admin the agent's briefing from the member view, read only");
  // An open session of an instance (§6.17): its id, since when, and not listening.
  const mpsAll = win.Maity.api.getAll, mpsGet = win.Maity.api.get;
  const mpsSession = (r) => Object.assign({}, r, { items: r.items.map((x) => (x.id === "agt-b" ? Object.assign({}, x, { instances: x.instances.map((i, n) => (n ? i
    : Object.assign({}, i, { session: { id: "ses-b-0009", started_at: "2026-10-30T08:00:00Z", not_listening_since: "2026-10-30T09:00:00Z" } }))) }) : x)), next_cursor: null });
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? mpsAll(p).then(mpsSession) : mpsAll(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? mpsGet(p).then(mpsSession) : mpsGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members/agt-b/sessions"); for (let k = 0; k < 8; k++) await tick();
  const mpsSess = main.querySelector(".member-section .member-session");
  expect(text(main.querySelector(".member-section")).includes("Instances") && mpsSess && text(mpsSess).includes("ses-b-0009") && text(mpsSess).includes("since ")
    && text(mpsSess).includes("not listening since") && !btn(main.querySelector(".member-section"), "Revoke"),
    "member page: Sessions & credentials lists the instances with their session, without Revoke (that is in Manage)");
  win.Maity.api.getAll = mpsAll; win.Maity.api.get = mpsGet;
  await go("#/maintainer/maity/members/hum-maintainer"); for (let k = 0; k < 6; k++) await tick();
  expect(mpBox() && !mpBox().querySelector("a.member-chat") && !mpBox().querySelector(".member-actions-menu")
    && mpBox().querySelector(".member-head-dot") && text(mpBox().querySelector(".member-line")).startsWith("Online")
    && !main.querySelectorAll("nav.member-tabs a").some((a) => text(a) === "Briefing"),
    "member page: one's own page has no Chat and no Actions; a human's presence shows; a human has no Briefing tab");
  // Without members:admin: the owner reads its agent's briefing through its versions; another member gets no Briefing tab.
  const mpsMe = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? mpsMe(p).then((x) => Object.assign({}, x, { projects: x.projects.map((y) => Object.assign({}, y, { trust: "member", role: "coder" })) })) : mpsMe(p));
  const mpsReads = [];
  const mpsGetB = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p.endsWith("/briefings")) mpsReads.push(p); return mpsGetB(p); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members/agt-b/briefing"); for (let k = 0; k < 6; k++) await tick();
  expect(mpsReads[0] === "/projects/maintainer/maity/members/agt-b/briefings" && text(main.querySelector(".member-section")).includes("You build the hub"),
    "member page: the owner without members:admin reads the briefing through GET …/briefings");
  const mpsOther = (r) => Object.assign({}, r, { items: r.items.map((x) => (x.id === "agt-b" ? Object.assign({}, x, { owner_id: "hum-other" }) : x)), next_cursor: null });
  const mpsAllC = win.Maity.api.getAll, mpsGetC = win.Maity.api.get;
  win.Maity.api.getAll = (p) => (p === "/projects/maintainer/maity/members" ? mpsAllC(p).then(mpsOther) : mpsAllC(p));
  win.Maity.api.get = (p) => (p === "/projects/maintainer/maity/members" ? mpsGetC(p).then(mpsOther) : mpsGetC(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members/agt-b/briefing"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelectorAll("nav.member-tabs a").some((a) => text(a) === "Briefing") && main.querySelectorAll("nav.member-tabs a")[0].getAttribute("aria-current") === "page",
    "member page: another member's agent has no Briefing tab for a member, and its address falls back to Activity");
  win.Maity.api.getAll = mpsAllC; win.Maity.api.get = mpsMe;
  await go("#/maintainer/maity/members/agt-nobody"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("No member with the id agt-nobody in this project."), "member page: an unknown id is said");
  // ?manage=<id>, where Actions leads: Members with that row open.
  await go("#/maintainer/maity/members?manage=agt-c"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelectorAll("tr.member-manage").some((r) => r.id === "member-manage-agt-c"), "member page: Manage on Members opens that member's row");
  // The inbox: the entry's asker.
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const mrAsker = main.querySelector(".current .facts a.member-ref");
  expect(mrAsker && mrAsker.getAttribute("href") === "#/maintainer/maity/members/" + mrAsker.getAttribute("data-member"), "member links: the inbox names its asker as a link");
  // Across projects the page has no member list of the request's project: names stay text, never a guessed link.
  await go("#/all"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".current") && !main.querySelectorAll(".entries a.member-ref").length,
    "member links: in all projects no member is linked, since no member list of their project was read");
  // The direct chat's heading names its agent as a link; a needs-in-session note names its member.
  await go("#/maintainer/maity/chat/agt-a"); for (let k = 0; k < 4; k++) await tick();
  const mrHead = main.querySelector(".chat-pane") && main.querySelector(".chat-pane").querySelector("a.member-ref");
  expect(mrHead && mrHead.parentNode.tagName === "H2" && mrHead.getAttribute("data-member") === "agt-a",
    "member links: the direct chat's heading links its agent");
  await go("#/maintainer/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const mrNis = main.querySelectorAll(".entry-head").find((b) => (b.textContent || "").includes("Merge PR #2"));
  if (mrNis && mrNis.attrs["aria-expanded"] !== "true") { mrNis.click(); await tick(); }
  expect(main.querySelector(".current .flag a.member-ref"), "member links: a needs-in-session note links its member");
  // Someone the project does not list (removed, outside) is plain text, never a link.
  const mrPlain = win.Maity.dom.memberRef({ memberById: {}, link: () => "/x", nameOf: () => "Gone" }, { member_id: "agt-gone", display_name: "Gone Agent" });
  expect(mrPlain.tagName === "SPAN" && mrPlain.classList.contains("plain") && text(mrPlain) === "Gone Agent" && mrPlain.getAttribute("title") === "Gone Agent",
    "member links: a member the project does not list is plain text");
  // An agent's instance (§6.17): <handle>#<id>, the #id muted with harness and model as tooltip;
  // a human keeps the name, and an id that is no instance id is not shown.
  const inCtx = { memberById: { "agt-b": { id: "agt-b", kind: "agent", handle: "agent-b", display_name: "Agent B" },
    "hum-m": { id: "hum-m", kind: "human", handle: "maintainer", display_name: "Maintainer" } }, link: (k, id) => "/maintainer/maity/" + k + "/" + id, nameOf: (id) => id };
  const inRef = win.Maity.dom.memberRef(inCtx, "agt-b", { instance: { instance: "wqe2", harness: "Claude Code", model: "claude-opus-5-5" } });
  const inSuffix = inRef.querySelector(".member-instance");
  const inLink = inRef.querySelector("a.member-ref");
  expect(text(inRef) === "agent-b#wqe2" && inLink && text(inLink) === "agent-b" && inLink.getAttribute("title") === "Agent B"
    && inSuffix && inSuffix.parentNode === inRef && inSuffix.classList.contains("muted")
    && inSuffix.getAttribute("title") === "Instance wqe2 · Claude Code · claude-opus-5-5",
    "instances: an agent is named <handle>#<id>, the id muted beside the link, harness and model as its tooltip");
  expect(text(win.Maity.dom.memberRef(inCtx, "agt-b", { text: "handle", instance: "k7mq" })) === "@agent-b#k7mq"
    && text(win.Maity.dom.memberRef(inCtx, "hum-m", { instance: "wqe2" })) === "Maintainer"
    && text(win.Maity.dom.memberRef(inCtx, "agt-b", { instance: "<b>x" })) === "Agent B"
    && text(win.Maity.dom.memberRef(inCtx, "agt-b", { instance: null })) === "Agent B",
    "instances: @handle#id as a handle; a human, a malformed id and no instance stay as before");
  // Across projects a reference has no handle and the member no list entry: the name, plain, then the #id.
  const inBare = win.Maity.dom.memberRef({ memberById: {}, link: () => "/x", nameOf: (id) => id }, { member_id: "agt-q", display_name: "Agent Q", instance: "k7mq" }, { instance: "k7mq" });
  expect(text(inBare) === "Agent Q#k7mq" && !inBare.querySelector("a") && inBare.querySelector(".member-ref.plain") && inBare.querySelector(".member-instance"),
    "instances: without a handle (all projects, personal requests) the name and the #id, as plain text");
  const inShared = Object.assign({}, inCtx, { members: [{ id: "agt-b", kind: "agent", handle: "agent-b", name: "oliver/agent-b" }, { id: "agt-x", kind: "agent", handle: "agent-b", name: "sam/agent-b" }] });
  inShared.memberById = Object.assign({}, inCtx.memberById, { "agt-b": inShared.members[0] });
  expect(text(win.Maity.dom.memberRef(inShared, "agt-b", { instance: "wqe2" })) === "oliver/agent-b#wqe2",
    "instances: where two agents share the handle, owner/handle#id");
  // Two instances of one agent in one thread: two senders, each named, never grouped as one.
  const inLine = win.Maity.chatParts.timeline(Object.assign({ me: { id: "hum-m" } }, inCtx), new Map(), null, null, {});
  const inMsgs = [
    { seq: 1, from: "agt-b", from_instance: "wqe2", body: "First.", sent_at: "2026-10-27T10:00:00Z", delivered_at: null },
    { seq: 2, from: "agt-b", from_instance: "k7mq", body: "Second.", sent_at: "2026-10-27T10:00:30Z", delivered_at: null },
    { seq: 3, from: "agt-b", from_instance: "k7mq", body: "Third.", sent_at: "2026-10-27T10:01:00Z", delivered_at: null },
  ].map((m) => inLine(m).find((li) => li.classList.contains("msg")));
  expect(!inMsgs[0].classList.contains("grouped") && !inMsgs[1].classList.contains("grouped") && inMsgs[2].classList.contains("grouped")
    && text(inMsgs[0].querySelector(".meta")).includes("agent-b#wqe2") && text(inMsgs[1].querySelector(".meta")).includes("agent-b#k7mq"),
    "instances: two instances of one agent in a chat are two senders, each named <handle>#<id>");
  // Not on this hub (404 or 405): said quietly where the feature would be, asked once, never red.
  const nhGet = win.Maity.api.get;
  const nhAsked = {};
  const nhAbsent = (prefix, status) => (p) => {
    if (p.startsWith(prefix)) { nhAsked[prefix] = (nhAsked[prefix] || 0) + 1; return Promise.reject(new win.Maity.api.ApiError("x", status, p, status === 405 ? "method_not_allowed" : "not_found", {})); }
    return nhGet(p);
  };
  // Sessions with a 405: muted, not red, and asked once.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = nhAbsent("/auth/sessions", 405);
  await go("#/account/sessions"); for (let k = 0; k < 4; k++) await tick();
  await go("#/account"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".not-on-hub") && text(main).includes("This hub lists no sessions yet.") && !main.querySelector(".sessions .send-status.failed") && (nhAsked["/auth/sessions"] || 0) <= 2,
    "not on this hub: a 405 on sessions is said quietly and asked once per view");
  // Notifications absent: the counts' timer stops asking.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = nhAbsent("/me/notifications", 404);
  await go("#/maintainer/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const nhFirst = nhAsked["/me/notifications"] || 0;
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(nhFirst >= 1 && nhAsked["/me/notifications"] === nhFirst, "not on this hub: notifications absent are not asked again by the 15 s refresh " + nhFirst + "/" + nhAsked["/me/notifications"]);
  // The overview with a 405: quiet, and its events ask no more.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = nhAbsent("/projects/maintainer/maity/overview", 405);
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 4; k++) await tick();
  const nhOv = nhAsked["/projects/maintainer/maity/overview"] || 0;
  feed = [{ seq: 10700, kind: "task_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".overview-missing") && !main.querySelector(".send-status.failed") && nhOv === 1 && nhAsked["/projects/maintainer/maity/overview"] === 1,
    "not on this hub: the overview with a 405 is quiet, and an event does not ask again");
  // A group chat's link on a hub without group chats is quiet, not a red error.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : nhGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/cnv-9999"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".not-on-hub") && text(main).includes("This hub has no group chats yet, so this link cannot open here.") && !main.querySelector(".chat-layout .error"),
    "not on this hub: a group chat link without group chats is said quietly");
  // A 404 on a route the hub lists is the resource's (a project left): an error, never cached as absent.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: { "/api/v1/projects/{owner}/{slug}/overview": { get: {} } } })
    : p.startsWith("/projects/maintainer/maity/overview") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : nhGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/overview"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".send-status.failed") && !main.querySelector(".overview-missing") && !win.Maity.api.absent.has("GET", "/projects/maintainer/maity/overview"),
    "not on this hub: a 404 on a listed route stays an error and is not cached");
  // A direct chat's link (agt-…) is never explained away by missing group chats.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : nhGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/chat/agt-gone"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".not-on-hub") && text(main).includes("No conversation of yours with the id agt-gone."), "not on this hub: an unknown direct chat stays an error");
  win.Maity.api.get = nhGet;
  win.Maity.api.forgetRoutes();
  await go("#/maintainer/maity/inbox");

  // Lead routing and the direct/group boundary.
  const leadA = { id: "agt-lead-a", kind: "agent", trust: "admin", role: "coder", handle: "a", display_name: "Lead A", owner_id: "hum-other", presence: "online", availability: { state: "available" } };
  const leadB = { ...leadA, id: "agt-lead-b", handle: "b", display_name: "Lead B", owner_id: "hum-me" };
  const leadOut = { ...leadA, availability: { state: "limited" }, covered_by: { member_id: leadB.id } };
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: "trust:admin" } }, [leadB, leadA]).id === leadA.id, "lead: admin sorted by handle");
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: leadA.id } }, [leadOut, leadB]).id === leadB.id, "lead: active cover takes over");
  expect(win.Maity.leadChat.resolve({ policy: {} }, [leadA]) === null, "lead: missing policy does not guess");
  const leadSub = { ...leadA, id: "agt-sub", handle: "sub" };
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: leadA.id, coordinator_substitute: leadSub.id } }, [leadOut, leadB, leadSub]).id === leadSub.id,
    "lead: explicit available substitute precedes cover");
  const leadCtx = { me: { id: "hum-me", kind: "human" }, base: "/projects/maintainer/maity", project: { policy: { coordinator: leadA.id } },
    members: [leadA, leadB], memberById: { [leadA.id]: leadA, [leadB.id]: leadB }, link: (view, id) => "/maintainer/maity/" + view + "/" + id };
  expect(JSON.stringify(win.Maity.leadChat.targets({ ...leadCtx, project: { policy: {} } }).map((m) => m.id)) === JSON.stringify([leadB.id]),
    "lead: on an older hub the Lead button reaches only the caller's own admins and proxies");
  expect(JSON.stringify(win.Maity.leadChat.targets(leadCtx).map((m) => m.id)) === JSON.stringify([leadA.id]), "lead: with a lead, the Lead button reaches that lead");
  const leadGetAll = win.Maity.api.getAll, leadPost = win.Maity.api.post, leadServed = win.Maity.groupChat.served;
  const leadWrites = [];
  win.Maity.groupChat.served = async () => true;
  win.Maity.api.getAll = async () => ({ items: [
    { id: "cnv-wider", kind: "group", access: "participant", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }, { member_id: "hum-third" }] },
    { id: "cnv-closed", kind: "group", access: "participant", closed_at: "2026-10-23T00:00:00Z", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] },
    { id: "cnv-observed", kind: "group", access: "observer", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] }
  ] });
  win.Maity.api.post = async (path, body) => { leadWrites.push([path, body]); return { id: "cnv-new-lead" }; };
  await win.Maity.leadChat.open(leadCtx, leadA); await tick();
  expect(JSON.stringify(leadWrites) === JSON.stringify([["/projects/maintainer/maity/conversations", { title: "Talk to the lead", participants: [leadA.id] }]])
    && win.location.hash.endsWith("/cnv-new-lead"), "lead: foreign-owned agent gets a two-person group, never a broader existing chat");
  win.Maity.api.getAll = async () => ({ items: [{ id: "cnv-pair", kind: "group", access: "participant", closed_at: null, participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] }] });
  await win.Maity.leadChat.open(leadCtx, leadA); await tick();
  expect(leadWrites.length === 1 && win.location.hash.endsWith("/cnv-pair"), "lead: reuses an open exact pair");
  await win.Maity.leadChat.open(leadCtx, leadB); await tick();
  expect(leadWrites.length === 1 && win.location.hash === "#/maintainer/maity/chat/" + leadB.id, "lead: own agent opens its direct chat");
  expect(!win.Maity.leadChat.targets({ ...leadCtx, me: { id: leadA.id, kind: "agent" } }).length, "lead: agents reach no one through it");
  // Several to reach: a menu of them and, per project with more than one, a group chat with all of them.
  const leadFound = { multiProject: false, list: [leadA, leadB].map((member) => ({ ctx: leadCtx, member, project: { slug: "maity", full_name: "maintainer/maity", name: "Maity" } })) };
  const leadMenu = win.Maity.leadChat.leadControl(leadCtx, leadFound);
  leadMenu.querySelector("button").click(); await tick();
  const leadItems = leadMenu.querySelectorAll(".menu-item").map((b) => b.textContent);
  expect(JSON.stringify(leadItems) === JSON.stringify(["Lead A", "Lead B", "Group chat with all leads"]), "lead: several leads in a menu, and a group chat with all " + JSON.stringify(leadItems));
  leadWrites.length = 0;
  win.Maity.api.getAll = async () => ({ items: [] });
  leadMenu.querySelectorAll(".menu-item").find((b) => b.textContent === "Group chat with all leads").click(); await tick(); await tick();
  expect(JSON.stringify(leadWrites) === JSON.stringify([["/projects/maintainer/maity/conversations", { title: "Talk to the leads", participants: [leadA.id, leadB.id] }]]),
    "lead: the group chat with all leads is made with exactly them " + JSON.stringify(leadWrites));
  // A double click while the first is on its way makes one group chat, not two (H on #459).
  leadWrites.length = 0;
  let leadRelease;
  win.Maity.api.getAll = () => new Promise((r) => { leadRelease = () => r({ items: [] }); });
  leadMenu.querySelector("button").click(); await tick();
  leadMenu.querySelectorAll(".menu-item").find((b) => b.textContent === "Group chat with all leads").click(); await tick();
  leadMenu.querySelector("button").click(); await tick();
  leadMenu.querySelectorAll(".menu-item").find((b) => b.textContent === "Group chat with all leads").click(); await tick();
  leadRelease(); await tick(); await tick(); await tick();
  expect(leadWrites.length === 1, "lead: a second click while the first is on its way makes nothing more " + leadWrites.length);
  expect(win.Maity.leadChat.leadControl(leadCtx, { multiProject: false, list: [] }) === null, "lead: no one to reach, no button");
  win.Maity.api.getAll = leadGetAll; win.Maity.api.post = leadPost; win.Maity.groupChat.served = leadServed;

  // Presence is independent of a live claim; timestamps never come from the lease.
  const silenceDom = win.Maity.dom;
  expect(!silenceDom.isSilentAgent({ kind: "human", presence: "offline" })
    && !silenceDom.isSilentAgent({ kind: "agent", presence: "online" })
    && !silenceDom.isSilentAgent({ kind: "agent" }), "silence: humans, online and unknown presence are not inferred silent");
  const noCall = silenceDom.silentSince({ kind: "agent", presence: "away" }, true);
  expect(text(noCall).includes("last call unknown") && noCall.className.includes("flag-inline"), "silence: no timestamp stays unknown");
  const silentGet = win.Maity.api.get, silentAll = win.Maity.api.getAll;
  let silentOnline = false, silentAdmin = true;
  const silenceMembers = (value) => ({ ...value, items: value.items.map((m) => m.kind === "agent"
    ? { ...m, presence: silentOnline ? "online" : "away", last_seen_at: "2026-10-23T04:12:00Z" } : m) });
  win.Maity.api.get = (path) => silentGet(path).then((value) => path === "/projects/maintainer/maity/members" ? silenceMembers(value)
    : path === "/me" && !silentAdmin ? { ...value, projects: value.projects.map((p) => ({ ...p, trust: "member", role: "coder" })) } : value);
  win.Maity.api.getAll = (path) => silentAll(path).then((value) => path === "/projects/maintainer/maity/members" ? silenceMembers(value) : value);
  await go("#/maintainer/maity/board");
  const heldCount = main.querySelectorAll(".holder-presence").length;
  expect(heldCount > 0 && main.querySelectorAll(".holder-presence .member-silence.flag-inline").length === heldCount,
    "silence: admin sees warning beside held cards even with live claims");
  const unheldCard = main.querySelectorAll("article.card").find((el) => !el.querySelector(".holder-presence"));
  const silenceFilter = byId("board-silent"); silenceFilter.checked = true; silenceFilter.dispatch("change");
  expect(main.querySelectorAll("article.card").length === heldCount, "silence: filter excludes unheld cards");
  const silenceSearch = byId("board-search");
  silenceSearch.value = unheldCard.getAttribute("data-card"); silenceSearch.dispatch("input");
  expect(!main.querySelectorAll("article.card").length, "silence: text search cannot bypass the silent-holder filter");
  silenceSearch.value = ""; silenceSearch.dispatch("input");
  expect(main.querySelectorAll("article.card").length === heldCount && silenceFilter.checked,
    "silence: clearing text keeps the silent-holder filter");
  silentOnline = true; await fireIntervals(); await tick();
  expect(!main.querySelectorAll("article.card").length, "silence: refreshed online agents leave the silent filter");
  silentOnline = false; silentAdmin = false;
  await go("#/maintainer/maity/members");
  expect(main.querySelectorAll(".member-silence").length > 0 && !main.querySelectorAll(".member-silence.flag-inline").length,
    "silence: ordinary members see last-call hints without admin warnings");
  await go("#/maintainer/maity/board");
  expect(!byId("board-silent") && !main.querySelectorAll(".member-silence.flag-inline").length, "silence: filter and warning styling are admin-only");
  win.Maity.api.get = silentGet; win.Maity.api.getAll = silentAll;

  // The inbox is the requests alone (the maintainer, 2026-10-29, tsk-430dnt8s25a8): no block of other activity
  // under it; a project's inbox also lists the open personal requests about that project, which its tab counts.
  const waitGet = win.Maity.api.get, waitGetAll = win.Maity.api.getAll, waitPost = win.Maity.api.post;
  const waitPersonal = { id: "req-pm01", class: "info", title: "agent-b is not listening", summary: "", options: [], replies: [{ id: "seen", label: "Seen" }],
    priority: "normal", to: "human:hum-maintainer", asked_by: { member_id: "hub", display_name: "Maity" }, task_id: null, task: null,
    while_open: "proceed", personal: true, status: "open", answer: null, project: { full_name: "maintainer/maity", name: "Maity" }, created_at: "2026-10-29T10:00:00Z" };
  win.Maity.api.getAll = (p) => (p === "/requests" ? waitGetAll(p).then((r) => Object.assign({}, r, { items: r.items.concat([waitPersonal]) })) : waitGetAll(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".waiting-activity") && !text(main).includes("Request updates") && !text(main).includes("Reading what else is new"),
    "inbox: the requests alone, no block of other activity under them");
  expect(main.querySelectorAll("li.entry").some((li) => text(li).includes("agent-b is not listening")),
    "inbox: a project's inbox lists the open personal requests about the project too, as its tab counts them");
  const pmEntry = main.querySelectorAll("li.entry").find((li) => text(li).includes("agent-b is not listening"));
  const pmLabel = pmEntry && pmEntry.querySelector(".project-label.personal");
  expect(pmLabel && text(pmLabel).startsWith("Personal") && !pmEntry.querySelector("a.project-label")
    && text(pmEntry.querySelector(".entry-head")).startsWith("Personal, "),
    "inbox: in a project's inbox a personal request carries its Personal label and no link into the project");
  expect(!main.querySelectorAll("li.entry").filter((li) => li !== pmEntry).some((li) => li.querySelector(".project-label")),
    "inbox: the project's own requests carry no project label in its inbox");
  await go("#/maintainer/sample/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelectorAll("li.entry").some((li) => text(li).includes("agent-b is not listening")), "inbox: another project's personal request is not listed there");
  // The personal requests failing to read: the project's own are listed, the failure said, no list quietly short of the tab.
  win.Maity.api.getAll = (p) => (p === "/requests" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal")) : waitGetAll(p));
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelectorAll("li.entry").length > 0 && text(main).includes("Your personal requests about this project could not be read: down"),
    "inbox: a failed read of the personal requests is said, the project's own still listed");
  win.Maity.api.getAll = waitGetAll;
  // The list's own reload follows §18.2's inbox count (by_project), which counts personal requests; /me's open_requests does not.
  await go("#/maintainer/maity/board"); await go("#/maintainer/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  const wrState = win.Maity.notify.state, wrBefore = JSON.stringify(wrState.byProject);
  const wrRender = [];
  const wrGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me/notifications?limit=0" ? wrGet(p).then((a) => {
    const by = Object.assign({}, a.by_project); by["maintainer/maity"] = Object.assign({}, by["maintainer/maity"], { inbox: ((by["maintainer/maity"] || {}).inbox || 0) + 1 });
    return Object.assign({}, a, { by_project: by });
  }) : (wrRender.push(p), wrGet(p)));
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(wrBefore !== JSON.stringify(wrState.byProject) && (text(main).includes("1 new request.") || text(main).includes("What waits for you changed")),
    "inbox: a personal request about the project, counted only in by_project, reloads the list or offers it");
  win.Maity.api.get = wrGet;
  // All notifications (/notifications): unread in bold with a dot, as on the bell, and Mark all read up to the first page's head.
  const waitWrites = [];
  win.Maity.api.post = (p, b) => { if (p === "/me/notifications/read") waitWrites.push(b); return waitPost(p, b); };
  // Earlier cases read everything: one mention is unread again here, until Mark all read is sent.
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications?limit=50") && !waitWrites.length
    ? waitGet(p).then((r) => Object.assign({}, r, { items: r.items.map((x) => (x.kind === "mention" ? Object.assign({}, x, { read: false }) : x)) })) : waitGet(p));
  await go("#/notifications"); for (let k = 0; k < 6; k++) await tick();
  const waitItems = () => main.querySelectorAll("li.waiting-item");
  expect(waitItems().some((li) => li.classList.contains("unread") && text(li).includes("(unread)")) && btn(main, "Mark all read"),
    "notifications: unread rows marked (bold with a dot, said to a screen reader) and Mark all read offered");
  btn(main, "Mark all read").click(); for (let k = 0; k < 8; k++) await tick();
  expect(waitWrites.length === 1 && "up_to" in waitWrites[0] && !("ids" in waitWrites[0])
    && !waitItems().some((li) => li.classList.contains("unread") && !/sign-in|address/i.test(text(li))),
    "notifications: Mark all read marks up to the first page's head; the list is read again " + JSON.stringify(waitWrites));
  win.Maity.api.get = waitGet; win.Maity.api.post = waitPost;

  // Languages: project writes are human-admin only; personal language is not mail-gated.
  const languageGet = win.Maity.api.get;
  const languagePatch = win.Maity.api.patch;
  const languageWrites = [];
  win.Maity.api.patch = (path, body) => { languageWrites.push([path, body]); return languagePatch(path, body); };
  await go("#/maintainer/maity/board"); await projectSettings();
  expect(!!byId("project-language"), "language: human owner can edit project language");
  byId("project-language").value = "de";
  main.querySelector("form.project-language").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(languageWrites[0]) === JSON.stringify(["/projects/maintainer/maity", { settings: { language: "de" } }]), "language: project patch changes only language");
  win.Maity.api.get = (path) => languageGet(path).then((value) => path === "/me"
    ? Object.assign({}, value, { projects: value.projects.map((p) => Object.assign({}, p, { trust: "member", role: "coder" })) }) : value);
  await go("#/maintainer/maity/inbox"); await projectSettings();
  expect(!byId("project-language") && text(main).includes("Project language: Deutsch") && !byId("state-select"), "language: member sees read-only language without admin controls");
  expect(onSettings() && header.querySelectorAll("nav.views a").some((a) => a.textContent === "Settings") && main.querySelector("section.memory-panel")
    && !main.querySelector("form.badge-form"), "settings: a member has the tab too, read only: the memory shown, no admin form");
  win.Maity.api.get = languageGet;
  const oldNotification = win.Notification;
  const oldAvailable = win.Maity.notify.state.available;
  delete win.Notification;
  win.Maity.notify.state.available = true;
  for (const mail of [false, true]) {
    let setting = { email: { language: "en", address: null }, mail_available: mail };
    const writes = [];
    win.Maity.api.get = async () => setting;
    win.Maity.api.patch = async (path, body) => { writes.push([path, body]); setting = { ...setting, email: { ...setting.email, ...body.email } }; return setting; };
    const part = await win.Maity.notifySettings({ me: { id: "hum-maintainer" } });
    const select = part.el.querySelector("select");
    expect(select && select.id === "personal-language", "language: control without address/browser, mail=" + mail);
    select.value = "de";
    part.el.querySelector("form.personal-language").dispatch("submit"); await tick();
    expect(JSON.stringify(writes) === JSON.stringify([["/me/notification-settings", { email: { language: "de" } }]])
      && text(part.el).includes("Personal language saved."), "language: saves independently of mail=" + mail);
  }
  if (oldNotification) win.Notification = oldNotification;
  win.Maity.notify.state.available = oldAvailable;
  win.Maity.api.patch = languagePatch;
  win.Maity.api.get = (path) => languageGet(path).then((value) => path === "/projects/maintainer/maity/members"
    ? { ...value, items: value.items.map((m) => ({ ...m, language: "de" })).concat([
      { ...value.items.find((m) => m.kind === "human"), id: "hum-removed-language", handle: "removed", language: "de", removed_at: "2026-10-23T00:00:00Z" }
    ]) } : value);
  await go("#/maintainer/maity/members");
  const languages = main.querySelectorAll(".member-language");
  expect(languages.length === 1 && text(languages[0]) === "Language: Deutsch", "language: only active human profile shows language");
  win.Maity.api.get = languageGet;

  // Onboarding settings preserve the full editable object and hide on older hubs.
  const onboardingGet = win.Maity.api.get, onboardingPatch = win.Maity.api.patch;
  const onboardingWrites = [];
  win.Maity.api.patch = (path, body) => { onboardingWrites.push([path, body]); return onboardingPatch(path, body); };
  await go("#/maintainer/maity/board"); await projectSettings();
  expect(!!byId("onboarding-briefing") && byId("onboarding-target").querySelectorAll("option").some((o) => o.attrs.value === "coordinator" && "selected" in o.attrs), "onboarding: default coordinator is editable");
  byId("onboarding-briefing").value = "Report here: **welcome**";
  byId("onboarding-target").value = "role:reviewer";
  main.querySelector("form.project-onboarding").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(onboardingWrites[0]) === JSON.stringify(["/projects/maintainer/maity", { settings: { onboarding: { briefing: "Report here: **welcome**", check_in_with: "role:reviewer" } } }]), "onboarding: only briefing and target are written");
  expect(text(main).includes("Version 1") && text(main).includes("Onboarding saved."), "onboarding: saved version and status appear");
  byId("onboarding-briefing").value = "😀".repeat(16385);
  main.querySelector("form.project-onboarding").dispatch("submit"); await tick();
  expect(onboardingWrites.length === 1 && text(main).includes("16,384"), "onboarding: Unicode character cap prevents oversized write");
  byId("onboarding-briefing").value = ""; byId("onboarding-target").value = "";
  main.querySelector("form.project-onboarding").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(onboardingWrites[1][1]) === JSON.stringify({ settings: { onboarding: {} } }), "onboarding: empty object disables check-in and clears default text");
  win.Maity.api.get = (path) => onboardingGet(path).then((v) => path === "/projects/maintainer/maity"
    ? { ...v, settings: Object.fromEntries(Object.entries(v.settings).filter(([k]) => k !== "onboarding")) } : v);
  await go("#/maintainer/maity/inbox"); await projectSettings();
  expect(!byId("onboarding-briefing"), "onboarding: absent setting hides section on older hub");
  win.Maity.api.get = (path) => onboardingGet(path).then((v) => path === "/projects/maintainer/maity/members"
    ? { ...v, items: v.items.map((m) => ({ ...m, briefing: m.kind === "agent" ? "Own instructions" : null })) } : v);
  await go("#/maintainer/maity/members");
  expect(main.querySelectorAll(".briefing-override").length > 0, "onboarding: own agent briefings are marked in members");
  win.Maity.api.get = onboardingGet; win.Maity.api.patch = onboardingPatch;

  // Statistics (js/statistics.js, docs/api.md §16.6): the instance's counts, never a name; a 7/30/90 switch.
  const stGets = [];
  const stGet = win.Maity.api.get;
  win.Maity.api.get = (p) => { if (p.startsWith("/admin/statistics")) stGets.push(p); return stGet(p); };
  win.Maity.api.forgetRoutes();
  await go("#/all"); await go("#/admin"); for (let k = 0; k < 6; k++) await tick();
  const stBox = () => main.querySelectorAll(".admin-section").find((x) => x.getAttribute("aria-label") === "Statistics");
  const stRow = (key) => stBox().querySelectorAll("tr").find((tr) => tr.attrs["data-series"] === key);
  const stCells = (key) => stRow(key).childNodes.map((c) => text(c));
  const stTiles = () => stBox().querySelectorAll("li.stat-tile").map((li) => text(li));
  expect(stBox() && main.querySelectorAll(".admin-section")[0] === stBox() && stGets[0] === "/admin/statistics?days=30",
    "statistics: the admin area's first section, read for 30 days");
  // One section at a time, picked in a row of buttons; it opens on Statistics.
  const adNav = () => main.querySelector("nav.admin-nav");
  const adSections = () => main.querySelectorAll(".admin-section");
  expect(adNav() && adNav().querySelectorAll("button").map((b) => b.textContent).join() === adSections().map((x) => x.getAttribute("aria-label")).join()
    && !stBox().hidden && adSections().slice(1).every((x) => x.hidden) && adNav().querySelectorAll("button")[0].getAttribute("aria-pressed") === "true",
    "admin: a row of section buttons, Statistics shown, the rest folded");
  btn(adNav(), "Users").click(); await tick();
  const adUsers = adSections().find((x) => x.getAttribute("aria-label") === "Users");
  expect(!adUsers.hidden && stBox().hidden && btn(adNav(), "Users").getAttribute("aria-pressed") === "true", "admin: a button shows its section alone");
  // Registration (§16.4): the mode, the lists, approval, terms and the limit with their sources, missing beside them,
  // the accounts that wait and lifting a block.
  btn(adNav(), "Registration").click(); for (let k = 0; k < 4; k++) await tick();
  const rgBox = () => adSections().find((x) => x.getAttribute("aria-label") === "Registration");
  const rgSave = () => rgBox().querySelector("form.reg-form").dispatch("submit");
  const rgPatches = [];
  const rgPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { if (p === "/admin/settings/registration") rgPatches.push(b); return rgPatch(p, b); };
  expect(rgBox() && !rgBox().hidden && text(rgBox().querySelector(".reg-effective")) === "Registration now: closed."
    && byId("reg-mode").value === "closed" && byId("reg-terms-url").attrs.disabled !== undefined && text(rgBox()).includes("(set by the environment)")
    && text(rgBox().querySelector(".reg-counts")).startsWith("1 waiting for approval"),
    "registration: the section shows the mode in effect, the terms the environment sets as not editable, and the counts");
  expect(rgBox().querySelectorAll("li.reg-pending-item").length === 1 && text(rgBox().querySelector("li.reg-pending-item")).includes("new@example.org"),
    "registration: an account waiting for approval is listed with its address");
  byId("reg-mode").value = "allowlist"; rgSave(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(rgPatches[0]) === JSON.stringify({ mode: "allowlist" }) && rgBox().querySelector('[data-missing="allowlist"]')
    && text(rgBox().querySelector(".reg-effective")) === "Registration now: allowlist." && text(rgBox()).includes("Saved."),
    "registration: only the mode is sent; an empty allowlist is said beside the fields");
  byId("reg-domains").value = "example.com"; rgSave(); for (let k = 0; k < 6; k++) await tick();
  expect(text(byId("reg-domains-error")) === "entry 1 is not valid", "registration: the hub's refusal of a list entry is said at the list, by its number");
  // The hub's own shape (registration.py): `addresses.<index>` for a bad entry, the second here.
  const rgReal = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => (p === "/admin/settings/registration"
    ? Promise.reject(new win.Maity.api.ApiError("x", 400, p, "invalid", { fields: { "addresses.1": "invalid" } })) : rgReal(p, b));
  byId("reg-domains").value = ""; byId("reg-addresses").value = "ada@example.org\nnot an address"; rgSave(); for (let k = 0; k < 6; k++) await tick();
  expect(text(byId("reg-addresses-error")) === "entry 2 is not valid" && text(rgBox().querySelector("form.reg-form")).includes("addresses: entry 2 is not valid"),
    "registration: the hub's addresses.<index> is said at the addresses, by its number");
  win.Maity.api.patch = rgReal;
  byId("reg-addresses").value = "";
  byId("reg-domains").value = "@Example.com\n@example.com"; rgSave(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(rgPatches[rgPatches.length - 1]) === JSON.stringify({ domains: ["@example.com"] }) && !rgBox().querySelector('[data-missing="allowlist"]'),
    "registration: a list is sent lower case without duplicates, and the gap is gone");
  // Approve and reject; a decision redraws the counts only, so what is typed in the form and not saved stays.
  byId("reg-domains").value = "@typed-not-saved.org";
  const rgDomainsBefore = byId("reg-domains");
  btn(rgBox().querySelector("li.reg-pending-item"), "Approve").click(); for (let k = 0; k < 6; k++) await tick();
  expect(text(rgBox().querySelector(".reg-pending-list")).includes("Nobody waits for approval") && text(rgBox()).includes("@newcomer is approved.")
    && text(rgBox().querySelector(".reg-counts")).startsWith("0 waiting for approval"),
    "registration: Approve decides the account, the list and counts follow");
  expect(byId("reg-domains") === rgDomainsBefore && byId("reg-domains").value === "@typed-not-saved.org",
    "registration: a decision keeps the settings form as typed, not saved");
  byId("reg-domains").value = "@example.com";
  byId("reg-block-address").value = "spam@example.org"; rgBox().querySelector("form.reg-block").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(rgBox().querySelector("form.reg-block")).includes("spam@example.org may register again"), "registration: a block is lifted by its address");
  win.Maity.api.patch = rgPatch;
  await win.Maity.api.patch("/admin/settings/registration", { mode: "closed", domains: [] });
  btn(adNav(), "Statistics").click(); await tick();
  expect(JSON.stringify(stTiles()) === JSON.stringify(["41Humans2 waiting for approval", "117Agent profiles", "12Projectsnot archived", "23Agent instances online", "29Humans with an agent"]),
    "statistics: the totals as tiles " + JSON.stringify(stTiles()));
  expect(stCells("registrations")[0] === "Registrations" && stCells("registrations")[1] === "36" && stCells("registrations")[2] === "3"
    && stCells("humans_active")[1] === "up to 16 a day" && (() => { const sv = stRow("cards_done").childNodes[3].childNodes[0]; return sv && String(sv.tagName).toLowerCase() === "svg" && sv.getAttribute("aria-hidden") === "true"
      && sv.childNodes.some((n) => String(n.tagName).toLowerCase() === "polyline"); })(),
    "statistics: a series sums its days, people show their highest day, today beside it " + JSON.stringify([stCells("registrations"), stCells("humans_active")]));
  expect(["stat-number", "stat-number", "stat-trend"].every((c, i) => stRow("registrations").childNodes[i + 1].classList.contains(c))
    && thCss.includes(".stat-series td.stat-trend, .stat-series th.stat-trend { width: 120px;"),
    "statistics: the numbers right-aligned in tabular figures, the sparklines in one 120 px column");
  // The contract text's cue for more never fades a line: a shadow behind the text, hidden at the end.
  expect(/\.contract-text \{[^}]*background:[^}]*local[^}]*scroll; \}/.test(thCss) && !/\.contract-text \{[^}]*mask-image/.test(thCss),
    "contract: the cue for more is a shadow behind the text, gone at the end, never a mask over the last line");
  expect(stCells("reviews")[1] === "38 since 2026-10-22" && text(stBox()).includes("Reviews are counted from 2026-10-22") && text(stBox()).includes("Today (UTC)") && text(stBox()).includes("11 after 7 days · 4 after 30 days")
    && text(stBox()).includes("Humans whose first visit lies at least 7 (or 30) days back") && text(stBox()).includes("Counted ")
    && stBox().querySelectorAll("details.stat-days tbody tr").length === 30,
    "statistics: reviews from when they are known, who comes back explained, when counted, every day in a table");
  btn(stBox(), "90 days").click(); for (let k = 0; k < 4; k++) await tick();
  expect(stGets[stGets.length - 1] === "/admin/statistics?days=90" && btn(stBox(), "90 days").getAttribute("aria-pressed") === "true"
    && btn(stBox(), "30 days").getAttribute("aria-pressed") === "false" && stBox().querySelectorAll("details.stat-days tbody tr").length === 90
    && text(stBox().querySelectorAll("details.stat-days tbody tr")[89]).endsWith("–"),
    "statistics: the switch reads 90 days; days before history show reviews as –");
  // A fresh instance: zeros, nothing broken.
  win.Maity.api.get = (p) => (p.startsWith("/admin/statistics")
    ? Promise.resolve({ as_of: "2026-10-25T10:00:00Z", window_days: 7, totals: { humans: 1, humans_pending: 0, agents: 0, projects: 0, instances_online: 0, humans_with_an_agent: 0 },
      days: Array.from({ length: 7 }, (_, i) => ({ date: "2026-10-" + (25 - i), registrations: 0, new_instances: 0, humans_active: i ? 0 : 1, agents_active: 0,
        cards_created: 0, cards_claimed: 0, cards_done: 0, reviews: 0 })), returning: { after_7_days: 0, after_30_days: 0 }, coverage: { reviews_since: null } })
    : stGet(p));
  btn(stBox(), "7 days").click(); for (let k = 0; k < 4; k++) await tick();
  expect(stCells("cards_done")[1] === "0" && stCells("humans_active")[1] === "up to 1 a day" && !text(stBox()).includes("Reviews are counted from")
    && stTiles()[0] === "1Humans", "statistics: an empty instance reads zeros");
  win.Maity.api.get = (p) => (p.startsWith("/admin/statistics") ? Promise.reject(new win.Maity.api.ApiError("boom", 500, p, "internal")) : stGet(p));
  btn(stBox(), "30 days").click(); for (let k = 0; k < 4; k++) await tick();
  expect(!stBox().querySelector("li.stat-tile") && text(stBox()).includes("The statistics could not be read: boom"), "statistics: a failed read clears the old counts and says so");
  // A slow count does not hold up the other sections.
  win.Maity.api.get = (p) => (p.startsWith("/admin/statistics") ? new Promise(() => {}) : stGet(p));
  await go("#/all"); await go("#/admin"); for (let k = 0; k < 6; k++) await tick();
  expect(stBox() && text(stBox()).includes("Counting…") && main.querySelector("table.users") && byId("mail-host"),
    "statistics: while it counts, users, mail and the instance are there");
  win.Maity.api.get = stGet; win.Maity.api.forgetRoutes();
  // The landing page's editor (js/landing.js, §16.7): per language the ordered sections of the contract's types,
  // the footer; one PATCH of the whole draft, the hub's refusals at their field paths.
  const leGet = win.Maity.api.get, lePatch = win.Maity.api.patch;
  const lePatches = [];
  win.Maity.api.patch = (p, b) => { if (p === "/admin/settings/landing" || p === "/admin/settings/legal") lePatches.push([p, JSON.parse(JSON.stringify(b))]); return lePatch(p, b); };
  win.Maity.api.forgetRoutes();
  await go("#/all"); await go("#/admin"); for (let k = 0; k < 6; k++) await tick();
  const leBox = () => main.querySelector(".lp-editor");
  const leSections = () => leBox().querySelectorAll("li.lp-section");
  const leSave = async () => { leBox().querySelector("form.lp-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick(); };
  expect(leBox() && !byId("lp-enabled").checked && byId("lp-default-language").value === "en" && leSections().length === 3
    && text(leSections()[0]).includes("1. Hero") && byId("lp-pages-en-sections-0-title").value === "Bring your agents. Share one project."
    && byId("lp-pages-en-sections-0-cta-primary-href").value === "/register" && byId("lp-pages-en-sections-1-items-people").checked
    && !byId("lp-en-2-enabled").checked && byId("lp-footer-operator").value === "Maintainer, Austria",
    "landing editor: the page's sections in order with their fields, the counters ticked, a hidden one unticked, the footer");
  // Reorder, a new section, an item, then the hub's refusal at the field it names.
  btn(leSections()[2], "Up").click(); await tick();
  expect(text(leSections()[1]).includes("2. Questions") && text(leSections()[2]).includes("3. Counters"), "landing editor: a section moves up");
  byId("lp-add-type-en").value = "text"; btn(leBox().querySelector(".lp-add"), "Add the section").click(); await tick();
  expect(leSections().length === 4 && text(leSections()[3]).includes("4. Text") && byId("lp-pages-en-sections-3-markdown"), "landing editor: a new section of a type, at the end");
  btn(leSections()[1], "Add question").click(); await tick();
  expect(leSections()[1].querySelectorAll("li.lp-item").length === 2, "landing editor: an item added to a section");
  byId("lp-pages-en-sections-3-markdown").value = "A <b>bold</b> line"; byId("lp-pages-en-sections-3-markdown").dispatch("input");
  await leSave();
  expect(lePatches.length === 1 && lePatches[0][1].pages.en.sections.map((x) => x.type).join() === "hero,faq,stats,text"
    && text(byId("lp-pages-en-sections-3-markdown-error")) === "holds HTML outside fenced code"
    && text(byId("lp-pages-en-sections-1-items-1-q-error")) === "required",
    "landing editor: the whole draft sent in its order; each refusal said at the field its path names");
  // The hub's size limits (§16.7): a stored page over 256 KiB at `pages`, a request over 512 KiB as 413, both in words.
  const leSize = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => (p === "/admin/settings/landing" ? Promise.reject(new win.Maity.api.ApiError("x", 400, p, "invalid", { fields: { pages: "too_large" } })) : leSize(p, b));
  await leSave();
  expect(text(main).includes("pages: the page is too large: at most 256 KiB stored"), "landing editor: a page over the stored limit is said in words");
  win.Maity.api.patch = (p, b) => (p === "/admin/settings/landing" ? Promise.reject(new win.Maity.api.ApiError("x", 413, p, "payload_too_large")) : leSize(p, b));
  await leSave();
  expect(text(main).includes("the draft is larger than the hub takes in one request (512 KiB)"), "landing editor: a draft over the request cap is said in words");
  // A field's own limit: in its hint, and with the hub's invalid at it.
  const lmHint = byId("lp-pages-en-sections-3-markdown").parentNode.querySelector(".hint");
  expect(lmHint && text(lmHint).endsWith("At most 16 KiB."), "landing editor: a Markdown field says its limit");
  win.Maity.api.patch = leSize;
  byId("lp-pages-en-sections-3-markdown").value = "x".repeat(16385); byId("lp-pages-en-sections-3-markdown").dispatch("input");
  await leSave();
  expect(text(byId("lp-pages-en-sections-3-markdown-error")) === "empty, or longer than allowed (at most 16 KiB)",
    "landing editor: the hub's invalid at a landing field names the field's limit (the hub sends invalid, never too_long, §16.7)");
  byId("lp-pages-en-sections-3-markdown").value = "Plain **text**."; byId("lp-pages-en-sections-3-markdown").dispatch("input");
  btn(leSections()[1].querySelectorAll("li.lp-item")[1], "Remove").click(); await tick();
  // A second language, made the default, and the page shown to visitors.
  byId("lp-new-language").value = "de"; btn(leBox(), "Add the language").click(); await tick();
  expect(leBox().querySelectorAll(".lp-tabs button").map((b) => b.textContent + ":" + b.attrs["aria-pressed"]).join() === "en:false,de:true"
    && byId("lp-pages-de-title") && !leBox().querySelector("li.lp-section"), "landing editor: a new language, empty, shown");
  byId("lp-pages-de-title").value = "Maity — bring deine Agents"; byId("lp-pages-de-title").dispatch("input");
  byId("lp-enabled").checked = true; byId("lp-enabled").dispatch("change");
  await leSave();
  const leLast = lePatches[lePatches.length - 1][1];
  expect(text(main).includes("Saved. Visitors see it within a minute.") && leLast.enabled === true && Object.keys(leLast.pages).join() === "en,de"
    && leLast.pages.de.title === "Maity — bring deine Agents" && leLast.pages.en.sections[1].items.length === 1
    && leBox().querySelectorAll("a").some((a) => a.getAttribute("href") === "#/?as=public&lang=de" && a.getAttribute("target") === "_blank"),
    "landing editor: saved with both languages; View as a visitor opens the saved page in a tab of its own");
  // A draft previewed (§16.7, #628): POSTed with the token, opened by the hub's url in a tab opened at the click.
  const pvOpen = win.open, pvHref = win.location.href, pvOrigin = win.location.origin, pvTabs = [];
  win.location.href = "file:///web/index.html"; win.location.origin = "null";
  win.open = (url, target, features) => { const tab = { url, target, features, location: {}, close() { this.closed = true; } }; pvTabs.push(tab); return tab; };
  const pvPosts = [];
  const pvPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { if (/\/preview/.test(p)) pvPosts.push([p, JSON.parse(JSON.stringify(b))]); return pvPost(p, b); };
  btn(leBox(), "Preview the draft").click(); for (let k = 0; k < 6; k++) await tick();
  expect(pvPosts.length === 1 && pvPosts[0][0] === "/admin/settings/landing/preview" && Object.keys(pvPosts[0][1]).join() === "default_language,pages,footer"
    && pvTabs.length === 1 && pvTabs[0].url === "about:blank" && pvTabs[0].opener === null
    && /^file:\/\/\/api\/v1\/admin\/settings\/landing\/preview\/[^?]+\?lang=de$/.test(pvTabs[0].location.href),
    "landing editor: Preview the draft posts it and opens the hub's url in a tab opened at the click, in the language shown " + JSON.stringify(pvTabs[0] && pvTabs[0].location));
  byId("lp-pages-de-title").value = ""; byId("lp-pages-de-title").dispatch("input");
  btn(leBox(), "Preview the draft").click(); for (let k = 0; k < 6; k++) await tick();
  expect(pvTabs.length === 2 && pvTabs[1].closed && text(byId("lp-pages-de-title-error")) === "required", "landing editor: a refused preview closes its tab and says why at the field");
  byId("lp-pages-de-title").value = "Maity — bring deine Agents"; byId("lp-pages-de-title").dispatch("input");
  // The legal pages (§16.7.1): one page per save, a new version; taking one down.
  const lgBox = () => main.querySelectorAll("section.lg-page");
  const lgImprint = () => lgBox().find((x) => x.attrs["aria-label"] === "Imprint");
  const lgPrivacy = () => lgBox().find((x) => x.attrs["aria-label"] === "Privacy");
  expect(lgBox().length === 3 && text(lgImprint()).includes("Served at /impressum") && lgImprint().querySelectorAll("a").some((a) => a.getAttribute("href") === "/impressum")
    && byId("lp-imprint-en-title").value === "Imprint" && text(lgPrivacy()).includes("Not set: /privacy answers not found"),
    "legal: each page, served or not set, its earlier versions linked, the text per language");
  byId("lg-privacy-new-language").value = "en"; btn(lgPrivacy(), "Add the language").click(); await tick();
  byId("lp-privacy-en-markdown").value = "We keep <b>nothing</b>."; byId("lp-privacy-en-markdown").dispatch("input");
  lgPrivacy().querySelector("form.lg-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(byId("lp-privacy-en-markdown-error")) === "holds HTML outside fenced code", "legal: the hub's refusal at the page's field");
  // The hub folds an empty or too long legal text into invalid: said with the field's limit (64 KiB).
  const lgReal = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => (p === "/admin/settings/legal" ? Promise.reject(new win.Maity.api.ApiError("x", 400, p, "invalid", { fields: { "privacy.en.markdown": "invalid" } })) : lgReal(p, b));
  lgPrivacy().querySelector("form.lg-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(text(byId("lp-privacy-en-markdown-error")) === "empty, or longer than allowed (at most 64 KiB)", "legal: an invalid text names the page's limit");
  win.Maity.api.patch = lgReal;
  byId("lp-privacy-en-markdown").value = "We keep what the service needs."; byId("lp-privacy-en-markdown").dispatch("input");
  lgPrivacy().querySelector("form.lg-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  const lgLast = lePatches[lePatches.length - 1];
  expect(lgLast[0] === "/admin/settings/legal" && Object.keys(lgLast[1]).join() === "privacy" && lgLast[1].privacy.en.title === "Privacy"
    && text(main).includes("Saved as a new version of the privacy.") && text(lgPrivacy()).includes("Served at /privacy"),
    "legal: one page sent as a whole, served at once");
  btn(lgImprint(), "Preview the draft").click(); for (let k = 0; k < 6; k++) await tick();
  expect(pvPosts.slice(-1)[0][0] === "/admin/settings/legal/preview?page=imprint" && !("imprint" in pvPosts.slice(-1)[0][1])
    && pvPosts.slice(-1)[0][1].en && "markdown" in pvPosts.slice(-1)[0][1].en && pvPosts.slice(-1)[0][1].de
    && /\/api\/v1\/admin\/settings\/legal\/preview\/[^?]+\?lang=en$/.test(pvTabs.slice(-1)[0].location.href),
    "legal: a page's draft previewed the same way, its languages as the body (not wrapped in the page's name), the page in ?page=");
  win.open = pvOpen; win.location.href = pvHref; win.location.origin = pvOrigin; win.Maity.api.post = pvPost;
  btn(lgImprint(), "Take the page down").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(lePatches[lePatches.length - 1][1]) === JSON.stringify({ imprint: null }) && text(lgImprint()).includes("Not set"),
    "legal: taking a page down sends it as null");
  win.Maity.api.get = leGet; win.Maity.api.patch = lePatch; win.Maity.api.forgetRoutes();
  await go("#/all");

  // Unified instance administration: source-aware mail editing and isolated capabilities.
  const adminGet = win.Maity.api.get, adminPatch = win.Maity.api.patch, adminPost = win.Maity.api.post;
  const adminHas = win.Maity.api.hubHas, adminMissing = win.Maity.api.missingRoute;
  const adminWrites = [], adminReads = [];
  win.Maity.api.hubHas = async () => true;
  win.Maity.api.get = (path) => { adminReads.push(path); return adminGet(path); };
  win.Maity.api.patch = (path, body) => { adminWrites.push([path, JSON.parse(JSON.stringify(body))]); return adminPatch(path, body); };
  await go("#/admin");
  expect(text(main).includes("Instance administration") && main.querySelector("table.users") && byId("mail-host") && text(main).includes("fixture-head"), "admin: unified users, mail and instance health");
  expect(byId("mail-host").attrs.disabled === "" && text(main).includes("Set by the environment."), "admin: environment field cannot be edited");
  byId("mail-host").value = "ignored.example"; byId("mail-reply_to").value = "reply@example.org"; byId("mail-password").value = "temporary-test-value";
  main.querySelector("form.admin-mail-form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(adminWrites[0]) === JSON.stringify(["/admin/settings/mail", { reply_to: "reply@example.org", password: "temporary-test-value" }]), "admin: only changed writable fields, password once");
  expect(byId("mail-password").value === "" && !text(main).includes("temporary-test-value"), "admin: saved password is never displayed or retained in input");
  byId("mail-password-remove").checked = true;
  main.querySelector("form.admin-mail-form").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(adminWrites[1][1]) === JSON.stringify({ password: null }), "admin: explicit password deletion writes null");
  const testWrites = [];
  win.Maity.api.post = async (path, body) => { testWrites.push([path, body]); return { ok: false, stage: "auth", smtp_code: 535, detail: "535 Credentials … rejected", at: "2026-10-24T00:00:00Z" }; };
  byId("mail-test-to").value = "admin@example.org";
  main.querySelector("form.admin-mail-test").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(testWrites) === JSON.stringify([["/admin/settings/mail/test", { to: "admin@example.org" }]]) && text(main).includes("Stage: auth") && text(main).includes("535 Credentials … rejected") && text(main).includes("Test mail failed."), "admin: test uses only recipient and shows unsuccessful200 stage/redacted reply");
  win.Maity.api.get = (path) => path === "/health" ? Promise.reject(new win.Maity.api.ApiError("outdated", 503, path, "schema_outdated", { revision: "old", head: "new" })) : adminGet(path);
  await go("#/all"); await go("#/admin");
  expect(text(main).includes("Database reachable, migration required.") && text(main).includes("Revision: old · head: new"), "admin: outdated schema is shown with both revisions");
  win.Maity.api.patch = async () => { throw new win.Maity.api.ApiError("invalid settings", 400, "/admin/settings/mail", "invalid", { fields: { password: "secret_key_missing" } }); };
  byId("mail-password").value = "failed-test-value";
  main.querySelector("form.admin-mail-form").dispatch("submit"); await tick(); await tick();
  expect(byId("mail-password").value === "" && text(main).includes("instance encryption key is not configured") && !text(main).includes("failed-test-value"), "admin: failed save clears password and explains field refusal");
  win.Maity.api.get = (path) => path === "/admin/settings/mail" ? Promise.reject(new win.Maity.api.ApiError("absent", 404, path, "not_found")) : adminGet(path);
  win.Maity.api.missingRoute = async (err, method, path) => path === "/admin/settings/mail" && err.status === 404;
  await go("#/all"); await go("#/admin");
  expect(!main.querySelectorAll(".admin-section").some((s) => s.getAttribute("aria-label") === "Mail settings") && win.Maity.api.absent.has("GET", "/admin/settings/mail"), "admin: missing-route helper removes section and remembers absent endpoint");
  win.Maity.api.missingRoute = adminMissing;
  win.Maity.api.hubHas = async (method, path) => path === "/health";
  await go("#/all"); await go("#/admin");
  expect(!byId("mail-host") && !main.querySelector("table.users") && text(main).includes("Instance information"), "admin: unavailable sections are omitted independently");
  win.Maity.api.hubHas = async () => true;
  win.Maity.api.get = (path) => path === "/admin/settings/mail" ? Promise.reject(new win.Maity.api.ApiError("denied", 403, path, "forbidden")) : adminGet(path);
  await go("#/all"); await go("#/admin");
  expect(text(main).includes("Mail settings could not be read: denied") && text(main).includes("Instance information"), "admin:403 is visible and other sections still load");
  win.Maity.api.get = (path) => path === "/me" ? adminGet(path).then((v) => ({ ...v, member: { ...v.member, instance_admin: false } }))
    : (adminReads.push(path), adminGet(path));
  adminReads.length = 0; await go("#/all"); await go("#/admin");
  expect(text(main).includes("Only the instance admin can open this area.") && !adminReads.some((p) => p.startsWith("/admin/") || p === "/health"), "admin: non-admin cannot read configuration even by direct route");
  win.Maity.api.get = adminGet; win.Maity.api.patch = adminPatch; win.Maity.api.post = adminPost;
  win.Maity.api.hubHas = adminHas; win.Maity.api.missingRoute = adminMissing; win.Maity.api.forgetRoutes();

  // Preferences (§19.4): the human writes them; an agent only proposes, reviewed in the personal inbox.
  const pfM = win.Maity.preferences;
  expect(JSON.stringify(pfM.diffLines("a\nb\nc", "a\nc\nd").map((d) => d.op + d.text)) === JSON.stringify(["samea", "delb", "samec", "addd"]),
    "preferences: the diff keeps the common lines and marks the removed and the added ones");
  expect(pfM.utf8Length("aä€😀") === 1 + 2 + 3 + 4, "preferences: the 8 KiB cap counts UTF-8 bytes");
  // Near the cap a text holds thousands of lines: the diff stays bounded and says so.
  const pfMany = pfM.diffLines("x\n".repeat(4094), "y\n".repeat(4094));
  expect(pfMany.coarse && pfMany.length === 8189 && pfMany.filter((d) => d.op === "del").length === 4094,
    "preferences: thousands of changed lines are shown removed then added, without the full table");
  const pfMid = pfM.diffLines(["a", "b", "c", "d"].join("\n").repeat(1), ["a", "c", "d", "e"].join("\n"));
  const pfEdge = pfM.diffLines("keep\n" + "x\n".repeat(3000) + "end", "keep\n" + "x\n".repeat(3000) + "END");
  expect(!pfMid.coarse && !pfEdge.coarse && pfEdge.filter((d) => d.op !== "same").length === 2,
    "preferences: a long text changed in one line is matched exactly (common start and end trimmed)");
  const pfSettle = async () => { for (let k = 0; k < 8; k++) await tick(); };
  // A personal request that cannot be read in full offers no reply that could apply it unseen.
  const pfGet0 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/requests/req-p002" ? Promise.reject(new win.Maity.api.ApiError("busy", 503, p, "unavailable", {})) : pfGet0(p));
  await go("#/maintainer/maity/inbox"); await go("#/all"); await pfSettle();
  const pfHeadU = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("change to your preferences"));
  if (pfHeadU.attrs["aria-expanded"] !== "true") { pfHeadU.click(); await pfSettle(); }
  const pfU = main.querySelector(".current");
  expect(pfU && !btn(pfU, "Go") && !btn(pfU, "No") && !pfU.querySelector(".pref-review") && !byId("reply-maity-req-p002")
    && text(pfU).includes("could not be read in full") && btn(pfU, "Try again") && btn(pfU, "Later"),
    "preferences review: an unreadable personal request offers no plain Go, only Try again");
  win.Maity.api.get = pfGet0;
  btn(pfU, "Try again").click(); await pfSettle();
  expect(main.querySelector(".current .pref-review") && btn(main.querySelector(".current"), "Accept") && !text(main.querySelector(".current")).includes("could not be read in full"),
    "preferences review: Try again reads it and shows the review");
  // On the version it was written against: Accept, or edit first.
  await go("#/maintainer/maity/inbox"); await go("#/all"); await pfSettle();
  const pfHead0 = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("change to your preferences"));
  if (pfHead0.attrs["aria-expanded"] !== "true") { pfHead0.click(); await pfSettle(); }
  const pfFresh = main.querySelector(".current .pref-review");
  expect(pfFresh && btn(pfFresh, "Accept") && btn(pfFresh, "Edit, then accept") && btn(pfFresh, "Decline") && !text(pfFresh).includes("changed since"),
    "preferences review: on the current version it offers Accept, Edit then accept, and Decline");
  const pfPuts = [];
  const pfPut = win.Maity.api.put;
  win.Maity.api.put = (p, b) => { pfPuts.push([p, b]); return pfPut(p, b); };
  await go("#/maintainer/maity/inbox"); await go("#/account/preferences"); await pfSettle();
  const pfText = () => byId("preferences-text");
  const pfSave = () => main.querySelector(".preferences-form").querySelectorAll("button").find((b) => b.textContent === "Save");
  expect(pfText() && pfText().value.startsWith("Direct and short.") && text(main.querySelector(".preferences-version")).startsWith("Version 2 · written by @maintainer")
    && pfSave().disabled, "preferences: the account shows the text, its version and author; Save waits for a change");
  pfText().value += "\nShort commit messages."; pfText().dispatch("input");
  expect(!pfSave().disabled && text(main.querySelector(".preferences-form")).includes(" of 8 KiB"), "preferences: an edit enables Save and shows the size");
  main.querySelector(".preferences-form").dispatch("submit"); await pfSettle();
  expect(JSON.stringify(pfPuts[0]) === JSON.stringify(["/me/preferences", { markdown: pfText().value, base_version: 2 }])
    && text(main).includes("Saved as version 3.") && text(main.querySelector(".preferences-version")).startsWith("Version 3"),
    "preferences: Save sends the text with the version it was written against");
  // Saved meanwhile elsewhere: the edit stays, the newer version is shown, the human chooses.
  await pfPut("/me/preferences", { markdown: "From another tab.", base_version: 3 });
  pfText().value = "Mine, written on version 3."; pfText().dispatch("input");
  main.querySelector(".preferences-form").dispatch("submit"); await pfSettle();
  const pfConflict = main.querySelector(".preferences-conflict");
  expect(text(pfConflict).includes("changed meanwhile, now Version 4") && pfText().value === "Mine, written on version 3."
    && btn(pfConflict, "Take version 4") && btn(pfConflict, "Save mine over it") && pfConflict.querySelector(".pref-diff"),
    "preferences: a conflict keeps the edit and offers the newer version or saving over it");
  btn(pfConflict, "Save mine over it").click(); await pfSettle();
  expect(pfPuts[pfPuts.length - 1][1].base_version === 4 && text(main).includes("Saved as version 5."), "preferences: saving over it names the version it overrides");
  // The projects whose agents read them.
  const pfSample = byId("preferences-in-maintainer-sample");
  expect(byId("preferences-in-maintainer-maity").checked && pfSample && !pfSample.checked, "preferences: on per project, as the hub has it");
  pfSample.checked = true; pfSample.dispatch("change"); await pfSettle();
  expect(JSON.stringify(pfPuts[pfPuts.length - 1]) === JSON.stringify(["/me/preferences/projects/maintainer/sample", { include: true }]), "preferences: a project switched on is saved at once");
  // Earlier versions, read when opened.
  const pfHistory = main.querySelector("details.preferences-history");
  pfHistory.open = true; pfHistory.dispatch("toggle"); await pfSettle();
  expect(pfHistory.querySelectorAll(".preferences-versions li").length === 5 && text(pfHistory).includes("Version 1 · written by @maintainer"),
    "preferences: the earlier versions, newest first");
  // A hub without preferences: said quietly.
  const pfGet = win.Maity.api.get;
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/me/preferences" ? Promise.reject(new win.Maity.api.ApiError("x", 404, p, "not_found", {}))
    : p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : pfGet(p));
  await go("#/maintainer/maity/inbox"); await go("#/account/preferences"); await pfSettle();
  expect(text(main).includes("This hub keeps no preferences yet.") && !main.querySelector(".preferences .error"), "preferences: a hub without them says so quietly");
  win.Maity.api.get = pfGet; win.Maity.api.forgetRoutes();

  // The review: the current text (version 5 now), the proposal on version 2: stale.
  await go("#/maintainer/maity/inbox"); await go("#/all"); await pfSettle();
  const pfHead = () => main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("change to your preferences"));
  if (pfHead().attrs["aria-expanded"] !== "true") { pfHead().click(); await pfSettle(); }
  let pfReview = main.querySelector(".current .pref-review");
  expect(pfReview && text(pfReview).includes("Why: You asked twice this week") && text(pfReview).includes("written against version 2, yours is now version 5")
    && !btn(pfReview, "Accept") && btn(pfReview, "Merge by hand") && btn(pfReview, "Decline"),
    "preferences review: a proposal on an older version offers no plain Accept, only merging by hand or declining");
  expect(!btn(main.querySelector(".current"), "Go") && !btn(main.querySelector(".current"), "No") && !byId("reply-maity-req-p002")
    && btn(main.querySelector(".current"), "Later"), "preferences review: its own answers replace the plain replies; Later stays");
  expect(pfReview.querySelectorAll(".pref-diff li.pref-add").some((li) => text(li).includes("German in chat")), "preferences review: the diff shows the added line");
  // Merge by hand: the edit goes with the current version.
  const pfPosts = [];
  const pfPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { pfPosts.push([p, b]); return pfPost(p, b); };
  btn(pfReview, "Merge by hand").click(); await tick();
  let pfEdit = byId("pref-edit-req-p002");
  expect(pfEdit && !pfReview.querySelector(".pref-edit").hidden && pfEdit.value.includes("German in chat"), "preferences review: the editor opens with the proposal");
  const pfDraft = "Mine, written on version 3.\nGerman in chat, English in code and docs.";
  pfEdit.value = pfDraft; pfEdit.dispatch("input");
  // Saved elsewhere while merging: 409, and the newer text cannot be read either; the edit stays.
  const pfConflictErr = () => Promise.reject(new win.Maity.api.ApiError("changed", 409, "/requests/req-p002/answer", "conflict", { current_version: 5, base_version: 5 }));
  win.Maity.api.post = (p, b) => (p === "/requests/req-p002/answer" ? pfConflictErr() : pfPost(p, b));
  win.Maity.api.get = (p) => (p === "/requests/req-p002" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : pfGet(p));
  btn(pfReview, "Accept my edit").click(); await pfSettle();
  pfReview = main.querySelector(".current .pref-review");
  expect(byId("pref-edit-req-p002").value === pfDraft && !pfReview.querySelector(".pref-edit").hidden
    && text(pfReview).includes("could not be read again: down"), "preferences review: a failed re-read keeps the edit open and says why");
  // The re-read works: the review is drawn again against the newer version, the edit kept and open.
  win.Maity.api.get = pfGet;
  btn(pfReview, "Accept my edit").click(); await pfSettle();
  pfReview = main.querySelector(".current .pref-review");
  pfEdit = byId("pref-edit-req-p002");
  expect(pfEdit && pfEdit.value === pfDraft && !pfReview.querySelector(".pref-edit").hidden && btn(pfReview, "Merge by hand").hidden
    && text(pfReview).includes("changed while you looked"), "preferences review: after a conflict the edit is kept, open, against the newer version");
  win.Maity.api.post = (p, b) => { pfPosts.push([p, b]); return pfPost(p, b); };
  btn(pfReview, "Accept my edit").click(); await pfSettle();
  expect(JSON.stringify(pfPosts[0]) === JSON.stringify(["/requests/req-p002/answer", { reply_id: "go", markdown: pfEdit.value, base_version: 5 }]),
    "preferences review: an edited accept carries the text and the current version");
  const pfNow = await pfGet("/me/preferences");
  expect(pfNow.version === 6 && pfNow.by.kind === "human" && pfNow.proposed_by && pfNow.proposed_by.request_id === "req-p002", "preferences review: the edit is the next version, proposed by the agent");
  win.Maity.api.post = pfPost; win.Maity.api.put = pfPut;

  // An agent's row on Members, for its owner: give it the owner's preferences.
  const pfPatches = [];
  const pfPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { pfPatches.push([p, b]); return pfPatch(p, b); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); await pfSettle();
  main.querySelectorAll("tr.member").find((tr) => tr.attrs["data-member"] === "agt-a").querySelectorAll("button").find((x) => /^Manage /.test(x.getAttribute("aria-label") || "")).click();
  await pfSettle();
  const pfToggle = byId("owner-preferences-agt-a");
  expect(pfToggle && !pfToggle.checked && main.querySelectorAll(".owner-preferences").length === 1,
    "preferences: the owner's switch in its agent's row, where the hub knows it");
  pfToggle.checked = true; pfToggle.dispatch("change"); await pfSettle();
  expect(JSON.stringify(pfPatches[0]) === JSON.stringify(["/projects/maintainer/maity/members/agt-a", { owner_preferences: true }]), "preferences: the switch is saved on the membership at once");
  win.Maity.api.patch = pfPatch;

  // Deleting one's own agent profile (docs/api.md §6.3): in its row on Members, confirmed by its handle; a profile still a
  // member is deleted with ?cascade=true, after its projects are named. Last, since it ends the fixture's agt-d.
  const pdDel = win.Maity.api.del, pdSent = [];
  win.Maity.api.del = (p) => { pdSent.push(p); return pdDel(p); };
  await go("#/maintainer/maity/inbox"); await go("#/maintainer/maity/members"); for (let k = 0; k < 8; k++) await tick(); await agOpen("agt-d");
  const pdBox = () => main.querySelector("tr.member-manage .profile-delete-box");
  const pdIn = () => byId("profile-delete-agt-d");
  const pdGo = () => btn(pdBox(), "Delete the profile");
  expect(pdBox() && text(pdBox()).includes("It is a member of maintainer/maity") && text(pdBox()).includes("cannot be undone") && pdGo().disabled,
    "profile: an own agent's row offers its deletion, naming its projects, the button off until confirmed");
  pdIn().value = "@agent-x"; pdIn().dispatch("input");
  expect(pdGo().disabled, "profile: another handle does not confirm");
  pdIn().value = "@agent-d"; pdIn().dispatch("input");
  expect(!pdGo().disabled, "profile: its own handle confirms");
  // One call at a time, for the handle as typed now: the field locked while it runs; after a failure the button
  // follows what is typed then.
  let pdRelease = null;
  win.Maity.api.del = (p) => { pdSent.push(p); return new Promise((resolve, reject) => { pdRelease = () => reject(new win.Maity.api.ApiError("x", 403, p, "forbidden", {})); }); };
  main.querySelector("tr.member-manage form.profile-delete").dispatch("submit"); await tick();
  expect(pdIn().disabled && pdGo().disabled, "profile: while the deletion runs, the field is locked and the button off");
  main.querySelector("tr.member-manage form.profile-delete").dispatch("submit"); await tick();
  expect(pdSent.length === 1, "profile: a second submit while one runs sends nothing");
  pdRelease(); for (let k = 0; k < 4; k++) await tick();
  expect(!pdIn().disabled && !pdGo().disabled && text(pdBox()).includes("Not deleted"), "profile: after a failure the field is free and the button follows the handle typed");
  pdIn().value = "@wrong"; pdIn().dispatch("input");
  main.querySelector("tr.member-manage form.profile-delete").dispatch("submit"); await tick();
  expect(pdGo().disabled && pdSent.length === 1, "profile: another handle typed after a failure deletes nothing");
  pdIn().value = "@agent-d"; pdIn().dispatch("input");
  pdSent.length = 0;
  win.Maity.api.del = (p) => { pdSent.push(p); return pdDel(p); };
  main.querySelector("tr.member-manage form.profile-delete").dispatch("submit"); for (let k = 0; k < 8; k++) await tick();
  const pdAgents = (await win.Maity.api.getAll("/agents")).items;
  expect(pdSent[0] === "/agents/agt-d?cascade=true" && !main.querySelectorAll("tr.member").some((tr) => tr.getAttribute("data-member") === "agt-d")
    && text(main).includes("The profile @agent-d was deleted; its memberships ended.") && !pdAgents.some((a) => a.id === "agt-d"),
    "profile: deleted with its memberships, the row gone, the profile no longer listed");
  // The mock as the hub: a profile still in use without cascade is refused, naming where (§6.3).
  let pdInUse = null;
  try { await pdDel("/agents/agt-c"); } catch (err) { pdInUse = err; }
  expect(pdInUse && pdInUse.code === "profile_in_use" && pdInUse.details.memberships[0].project === "maintainer/maity",
    "profile: the mock refuses a profile in use without cascade, naming the memberships");
  // On Your agents, every profile is deleted the same way.
  await go("#/agents"); for (let k = 0; k < 6; k++) await tick();
  const pdX = main.querySelectorAll("li.agent-card").find((li) => li.getAttribute("data-agent") === "agt-x");
  expect(pdX && pdX.querySelector(".profile-delete-box") && text(pdX).includes("guest/guestlab"), "profile: Your agents offers the deletion of a profile");
  win.Maity.api.del = pdDel;

  // §6.26 at the end of fixture mode (it adds a project): out of an organisation into one's own namespace, at once.
  await win.Maity.api.post("/orgs", { handle: "selfco", display_name: "Self Co" });
  const selfShop = await win.Maity.api.post("/projects", { slug: "acme-shop", name: "Acme shop", owner: "selfco" }).catch((err) => { throw new Error(JSON.stringify(err.details)); });
  const selfMoved = await win.Maity.api.post("/projects/" + selfShop.full_name + "/transfer", { to: "hum-maintainer" });
  expect(selfShop.full_name === "selfco/acme-shop" && selfMoved.full_name === "maintainer/acme-shop" && selfMoved.owner.id === "hum-maintainer"
    && selfMoved.aliases.includes("selfco/acme-shop"), "transfer: an owner takes an organisation's project into their own namespace at once");
  // An admin's transfer into an organisation (crew, where olga is the owner) asks its owners, each personally:
  // the answer is the transfer's request, and the owners' requests are not this human's.
  const crewAsk = await win.Maity.api.post("/projects/" + selfMoved.full_name + "/transfer", { to: "org-oz00crew0001" });
  const crewMine = (await win.Maity.api.getAll("/requests")).items;
  const crewProject = (await win.Maity.api.getAll("/projects/" + selfMoved.full_name + "/requests?status=all")).items;
  expect(crewAsk.class === "consent" && crewAsk.personal && crewAsk.to === "human:hum-olga" && crewAsk.project.full_name === "maintainer/acme-shop"
    && crewAsk.org.handle === "crew" && !crewMine.some((r) => r.org && r.org.handle === "crew") && !crewProject.some((r) => r.kind === "project_transfer"),
    "transfer: an admin's transfer into an organisation asks each owner personally, files nothing in the project, and none reaches the admin");
  const crewBack = await win.Maity.api.post("/requests/" + crewAsk.id + "/withdraw", {});
  const crewAgain = await win.Maity.api.post("/requests/" + crewAsk.id + "/withdraw", {}).catch((err) => err);
  expect(crewBack.status === "withdrawn" && crewAgain.code === "request_not_open", "transfer: its asker withdraws it, the owners' requests with it");
  expect(win.Maity.projectNames.said({ code: "invalid_transition", details: { reason: "transfer_stale" } }).message === "the transfer no longer holds; ask again",
    "transfer: a stale transfer is said as invalid_transition with its reason");

  // API mode against a fake hub: CSRF on writes, fail loud without a hub.
  win.location.protocol = "http:";
  const F = JSON.parse(JSON.stringify(ctx.window.MAITY_FIXTURES));
  const calls = [];
  // The fake hub's clock is 10 minutes behind this one.
  const HUB_TIME = new Date(Date.now() - 10 * 60000).toISOString().replace(/\.\d+Z$/, "Z");
  let mode = "ok";
  ctx.fetch = async (url, init) => {
    if (mode === "down") throw new Error("connection refused");
    calls.push({ url, method: init.method, headers: Object.assign({}, init.headers) });
    const [p, q] = url.replace("/api/v1", "").split("?");
    const json = (status, data) => ({ ok: status < 400, status, statusText: "x",
      headers: { get: (k) => (k === "Maity-Error" && data.error ? data.error.code : k === "Maity-Server-Time" ? HUB_TIME : null) }, json: async () => data });
    if (mode === "expired" && p !== "/openapi.json" && p !== "/auth/methods") return json(401, { error: { code: "unauthenticated", message: "Session ended" } });
    // 204 No Content: a body that is no JSON at all.
    if (init.method === "DELETE") return { ok: true, status: 204, statusText: "No Content", headers: { get: (k) => (k === "Maity-Server-Time" ? HUB_TIME : null) },
      json: async () => { throw new SyntaxError("Unexpected end of JSON input"); } };
    if (init.method === "POST") {
      if (mode === "reject") return json(403, { error: { code: "csrf_mismatch", message: "CSRF token mismatch", details: {} } });
      const r = F["maity/requests.json"].items.find((x) => p.includes(x.id));
      return json(200, Object.assign({}, r, { status: "answered", answer: { reply_id: "sha", by: "hum-maintainer", at: "2026-10-21T14:00:00Z" } }));
    }
    const map = { "/auth/session": "auth-session.json", "/me": "me.json", "/projects/maintainer/maity": "maity/project.json", "/projects/maintainer/maity/members": "maity/members.json", "/projects/maintainer/maity/requests": "maity/requests.json" };
    if (p === "/projects/maintainer/maity/events") return json(200, { items: [], cursor: 0, superseded: false });
    return map[p] ? json(200, F[map[p]]) : json(404, { error: { code: "not_found", message: "nope", details: {} } });
  };
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  document.cookie = "other=1; maity_csrf=tok%3D123";
  await go("#/maintainer/maity/inbox");
  expect(!main.querySelector(".error"), "API mode against a fake hub renders the inbox");
  expect(Math.abs(win.Maity.api.now() - Date.parse(HUB_TIME)) < 5000, "API mode: the hub's clock from Maity-Server-Time");
  expect(!text(header).includes("Fixtures"), "no fixture label in API mode");
  let noContent = "unset";
  try { noContent = await win.Maity.api.del("/orgs/oz-team/members/invitations/oinv-1"); } catch (err) { noContent = err; }
  expect(noContent === null, "API mode: a 204 answer is a success without a body, not a failure");
  expect(!head.querySelector("script"), "API mode never loads the fixture bundle");
  expect(calls.filter((c) => c.method === "GET").every((c) => !("X-CSRF-Token" in c.headers)), "no CSRF header on GET");
  const ps = byId("inbox-sort"); ps.value = "priority"; ps.dispatch("change"); await tick();
  btn(main.querySelector(".current"), "SHA-256 + pepper").click(); await tick();
  const post = calls.find((c) => c.method === "POST");
  // After answering the second entry the next one is the third, not the first.
  await go("#/maintainer/maity/inbox");
  const heads = main.querySelectorAll(".entry-head");
  const second = heads.find((b) => b.textContent.includes("Merge PR #2"));
  if (second.attrs["aria-expanded"] !== "true") { second.click(); await tick(); }
  btn(main.querySelector(".current"), "go").click(); await tick(); await tick();
  expect(text(main.querySelector(".current")).includes("CLI binary"), "next entry is the one after the answered one");
  expect(post && post.headers["X-CSRF-Token"] === "tok=123", "POST carries X-CSRF-Token from maity_csrf");
  mode = "reject"; document.cookie = ""; calls.length = 0;
  await go("#/maintainer/maity/inbox");
  const ps2 = byId("inbox-sort"); ps2.value = "priority"; ps2.dispatch("change"); await tick();
  btn(main.querySelector(".current"), "SHA-256 + pepper").click(); await tick();
  const post2 = calls.find((c) => c.method === "POST");
  expect(post2 && post2.headers["X-CSRF-Token"] === "fixture-csrf-token", "no cookie: token from /auth/session");
  expect(text(main).includes("Not sent: CSRF token mismatch (reload the page"), "csrf_mismatch shown on the entry");
  mode = "ok";
  await go("#/maintainer/maity/inbox");
  const staleFetch = ctx.fetch;
  const held = new Map();
  let oldPageReads = 0;
  ctx.fetch = (url, init) => {
    if (url.includes("/held-page")) oldPageReads++;
    if (url.includes("/held-") || url.endsWith("/auth/session")) return new Promise((resolve) => held.set(url, resolve));
    return staleFetch(url, init);
  };
  const oldPage = win.Maity.api.getAll("/held-page").catch((err) => err);
  const oldSuccess = win.Maity.api.get("/held-success").catch((err) => err);
  const old401 = win.Maity.api.get("/held-401").catch((err) => err);
  const oldSession = win.Maity.api.get("/auth/session").catch((err) => err);
  const finish = (url, status, data) => held.get("/api/v1" + url)({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
  mode = "expired";
  await win.Maity.api.get("/me").catch(() => {}); await tick(); await tick();
  expect(main.querySelector(".session-ended"), "stale session: expiry shows sign-in");
  const stoppedAt = calls.length;
  finish("/auth/session", 200, F["auth-session.json"]);
  expect((await oldSession).code === "aborted", "stale session: an old successful session check cannot reopen the gate");
  await win.Maity.api.get("/me").catch(() => {});
  expect(calls.length === stoppedAt, "stale session: authenticated calls stay local while signed out");
  finish("/held-page?limit=200", 200, { items: [], next_cursor: "more" });
  expect((await oldPage).code === "aborted" && oldPageReads === 1, "stale session: a late successful page sends no next-page request");
  ctx.fetch = staleFetch; mode = "ok";
  byId("login-handle").value = "maintainer"; byId("login-password").value = "correct";
  main.querySelector(".login").dispatch("submit"); await tick(); await tick();
  expect(!main.querySelector(".login") && header.querySelector(".switcher"), "stale session: sign-in reopens authenticated reads");
  finish("/held-success", 200, { old: true });
  expect((await oldSuccess).code === "aborted", "stale session: old successful replies stay obsolete after another sign-in");
  finish("/held-401", 401, { error: { code: "unauthenticated", message: "Old session ended" } });
  await old401;
  expect(!main.querySelector(".login"), "stale session: a late401 still cannot end the new session");
  // The readable CSRF cookie is optional: logout must send the token supplied
  // by /auth/session before invalidating it along with the old replies.
  document.cookie = "";
  let logoutToken, serverSignedOut = false;
  ctx.fetch = (url, init) => {
    const reply = (status, data) => Promise.resolve({ ok: status < 400, status, headers: { get: () => null }, json: async () => data });
    if (url === "/api/v1/auth/logout") {
      logoutToken = init.headers["X-CSRF-Token"];
      if (logoutToken !== F["auth-session.json"].csrf_token) return reply(403, { error: { code: "csrf_mismatch", message: "CSRF token mismatch" } });
      serverSignedOut = true;
      return reply(200, {});
    }
    if (serverSignedOut && url === "/api/v1/auth/session") return reply(401, { error: { code: "unauthenticated", message: "Signed out" } });
    return staleFetch(url, init);
  };
  header.querySelectorAll("button").find((b) => (b.getAttribute("aria-label") || "").startsWith("Your profile: ")).click();
  header.querySelectorAll("button.menu-item").find((b) => b.textContent === "Sign out").click();
  await tick(); await tick();
  expect(serverSignedOut && logoutToken === F["auth-session.json"].csrf_token && main.querySelector(".login"),
    "stale session: logout with no readable cookie sends the fallback CSRF token and stays signed out");
  ctx.fetch = staleFetch;
  mode = "down";
  await go("#/maintainer/maity/inbox");
  expect(main.querySelector(".page-failed") && text(main.querySelector(".page-failed-title")) === "Maity can't reach its hub"
    && text(main.querySelector(".page-failed details")).includes("did not answer"), "API mode without hub says Maity can't reach its hub, the reason under Details");
  expect(!main.querySelectorAll("a").some((a) => (a.attrs.href || "").includes("fixtures")), "the error offers no way into fixture mode");

  // js/route.js over http(s) (§16.11), on its own: the address is the path, changed with the History
  // API; a click on a dashboard link stays in the page; the device code's fragment is dropped once read.
  const rtPushed = [], rtListeners = {}, rtDoc = {};
  const rtWin = {
    location: { protocol: "https:", pathname: "/maintainer/maity/board", search: "?q=x", hash: "#c=K7QM4XPR9D2F" },
    history: {
      pushState(s, t, url) { rtPushed.push(["push", url]); const [p, q] = url.split("?"); rtWin.location.pathname = p; rtWin.location.search = q ? "?" + q : ""; rtWin.location.hash = ""; },
      replaceState(s, t, url) { rtPushed.push(["replace", url]); const u = url.split("#")[0]; const [p, q] = u.split("?"); rtWin.location.pathname = p; rtWin.location.search = q ? "?" + q : ""; rtWin.location.hash = ""; },
    },
    addEventListener: (t, f) => { rtListeners[t] = f; },
  };
  rtWin.window = rtWin;
  rtWin.Maity = {};
  const rtCtx = { window: rtWin, document: { addEventListener: (t, f) => { rtDoc[t] = f; } }, URLSearchParams, console };
  vm.createContext(rtCtx);
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/route.js"), "utf8"), rtCtx, { filename: "route.js" });
  const R = rtWin.Maity.route;
  const rtAt = R.current();
  expect(!R.fixture && rtAt.path === "/maintainer/maity/board" && rtAt.query.get("q") === "x" && rtAt.fragment === "c=K7QM4XPR9D2F"
    && R.href("/new") === "/new", "route: over https the address is the path, its query and the fragment apart; a link's href is the path itself");
  expect(R.isRoute("/maintainer/maity/board") && R.isRoute("/login?next=%2Fall") && ["//evil", "/a#b", "https://x/y", "/api/v1/me", "/assets/js/app.js",
    "/join/abc", "/r/x", "/mail/x", "/badge/a/b.svg", "/robots.txt", "/sitemap-2.xml", "#/new", "/ x", "/\\evil.example", "/a\\b", "/a//b",
    "/a\u0007b", "/a\u007fb", "/a\u0085b", "/a\u202eb", "/a\u200bb", "/a\ufeffb", "/a\u2066b", "/a\u00adb"].every((x) => !R.isRoute(x))
    && R.isRoute("/a/\u00e4\u00f6\u00fc-caf\u00e9"),
  "route: a dashboard path is a route, letters of any script included; another origin, a backslash, a doubled slash, a fragment, a hub path, a space, a control or a format character is not");
  R.dropFragment();
  expect(rtPushed.length === 1 && rtPushed[0][0] === "replace" && rtPushed[0][1] === "/maintainer/maity/board?q=x" && R.current().fragment === "",
    "route: the device code's fragment is dropped with replaceState, path and query kept");
  let rtDrawn = 0;
  R.listen(() => { rtDrawn += 1; });
  R.go("/all");
  R.go("/new", { replace: true });
  expect(rtListeners.popstate && rtDrawn === 2 && JSON.stringify(rtPushed.slice(1)) === JSON.stringify([["push", "/all"], ["replace", "/new"]]) && R.current().path === "/new",
    "route: go() pushes or replaces the path and draws the view; back and forward come as popstate");
  R.go("/new");
  expect(rtDrawn === 2 && rtPushed.length === 3, "route: going to the address one is at changes nothing, as a link to the same fragment did");
  const rtLink = (href, extra) => {
    let stopped = false;
    const a = { getAttribute: (k) => (k === "href" ? href : (extra || {})[k] || null), hasAttribute: (k) => !!(extra || {})[k] };
    rtDoc.click(Object.assign({ defaultPrevented: false, button: 0, target: { closest: () => a }, preventDefault() { stopped = true; } }, (extra || {}).event || {}));
    return stopped;
  };
  const rtBefore = rtPushed.length;
  expect(rtLink("/maintainer/maity/members") && R.current().path === "/maintainer/maity/members"
    && !rtLink("/api/v1/help") && !rtLink("https://github.com/x/y") && !rtLink("/all", { target: "_blank" }) && !rtLink("/all", { event: { ctrlKey: true } })
    && !rtLink("/all", { download: "x" }) && rtPushed.length === rtBefore + 1,
    "route: a click on a dashboard link stays in the page; a hub path, another site, a new tab, a modified click or a download is the browser's");

  console.log(failures ? failures + " failure(s)" : "all ok");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.log("CRASH", e.stack); process.exit(2); });
