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
  // The gear menu in the header, and its "Project settings" item, which opens and closes the panel.
  const gearButton = () => header.querySelectorAll("button").find((b) => b.getAttribute("aria-label") === "Settings");
  const projectSettings = async () => {
    gearButton().click(); await tick();
    header.querySelectorAll(".menu-item").find((el) => /^(Close project settings|Project settings)$/.test(el.textContent)).click(); await tick();
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
  expect(gets.some((p) => p.startsWith("/requests")) && main.querySelector(".lead-projects"), "#/all renders requests and project lead controls");
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
    && /^#\/p\/(maity|sample)\/inbox$/.test(firstRow.childNodes[0].getAttribute("href")) && firstRow.childNodes[1].className === "entry-head",
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
    && refuses("/api/v1/projects/../logo?v=1") && !refuses("fixtures/maity/logo.png") && !refuses("/api/v1/projects/maity/logo?v=%22f1%22"),
    "dom: an image is a local file or the hub's own image, never another origin, not even https");
  let cur = main.querySelector(".current");
  expect(cur && text(cur).includes("rounding fix") && text(cur).includes("Freeze") && text(cur).includes("urgent"), "urgent first (Sample shop, with its state)");
  expect(cur && !btn(cur, "Later (stays open)") && btn(cur, "Later"), "local Later button present");
  btn(cur, "Later").click(); await tick();
  cur = main.querySelector(".current");
  expect(cur && text(cur).includes("Argon2id"), "Later moves to the next entry without answering");
  expect(chipCount("All projects") === "7", "Later sends nothing, counts unchanged");
  btn(cur, "SHA-256 + pepper").click(); await tick(); await tick();
  expect(chipCount("All projects") === "6" && chipCount("Maity") === "4", "answer re-reads /me counts");
  const projSort = byId("inbox-sort"); projSort.value = "project"; projSort.dispatch("change"); await tick();
  expect(main.querySelectorAll(".project-label")[0].textContent.startsWith("Personal") && main.querySelectorAll(".project-label")[1].textContent.startsWith("Maity"), "sort by project");
  // A project filter and grouping by project.
  const pf = byId("inbox-project");
  expect(pf.querySelectorAll("option").map((o) => o.textContent).join("|") === "every project|Maity|Sample shop", "inbox: the project options carry no counts that could go stale");
  pf.value = "sample"; pf.dispatch("change"); await tick();
  expect(main.querySelectorAll("li.entry").length === 1 && text(main.querySelector("li.entry")).includes("Sample shop"), "inbox: filtered to one project");
  // The filter is the cross-project view's: a project's own inbox shows its entries.
  await go("#/p/maity/inbox");
  const maityOpenNow = (await win.Maity.api.get("/me")).projects.find((x) => x.slug === "maity").open_requests;
  expect(maityOpenNow > 0 && main.querySelectorAll("li.entry").length === maityOpenNow, "inbox: a project's inbox ignores the cross-project filter");
  await go("#/all");
  expect(byId("inbox-project").value === "sample" && main.querySelectorAll("li.entry").length === 1, "inbox: back in all projects, the filter is still set");
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

  await go("#/p/maity/inbox");
  expect(text(header).includes("Build") && text(header).includes("Fixtures") && header.querySelectorAll("button").some((b) => (b.getAttribute("aria-label") || "").startsWith("Your profile: ")), "project header: state, fixtures label, sign out");
  expect(chip("Maity").getAttribute("aria-current") === "page", "switcher marks the current project");
  const sRow = header.querySelector(".switcher-row");
  expect(sRow && sRow.childNodes[0].className === "switcher" && sRow.childNodes[1].className === "project-state"
    && sRow.childNodes[1].querySelector(".state") && !header.querySelector(".bar .state"),
    "header: the state and the settings sit at the projects' right, apart, not in the top bar");
  let c2 = main.querySelector(".current");
  expect(c2 && text(c2).includes("Merge PR #2") && text(c2).includes("On behalf of") && text(c2).includes("Reviewer · reviewer"), "consent without options, on_behalf_of shown");
  expect(btn(c2, "go") && btn(c2, "no") && !btn(c2, "Discuss"), "replies go/no from the hub, no discuss");
  expect(btn(c2, "go").className === "reply primary" && btn(c2, "no").className === "reply", "only the hub's go of a consent is primary");
  expect(JSON.stringify(c2.querySelector(".replies").querySelectorAll("button").map((b) => b.textContent)) === JSON.stringify(["Later", "Neither — let's talk", "no", "go"]),
    "the replies at the right edge: Later and talk first, the primary one last");
  // A request's stored mention links to the member; the @ picker in its free text.
  const hashHead = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("Name of the CLI binary"));
  if (hashHead.attrs["aria-expanded"] !== "true") { hashHead.click(); await tick(); }
  const hashEntry = main.querySelector(".current");
  const triedLink = hashEntry.querySelectorAll("a.mention").find((a) => a.textContent === "@agent-b");
  expect(triedLink && triedLink.getAttribute("href") === "#/p/maity/members/agt-b", "mentions: a request's tried links its stored mention");
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
  gnText.value = "@ol"; gnText.dispatch("input"); await tick();
  expect(JSON.stringify(gnOpts()) === JSON.stringify(["@oliver", "@anna/oliver"]), "global names: a human comes first and keeps the short handle");
  gnText.dispatch("keydown", { key: "Escape" });
  const gnRefused = win.Maity.dom.ambiguousMention(new win.Maity.api.ApiError("x", 400, "/x", "invalid",
    { fields: { body: "ambiguous_mention" }, mentions: { "agent-b": ["anna/agent-b", "oliver/agent-b"] } }));
  expect(gnRefused && gnRefused.message === "@agent-b is 2 agents here: write @anna/agent-b or @oliver/agent-b."
    && win.Maity.dom.ambiguousMention(new win.Maity.api.ApiError("x", 400, "/x", "invalid", { fields: { body: "too_many_mentions" } })) === null,
    "global names: the hub's ambiguous_mention in words with the long forms");
  // A project with two shop-dev of different owners (fixtures/sample): both by their global names; a
  // project without a shared handle keeps the short ones; the hub's refusal of the short form is said.
  await go("#/p/sample/agents"); for (let k = 0; k < 4; k++) await tick();
  const gnHandles = main.querySelectorAll("article.profile").map((a) => text(a.querySelector(".handle")));
  expect(gnHandles.includes("@maintainer/shop-dev") && gnHandles.includes("@anna/shop-dev"), "global names: two owners' shop-dev in Agents by their long names " + JSON.stringify(gnHandles));
  await go("#/p/sample/members"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes(" @anna/shop-dev") && text(main).includes(" @maintainer/shop-dev") && text(main).includes(" @maintainer") && !text(main).includes("@hum-"),
    "global names: and in Members; the human by the short handle");
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll("article.profile").some((a) => text(a.querySelector(".handle")) === "@agent-b"), "global names: no shared handle, the short one");
  const gnPosts = [];
  const gnPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { gnPosts.push([p, b]); return gnPost(p, b); };
  await go("#/p/sample/message"); for (let k = 0; k < 2; k++) await tick();
  byId("message-to").value = "all"; byId("message-body").value = "Ship it, @shop-dev.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main.querySelector("form.message-form")).includes("Not sent: @shop-dev is 2 agents here: write @anna/shop-dev or @maintainer/shop-dev.")
    && byId("message-body").value === "Ship it, @shop-dev.", "global names: a short handle two agents share is refused with the long forms, the text kept");
  byId("message-body").value = "Ship it, @anna/shop-dev.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(gnPosts.length === 2 && text(main).includes("mentioned and notified: Anna's Shop Dev"), "global names: the long form is sent and resolves to that agent");
  win.Maity.api.post = gnPost;
  await go("#/p/sample/messages"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".pmsg-mentions a").some((a) => text(a) === "@anna/shop-dev"), "global names: the message's stored mention by the long name where the short one is shared");
  await go("#/p/maity/inbox");

  slowText.value = "@agent"; slowText.dispatch("input"); await tick(); await tick();
  expect(!slowList.hidden, "mentions: once read, the list is there at once");
  // A mention's link opens the member: Members with that row marked and focused.
  const mlProto = Object.getPrototypeOf(main);
  const mlFocus = mlProto.focus;
  mlProto.focus = function () { document.activeElement = this; };
  await go(triedLink.getAttribute("href")); await tick(); await new Promise((r) => setTimeout(r, 5));
  const wantedRow = main.querySelector("tr.wanted");
  expect(plainTitle() === "Members · Maity · Maity" && wantedRow && wantedRow.getAttribute("data-member") === "agt-b"
    && main.querySelectorAll("tr.wanted").length === 1 && document.activeElement === wantedRow.childNodes[0], "mentions: the link opens Members with the member marked and focused");
  await go("#/p/maity/members/agt-nobody"); await tick();
  expect(text(main).includes("No member with the id agt-nobody in this project.") && !main.querySelector("tr.wanted"), "mentions: an unknown member is said");
  mlProto.focus = mlFocus; document.activeElement = undefined;
  // Back in the inbox, the entry the next checks answer is open again, in this view.
  await go("#/p/maity/inbox");
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
  expect(main.querySelector(".error") && text(main).includes("URI"), "malformed hash shows an error box");
  await go("#/p/maity/constructor");
  expect(text(main).includes("No such view") && plainTitle() === "No such view · Maity", "prototype key is no view, sane title");
  await go("#/p/maity/nonsense");
  expect(text(main).includes("No such view"), "unknown view");
  expect(throws(() => win.Maity.dom.h("a", { href: "javascript:alert(1)" })), "h() refuses a javascript: href");
  expect(throws(() => win.Maity.dom.h("a", { onclick: "alert(1)" })), "h() refuses a string handler");

  await go("#/p/maity/board");
  expect(!main.querySelector(".error"), "board renders");
  // Mentions (docs/api.md §8.6): stored ones become member links, nothing typed does.
  const reportMention = main.querySelectorAll("a.mention").find((a) => a.textContent === "@agent-d");
  expect(reportMention && reportMention.getAttribute("href") === "#/p/maity/members/agt-d", "mentions: a report's stored mention links to the member");
  const wm = (t, ms, f) => win.Maity.dom.withMentions(t, ms, f || "body", (id) => "#/m/" + id);
  const linkOf = (nodes) => nodes.filter((n) => typeof n !== "string");
  const emoji = wm("\u{1F642} hi @agent-b!", [{ member_id: "agt-b", handle: "agent-b", field: "body", offset: 5, length: 8 }]);
  expect(linkOf(emoji).length === 1 && linkOf(emoji)[0].textContent === "@agent-b" && emoji[emoji.length - 1] === "!",
    "mentions: offsets count code points, not UTF-16 units");
  expect(!linkOf(wm("hi @agent-c", [{ member_id: "agt-b", handle: "agent-b", field: "body", offset: 3, length: 8 }])).length,
    "mentions: a stored mention whose text does not match stays text");
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
  expect(relWrites[0][0] === "POST" && relWrites[0][1] === "/projects/maity/tasks/rel-0001/checklist/chk-2" && JSON.stringify(relWrites[0][2]) === JSON.stringify({ done: true })
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
  expect(JSON.stringify(relWrites[2]) === JSON.stringify(["PATCH", "/projects/maity/tasks/rel-0001", { release: { checklist: [
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
  win.Maity.api.get = (p) => (p === "/me" ? realGet5(p).then((m) => { m.projects.find((x) => x.slug === "maity").role = "member"; return m; }) : realGet5(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/board");
  expect(!byId("chk-rel-0001-chk-1") && !btn(rel(), "Edit checklist"), "release: no editing without releases:write");
  expect(!main.querySelector(".card-order"), "board: without tasks:admin no card offers Place");
  win.Maity.api.get = realGet5;
  await go("#/p/sample/board");
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
  await go("#/p/maity/board");
  expect(text(main).includes("lease expired"), "expired lease shown");
  expect(text(main).includes("Checkpoint") && text(main).includes("Report"), "checkpoint and report shown");
  expect(main.querySelectorAll("a").some((a) => a.attrs.href === "https://github.com/oliver-zehentleitner/maity/pull/3"), "https PR link kept");

  const realGetAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p.includes("/members/agt-c/credentials")
    ? Promise.reject(new win.Maity.api.ApiError("boom", 500, p, "internal")) : realGetAll(p));
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".profile").filter((x) => !x.classList.contains("seat")).length === 5 && main.querySelectorAll(".error").length === 1, "one failing credentials call costs one card section");
  win.Maity.api.getAll = realGetAll;
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(!main.querySelector(".error"), "agents render");
  expect(main.querySelectorAll(".profile").filter((x) => !x.classList.contains("seat")).length === 5, "5 agent profiles");
  expect(text(main).includes("never resumed") && text(main).includes("revoked") && text(main).includes("replaced by a new clone"), "never resumed and revoked credentials");
  expect(text(main).includes("Areas") && text(main).includes("capabilities".slice(0, 0) + "tag"), "areas and capabilities");
  expect(text(byId("pause-agt-b").parentNode).includes("A pause tells the agent at once and refuses it new work (claims, new cards)"),
    "the pause form says what a pause does");
  // Briefing: shown to an owner, edited in place with PATCH members.
  const patches = [];
  const realPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { patches.push([p, b]); return realPatch(p, b); };
  const profileB = byId("pause-agt-b").parentNode.parentNode;
  const bBox = () => profileB.querySelector(".briefing");
  expect(bBox() && text(bBox()).includes("You build the hub (hub/). First: the credential exchange"), "the briefing is shown on the agent's card");
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
  expect(patches.length === 1 && patches[0][0] === "/projects/maity/members/agt-b" && JSON.stringify(patches[0][1]) === JSON.stringify({ briefing: "  Review hub PRs first.  " })
    && !byId("briefing-agt-b") && text(main).includes("Review hub PRs first.") && text(main).includes("Set by @maintainer"),
    "a saved briefing is PATCHed as typed (Markdown keeps its spaces), shown, and says who set it");
  const bStored = (await win.Maity.api.getAll("/projects/maity/members")).items.find((x) => x.id === "agt-b");
  expect(bStored.briefing_version > 1 && text(bBox()).includes("Set by @maintainer · version " + bStored.briefing_version),
    "a saved briefing shows the version the hub answered, not the one read before");
  btn(bBox(), "Edit briefing").click(); await tick();
  byId("briefing-agt-b").value = "";
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(patches[1][1]) === JSON.stringify({ briefing: null }) && text(main).includes("No briefing yet."), "an empty briefing clears it");
  win.Maity.api.patch = realPatch;
  // A hub without briefings (the sample fixtures carry no such key): nothing offered.
  await go("#/p/sample/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".profile").filter((x) => !x.classList.contains("seat")).length && !main.querySelector(".briefing"), "no briefing editor where the hub has no briefings");
  await go("#/p/sample/join"); for (let k = 0; k < 4; k++) await tick();
  expect(byId("join-agent") && !byId("join-briefing"), "no briefing field in the join where the hub has no briefings");
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const pauseInput = byId("pause-agt-b"); pauseInput.value = "quota";
  pauseInput.parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(main).includes("Paused") && text(main).includes("by Maintainer: quota"), "pause by the human");
  expect(text(main).includes("The agent was told at once and gets no new work"), "a human's pause says what it does");
  expect(!text(main.querySelectorAll(".profile").find((p) => text(p).includes("Waiting for the API contract"))).includes("The agent was told at once"),
    "an agent's own pause is a declaration, without that line");
  btn(main.querySelectorAll(".credentials").find((c) => btn(c, "Revoke")), "Revoke").click(); await tick(); await tick();
  expect(main.querySelectorAll(".credentials li.revoked").length === 2, "revoke keeps the credential listed as revoked");

  // The theme (System, Light, Dark): a menu beside the gear; the pick on <html> as data-theme, per browser.
  const thButton = () => header.querySelectorAll("button").find((b) => (b.getAttribute("aria-label") || "").startsWith("Theme: "));
  const thHtml = document.documentElement;
  const thStore = {};
  win.localStorage = { getItem: (k) => (k in thStore ? thStore[k] : null), setItem: (k, v) => { thStore[k] = String(v); }, removeItem: (k) => { delete thStore[k]; } };
  expect(thButton() && thButton().getAttribute("aria-label") === "Theme: System" && thHtml.attrs["data-theme"] === undefined,
    "theme: System by default, no data-theme on <html>");
  const thPick = async (label) => {
    thButton().click(); await tick();
    header.querySelectorAll(".menu-item").find((el) => el.textContent === label && el.getAttribute("role") === "menuitemradio").click(); await tick();
  };
  thButton().click(); await tick();
  expect(JSON.stringify(header.querySelectorAll(".menu-item").filter((el) => el.getAttribute("role") === "menuitemradio").map((el) => el.textContent + ":" + el.getAttribute("aria-checked")))
    === JSON.stringify(["System:true", "Light:false", "Dark:false"]), "theme: three choices, the current one checked");
  thButton().click(); await tick();
  await thPick("Dark");
  expect(thHtml.attrs["data-theme"] === "dark" && thStore["maity.theme"] === "dark" && thButton().getAttribute("aria-label") === "Theme: Dark", "theme: Dark sets data-theme=dark and is kept");
  expect(byId(thButton().getAttribute("aria-controls")).getAttribute("aria-label") === "Theme",
    "theme: the menu's name stays Theme when the pick changes");
  await thPick("Light");
  expect(thHtml.attrs["data-theme"] === "light" && thStore["maity.theme"] === "light", "theme: Light sets data-theme=light");
  await thPick("System");
  expect(thHtml.attrs["data-theme"] === undefined && !("maity.theme" in thStore), "theme: System removes both");
  // Storage that refuses: the pick still applies, nothing throws.
  win.localStorage = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
  await thPick("Dark");
  expect(thHtml.attrs["data-theme"] === "dark", "theme: without storage the pick applies to this page");
  await thPick("System");
  delete win.localStorage;
  // Both ways to dark hold the same tokens: the system's (unless Light was picked) and an explicit Dark.
  const thCss = fs.readFileSync(path.join(WEB, "css/app.css"), "utf8");
  const thDark = (sel) => { const m = thCss.split(sel + " {")[1]; return m ? m.split("}")[0].replace(/\s+/g, " ").trim() : ""; };
  expect(thCss.includes('@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {') && thDark(':root[data-theme="dark"]').includes("--bg: #111418;")
    && thDark(':root:not([data-theme="light"])') === thDark(':root[data-theme="dark"]'),
    "theme: the dark tokens apply by the system unless Light is picked, and when Dark is picked, the same in both");
  // The brand (web/brand/BRAND.md): the 28 px header lockup in the page's theme, the favicons, the loader.
  const brImgs = header.querySelector(".brand").querySelectorAll("img");
  expect(brImgs.length === 2 && brImgs.map((i) => i.getAttribute("src")).join(" ") === "brand/maity-lockup.svg brand/maity-lockup-dark.svg"
    && brImgs.every((i) => i.getAttribute("alt") === "Maity" && i.getAttribute("height") === "28"), "brand: the header's title is the lockup, one file per theme, named Maity");
  expect(thCss.includes(".brand-lockup.brand-dark { display: none; }")
    && thCss.includes(':root:not([data-theme="light"]) .brand-lockup.brand-dark { display: block; }')
    && thCss.includes(':root[data-theme="dark"] .brand-lockup.brand-light { display: none; }'),
    "brand: the dark lockup shows where the page is dark, by the system or by the pick");
  expect(['rel="icon" href="brand/favicon.svg"', 'rel="apple-touch-icon" href="brand/apple-touch-icon.png"', 'property="og:image" content="brand/og-image.png"', 'href="brand/loader.css"']
    .every((x) => html.includes(x)) && /<p class="page-loading" role="status"><svg class="maity-loader"[^]*<\/svg> Loading…<\/p>/.test(html)
    && !/ style=/.test(html.split('<main id="main">')[1]), "brand: favicons, the social image and the page loader, with no inline style (CSP)");
  expect(!main.querySelector(".page-loading"), "brand: the first view replaces the loader");
  expect(/<script src="js\/theme.js"><\/script>/.test(html) && html.indexOf("js/theme.js") < html.indexOf("js/dom.js"),
    "theme: applied before the first paint, by a script in <head> without defer");
  // Users of this hub (docs/api.md §16.1), for the instance admin only.
  gearButton().click(); await tick();
  expect(JSON.stringify(gearButton().parentNode.querySelectorAll(".menu-item").map((el) => el.textContent)) === JSON.stringify(["Project settings", "Runners", "Instance administration"])
    && gearButton().attrs["aria-haspopup"] === "menu", "header: the gear menu has this project's settings, the runners and, for the instance admin, the users");
  const usersLink = header.querySelectorAll("a.menu-item").find((a) => a.textContent === "Instance administration");
  expect(usersLink && usersLink.getAttribute("href") === "#/admin", "users: in the settings menu for the instance admin");
  gearButton().click(); await tick();
  await go("#/admin/users"); await tick();
  const userRows = () => main.querySelectorAll("table.users tbody tr");
  const userNames = () => userRows().map((tr) => tr.querySelector(".user-name").textContent);
  expect(plainTitle() === "Users · Maity" && JSON.stringify(userNames()) === JSON.stringify(["Guest Reviewer", "Maintainer", "Ops on call"]),
    "users: every human, by handle");
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
  await go("#/all"); await go("#/admin/users"); await tick();
  expect(text(main).includes("The users could not be read: instance:admin needed"), "users: the endpoint's 403 is said");
  uq.value = "";
  // A hub without the list, and someone who is not the instance admin.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => p === "/openapi.json" ? Promise.resolve({ paths: {} }) : (p.startsWith("/admin/users") ? Promise.reject(new win.Maity.api.ApiError("nope", 404, p, "not_found")) : uGet(p));
  await go("#/all"); await go("#/admin/users"); await tick();
  expect(text(main).includes("This hub has no user list yet.") && !main.querySelector(".error"), "users: a hub without the list says so");
  win.Maity.api.get = (p) => (p === "/me" ? uGet(p).then((x) => { x.member.instance_admin = false; return x; }) : uGet(p));
  await go("#/all"); await go("#/admin/users"); await tick();
  expect(!header.querySelectorAll("a").some((a) => a.textContent === "Users") && text(main).includes("Only the instance admin sees the users of this hub."),
    "users: no link and no list for anyone else");
  win.Maity.api.get = uGet; win.Maity.api.forgetRoutes();
  await go("#/p/maity/inbox");
  // Project → Runners (docs/api.md §15.4): the runners allowed in a project.
  const prTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Runners");
  expect(prTab() && prTab().getAttribute("href") === "#/p/maity/runners", "project runners: a tab for the project's admin");
  const prWrites = [];
  const prPost = win.Maity.api.post, prDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { prWrites.push(["POST", p, b]); return prPost(p, b); };
  win.Maity.api.del = (p) => { prWrites.push(["DELETE", p]); return prDel(p); };
  await go("#/p/maity/runners"); await tick();
  const prCard = (name) => main.querySelectorAll("article.runner").find((a) => a.getAttribute("aria-label") === name);
  expect(plainTitle() === "Runners · Maity · Maity" && main.querySelectorAll("article.runner").length === 2 && prCard("cluster") && prCard("home-laptop"),
    "project runners: the attached runners, by name");
  const prLaptop = text(prCard("home-laptop"));
  expect(prLaptop.includes("online") && prLaptop.includes("1 agent running here") && prLaptop.includes("Claude Code 2.1.308")
    && prLaptop.includes("Agents on home-laptop run as one user, oliver") && !prLaptop.includes("does not allow"),
    "project runners: presence, agents running here, capabilities in plain words");
  expect(text(prCard("cluster")).includes("Its credential was revoked: it starts nothing until it is paired again"), "project runners: a revoked runner says it starts nothing");
  const prAllN = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/runners"
    ? prAllN(p).then((r) => ({ items: r.items.map((a) => (a.runner.name === "cluster" ? Object.assign({}, a, { runner: Object.assign({}, a.runner, { credential_state: "none" }) }) : a)), next_cursor: null }))
    : prAllN(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/runners"); await tick();
  expect(text(prCard("cluster")).includes("It has not been paired yet: it starts nothing until it is") && !text(prCard("cluster")).includes("again"),
    "project runners: a runner never paired is not told to pair again");
  win.Maity.api.getAll = prAllN;
  await go("#/p/maity/inbox"); await go("#/p/maity/runners"); await tick();
  const prSelect = byId("allow-runner");
  expect(prSelect && prSelect.querySelectorAll("option").length === 1 && prSelect.value === "rnr-0003", "project runners: only the own runners not attached here are offered");
  // The 30-second refresh leaves an unchanged Allow form and the focused Detach where they are.
  const prProto = Object.getPrototypeOf(prSelect);
  const prFocus = prProto.focus;
  prProto.focus = function () { document.activeElement = this; };
  const clusterDetach = btn(prCard("cluster"), "Detach");
  clusterDetach.focus();
  const prAll0 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/runners"
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
  expect(JSON.stringify(prWrites[0]) === JSON.stringify(["POST", "/projects/maity/runners", { runner_id: "rnr-0003" }]) && prCard("build-box")
    && text(prCard("build-box")).includes("Its own configuration does not allow maity, so it starts nothing here"),
    "project runners: allowed, and warned where its own configuration does not allow the project");
  expect(text(main).includes("All your runners are allowed here."), "project runners: nothing left to allow");
  let prAsked = "";
  const prConfirm = win.confirm;
  win.confirm = (q) => { prAsked = q; return true; };
  // The count is read when Detach is pressed: an agent started meanwhile is named.
  const prAll1 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/runners"
    ? prAll1(p).then((r) => ({ items: r.items.map((a) => (a.runner.name === "home-laptop" ? Object.assign({}, a, { active_placements: 2 }) : a)), next_cursor: null }))
    : prAll1(p));
  win.confirm = (q) => { prAsked = q; return false; };
  btn(prCard("home-laptop"), "Detach").click(); for (let k = 0; k < 4; k++) await tick();
  expect(prAsked.includes("of the 2 agents it runs here"), "project runners: the confirmation names the agents running now, not at the last refresh");
  win.Maity.api.getAll = prAll1;
  win.confirm = (q) => { prAsked = q; return true; };
  btn(prCard("home-laptop"), "Detach").click(); for (let k = 0; k < 4; k++) await tick();
  expect(prAsked === "Detach home-laptop from Maity? The hub closes the placement of the 1 agent it runs here, and the runner stops it."
    && JSON.stringify(prWrites[1]) === JSON.stringify(["DELETE", "/projects/maity/runners/rnr-0002"]) && !prCard("home-laptop")
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
  await prPost("/projects/maity/runners", { runner_id: "rnr-0002" });
  // A refusal fails loud, as in every view; the empty state; no tab for a member.
  const prAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/runners" ? Promise.reject(new win.Maity.api.ApiError("nope", 404, p, "not_found")) : prAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/runners"); await tick();
  expect(main.querySelector(".error") && !text(main).includes("cannot allow runners"), "project runners: a 404 is an error, not a missing feature");
  win.Maity.api.getAll = (p) => (p === "/projects/maity/runners" || p === "/runners" ? Promise.resolve({ items: [], next_cursor: null }) : prAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/runners"); await tick();
  expect(text(main).includes("No runner is allowed in this project yet.") && text(main).includes("You have no runner yet. Pair one on the Runners page."),
    "project runners: the empty state points to pairing");
  win.Maity.api.getAll = prAll;
  const prGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? prGet(p).then((m) => { m.projects.find((x) => x.slug === "maity").role = "member"; return m; }) : prGet(p));
  await go("#/p/maity/runners"); await tick();
  expect(!prTab() && text(main).includes("No such view."), "project runners: no tab and no view for a member");
  win.Maity.api.get = prGet;
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();

  // Runners (docs/api.md §15): the instance-level view.
  const runnersLink = header.querySelectorAll(".switcher a").find((a) => a.textContent === "Runners");
  expect(runnersLink && runnersLink.getAttribute("href") === "#/runners", "runners: a link beside the projects");
  const rWrites = [];
  const rPost = win.Maity.api.post, rPatch = win.Maity.api.patch, rDel = win.Maity.api.del;
  win.Maity.api.post = (p, b) => { rWrites.push(["POST", p, b]); return rPost(p, b); };
  win.Maity.api.patch = (p, b) => { rWrites.push(["PATCH", p, b]); return rPatch(p, b); };
  win.Maity.api.del = (p) => { rWrites.push(["DELETE", p]); return rDel(p); };
  await go("#/runners"); await tick();
  const card = (name) => main.querySelectorAll("article.runner").find((a) => a.getAttribute("aria-label") === name);
  expect(plainTitle() === "Runners · Maity" && main.querySelectorAll("article.runner").length === 3, "runners: the view lists the runners");
  const laptop = text(card("home-laptop"));
  expect(laptop.includes("online") && laptop.includes("this machine") && laptop.includes("Allowed in maity.")
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
  expect(JSON.stringify(rWrites[0]) === JSON.stringify(["POST", "/runners/enrollments", { name: "new-laptop", ttl_seconds: 900, attach: ["maity", "sample"] }]),
    "runners: pairing asks for an enrollment that allows the chosen projects");
  const steps = main.querySelector(".pair-steps");
  const config = text(steps.querySelector(".runner-config"));
  expect(text(steps).includes("maity runner pair https://maity.example/r/FIXTURE-") && text(steps).includes("pipx install")
    && text(steps).includes("maity runner check") && text(steps).includes("maity runner serve"), "runners: the steps: install, configure, pair, check, serve");
  expect(config.includes('url = "https://maity.example"') && config.includes('projects = ["maity", "sample"]')
    && config.includes('"github.com/oliver-zehentleitner/maity"') && config.includes('"github.com/example/sample-shop"')
    && config.includes("[harness.claude-code]") && config.includes('layout = "single"') && !config.includes("FIXT-URE0") && !config.includes("/r/FIXTURE"),
    "runners: the starter configuration names the hub, the projects and their repositories, and no secret");
  expect(["state_dir", "workspaces", "tmux_socket", "max_agents", "default_mode", "default_model", "binary"].every((k) => !config.includes(k + " =")),
    "runners: the starter configuration holds only the keys without a default");
  expect(text(steps).includes("installs the repository's current main, which has maity runner pair and maity runner check")
    && text(steps).includes("(with the next runner release; not in the CLI yet)"),
    "runners: the steps say what the CLI has today and what is still to come");
  const hostile = win.Maity.runnerStarterConfig("https://h.example", [{ slug: "a\"b\\c\u007f\n\ud800", repository: null }]);
  expect(hostile.includes('projects = ["a\\"b\\\\c\\u007f\\u000a\ufffd"]'), "runners: TOML strings escape quotes, backslashes, control characters and DEL; a lone surrogate is replaced");
  expect(win.Maity.runnerStarterConfig("https://h.example", []).includes("projects = []   # none chosen"), "runners: no project chosen is said in the configuration");
  expect(win.Maity.runnerConfigCommand("x\n").includes("(set -C; umask 077; cat > ~/.config/maity-runner/runner.toml) <<'EOF'\nx\nEOF"),
    "runners: the command writes the configuration owner-only and never over an existing one");
  expect(text(main).includes("Open pairings") && text(main).includes("new-laptop"), "runners: the open pairing is listed, revocable");
  // A hub before attachments refuses `attach`: paired without it, and said.
  const rPost2 = win.Maity.api.post;
  const attachTries = [];
  win.Maity.api.post = (p, b) => {
    attachTries.push(b);
    return p === "/runners/enrollments" && b.attach && b.attach.length
      ? Promise.reject(new win.Maity.api.ApiError("attachments are not available yet", 400, p, "invalid", { fields: { attach: "not_supported_yet" } }))
      : rPost2(p, b);
  };
  byId("pair-name").value = "older-hub";
  main.querySelector("form.pair-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(attachTries.length === 2 && !("attach" in attachTries[1]) && main.querySelector(".pair-steps")
    && text(main).includes("cannot allow the runner in projects while pairing yet"), "runners: without attachments in the hub, paired without them and said so");
  win.Maity.api.post = rPost2;
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
  btn(card("builder"), "Revoke").click(); await tick(); await tick(); await tick();
  expect(text(card("builder")).includes("revoked") && !btn(card("builder"), "Revoke"), "runners: revoked, no second Revoke");
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
  await go("#/p/maity/inbox");

  // Why: the Keep the Why export (docs/api.md §11.3), from the published maity.dev family.
  const whyTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Why");
  expect(whyTab() && whyTab().getAttribute("href") === "#/p/maity/why", "why: a tab where the hub has the export");
  const whyGets = [];
  const realGet6 = win.Maity.api.get;
  win.Maity.api.get = (p) => { whyGets.push(p); return realGet6(p); };
  await go("#/p/maity/why");
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
  expect(whyGets.includes("/projects/maity/keep-the-why?max_age=0"), "why: Read again asks for a fresh read");
  // A member that fails, a root that cannot be read, strings and links from the export.
  const baseAnswer = await realGet6("/projects/maity/keep-the-why");
  const withFailed = JSON.parse(JSON.stringify(baseAnswer));
  withFailed.members[3].error = { code: "ktw_unavailable", reason: "timeout" };
  withFailed.summary.failed = 1;
  withFailed.attention.push({ member: "web", id: "x", uuid: null, title: "<b>not markup</b>", type: ["question"], status: "needs-review",
    file: "views.md", topic: null, link: "javascript:alert(1)" });
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why") ? Promise.resolve(withFailed) : realGet6(p));
  await go("#/p/maity/board"); await go("#/p/maity/why");
  const webRow = main.querySelectorAll(".why-members tbody tr")[3];
  expect(webRow.className === "failed" && text(webRow).includes("Could not be read: its state.json did not answer in time. Shown is its last good read.")
    && text(main).includes("· 1 could not be read"), "why: a part that fails is named with its reason and its last good read");
  const odd = main.querySelectorAll(".why-entries li").find((li) => li.textContent.includes("<b>not markup</b>"));
  expect(odd && !odd.querySelector("a") && !odd.querySelector("b"), "why: an export's strings are text, a link that is not https is none");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why")
    ? Promise.reject(new win.Maity.api.ApiError("root unreadable", 503, p, "ktw_unavailable", { reason: "forge_unavailable", last: Object.assign({}, baseAnswer, { fresh: false }) }))
    : realGet6(p));
  await go("#/p/maity/board"); await go("#/p/maity/why");
  expect(text(main).includes("The hub could not read the project's root .keep-the-why just now (the forge did not give the hub the repository's root .keep-the-why). Shown is its last good read")
    && main.querySelectorAll(".why-members tbody tr").length === 4, "why: the root unreadable, the last good read is shown and said so");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why")
    ? Promise.reject(new win.Maity.api.ApiError("root unreadable", 503, p, "ktw_unavailable", { reason: "forge_unavailable" })) : realGet6(p));
  await go("#/p/maity/board"); await go("#/p/maity/why");
  expect(text(main).includes("could not read the project's root .keep-the-why") && !main.querySelector(".why-members") && btn(main, "Read again"),
    "why: no last read, only the note, and Read again");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why") ? Promise.reject(new win.Maity.api.ApiError("boom", 500, p, "internal")) : realGet6(p));
  await go("#/p/maity/board"); await go("#/p/maity/why");
  expect(main.querySelector(".error") && btn(main, "Read again"), "why: any other error, with Read again");
  // Read again is off while its read runs.
  let release;
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why?max_age=0") ? new Promise((r) => { release = () => r(baseAnswer); }) : realGet6(p));
  const again = btn(main, "Read again"); again.click(); await tick();
  expect(again.disabled === true, "why: Read again is disabled while a read runs");
  release(); await tick(); await tick();
  expect(btn(main, "Read again") && !btn(main, "Read again").disabled, "why: and on again after it");
  // Linter counts per field; an entry link outside its part's dashboard is no link.
  const odd2 = JSON.parse(JSON.stringify(baseAnswer));
  odd2.members[1].summary.findings = { errors: 2, warnings: null };
  odd2.attention.push({ member: "hub", id: "y", uuid: "u", title: "Elsewhere", type: [], status: "open", file: "a.md", topic: null,
    link: "https://maity.dev/keep-the-why-dashboard/#entry/u" });
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/keep-the-why") ? Promise.resolve(odd2) : realGet6(p));
  await go("#/p/maity/board"); await go("#/p/maity/why");
  expect(text(main.querySelectorAll(".why-members tbody tr")[1]).includes("2 errors, — warnings"), "why: a missing linter count is shown as such, per field");
  const elsewhere = main.querySelectorAll(".why-entries li").find((li) => li.textContent.includes("Elsewhere"));
  expect(elsewhere && !elsewhere.querySelector("a"), "why: an entry link that leaves its part's dashboard is no link");
  win.Maity.api.get = realGet6;
  await go("#/p/sample/why");
  expect(text(main).includes("This project publishes no Keep the Why dashboard yet.") && text(main).includes("dashboard-state line") && btn(main, "Read again"),
    "why: not configured, said so with what the hub reads");
  // A hub that does not know the export: no tab.
  win.Maity.api.get = (p) => (p === "/projects/maity" ? realGet6(p).then((v) => { delete v.keep_the_why_export; return v; }) : realGet6(p));
  await go("#/p/maity/inbox");
  expect(!whyTab(), "why: no tab where the hub has no export field");
  win.Maity.api.get = realGet6;
  await go("#/p/maity/org");
  const tree = main.querySelector(".org-tree");
  expect(tree.childNodes.length === 1 && text(tree).includes("(by area)") && text(main).includes("Policy: hierarchical"), "org tree by areas, policy preset");

  // Presence is re-read in place; nothing else on the page is replaced.
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const realGet3 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maity/members"
    ? realGet3(p).then((r) => { r.items.forEach((m) => { m.presence = "away"; }); return r; })
    : realGet3(p));
  const pauseBefore = main.querySelector("form.pause");
  await fireIntervals(); await tick(); await tick();
  const labels = main.querySelectorAll("span.presence");
  expect(labels.length > 0 && labels.every((l) => l.textContent === "Away"), "presence re-read in place");
  expect(main.querySelector("form.pause") === pauseBefore, "the presence refresh keeps the forms");
  win.Maity.api.get = realGet3;

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
  expect(AV({ id: "agt-a", avatar_url: "/api/v1/projects/maity/logo?v=1" }).tagName === "IMG", "avatars: a picture the page may load wins");
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const profA = main.querySelectorAll("article.profile").find((a) => a.getAttribute("aria-label") === "Agent A");
  expect(profA.querySelector("header").querySelector("svg") && profA.querySelector("header").querySelector("svg").style["--avatar-h"] === "340", "avatars: on the agent's card");
  await go("#/p/maity/org");
  expect(main.querySelectorAll(".org-node svg").length === main.querySelectorAll(".org-node").length, "avatars: in the organisation, one per member");
  // Managing cards on the board (docs/api.md §6.4).
  const T = win.Maity.boardEdit.targets;
  const bctx = { me: { id: "hum-maintainer" }, role: "owner", project: { policy: { done_authority: "reviewer" } } };
  const tc = (status, extra) => Object.assign({ id: "x", status, created_by: "agt-a", claim: null }, extra || {});
  expect(JSON.stringify(T(bctx, tc("proposed"))) === JSON.stringify(["open", "cancelled"])
    && JSON.stringify(T(bctx, tc("review"))) === JSON.stringify(["done", "in_progress", "cancelled"])
    && JSON.stringify(T(bctx, tc("in_progress"))) === JSON.stringify(["cancelled"]) && !T(bctx, tc("done")).length,
    "board: an owner's moves, as the hub allows them");
  const mctx = Object.assign({}, bctx, { role: "member" });
  expect(!T(mctx, tc("proposed")).length && JSON.stringify(T(mctx, tc("open", { created_by: "hum-maintainer" }))) === JSON.stringify(["proposed", "cancelled"])
    && !T(mctx, tc("review")).length && JSON.stringify(T(Object.assign({}, mctx, { role: "reviewer" }), tc("review"))) === JSON.stringify(["done", "in_progress"]),
    "board: a member moves only its own cards; a reviewer has done authority");
  expect(JSON.stringify(T(Object.assign({}, mctx, { project: { policy: { done_authority: "holder" } } }), tc("in_progress", { claim: { holder: "hum-maintainer" } }))) === JSON.stringify(["done"]),
    "board: with holder authority the holder moves its card to done");
  const bWrites = [];
  const bPatch = win.Maity.api.patch, bPost = win.Maity.api.post;
  win.Maity.api.patch = (p, b) => { bWrites.push(["PATCH", p, b]); return bPatch(p, b); };
  win.Maity.api.post = (p, b) => { bWrites.push(["POST", p, b]); return bPost(p, b); };
  await go("#/p/maity/board");
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
  expect(bWho && text(bWho).includes("@agent-c") && bWho.getAttribute("href") === "#/p/maity/members/agt-c" && bWho.getAttribute("title") === "Agent C" && bWho.getAttribute("aria-label") === "Assigned to Agent C"
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
  expect(JSON.stringify(bWrites[0]) === JSON.stringify(["PATCH", "/projects/maity/tasks/tsk-0008", { status: "open" }])
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
  expect(JSON.stringify(bWrites[1]) === JSON.stringify(["PATCH", "/projects/maity/tasks/tsk-0008", { status: "proposed" }]) && colOf("tsk-0008").attrs["data-status"] === "proposed",
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
  expect(JSON.stringify(bWrites[bWrites.length - 1]) === JSON.stringify(["POST", "/projects/maity/tasks/tsk-0006/assign", { assignee: "agt-d" }])
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
  expect(JSON.stringify(bWrites[ordBefore]) === JSON.stringify(["POST", "/projects/maity/tasks/tsk-0009/move", { after: "tsk-0001" }])
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
  expect(JSON.stringify(bWrites[bWrites.length - 1]) === JSON.stringify(["POST", "/projects/maity/tasks/tsk-0009/move", { before: "tsk-0007" }])
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
  try { await bPost("/projects/maity/tasks/tsk-0001/move", { before: "tsk-0006" }); } catch (err) { otherCol = err; }
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
  const fixtureSearch = await savedGetAll("/projects/maity/tasks?status=all&q=" + encodeURIComponent("ＴＳＫ－０００６"));
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
  expect(!bWrites.some((w) => w[1] === "/projects/maity/tasks") && text(main).includes("Not created: the card needs a title"), "board: no card without a title");
  byId("new-card-title").value = "Web: a card from the board";
  byId("new-card-area").value = "web/board/";
  byId("new-card-status").value = "open";
  byId("new-card-label").value = "feature";
  byId("new-card-assigned").value = "agt-d";
  byId("new-card-depends").querySelectorAll("option").find((o) => o.attrs.value === "tsk-0007").selected = true;
  nf.dispatch("submit"); for (let k = 0; k < 5; k++) await tick();
  const createdW = bWrites.find((w) => w[1] === "/projects/maity/tasks");
  expect(JSON.stringify(createdW) === JSON.stringify(["POST", "/projects/maity/tasks", { title: "Web: a card from the board", kind: "task", status: "open",
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
  try { await bPost("/projects/maity/tasks", { title: "x", ships_with: ["rel-0001"] }); } catch (err) { relShip = err; }
  expect(relShip && relShip.details.fields.ships_with === "release_card", "board: the mock refuses shipping with a release, as the hub does");
  win.Maity.api.patch = bPatch; win.Maity.api.post = bPost;
  // A frozen project asks for a reason.
  await go("#/p/sample/board");
  btn(main, "New card").click(); await tick();
  byId("new-card-title").value = "Something during the freeze";
  main.querySelector("form.new-card").dispatch("submit"); await tick();
  expect(byId("new-card-reason") && text(main).includes("Not created: the project is in freeze"), "board: in freeze a new card needs a reason");
  await go("#/p/maity/inbox");
  // Members (docs/api.md §6.2): humans and agents, managed by an admin.
  const membersTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Members");
  expect(membersTab && membersTab.getAttribute("href") === "#/p/maity/members", "members: a tab");
  await go("#/p/maity/members");
  const mRow = (name) => main.querySelectorAll("tr.member").find((tr) => tr.querySelector(".member-name").textContent === name);
  const tables = main.querySelectorAll("table.members");
  expect(plainTitle() === "Members · Maity · Maity" && tables.length === 2 && tables[0].querySelectorAll("tr.member").length === 1
    && tables[1].querySelectorAll("tr.member").length === 5 && text(main).includes("Humans (1)") && text(main).includes("Agents (5)"),
    "members: humans first, then agents");
  const ths = tables[1].querySelector("thead").querySelectorAll("th").map((t) => t.textContent);
  expect(JSON.stringify(ths) === JSON.stringify(["Name", "Role", "Owner", "Presence", "Joined", "Paused", "Credentials", "Actions"]),
    "members: an admin's agent columns, with owner and credentials " + JSON.stringify(ths));
  expect(text(mRow("Agent C")).includes("paused itself") && text(mRow("Agent C")).includes("Waiting for the API contract")
    && mRow("Agent C").classList.contains("paused"), "members: a paused agent says by whom and why");
  expect(text(mRow("Agent A")).includes("Maintainer") && / active/.test(text(mRow("Agent A"))) && text(mRow("Maintainer")).includes("owner"),
    "members: owner and a credentials summary");
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
  win.Maity.api.getAll = (p) => pAll(p).then((r) => (p !== "/projects/maity/members" ? r
    : { items: r.items.map((x) => (x.id === "agt-d" ? Object.assign({}, x, { presence: "away" }) : x)), next_cursor: null }));
  await fireIntervals(); await tick(); await tick();
  expect(main.querySelector("tr.member-manage select") === openSelect && text(mRow("Agent D")).includes("Away"), "members: presence refreshed in place, the open row untouched");
  win.Maity.api.getAll = pAll;
  elProto.focus = focus0; document.activeElement = undefined;
  const dManage = main.querySelector("tr.member-manage");
  expect(dManage && btn(mRow("Agent D"), "Done") && btn(mRow("Agent D"), "Done").getAttribute("aria-expanded") === "true", "members: Manage opens the row");
  const dRole = dManage.querySelector("select"); dRole.value = "reviewer";
  dManage.querySelector("form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[0]) === JSON.stringify(["PATCH", "/projects/maity/members/agt-d", { role: "reviewer" }]) && text(mRow("Agent D")).includes("reviewer"),
    "members: the role changed");
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); await tick();
  expect(mWrites.length === 1, "members: no pause without a reason");
  main.querySelector("tr.member-manage form.member-pause input").value = "quota";
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[1][2]) === JSON.stringify({ paused: { reason: "quota" } }) && text(mRow("Agent D")).includes("quota"), "members: an agent paused with a reason");
  btn(main.querySelector("tr.member-manage"), "Clear pause").click(); for (let k = 0; k < 4; k++) await tick();
  main.querySelector("tr.member-manage select").value = "member";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(mRow("Agent D")).includes("quota") && text(mRow("Agent D")).includes("member"), "members: pause cleared, role back");
  btn(mRow("Agent D"), "Done").click(); await tick();
  btn(mRow("Maintainer"), "Manage").click(); await tick();
  const ownerSel = main.querySelector("tr.member-manage select");
  expect(ownerSel.querySelectorAll("option").length === 5 && !main.querySelector("tr.member-manage form.member-pause"), "members: a human can be owner, has no pause");
  ownerSel.value = "admin";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Saving failed: The project's last owner cannot be demoted or removed.") && text(mRow("Maintainer")).includes("owner"),
    "members: the last owner is not demoted, said in words");
  btn(mRow("Maintainer"), "Done").click(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  expect(main.querySelector("tr.member-manage select").querySelectorAll("option").every((o) => o.attrs.value !== "owner"), "members: an agent is never offered owner");
  let mAsked = "";
  const mConfirm = win.confirm;
  win.confirm = (q) => { mAsked = q; return true; };
  btn(main.querySelector("tr.member-manage"), "Remove from the project").click(); for (let k = 0; k < 4; k++) await tick();
  win.confirm = mConfirm;
  expect(mAsked === "Remove Reviewer from Maity? Its credentials are revoked and the cards it claimed are released."
    && JSON.stringify(mWrites[mWrites.length - 1]) === JSON.stringify(["DELETE", "/projects/maity/members/agt-r"]), "members: removing asks first and says what it does");
  // The full edit (docs/api.md §6.2): reports to, areas, capabilities, briefing, in one PATCH.
  win.Maity.api.patch = mPatch; win.Maity.api.del = mDel;
  const eWrites = [];
  win.Maity.api.patch = (p, b) => { eWrites.push([p, b]); return mPatch(p, b); };
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const eRow = () => main.querySelector("tr.member-manage");
  const eSel = (i) => eRow().querySelectorAll("select")[i];
  const eIn = () => eRow().querySelector("form.member-edit").querySelectorAll("input");
  const submitEdit = async () => { eRow().querySelector("form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick(); };
  expect(eSel(1).value === "agt-a" && !eSel(1).querySelectorAll("option").some((o) => o.attrs.value === "agt-r")
    && eSel(1).querySelectorAll("option")[0].textContent === "nobody", "members: reports to offers nobody and everyone else, set to the current one");
  await submitEdit();
  expect(!eWrites.length && text(main).includes("Nothing changed."), "members: nothing changed, nothing sent");
  expect(!eRow().querySelector("textarea") && text(eRow()).includes("The briefing is edited on the agent's card"), "members: one briefing editor, on the agent's card");
  eSel(1).value = "agt-d"; eSel(1).dispatch("change");
  eIn()[0].value = "docs/, web/tools/, docs/"; eIn()[0].dispatch("input");
  eIn()[1].checked = true; eIn()[1].dispatch("change");
  // Edits survive a redraw (here: another row opened and closed, each a
  // rebuild of the table), and are sent as typed.
  const formBefore = eRow().querySelector("form.member-edit");
  const pauseIn = () => eRow().querySelector(".member-pause input");
  pauseIn().value = "quota, half typed"; pauseIn().dispatch("input");
  btn(mRow("Agent D"), "Manage").click(); await tick();
  btn(mRow("Agent D"), "Done").click(); await tick();
  expect(eRow().querySelector("form.member-edit") !== formBefore && eSel(1).value === "agt-d" && eIn()[0].value === "docs/, web/tools/, docs/" && eIn()[1].checked,
    "members: unsaved edits survive a redraw");
  expect(pauseIn().value === "quota, half typed", "members: a half-typed pause reason survives a redraw too");
  await submitEdit();
  expect(JSON.stringify(eWrites[0]) === JSON.stringify(["/projects/maity/members/agt-r",
    { reports_to: "agt-d", areas: ["docs/", "web/tools/"], capabilities: ["tag"] }])
    && text(main).includes("Saved for Reviewer: reports to, areas, capabilities."), "members: one PATCH with exactly what changed");
  // A circle is refused before sending: Agent D would report to the Reviewer, who reports to Agent D.
  btn(mRow("Reviewer"), "Done").click(); await tick();
  btn(mRow("Agent D"), "Manage").click(); await tick();
  eSel(1).value = "agt-r";
  await submitEdit();
  expect(eWrites.length === 1 && text(main).includes("Not saved: That would close a circle") && eSel(1).getAttribute("aria-invalid") === "true"
    && text(byId("member-reports-agt-d-error")).includes("close a circle") && eSel(1).getAttribute("aria-describedby") === "member-reports-agt-d-error", "members: a reports-to circle is refused before sending, at its field");
  eSel(1).value = "";
  eIn()[0].value = "../secret";
  await submitEdit();
  expect(eWrites.length === 1 && text(main).includes("Not saved: An area is a repository path"), "members: an area with .. is refused before sending");
  btn(mRow("Agent D"), "Done").click(); await tick();
  // The hub's own cycle refusal reads the same.
  win.Maity.api.patch = (p, b) => Promise.reject(new win.Maity.api.ApiError("cycle", 400, p, "invalid", { fields: { reports_to: "cycle" } }));
  btn(mRow("Agent C"), "Manage").click(); await tick();
  eSel(1).value = "agt-d";
  await submitEdit();
  expect(text(main).includes("Saving failed: That would close a circle"), "members: the hub's cycle refusal in the same words");
  btn(mRow("Agent C"), "Done").click(); await tick();
  win.Maity.api.patch = mPatch;
  // The organisation follows at once.
  await go("#/p/maity/org");
  const orgNode = (name) => main.querySelectorAll(".org-tree li").find((li) => li.querySelector(".org-node strong").textContent === name);
  expect(orgNode("Agent D").querySelector("ul") && text(orgNode("Agent D").querySelector("ul")).includes("Reviewer"), "members: the organisation shows the Reviewer under Agent D");
  // The mock refuses a circle as the hub does (docs/api.md §6.2, #118); a removal clearing reports_to is checked with the removal below.
  let circle = null;
  try { await mPatch("/projects/maity/members/agt-d", { reports_to: "agt-r" }); } catch (err) { circle = err; }
  expect(circle && circle.details.fields.reports_to === "cycle", "members: the mock refuses a circle with cycle");
  // Atomic as the hub: one bad field, nothing written, every bad field named.
  let atomic = null;
  try { await mPatch("/projects/maity/members/agt-r", { role: "member", areas: ["../x"], capabilities: ["fly"] }); } catch (err) { atomic = err; }
  const afterBad = (await win.Maity.api.getAll("/projects/maity/members")).items.find((x) => x.id === "agt-r");
  expect(atomic && atomic.details.fields.areas === "invalid_path" && atomic.details.fields.capabilities === "unknown" && afterBad.role !== "member",
    "members: the mock checks every field before it writes anything");
  await mPatch("/projects/maity/members/agt-r", { reports_to: "agt-a", areas: [], capabilities: [] });
  // A boss not in the list read stays chosen (and is not sent as nobody).
  const nlGet = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => nlGet(p).then((r) => (p !== "/projects/maity/members" ? r
    : { items: r.items.map((x) => (x.id === "agt-r" ? Object.assign({}, x, { reports_to: "agt-gone" }) : x)), next_cursor: null }));
  await go("#/p/maity/members");
  await fireIntervals(); await tick(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const nlSent = [];
  win.Maity.api.patch = (p, b) => { nlSent.push(b); return Promise.resolve(Object.assign({ id: "agt-r", kind: "agent" }, b)); };
  expect(eSel(1).value === "agt-gone" && text(eSel(1)).includes("(not in this list)"), "members: a boss not in the list stays chosen");
  eSel(0).value = "member"; eSel(0).dispatch("change");
  await submitEdit();
  expect(nlSent.length === 1 && !("reports_to" in nlSent[0]), "members: saving the role leaves an unlisted boss alone");
  win.Maity.api.patch = mPatch; win.Maity.api.getAll = nlGet;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // A change that waits for a human's go (202, the consent request) is no "Saved".
  const consents = [];
  win.Maity.api.patch = (p, b) => { consents.push(b); return Promise.resolve({ id: "req-c009", class: "consent", status: "open", to: "owner", title: "Change reviewer to member" }); };
  await go("#/p/maity/members");
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel(0).value = "member"; eSel(0).dispatch("change");
  await submitEdit();
  expect(text(main).includes("Not changed yet: waiting for the owner's consent (req-c009, Change reviewer to member).") && !text(main).includes("Saved for Reviewer"),
    "members: a change waiting for consent says so, and not that it was saved");
  // The form shows the member as it is again, so a second Save asks nothing twice.
  expect(eSel(0).value === "reviewer", "members: after a consent request the form shows the hub's state, not the draft");
  await submitEdit();
  expect(consents.length === 1 && text(main).includes("Nothing changed."), "members: saving again after a consent request files no second one");
  win.Maity.api.patch = mPatch;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // Done drops a row's unsaved edits.
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel(0).value = "member"; eSel(0).dispatch("change");
  btn(mRow("Reviewer"), "Done").click(); await tick();
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  expect(eSel(0).value === "reviewer", "members: Done drops the row's unsaved edits");
  btn(mRow("Reviewer"), "Done").click(); await tick();
  // A drafted boss who has left since is dropped and said, never sent as nobody.
  const goneSent = [];
  win.Maity.api.patch = (p, b) => { goneSent.push(b); return mPatch(p, b); };
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  eSel(1).value = "agt-c"; eSel(1).dispatch("change");
  const gGet = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => gGet(p).then((r) => (p !== "/projects/maity/members" ? r : { items: r.items.filter((x) => x.id !== "agt-c"), next_cursor: null }));
  await fireIntervals(); await tick(); await tick();
  expect(eSel(1).value === "agt-a" && text(eRow()).includes("whom you picked, is no longer a member"), "members: a drafted boss who left is dropped, and said");
  eIn()[0].value = "docs/"; eIn()[0].dispatch("input");
  await submitEdit();
  expect(goneSent.length === 1 && !("reports_to" in goneSent[0]), "members: saving then leaves the boss as it is");
  win.Maity.api.getAll = gGet;
  await mPatch("/projects/maity/members/agt-r", { areas: [] });
  win.Maity.api.patch = mPatch;
  btn(mRow("Reviewer"), "Done").click(); await tick();
  await go("#/p/maity/members");
  // A write that went through is said as done when the re-read fails.
  win.Maity.api.patch = mPatch; win.Maity.api.del = mDel;
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const rAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/members" ? Promise.reject(new win.Maity.api.ApiError("down", 0, p)) : rAll(p));
  main.querySelector("tr.member-manage select").value = "proxy";
  main.querySelector("tr.member-manage form.member-edit").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Saved for Reviewer: role. Could not refresh: down") && !text(main).includes("Saving failed"),
    "members: a failed re-read after a write is no failed write");
  win.Maity.api.getAll = rAll;
  await win.Maity.api.patch("/projects/maity/members/agt-r", { role: "reviewer" });
  // The mock as the hub: removal revokes, releases claims, and answers again as it is.
  const credsBefore = (await win.Maity.api.getAll("/projects/sample/members/agt-s1/credentials")).items.filter((c) => !c.revoked_at).length;
  await win.Maity.api.patch("/projects/sample/members/hum-maintainer", { reports_to: "agt-s1" });
  const removedS = await win.Maity.api.del("/projects/sample/members/agt-s1");
  const sampleOwner = (await win.Maity.api.getAll("/projects/sample/members")).items.find((x) => x.id === "hum-maintainer");
  expect(sampleOwner.reports_to === null, "members: the mock's removal clears reports_to on whoever reported to the removed member");
  const removedAgain = await win.Maity.api.del("/projects/sample/members/agt-s1");
  const tasksAfter = (await win.Maity.api.getAll("/projects/sample/tasks?status=all")).items;
  const credsAfter = (await win.Maity.api.getAll("/projects/sample/members/agt-s1/credentials")).items;
  expect(credsBefore > 0 && removedS.removed_at && removedAgain.removed_at === removedS.removed_at
    && credsAfter.every((c) => c.revoked_at) && !tasksAfter.some((t) => t.claim && t.claim.holder === "agt-s1"),
    "members: the mock's DELETE revokes, releases, and answers a second time as it is");
  // A plain member: no actions, no owner or credentials from the hub.
  const mGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? mGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").role = "member"; return x; })
    : p === "/projects/maity/members" ? mGet(p).then((x) => ({ items: x.items.map((y) => { const o = Object.assign({}, y); delete o.owner; delete o.credentials; return o; }), next_cursor: null }))
      : mGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/members");
  const ths2 = main.querySelectorAll("table.members")[1].querySelector("thead").querySelectorAll("th").map((t) => t.textContent);
  expect(!btn(main, "Manage") && !ths2.includes("Credentials") && !ths2.includes("Actions") && text(mRow("Agent A")).includes("Maintainer"),
    "members: a member reads the list without actions; the owner from the members");
  win.Maity.api.get = mGet;

  // Message the project (docs/api.md §8.4): from the inbox, no tab of its own.
  await go("#/p/maity/inbox");
  const msgLink = main.querySelectorAll("a").find((a) => a.textContent === "Message the project");
  expect(msgLink && msgLink.getAttribute("href") === "#/p/maity/message"
    && !header.querySelectorAll("nav.views a").some((a) => a.textContent === "Message the project"), "message: a link in the inbox, no tab");
  const msgPosts = [];
  const mPost0 = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { msgPosts.push([p, b]); return mPost0(p, b); };
  await go("#/p/maity/message");
  const toOpts = byId("message-to").querySelectorAll("option").map((o) => o.attrs.value);
  expect(plainTitle() === "Message the project · Maity · Maity" && toOpts[0] === "all" && toOpts.includes("role:reviewer") && toOpts.includes("agt-b")
    && !toOpts.includes("hum-maintainer") && byId("message-type").value === "notice", "message: to everyone, a role or a member (not oneself); a notice by default");
  main.querySelector("form.message-form").dispatch("submit"); await tick();
  expect(!msgPosts.length && text(main).includes("Not sent: the message is empty"), "message: an empty one is not sent");
  byId("message-to").value = "role:reviewer"; byId("message-type").value = "handover"; byId("message-card").value = "tsk-0006";
  byId("message-body").value = "Please look at the join path, @agent-b; mail x@agent-c is no mention.";
  main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(msgPosts[0]) === JSON.stringify(["/projects/maity/events", { kind: "message", type: "handover", to: "role:reviewer",
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
  expect(byId("message-to").querySelectorAll("option").some((o) => o.attrs.value === "role:owner"), "message: the owner is a role to write to");
  let badRole = null;
  try { await mPost0("/projects/maity/events", { kind: "message", type: "notice", to: "role:wizard", body: "x" }); } catch (err) { badRole = err; }
  let chatNoConv = null;
  try { await mPost0("/projects/maity/events", { kind: "message", type: "chat", to: "agt-a", body: "x" }); } catch (err) { chatNoConv = err; }
  expect(badRole && badRole.details.fields.to && chatNoConv && chatNoConv.details.fields.conversation_id === "missing", "message: the mock refuses an unknown role and a chat without its conversation");
  // From a chat: an @name there tells nobody; the hint offers a project message with it.
  await go("#/p/maity/chat/agt-d");
  const chatText = byId("chat-text");
  const hintEl = () => main.querySelector(".mention-hint");
  expect(hintEl() && hintEl().hidden, "message: no hint while the chat has no @name");
  chatText.value = "Ask @agent-c about the join path"; chatText.dispatch("input");
  const hintLink = hintEl().querySelector("a");
  expect(!hintEl().hidden && text(hintEl()).includes("In this chat @agent-c notifies nobody.") && hintLink
    && hintLink.getAttribute("href") === "#/p/maity/message/%40agent-c", "message: a chat's @name is said to notify nobody, with a project message offered");
  chatText.value = "mail me@agent-c"; chatText.dispatch("input");
  expect(hintEl().hidden, "message: an @ inside a word gives no hint");
  chatText.value = "run `@agent-c` or\n```\n@agent-c\n```"; chatText.dispatch("input");
  expect(hintEl().hidden, "message: an @name in code gives no hint, as the hub skips code");
  chatText.value = ""; chatText.dispatch("input");
  // Opened from a chat with the @name in it.
  await go("#/p/maity/message/" + encodeURIComponent("@agent-c"));
  expect(byId("message-body").value === "@agent-c ", "message: opened with an @name already written");

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
    && mdBlock.querySelector(".md-code-bar .md-lang"), "markdown: a code block is a named region, its Copy names it, the bar sits above the code");
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
  await go("#/p/maity/chat");
  const convs = () => main.querySelectorAll(".chat-list a.conv");
  const conv = (name) => convs().find((a) => a.querySelector(".conv-title").textContent === name);
  // Own agents' direct chats and the fixtures' one group chat (§9.3).
  expect(convs().length === 6 && text(main).includes("Pick a conversation.") && !main.querySelector(".chat-pane"), "chat: the list of own agents and group chats, nothing open yet");
  // Unread first (the group chat with a mention, Agent A), then the newest; without messages last.
  const convOrder = () => convs().map((a) => a.querySelector(".conv-title").textContent + (a.classList.contains("unread") ? "*" : ""));
  expect(JSON.stringify(convOrder()) === JSON.stringify(["Release 0.2 go/no-go*", "Agent A*", "Agent D", "Agent B", "Agent C", "Reviewer"]),
    "chat: unread first, then the newest, the ones without messages after " + JSON.stringify(convOrder()));
  const convA = conv("Agent A");
  expect(convA.getAttribute("href") === "#/p/maity/chat/agt-a" && text(convA).includes("Endpoints for join, tasks and requests are drafted.")
    && convA.querySelector(".count") && convA.querySelector(".count").textContent === "1" && convA.classList.contains("unread")
    && text(convA).includes("online") && convA.querySelector(".avatars svg").style["--avatar-h"] === "340",
    "chat: an entry has the agent, the last message, its time, the unread count, presence and an avatar");
  expect(text(conv("Agent D")).includes("You: Keep the inbox usable"), "chat: one's own last message reads You:");
  expect(!conv("Agent B").querySelector(".preview") && text(conv("Agent C")).includes("paused"), "chat: no messages, no preview; presence in words");
  // Names that share their owner's long prefix (Oliver's list: every row read "Oliver Zehentleit…"): whole, wrapped, and told apart.
  const clLong = (r) => ({ items: r.items.map((m) => (m.kind === "agent" && m.owner_id === "hum-maintainer"
    ? Object.assign({}, m, { display_name: "Oliver Zehentleitner " + m.display_name, handle: "oz-" + m.handle }) : m)), next_cursor: null });
  const clGet = win.Maity.api.getAll, clGet1 = win.Maity.api.get;
  win.Maity.api.getAll = (p) => (p.startsWith("/projects/maity/members") ? clGet(p).then(clLong) : clGet(p));
  win.Maity.api.get = (p) => (p === "/projects/maity/members" ? clGet1(p).then(clLong) : clGet1(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat"); for (let k = 0; k < 4; k++) await tick();
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
  await go("#/p/maity/inbox"); await go("#/p/maity/chat");
  // The header's link rows no longer style every nav: the chat list was a squeezed row of one-line links.
  const clCss = fs.readFileSync(path.join(WEB, "css/app.css"), "utf8");
  expect(!/(^|\n)nav \{/.test(clCss) && !/(^|\n)nav a \{/.test(clCss) && /nav\.switcher, nav\.views \{/.test(clCss)
    && !/\.conv-title \{[^}]*nowrap/.test(clCss) && /@media \(max-width: 720px\) \{\s*\.chat-layout \{ grid-template-columns: minmax\(0, 1fr\); \}/.test(clCss),
    "chat list: no header rule reaches it, its names wrap, and a phone shows it as one column");
  await go("#/p/maity/chat/agt-a");
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
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/conversations/agt-c/messages?limit=") ? Promise.resolve({ cursor: 5, items: [
    { id: "e1", seq: 1, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "one", sent_at: at(0), delivered_at: at(0) },
    { id: "e2", seq: 2, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "two", sent_at: at(2), delivered_at: at(2) },
    { id: "e3", seq: 3, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "later", sent_at: at(20), delivered_at: at(20) },
    { id: "e4", seq: 4, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "next day", sent_at: at(24 * 60), delivered_at: at(24 * 60) },
  ] }) : hGet(p));
  await go("#/p/maity/chat/agt-c");
  const gl = main.querySelector("ol.messages").childNodes.map((li) => li.className);
  expect(JSON.stringify(gl) === JSON.stringify(["day", "msg in", "msg in grouped", "msg in", "day", "msg in"])
    && !main.querySelectorAll("li.msg")[1].querySelector(".msg-avatar"), "chat: within five minutes grouped without the picture again; a new day separated " + JSON.stringify(gl));
  win.Maity.api.get = hGet;
  // A history longer than a page is read to its end; the unread line stands before the unread ones there.
  const longMsg = (seq) => ({ id: "l" + seq, seq, conversation_id: "agt-c", from: "agt-c", to: "hum-maintainer", body: "m" + seq, sent_at: at(seq), delivered_at: at(seq) });
  const longReads = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/projects/maity/conversations/agt-c/messages?limit=200")) { longReads.push(p); return Promise.resolve({ cursor: 200, items: Array.from({ length: 200 }, (_, i) => longMsg(i + 1)) }); }
    if (p.startsWith("/projects/maity/conversations/agt-c/messages?after=200&limit=200")) { longReads.push(p); return Promise.resolve({ cursor: 203, items: [201, 202, 203].map(longMsg) }); }
    return hGet(p);
  };
  const hAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/conversations?observed=true"
    ? hAll(p).then((r) => ({ items: r.items.map((c) => (c.agent_id === "agt-c" ? Object.assign({}, c, { unread: 3 }) : c)), next_cursor: null })) : hAll(p));
  await go("#/p/maity/chat/agt-c");
  const histList = main.querySelector("ol.messages");
  const nl = histList.childNodes.findIndex((li) => li.className === "new-line");
  expect(longReads.length === 2 && histList.querySelectorAll("li.msg").length === 203 && nl > 0
    && histList.childNodes[nl + 1].attrs["data-seq"] === "201", "chat: the history is read to its end, the unread line before the first unread at the end");
  // The unread count that cannot be read draws no line, and says so.
  win.Maity.api.get = hGet;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/conversations?observed=true" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : hAll(p));
  await go("#/p/maity/chat/agt-a");
  expect(!main.querySelector("li.new-line") && text(main).includes("Which messages are new could not be read: down"), "chat: a failed unread read is said");
  win.Maity.api.getAll = hAll;
  await go("#/p/maity/chat/agt-b");
  expect(text(main.querySelector("ol.messages")).includes("No messages yet.") && text(main.querySelector("ol.messages")).includes("reads what you write here at its next wait or resume"),
    "chat: an empty chat says when the agent reads it");
  await go("#/p/maity/chat/agt-a");
  // A draft per chat survives switching to another chat and back.
  main.querySelector("textarea").value = "half a thought"; main.querySelector("textarea").dispatch("input");
  await go("#/p/maity/chat/agt-d");
  expect(main.querySelector("textarea").value === "" && text(conv("Agent A")).includes("Draft: half a thought"), "chat: switching keeps the draft, shown in the list");
  await go("#/p/maity/chat/agt-a");
  expect(main.querySelector("textarea").value === "half a thought", "chat: the draft is back in its chat");
  expect(!text(conv("Agent A")).includes("Draft:"), "chat: the open chat's draft is in its composer, not in its row");
  expect(!conv("Agent D").getAttribute("aria-label") && /^Agent D, online, .+, agent · @agent-d · Claude Code: You: Keep the inbox/.test(text(conv("Agent D"))),
    "chat: a row's name is its text, its parts apart " + JSON.stringify(text(conv("Agent D"))));
  main.querySelector("textarea").value = ""; main.querySelector("textarea").dispatch("input");
  // A redacted last message.
  const cAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maity/conversations?observed=true" ? r : { items: r.items.map((c) => (c.agent_id !== "agt-d" ? c
    : Object.assign({}, c, { last_message: Object.assign({}, c.last_message, { body: null, redacted: true }) }))), next_cursor: null }));
  await go("#/p/maity/chat");
  expect(text(conv("Agent D")).includes("A message was removed.") && !text(conv("Agent D")).includes("null"), "chat: a redacted last message");
  // A hub before last_message: no preview, the rest stays.
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maity/conversations?observed=true" ? r
    : { items: r.items.map((c) => { const o = Object.assign({}, c); delete o.last_message; return o; }), next_cursor: null }));
  await go("#/p/maity/chat");
  expect(convs().length === 6 && !main.querySelector(".chat-list .preview"), "chat: a hub without last_message shows no preview");
  // A refresh asked for while a read runs is read once more after it.
  let convReads = 0;
  win.Maity.api.getAll = (p) => {
    if (p !== "/projects/maity/conversations?observed=true") return cAll(p);
    convReads += 1;
    return new Promise((r) => setTimeout(r, 40)).then(() => cAll(p));
  };
  await go("#/p/maity/chat"); await new Promise((r) => setTimeout(r, 120));
  convReads = 0;
  await fireIntervals(); await fireIntervals(); await new Promise((r) => setTimeout(r, 150));
  expect(convReads === 2, "chat: two refreshes during one read make one more read, not none " + convReads);
  win.Maity.api.getAll = cAll;
  // Agents appearing later fill an empty list.
  const cGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maity/members" ? cGet(p).then((r) => ({ items: r.items.filter((m) => m.kind === "human"), next_cursor: null })) : cGet(p));
  const cAll2 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/conversations?observed=true" ? cAll2(p).then((r) => ({ items: r.items.filter((c) => c.kind !== "group"), next_cursor: null })) : cAll2(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat");
  expect(text(main).includes("You own no agents in this project, and are in no group chat.") && !convs().length, "chat: no agents and no group chat, said");
  win.Maity.api.get = cGet; win.Maity.api.getAll = cAll2;
  await fireIntervals(); await tick(); await tick();
  expect(convs().length === 6 && main.querySelector(".chat-list-pane p.muted").hidden, "chat: agents that appear fill the list");
  await go("#/p/maity/chat/agt-a");
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
  const convPath = "/projects/maity/conversations/agt-a/messages";
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
  let arriving = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/projects/maity/conversations/agt-c/messages?limit=200")) return Promise.resolve({ cursor: 203, items: Array.from({ length: 203 }, (_, i) => longMsg(i + 1)).slice(0, 200) });
    if (p.startsWith("/projects/maity/conversations/agt-c/messages?after=200&limit=200")) return Promise.resolve({ cursor: 203, items: [201, 202, 203].map(longMsg) });
    if (p.startsWith("/projects/maity/conversations/agt-c/messages?after=")) { const items = arriving; arriving = []; return Promise.resolve({ cursor: 205, items }); }
    return nGet2(p);
  };
  await go("#/p/maity/chat/agt-c");
  const longList = main.querySelector("ol.messages");
  // Scrolled up, two messages arrive: the view stays, both are counted; Newest goes down and keeps the focus in the chat.
  Object.assign(longList, { scrollHeight: 5000, clientHeight: 400, scrollTop: 100 });
  longList.dispatch("scroll");
  arriving = [longMsg(204), longMsg(205)];
  feed = [{ seq: 204, kind: "message", actor: { member_id: "agt-c" }, payload: { type: "chat", conversation_id: "agt-c" } }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  const jumpBtn = main.querySelector(".jump-latest");
  expect(longList.querySelectorAll("li.msg").length === 205 && longList.scrollTop === 100 && !jumpBtn.hidden && jumpBtn.textContent === "2 new · Newest",
    "chat: two messages arriving while scrolled up leave the view where it is and count both " + jumpBtn.textContent);
  const jProto = Object.getPrototypeOf(jumpBtn);
  const jFocus = jProto.focus;
  jProto.focus = function () { document.activeElement = this; };
  jumpBtn.click(); await tick();
  expect(jumpBtn.hidden && longList.scrollTop === 5000 && document.activeElement === byId("chat-text"), "chat: Newest goes to the end and puts the focus in the composer");
  jProto.focus = jFocus; document.activeElement = undefined;
  // At the end, a message that arrives is followed, and so is content that grows after it was drawn (an image loading).
  Object.assign(longList, { scrollHeight: 5200, scrollTop: 4800 }); longList.dispatch("scroll");
  arriving = [longMsg(206)];
  feed = [{ seq: 206, kind: "message", actor: { member_id: "agt-c" }, payload: { type: "chat", conversation_id: "agt-c" } }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(longList.scrollTop === 5200 && main.querySelector(".jump-latest").hidden, "chat: at the end, an arriving message is followed, no pill");
  longList.scrollHeight = 5600; longList.dispatch("load");
  expect(longList.scrollTop === 5600, "chat: at the end, content that grows after it was drawn keeps the reader at the end");
  win.Maity.api.get = nGet2;

  // The feed in other views: someone else's card event offers a reload,
  // one's own does not; a request event re-reads the counts at once.
  await go("#/p/maity/board");
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
  await go("#/p/maity/inbox");
  const before = gets.length;
  feed = [{ seq: 10004, kind: "request_created", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick();
  expect(gets.slice(before).filter((p) => p === "/me").length >= 1, "a request event re-reads /me");
  const realGet4 = win.Maity.api.get;
  const bump = (slug) => (p) => (p === "/me"
    ? realGet2(p).then((m) => { m.projects.find((x) => x.slug === slug).open_requests += 1; return m; })
    : (p.includes("/events?") ? Promise.resolve({ items: [], cursor: 10004 }) : realGet2(p)));
  // Nothing open on screen: nothing is being read or typed, so the list reloads on its own.
  expect(!main.querySelectorAll("li.entry").some((e) => !e.className.includes("done")), "maity inbox has no open entry here");
  win.Maity.api.get = bump("maity");
  const beforeQuiet = gets.length;
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(!text(main).includes("What waits for you changed") && gets.slice(beforeQuiet).some((p) => p.startsWith("/projects/maity/requests")),
    "a changed count reloads an empty list on its own, without a notice");
  expect(main.querySelector(".notice") && main.querySelector(".notice").getAttribute("role") === "status" && text(main.querySelector(".notice")).includes("1 new request."),
    "the quiet reload says \"1 new request.\" in the status notice");
  // The same with the Project settings panel open and typed in: no reload, the offer instead.
  win.Maity.api.get = realGet2; await go("#/p/maity/board"); await go("#/p/maity/inbox");
  await projectSettings(); await tick();
  byId("state-reason").value = "typed, not sent";
  win.Maity.api.get = bump("maity");
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "typed, not sent" && text(main).includes("What waits for you changed"),
    "with the Project settings panel open the empty list is not reloaded; the panel and its text stay");
  await projectSettings(); await tick();
  // An open entry on screen: the change is offered as a reload instead.
  win.Maity.api.get = realGet2;
  await go("#/p/sample/inbox");
  expect(main.querySelector("li.entry.current"), "sample inbox has an open entry");
  win.Maity.api.get = bump("sample");
  await fireIntervals(); await tick(); await tick();
  expect(text(main).includes("What waits for you changed") && btn(main, "Reload the list"), "a changed open count offers to reload the list");
  win.Maity.api.get = realGet4;
  win.Maity.api.get = realGet2;
  win.Maity.api.get = realGet2;
  await go("#/p/maity/chat/nobody");
  expect(text(main).includes("No conversation of yours"), "unknown conversation id reported");

  // A new profile's handle, free or taken while it is typed (§6.3); a deleted profile frees its handle.
  const hcAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/agents"
    ? hcAll(p).then((r) => ({ items: r.items.concat([{ id: "agt-old", handle: "old-one", display_name: "Old one", owner_id: "hum-maintainer", memberships: [], deleted_at: "2026-10-01T00:00:00Z" }]), next_cursor: null }))
    : hcAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
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
  win.Maity.api.post = (p, b) => (p === "/projects/maity/joins"
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
  win.Maity.api.post = (p, b) => (p === "/projects/maity/joins"
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
  await go("#/p/maity/inbox");
  await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
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
  const newOpt = byId("join-agent").querySelectorAll("option").find((o) => o.textContent.startsWith("Agent New (@maintainer/agent-new)"));
  expect(newOpt && byId("join-agent").value === newOpt.attrs.value && /^agt-/.test(newOpt.attrs.value),
    "a new profile is offered and selected after its join is created");
  expect(main.querySelectorAll("article.seat").some((a) => text(a).includes("Agent New")), "the new profile's join is a seat in the grid");
  // Joining lives in Agents: no tab of its own; the old route opens the panel there.
  expect(!header.querySelectorAll("nav.views a").some((a) => a.textContent.startsWith("Join an agent")), "join: no tab of its own any more");
  await go("#/p/maity/inbox"); await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const jpPanel = () => main.querySelector(".join-panel");
  const jpButton = () => main.querySelector("button.join-open");
  expect(jpPanel() && jpPanel().hidden && jpButton() && !jpButton().hidden && text(jpButton()) === "+ Join an agent",
    "join: Agents has + Join an agent in its title row, the panel closed");
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
  await go("#/p/maity/inbox"); await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".view-agents, .view-join") && !jpPanel().hidden && main.querySelector(".profiles"), "join: #/join opens Agents with the panel open");
  await go("#/p/maity/inbox"); await go("#/p/maity/agents/join"); for (let k = 0; k < 4; k++) await tick();
  expect(!jpPanel().hidden, "join: so does #/agents/join");
  // A failed read of the joins stays in the panel, with a retry; the agents' cards are drawn all the same.
  const jfAll = win.Maity.api.getAll;
  let jfFail = true;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/joins" && jfFail ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : jfAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelectorAll(".profile").filter((x) => !x.classList.contains("seat")).length === 5 && !main.querySelector("article.seat"),
    "join: the joins failing to load leave every agent card on screen");
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
  win.Maity.api.getAll = (p) => { if (p === "/projects/maity/joins") mjReads++; return jfAll(p); };
  await go("#/p/maity/inbox"); await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  const mjBefore = jpPanel();
  mjFeed = [{ seq: 10100, kind: "member_joined", actor: { member_id: "agt-x" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(jpPanel() && jpPanel() !== mjBefore, "join: an agent joining redraws Agents while the panel is closed");
  main.querySelector("button.join-open").click(); await tick();
  const mjOpen = jpPanel();
  mjReads = 0;
  mjFeed = [{ seq: 10101, kind: "member_joined", actor: { member_id: "agt-x" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(jpPanel() === mjOpen && !mjOpen.hidden && mjReads === 1, "join: with the panel open only the joins are read again (" + mjReads + ")");
  win.Maity.api.get = mjGet; win.Maity.api.getAll = jfAll;
  // A join that expires while the view is open moves to the others without a reload.
  const jAll = win.Maity.api.getAll;
  const soon = { id: "join-soon", agent_id: "agt-b", role: "member", created_by: "hum-maintainer", created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 60).toISOString(), used_at: null, burned: false, revoked_at: null };
  win.Maity.api.getAll = (p) => (p === "/projects/maity/joins" ? Promise.resolve({ items: [soon], next_cursor: null }) : jAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
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
  await go("#/p/maity/inbox"); await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
  expect(joinRow("join-soon").tagName === "ARTICLE" && btn(joinRow("join-soon"), "Revoke"), "joins: a browser ahead of the hub still sees an open join open");
  // A Revoke the hub refuses (expired by its clock): said, kept on screen, the list re-read.
  win.Maity.api.getAll = jAll;
  win.Maity.api.now = () => Date.parse("2026-10-21T08:10:00Z");
  await go("#/p/maity/inbox"); await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick();
  const jReads = [];
  const jAll2 = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => { jReads.push(p); return jAll2(p); };
  btn(joinRow("join-0009"), "Revoke").click(); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Not revoked: the join is expired") && jReads.includes("/projects/maity/joins"),
    "joins: a refused Revoke is said and the list re-read");
  win.Maity.api.getAll = jAll2;
  win.Maity.api.now = jNow;
  win.Maity.api.getAll = jAll;
  await go("#/p/maity/inbox");
  expect(!text(main).includes("FIXTURE"), "the line is gone after leaving the view");
  // count polling: a change offers a reload instead of replacing the list
  await fireIntervals(); await tick();
  expect(!main.querySelector(".notice .flag"), "no notice while nothing changed");

  // state and absence
  await projectSettings(); await tick();
  const sel = byId("state-select"); sel.value = "freeze";
  byId("state-reason").value = "release 0.1.0";
  // The 15-s count re-read replaces the switcher only; the open panel and what is typed stay.
  const switcherBefore = header.querySelector("nav.switcher");
  await fireIntervals(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "release 0.1.0" && byId("state-select").value === "freeze",
    "the count re-read keeps the open Project settings panel and its input");
  expect(header.querySelector("nav.switcher") !== switcherBefore && header.querySelectorAll("nav.switcher").length === 1,
    "the count re-read replaces the switcher, once");
  byId("state-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header).includes("Freeze"), "state changed to freeze");
  await projectSettings(); await tick();
  byId("absence-until").value = "2026-10-25T08:00"; byId("absence-scope").value = "fixes only";
  byId("absence-until").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header.querySelector(".project-state")).includes("Away until") && text(header.querySelector(".absence")).includes("While away: fixes only"), "absence set");

  // policy.signing: before required, the agents a bearer token would cut off.
  const sigPatches = [];
  const realPatch4 = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { sigPatches.push([p, b]); return realPatch4(p, b); };
  await projectSettings(); await tick();
  const sigSel = byId("signing-select");
  expect(sigSel && sigSel.value === "optional", "signing: the switch shows the project's policy");
  sigSel.value = "required"; sigSel.dispatch("change"); await tick(); await tick(); await tick();
  const impact = header.querySelector(".signing-impact");
  expect(text(impact).includes("This agent calls with a bearer token and would be refused (signature_required) until it signs") && text(impact).includes("Agent B · crd-b-0003")
    && !text(impact).includes("crd-d-0001") && !text(impact).includes("crd-c-0002") && !text(impact).includes("Agent A ·"),
    "signing: the agents last using a bearer token are listed, revoked and signed ones are not");
  expect(text(impact).includes("1 credential has not been used yet (Agent C)"), "signing: unused credentials are named");
  byId("signing-reason").value = "all agents run the CLI now";
  byId("signing-select").parentNode.dispatch("submit"); await tick();
  expect(!sigPatches.length, "signing: required is not sent while bearer agents are listed and not confirmed");
  byId("signing-confirm").checked = true;
  byId("signing-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(sigPatches.length === 1 && sigPatches[0][0] === "/projects/maity"
    && JSON.stringify(sigPatches[0][1]) === JSON.stringify({ policy: { signing: "required" }, reason: "all agents run the CLI now" }),
    "signing: confirmed, the PATCH carries the policy field and the reason");
  await projectSettings(); await tick();
  expect(byId("signing-select").value === "required", "signing: the switch reads required after the change");
  byId("signing-select").value = "optional"; byId("signing-select").dispatch("change"); await tick();
  expect(!text(header.querySelector(".signing-impact")).length, "signing: back to optional needs no check");
  byId("signing-reason").value = "back to optional";
  byId("signing-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(sigPatches[1][1]) === JSON.stringify({ policy: { signing: "optional" }, reason: "back to optional" }), "signing: back to optional is sent");
  win.Maity.api.patch = realPatch4;
  await go("#/p/sample/inbox");
  await projectSettings(); await tick();
  expect(byId("state-select") && !byId("signing-select"), "signing: no switch where the hub has no signing policy");
  await projectSettings(); await tick();
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("(signed)") && text(main).includes("(bearer token)"), "credentials: how each was last used");
  await go("#/p/maity/inbox");
  // Logo in the header, the tab's icon, the banner on the project's inbox.
  const headerMark = header.querySelector(".bar .project-mark");
  const icon = () => head.querySelectorAll("link").find((l) => l.getAttribute("rel") === "icon");
  expect(headerMark && headerMark.tagName === "IMG" && icon() && icon().getAttribute("href") === "fixtures/maity/logo.png",
    "logo: in the header, and as the tab's icon");
  const bannerImg = main.querySelector("img.project-banner");
  expect(bannerImg && bannerImg.getAttribute("src") === "fixtures/maity/banner.png" && bannerImg.getAttribute("alt") === "", "banner: heads the project's inbox");
  await go("#/p/sample/inbox");
  expect(header.querySelector(".bar .project-mark").textContent === "SS" && !icon() && !main.querySelector("img.project-banner"),
    "logo: a project without images has a monogram, no icon and no banner");
  await go("#/p/maity/inbox");
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
  expect(header.querySelector(".images") && text(header.querySelector(".images")).includes("from the repository's forge")
    && text(header.querySelector(".images")).includes("uploaded here") && byId("upload-logo"), "images: what shows now and where it comes from");
  await pick("upload-logo", fakeFile(SVG, 0, "image/svg+xml"));
  expect(!imgPuts.length && text(header).includes("Logo not uploaded: not a PNG, JPEG or WebP image"), "images: an SVG is refused by its bytes, before sending");
  await pick("upload-logo", fakeFile(PNG, 1024 * 1024 + 1));
  expect(!imgPuts.length && text(header).includes("Logo not uploaded: larger than 1 MiB"), "images: over 1 MiB is refused before sending");
  await pick("upload-logo", fakeFile(WEBP, 2000, "image/png"));
  expect(JSON.stringify(imgPuts[0]) === JSON.stringify(["PUT", "/projects/maity/logo", "image/webp", 2000]),
    "images: the upload is a PUT of the raw file, typed by its bytes (WebP, whatever the file claims)");
  // The panel opens again by itself and says what happened.
  const removeLogo = btn(header, "Remove the uploaded logo");
  expect(removeLogo && text(header.querySelector(".images")).includes("Logo uploaded.") && text(header.querySelector(".images")).includes("uploaded here"),
    "images: after an upload the panel says so, and the logo can be removed");
  removeLogo.click(); await tick(); await tick(); await tick();
  expect(JSON.stringify(imgPuts[1]) === JSON.stringify(["DELETE", "/projects/maity/logo"]) && header.querySelector(".bar .project-mark").getAttribute("src") === "fixtures/maity/logo.png",
    "images: removed, the forge's logo applies again");
  expect(text(header).includes("Uploaded logo removed; the forge's logo, or a monogram, shows again."), "images: the removal is said too");
  await projectSettings(); await tick();
  // A hub before /me's logo: the switcher falls back to GET /projects.
  const realGet7 = win.Maity.api.get;
  const fallbackGets = [];
  win.Maity.api.get = (p) => { fallbackGets.push(p); return p === "/me" ? realGet7(p).then((m) => { m.projects.forEach((x) => { delete x.logo; }); return m; }) : realGet7(p); };
  await go("#/all"); await go("#/p/maity/inbox");
  expect(fallbackGets.includes("/projects") && chip("Maity").querySelector(".project-mark").tagName === "IMG",
    "logo: without logos on /me, the project views are read and the logo still shows");
  win.Maity.api.get = realGet7;
  win.Maity.api.putImage = realPut; win.Maity.api.del = realDel;
  // The repository in Project settings (docs/api.md §6.1): https only here, the hub checks the forge.
  const repoPatches = [];
  const repoRealPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { if ("repository" in b) repoPatches.push(b); return repoRealPatch(p, b); };
  await go("#/p/maity/inbox"); await projectSettings();
  const repoIn = () => byId("repo-url");
  const repoSave = async () => { header.querySelector("form.repository-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick(); };
  expect(repoIn() && repoIn().value === "https://github.com/oliver-zehentleitner/maity", "repository: Project settings shows the project's repository");
  repoIn().value = "http://github.com/a/b"; await repoSave();
  expect(!repoPatches.length && text(byId("repo-url-error")).startsWith("Must be https://") && repoIn().getAttribute("aria-invalid") === "true",
    "repository: anything but an https forge URL is refused at its field, nothing sent");
  repoIn().value = "https://gitlab.com/a/b"; await repoSave();
  expect(repoPatches.length === 1 && text(byId("repo-url-error")).startsWith("Must be https://"), "repository: the hub's not_a_configured_forge is said at the field");
  let repoAsked = null;
  win.confirm = (q) => { repoAsked = q; return true; };
  repoIn().value = "https://github.com/acme/widget/"; await repoSave();
  const repoNow = (await win.Maity.api.get("/projects/maity")).repository;
  expect(JSON.stringify(repoPatches[1]) === JSON.stringify({ repository: { url: "https://github.com/acme/widget" } }) && repoNow.url === "https://github.com/acme/widget"
    && /^Change the repository to https:\/\/github\.com\/acme\/widget\?/.test(repoAsked), "repository: a change asks first, then is sent without the trailing slash");
  await projectSettings();
  repoIn().value = ""; await repoSave();
  expect(JSON.stringify(repoPatches[2]) === JSON.stringify({ repository: null }) && (await win.Maity.api.get("/projects/maity")).repository === null
    && repoAsked.startsWith("Remove the repository?"), "repository: emptied, it is removed after asking");
  win.confirm = () => true;
  await repoRealPatch("/projects/maity", { repository: { url: "https://github.com/oliver-zehentleitner/maity" } });
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
  expect(!pMenu.hidden && pb.attrs["aria-expanded"] === "true" && JSON.stringify(pItems) === JSON.stringify(["Profile", "Picture", "Preferences", "Change password", "Linked accounts · later", "Sign out"])
    && document.activeElement === pMenu.querySelectorAll(".menu-item")[0], "header: the profile menu opens with its items, the first focused");
  pMenu.dispatch("keydown", { key: "ArrowDown" });
  expect(document.activeElement === pMenu.querySelectorAll(".menu-item")[1] && pMenu.querySelectorAll(".menu-item")[1].getAttribute("href") === "#/account/picture",
    "header: arrows move through the items; Picture goes to the account's picture");
  pMenu.dispatch("keydown", { key: "ArrowDown" }); pMenu.dispatch("keydown", { key: "ArrowDown" }); pMenu.dispatch("keydown", { key: "ArrowDown" });
  expect(pMenu.querySelectorAll(".menu-item")[4].attrs["aria-disabled"] === "true" && document.activeElement === pMenu.querySelectorAll(".menu-item")[4],
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

  // Pictures (docs/api.md §6.10): one's own and one's agents', on the account.
  const avCalls = [];
  win.Maity.api.putImage = (p, blob, type) => { avCalls.push(["PUT", p, type]); return realPut(p, blob, type); };
  win.Maity.api.del = (p) => { avCalls.push(["DELETE", p]); return realDel(p); };
  await go("#/account/picture");
  const avHeading = main.querySelector(".picture-heading");
  expect(avHeading && avHeading.getAttribute("tabindex") === "-1" && byId("avatar-file-hum-maintainer") && text(main).includes("Generated from the member id")
    && !btn(main, "Remove the upload"), "picture: the account shows the picture, where it comes from and an upload; nothing to remove yet");
  const avAgents = main.querySelectorAll(".picture-list li");
  // The fixtures' seven, and any joined earlier in this run.
  expect(avAgents.length >= 7 && byId("avatar-file-agt-b") && avAgents.some((li) => text(li).includes("Agent B @maintainer/agent-b")), "picture: the human's agents, each with its own upload and its global name");
  await pick("avatar-file-hum-maintainer", fakeFile(SVG, 0, "image/svg+xml"));
  expect(!avCalls.length && text(main).includes("Not uploaded: not a PNG, JPEG or WebP image"), "picture: an SVG is refused by its bytes, before sending");
  await pick("avatar-file-hum-maintainer", fakeFile(PNG, 1024 * 1024 + 1));
  expect(!avCalls.length && text(main).includes("Not uploaded: larger than 1 MiB"), "picture: over 1 MiB is refused before sending");
  await pick("avatar-file-hum-maintainer", fakeFile(WEBP, 2000, "image/png"));
  await tick(); await tick();
  const meAfter = await win.Maity.api.get("/me");
  const memberAfter = (await win.Maity.api.getAll("/projects/maity/members")).items.find((x) => x.id === "hum-maintainer");
  expect(JSON.stringify(avCalls[0]) === JSON.stringify(["PUT", "/me/avatar", "image/webp"]) && meAfter.member.avatar_source === "uploaded"
    && memberAfter.avatar_source === "uploaded" && memberAfter.avatar_url === meAfter.member.avatar_url,
    "picture: uploaded with the sniffed type; the member is the same everywhere");
  expect(text(main).includes("Picture uploaded.") && text(main).includes("Uploaded.") && btn(main, "Remove the upload"), "picture: the page says so and offers Remove");
  btn(main, "Remove the upload").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(avCalls[1]) === JSON.stringify(["DELETE", "/me/avatar"]) && text(main).includes("Uploaded picture removed; the generated one shows again.")
    && !btn(main, "Remove the upload"), "picture: Remove deletes the upload; the generated picture applies again");
  await pick("avatar-file-agt-b", fakeFile(PNG, 3000));
  await tick(); await tick();
  const bAfter = (await win.Maity.api.getAll("/projects/maity/members")).items.find((x) => x.id === "agt-b");
  expect(JSON.stringify(avCalls[2]) === JSON.stringify(["PUT", "/agents/agt-b/avatar", "image/png"]) && bAfter.avatar_source === "uploaded",
    "picture: an owner sets an agent's picture, which its member view carries");
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
  byId("login-handle").value = "maintainer"; byId("login-password").value = "initial-generated";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(byId("login-handle") && text(main).includes("wrong"), "password: the old password no longer signs in");
  byId("login-password").value = "a long new password";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(!byId("login-handle") && !main.querySelector(".error"), "sign in with the new password returns to the dashboard");

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
  expect(text(main).includes("No projects yet") && !main.querySelector("li.entry") && !text(main).includes("Nothing waits for you"),
    "no project and nothing personal: only the empty state");
  win.Maity.api.getAll = npGetAll;
  const createLink = main.querySelectorAll("a").find((a) => a.textContent === "Create a project");
  expect(createLink && createLink.getAttribute("href") === "#/new", "empty state offers Create a project");
  expect(chip("+ New project") && chip("+ New project").getAttribute("href") === "#/new", "switcher links to #/new");
  await go("#/new");
  expect(plainTitle() === "New project · Maity" && byId("project-slug"), "create-project view");
  expect(byId("project-slug").attrs.pattern && !badPatterns().length, "create: every pattern compiles with the v flag " + badPatterns());
  byId("project-name").value = "Dogfood Hub"; byId("project-name").dispatch("input");
  expect(byId("project-slug").value === "dogfood-hub", "slug proposed from the name");
  const posts = [];
  const realPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { posts.push([p, b]); return realPost(p, b); };
  const fieldError = (id) => text(byId(id + "-error"));
  byId("project-slug").value = "-Bad"; byId("project-slug").dispatch("input");
  main.querySelector("form").dispatch("submit"); await tick();
  expect(text(main).includes("Lowercase letters, digits and -, 2–63 characters, starting with a letter or digit. Used in links") && byId("project-slug").getAttribute("aria-describedby") === "project-slug-hint project-slug-error",
    "create: the slug's rule is said up front, tied to its field");
  expect(!posts.length && fieldError("project-slug") === "Lowercase letters, digits and -, 2–63 characters, starting with a letter or digit." && byId("project-slug").getAttribute("aria-invalid") === "true",
    "a malformed slug is refused next to the field, nothing sent");
  byId("project-slug").value = "maity";
  byId("project-repository").value = "https://gitlab.example/a/b";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(fieldError("project-slug").includes("exists") && fieldError("project-repository").includes("forge"),
    "the hub's invalid fields shown next to slug and repository");
  byId("project-slug").value = "dogfood"; byId("project-repository").value = "https://github.com/example/dogfood";
  byId("project-ktw").checked = true; byId("project-preset").value = "solo";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  const sent = posts[posts.length - 1];
  expect(sent[0] === "/projects" && JSON.stringify(sent[1]) === JSON.stringify({
    slug: "dogfood", name: "Dogfood Hub", repository: { url: "https://github.com/example/dogfood" }, keep_the_why: true, policy: { preset: "solo" },
  }), "POST /projects with the contract's body");
  expect(!fieldError("project-slug") && !byId("project-slug").getAttribute("aria-invalid"), "errors cleared on resubmit");
  noProjects = false;
  win.onhashchange(); await tick(); await tick();
  expect(win.location.hash === "#/p/dogfood/agents" && text(header).includes("Dogfood Hub") && text(header).includes("Build"),
    "on 201 the page switches into the new project's Agents view");
  for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("No agents in this project yet") && main.querySelector(".join-panel") && !main.querySelector(".join-panel").hidden && byId("join-agent"),
    "the new project opens Join an agent at once");
  expect(chip("Dogfood Hub") && chip("Dogfood Hub").getAttribute("aria-current") === "page", "the new project is in the switcher");
  // A first-time human: the empty board and inbox say where their content comes from.
  await go("#/p/dogfood/board");
  expect(text(main).includes("Every open card, and the done and cancelled ones of the last 14 days.")
    && main.querySelector(".first-hint") && text(main).includes("No cards yet. Your agents put the work here"), "empty board: subtitle and first hint");
  await go("#/p/dogfood/inbox");
  expect(text(main).includes("No open requests.") && text(main).includes("Your agents ask here when they need you"), "empty inbox: first hint");
  win.Maity.api.get = (p) => { gets.push(p); return realGet(p); };
  win.Maity.api.post = realPost;

  // Group chats (docs/api.md §9.2): in the list, open, write, manage, remove, read along.
  await go("#/p/maity/chat");
  const gcConv = () => main.querySelectorAll(".chat-list a.conv").find((a) => a.getAttribute("href") === "#/p/maity/chat/cnv-0007");
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
  expect(main.querySelector(".chat-list-pane a.new-group") && main.querySelector(".chat-list-pane a.new-group").getAttribute("href") === "#/p/maity/chat/new",
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
  await go("#/p/maity/chat/cnv-0007");
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
  expect(JSON.stringify(gcWrites[0]) === JSON.stringify(["POST", "/projects/maity/conversations/cnv-0007/messages", { body: "@agent-a go ahead" }])
    && gcList().querySelectorAll("li.msg").length === 4 && byId("chat-text").value === "", "group chat: a message is sent and shown");
  // Removing a message for everyone (§8.5).
  const gcPrompt = win.prompt;
  win.prompt = () => "pasted a token";
  btn(gcList().querySelectorAll("li.msg")[0], "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gcWrites[1]) === JSON.stringify(["POST", "/projects/maity/events/5010/redact", { reason: "pasted a token" }])
    && text(gcList().querySelectorAll("li.msg")[0]).includes("This message was removed by Maintainer: pasted a token.")
    && !btn(gcList().querySelectorAll("li.msg")[0], "Remove"), "group chat: a human in it removes a message, its tombstone says by whom and why");
  const gcHub = (await win.Maity.api.get("/projects/maity/conversations/cnv-0007/messages?before=5011&limit=5")).items[0];
  const gcKept = (await win.Maity.api.get("/projects/maity/conversations/cnv-0007/messages?before=5016&limit=5")).items.find((m) => m.seq === 5015);
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
  try { await gcPost("/projects/maity/events/5015/redact", {}); } catch (err) { gcNoReason = err; }
  expect(gcNoReason && gcNoReason.code === "invalid", "group chat: the mock refuses a removal without a reason");
  win.prompt = gcPrompt;
  const gcComposer = byId("chat-text");
  // Managing: rename, add (the latecomer's history said), remove.
  byId("group-rename").value = "Release 0.2"; header.querySelector && main.querySelector(".group-manage form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(gcWrites[2]) === JSON.stringify(["PATCH", "/projects/maity/conversations/cnv-0007", { title: "Release 0.2" }])
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
  expect(JSON.stringify(gcWrites[3]) === JSON.stringify(["POST", "/projects/maity/conversations/cnv-0007/participants", { member_id: "agt-c" }])
    && text(main.querySelector(".group-people-line")).includes("Agent C (agent)"), "group chat: a participant added");
  const gcConfirm = win.confirm;
  win.confirm = () => true;
  btn(main.querySelectorAll(".group-members li").find((li) => text(li).startsWith("Agent C")), "Remove").click(); for (let k = 0; k < 6; k++) await tick();
  expect(JSON.stringify(gcWrites[4]) === JSON.stringify(["DELETE", "/projects/maity/conversations/cnv-0007/participants/agt-c"])
    && !text(main.querySelector(".group-people-line")).includes("Agent C"), "group chat: a participant removed");
  expect(main.querySelectorAll(".group-members button").every((b) => /^Remove .+ from the chat$/.test(b.getAttribute("aria-label") || "")),
    "group chat: each participant's Remove names whom it removes");
  // Someone else's removal and someone else's rename reach the open chat in place.
  const gcEvGet = win.Maity.api.get;
  let gcFeed = [];
  let gcRenamed = false;
  win.Maity.api.get = (p) => {
    if (p.includes("/events?")) { const items = gcFeed; gcFeed = []; return Promise.resolve({ items, cursor: items.length ? items[items.length - 1].seq : 9000, superseded: false }); }
    if (p === "/projects/maity/conversations/cnv-0007" && gcRenamed) return gcEvGet(p).then((v) => Object.assign({}, v, { title: "Renamed by Ops" }));
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
  await go("#/p/maity/chat/agt-a");
  gcFeed = [{ seq: 9103, kind: "event_redacted", actor: { member_id: "hum-maintainer" }, payload: { seq: 4202, reason: "pasted" } }];
  await fireIntervals(); await tick(); await tick();
  const gcDirect = main.querySelectorAll("li.msg").find((li) => li.getAttribute("data-seq") === "4202");
  expect(gcDirect && text(gcDirect).includes("This message was removed by Maintainer: pasted.") && !btn(gcDirect, "Quote"), "direct chat: a removal reaches the open chat too");
  win.Maity.api.get = gcEvGet;
  // A removed message as the hub gives it: body null, with or without redacted.
  win.Maity.api.get = (p) => (p === "/projects/maity/conversations/cnv-0007/messages?limit=200"
    ? gcEvGet(p).then((r) => Object.assign({}, r, { items: r.items.map((m, i) => (i === 1 ? Object.assign({}, m, { body: null }) : m)) })) : gcEvGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007");
  const gcNull = gcList().querySelectorAll("li.msg")[1];
  expect(text(gcNull).includes("This message was removed.") && !btn(gcNull, "Quote") && !btn(gcNull, "Remove"), "group chat: body null reads as removed, nothing to quote or remove");
  // A latecomer with nothing new: said, with the earlier part a button away.
  win.Maity.api.get = (p) => (p === "/projects/maity/conversations/cnv-0007/messages?limit=200" ? Promise.resolve({ items: [], cursor: null, earlier: 5021 }) : gcEvGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007");
  expect(text(gcList()).includes("Nothing new since you joined.") && btn(main.querySelector(".earlier"), "Show earlier messages"), "group chat: a latecomer with nothing new is told the earlier part is there");
  win.Maity.api.get = gcEvGet;
  // The earlier part, on demand.
  const gcGet = win.Maity.api.get;
  win.Maity.api.get = (p) => {
    if (p === "/projects/maity/conversations/cnv-0007/messages?limit=200") return gcGet(p).then((r) => Object.assign({}, r, { items: r.items.slice(1), earlier: 5010 }));
    if (p === "/projects/maity/conversations/cnv-0007/messages?before=5010&limit=50") return Promise.resolve({ items: [{ id: "evt-5001", seq: 5001, conversation_id: "cnv-0007", from: "agt-a", to: "cnv-0007", body: "before you came", sent_at: "2026-10-21T12:00:00Z", mentions: [] }], cursor: 5001, earlier: null });
    return gcGet(p);
  };
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007");
  const gcBefore = gcList().querySelectorAll("li.msg").length;
  btn(main.querySelector(".earlier"), "Show earlier messages").click(); for (let k = 0; k < 4; k++) await tick();
  expect(gcList().querySelectorAll("li.msg").length === gcBefore + 1 && text(gcList().querySelectorAll("li.msg")[0]).includes("before you came")
    && !main.querySelector(".earlier button"), "group chat: the earlier part is read on demand and put before");
  // Reading along as an agent's owner: no writing, no managing, no removing; the observers named.
  win.Maity.api.get = (p) => (p === "/projects/maity/conversations/cnv-0007"
    ? gcGet(p).then((v) => Object.assign({}, v, { access: "observer", observers: ["hum-maintainer", "hum-outside"],
      participants: v.participants.filter((x) => x.member_id !== "hum-maintainer").concat([{ member_id: "hum-ops", kind: "human", handle: "ops", owner_id: null, joined_at: v.created_at }]) }))
    : gcGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007");
  expect(!byId("chat-text") && text(main).includes("You read along as the owner of an agent in this chat") && !main.querySelector(".group-manage")
    && !gcList().querySelectorAll("button").some((b) => b.textContent === "Remove" || b.textContent === "Quote")
    && text(main.querySelector(".group-observers")).includes("Also read by: you (owner of Agent A, Agent B), an owner outside the project"),
    "group chat: an owner reads along, writes and manages nothing, and is named as reading along");
  // A closed chat stays readable and takes nothing.
  win.Maity.api.get = (p) => (p === "/projects/maity/conversations/cnv-0007" ? gcGet(p).then((v) => Object.assign({}, v, { closed_at: "2026-10-22T10:00:00Z", closed_reason: "no_human" })) : gcGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007");
  expect(!byId("chat-text") && text(main).includes("This chat is closed") && !main.querySelector(".group-manage") && gcList().querySelectorAll("li.msg").length >= 4,
    "group chat: a closed chat is read only");
  win.Maity.api.get = gcGet;
  // Creating: at least one other, not one's own agent alone, then the chat opens.
  await go("#/p/maity/chat/new");
  const gcBox = (id) => byId("group-member-" + id);
  main.querySelector("form.group-form").dispatch("submit"); await tick();
  expect(text(byId("group-people-error")) === "Choose at least one other participant." && gcWrites.length === 5, "group chat: none chosen, said, nothing sent");
  gcBox("agt-a").checked = true;
  main.querySelector("form.group-form").dispatch("submit"); await tick();
  expect(text(byId("group-people-error")).startsWith("That is your direct chat with Agent A") && byId("group-people-error").querySelector("a").getAttribute("href") === "#/p/maity/chat/agt-a",
    "group chat: one's own agent alone is the direct chat, and it says so");
  gcBox("agt-b").checked = true; byId("group-title").value = "Hub and CLI";
  main.querySelector("form.group-form").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const gcMade = gcWrites[5];
  expect(gcMade[0] === "POST" && gcMade[1] === "/projects/maity/conversations" && JSON.stringify(gcMade[2]) === JSON.stringify({ title: "Hub and CLI", participants: ["agt-a", "agt-b"] })
    && /^#\/p\/maity\/chat\/cnv-/.test(win.location.hash), "group chat: created with its title and participants, and opened");
  await go(win.location.hash);
  expect(text(main.querySelector(".group-chat .group-title")) === "Hub and CLI" && text(main).includes("No messages yet."), "group chat: the new chat is empty and open");
  // Leaving as the last human closes it; it is gone from one's list.
  win.confirm = (q) => { gcWrites.push(["CONFIRM", q]); return true; };
  btn(main.querySelector(".group-manage"), "Leave the chat").click(); for (let k = 0; k < 6; k++) await tick();
  const gcLeft = gcWrites.filter((w) => w[0] === "DELETE").pop();
  expect(gcWrites.some((w) => w[0] === "CONFIRM" && w[1].includes("You are its last human: it closes")) && /\/participants\/hum-maintainer$/.test(gcLeft[1])
    && win.location.hash === "#/p/maity/chat", "group chat: leaving as its last human says it closes, and goes back to the list");
  win.confirm = gcConfirm;
  win.Maity.api.post = gcPost; win.Maity.api.patch = gcPatch; win.Maity.api.del = gcDel;
  // The mock as the hub: its refusals (§9.2).
  const gcErr = async (call) => { try { await call(); return null; } catch (err) { return err; } };
  const tooMany = await gcErr(() => gcPost("/projects/maity/conversations", { participants: Array.from({ length: 12 }, (_, i) => "agt-" + i) }));
  const direct = await gcErr(() => gcPost("/projects/maity/conversations", { participants: ["agt-a"] }));
  const both = await gcErr(() => win.Maity.api.get("/projects/maity/conversations/cnv-0007/messages?after=1&before=9"));
  expect(tooMany && tooMany.details.fields.participants === "not_a_member" && direct && direct.details.fields.participants === "use_direct"
    && both && both.code === "invalid", "group chat: the mock refuses a non-member, one's own agent alone, and after with before");
  // Removing a message in a direct chat: the human party, with a reason (§8.5).
  const gcPost2 = win.Maity.api.post;
  const gcRemoves = [];
  win.Maity.api.post = (p, b) => { if (p.includes("/redact")) gcRemoves.push([p, b]); return gcPost2(p, b); };
  await go("#/p/maity/chat/agt-a");
  win.prompt = () => "wrong chat";
  const gcDirectMsg = main.querySelectorAll("li.msg")[0];
  btn(gcDirectMsg, "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(gcRemoves.length === 1 && /\/projects\/maity\/events\/\d+\/redact$/.test(gcRemoves[0][0]) && gcRemoves[0][1].reason === "wrong chat"
    && text(main.querySelectorAll("li.msg")[0]).includes("This message was removed by Maintainer: wrong chat.") && !btn(main.querySelectorAll("li.msg")[0], "Remove"),
    "direct chat: the human party removes a message with a reason");
  win.prompt = gcPrompt;
  // Blind removal (§8.5, #206): a closed group chat's message the admin was never in, by its number.
  await go("#/p/maity/inbox"); await projectSettings();
  byId("remove-seq").value = "x1";
  header.querySelector("form.remove-reported").dispatch("submit"); await tick();
  expect(text(header).includes("Not removed: the message number is a whole number") && gcRemoves.length === 1, "blind removal: the number is checked before sending");
  let gcAsked = "";
  win.confirm = (q) => { gcAsked = q; return true; };
  byId("remove-seq").value = "5020"; byId("remove-reason").value = "typo";
  header.querySelector("form.remove-reported").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const gc5010 = (await win.Maity.api.get("/projects/maity/conversations/cnv-0007/messages?before=5021&limit=1")).items[0];
  expect(gcRemoves[1][1].expect === "closed_chat_message" && text(header).includes("number 5020 is no message of a closed group chat in this project; nothing was removed")
    && gc5010.body !== null, "blind removal: always sends expect, so a number that is no closed chat's message removes nothing");
  byId("remove-seq").value = "4990"; byId("remove-reason").value = "reported by a reviewer";
  header.querySelector("form.remove-reported").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(gcRemoves[2]) === JSON.stringify(["/projects/maity/events/4990/redact", { reason: "reported by a reviewer", expect: "closed_chat_message" }])
    && text(header).includes("Message 4990 is removed.") && gcAsked.startsWith("Remove the closed group chat's message with number 4990"),
    "blind removal: an admin removes a closed chat's message it was never in, by its number, without reading it");
  win.confirm = gcConfirm;
  win.Maity.api.post = gcPost2;
  await projectSettings();
  // Without events:admin a direct chat offers no Remove (§8.5).
  const gcRole = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me" ? gcRole(p).then((x) => { x.projects.find((y) => y.slug === "maity").role = "member"; return x; }) : gcRole(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/agt-a");
  expect(main.querySelectorAll("li.msg").length && !main.querySelectorAll("li.msg button").some((b) => b.textContent === "Remove"), "direct chat: a member without events:admin gets no Remove");
  win.Maity.api.get = gcRole;
  // Reading along outside one's projects (§9.2): Spare is in guestlab, its owner is not.
  const gcOutGets = [];
  const gcOutGet = win.Maity.api.get, gcOutAll = win.Maity.api.getAll;
  win.Maity.api.get = (p) => { gcOutGets.push(p); return gcOutGet(p); };
  win.Maity.api.getAll = (p) => { gcOutGets.push(p); return gcOutAll(p); };
  await go("#/all");
  const gcNote = main.querySelector(".observe-note");
  expect(gcNote && gcNote.querySelector("a").getAttribute("href") === "#/observe/guestlab" && text(gcNote).includes("through Spare"),
    "read along: everything waiting names the projects one's agents are in and one is not");
  await go("#/observe/guestlab");
  expect(text(main).includes("Read along in guestlab") && main.querySelectorAll(".chat-list a.conv").length === 1
    && main.querySelector(".chat-list a.conv").getAttribute("href") === "#/observe/guestlab/cnv-0301" && !main.querySelector("a.new-group")
    && !gcOutGets.some((p) => p.startsWith("/projects/guestlab/members") || p === "/projects/guestlab" || p.startsWith("/projects/guestlab/events")),
    "read along: the chats one's agent is in, nothing else of the project read");
  await go("#/observe/guestlab/cnv-0301");
  expect(!byId("chat-text") && text(main).includes("You read along as the owner of an agent in this chat") && text(main.querySelector(".group-observers")).includes("you (owner of Spare)")
    && main.querySelector(".group-chat a.chat-back").getAttribute("href") === "#/observe/guestlab" && main.querySelectorAll(".group-chat li.msg").length === 1
    && text(main.querySelector(".group-chat li.msg")).includes("@guest"), "read along: the chat read only, its people by handle");
  // From outside: other observers neutrally, someone who left as a former participant, the access ending said.
  win.Maity.api.get = (p) => {
    gcOutGets.push(p);
    if (p === "/projects/guestlab/conversations/cnv-0301") return gcOutGet(p).then((v) => Object.assign({}, v, { observers: v.observers.concat(["hum-other"]) }));
    if (p === "/projects/guestlab/conversations/cnv-0301/messages?limit=200") {
      return gcOutGet(p).then((r) => Object.assign({}, r, { items: r.items.concat([{ id: "evt-7002", seq: 7002, conversation_id: "cnv-0301", from: "hum-gone", to: "cnv-0301", body: "bye", sent_at: "2026-10-22T09:05:00Z", mentions: [], redacted: false, redaction: null }]) }));
    }
    return gcOutGet(p);
  };
  await go("#/observe/guestlab/cnv-0301");
  expect(text(main.querySelector(".group-observers")).includes("another agent's owner") && !text(main.querySelector(".group-observers")).includes("outside the project")
    && text(main.querySelectorAll(".group-chat li.msg")[1]).includes("someone not in the chat"), "read along: other observers and someone not in the chat named neutrally");
  // The 30-second re-read pages to the end, and draws again only on a change.
  const gcLong = (seq) => ({ id: "evt-" + seq, seq, conversation_id: "cnv-0301", from: "hum-guest", to: "cnv-0301", body: "m" + seq, sent_at: "2026-10-22T10:00:00Z", mentions: [], redacted: false, redaction: null });
  let gcLongN = 205;
  const gcPages = [];
  win.Maity.api.get = (p) => {
    if (p === "/projects/guestlab/conversations/cnv-0301/messages?limit=200") { gcPages.push(p); return Promise.resolve({ items: Array.from({ length: 200 }, (_, i) => gcLong(8001 + i)), cursor: 8200, earlier: null }); }
    if (p === "/projects/guestlab/conversations/cnv-0301/messages?after=8200&limit=200") { gcPages.push(p); return Promise.resolve({ items: Array.from({ length: gcLongN - 200 }, (_, i) => gcLong(8201 + i)), cursor: 8000 + gcLongN }); }
    return gcOutGet(p);
  };
  await fireIntervals(); await tick(); await tick(); await tick();
  const gcFirstLi = main.querySelector(".group-chat li.msg");
  expect(main.querySelectorAll(".group-chat li.msg").length === 205 && gcPages.includes("/projects/guestlab/conversations/cnv-0301/messages?after=8200&limit=200"),
    "read along: the re-read pages to the end of a chat longer than 200");
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(main.querySelector(".group-chat li.msg") === gcFirstLi, "read along: nothing new, nothing drawn again (the list is a live region)");
  gcLongN = 206;
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(main.querySelectorAll(".group-chat li.msg").length === 206, "read along: a new message after the 200th shows");
  win.Maity.api.get = (p) => (p.startsWith("/projects/guestlab/conversations/cnv-0301/messages") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : gcOutGet(p));
  await fireIntervals(); await tick(); await tick();
  expect(text(main).includes("You no longer read this chat: your agent left it, or left the project"), "read along: an access that ended is said on the next re-read");
  win.Maity.api.get = gcOutGet;
  await go("#/observe/nowhere");
  expect(text(main).includes("None of your agents is in a project nowhere"), "read along: a project none of one's agents is in is said");
  win.Maity.api.get = gcOutGet; win.Maity.api.getAll = gcOutAll;
  // Without a project of one's own the landing still names where one reads along.
  win.Maity.api.get = (p) => (p === "/me" ? gcOutGet(p).then((x) => Object.assign({}, x, { projects: [] })) : gcOutGet(p));
  await go("#/all");
  expect(main.querySelector(".observe-note") && main.querySelector(".observe-note a").getAttribute("href") === "#/observe/guestlab", "read along: the empty landing names it too");
  win.Maity.api.get = gcOutGet;

  // A closed project: no new group chat.
  const gcMe = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maity" ? gcMe(p).then((x) => Object.assign({}, x, { state: "accepted" })) : gcMe(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat");
  expect(!main.querySelector("a.new-group"), "group chat: a closed project offers no new group chat");
  await go("#/p/maity/chat/new");
  expect(text(main).includes("The project is closed: it takes no new group chat.") && !main.querySelector("form.group-form"), "group chat: nor its form");
  win.Maity.api.get = gcMe;
  await go("#/p/maity/inbox");

  // Per hub, from its machine form (GET /openapi.json): what it does not serve is not offered.
  const hgGet = win.Maity.api.get;
  const hgPaths = (paths) => {
    win.Maity.api.forgetRoutes();
    win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths }) : hgGet(p));
  };
  const hgSettle = async () => { for (let k = 0; k < 6; k++) await tick(); };
  hgPaths({ "/api/v1/projects/{slug}/conversations": { get: {} } });
  await go("#/p/maity/inbox"); await go("#/p/maity/chat"); await hgSettle();
  expect(!main.querySelector("a.new-group") && text(main).includes("This hub has no group chats yet."),
    "hub without group chats: no New group chat, and that is said instead of an empty-looking list");
  await go("#/p/maity/chat/new"); await hgSettle();
  expect(!main.querySelector("form.group-form") && text(main).includes("there is none to create"), "hub without group chats: nor the form");
  await go("#/p/maity/inbox"); await projectSettings(); await hgSettle();
  expect(header.querySelector(".attach-admin") && !header.querySelector("form.remove-reported"), "hub without group chats: no removal of a closed group chat's message");
  await projectSettings();
  await go("#/all"); await hgSettle();
  expect(!main.querySelector(".observe-note"), "hub without group chats: nothing to read along in is named");
  await go("#/observe/guestlab"); await hgSettle();
  expect(text(main).includes("there is nothing to read along in") && !main.querySelector(".chat-list"), "hub without group chats: the read-along view says so");
  await go("#/p/maity/chat/agt-b"); await hgSettle();
  // The whole attachments part is hidden, so no file field is left without its label.
  const hgChooser = () => main.querySelector(".attach");
  expect(hgChooser() && hgChooser().hidden && byId("chat-files").disabled, "hub without attachments: no Attach files");
  expect(/\.attach\[hidden\] \{ display: none; \}/.test(fs.readFileSync(path.join(WEB, "css/app.css"), "utf8")),
    "hub without attachments: the part's own display does not beat its hidden attribute");
  // With both: offered (the route's parameter name and prefix do not matter).
  hgPaths({ "/projects/{slug}/conversations": { get: {}, post: {} }, "/api/v1/projects/{project}/attachments": { post: {} } });
  await go("#/p/maity/inbox"); await go("#/p/maity/chat"); await hgSettle();
  expect(main.querySelector("a.new-group") && !text(main).includes("This hub has no group chats yet."), "hub with group chats: New group chat is offered");
  await go("#/p/maity/inbox"); await projectSettings(); await hgSettle();
  expect(header.querySelector("form.remove-reported"), "hub with group chats: the removal of a closed group chat's message is offered");
  await projectSettings();
  await go("#/p/maity/chat/agt-b"); await hgSettle();
  expect(hgChooser() && !hgChooser().hidden, "hub with attachments: Attach files is offered");
  // A machine form that cannot be read keeps the controls.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : hgGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat"); await hgSettle();
  expect(main.querySelector("a.new-group"), "an unreadable machine form keeps New group chat");
  win.Maity.api.get = hgGet;
  win.Maity.api.forgetRoutes();
  await go("#/p/maity/inbox");

  // Personal requests (§7): in the cross-project inbox only, answered and withdrawn on /requests/{id}.
  const psCalls = [];
  const psPost = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { psCalls.push([p, b]); return psPost(p, b); };
  await go("#/p/maity/inbox"); await hgSettle();
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
  win.Maity.api.attachmentUrl = (slug, id, download) => "/api/v1/projects/" + slug + "/attachments/" + id + "/content" + (download ? "?download=1" : "");
  const atPick = async (id, files) => { const i = byId(id); i.files = files; i.dispatch("change"); for (let k = 0; k < 8; k++) await tick(); };
  const atFile = (name, bytes, size, type) => Object.assign(fakeFile(bytes, size, type), { name });
  await go("#/p/maity/chat/agt-b");
  expect(byId("chat-files") && main.querySelector("label.attach-button").getAttribute("for") === "chat-files", "attachments: the composer offers Attach files");
  await atPick("chat-files", [atFile("big.bin", [1, 2, 3], 10 * 1024 * 1024 + 1, "application/octet-stream")]);
  expect(!atCalls.length && text(main).includes("big.bin is larger than 10 MiB"), "attachments: over 10 MiB refused before uploading");
  await atPick("chat-files", [atFile("shot.png", PNG, 2048, "image/png"), atFile("notes.txt", [0x68, 0x69], 2, "text/plain")]);
  expect(atCalls[0][0] === "RAW" && atCalls[0][1] === "/projects/maity/attachments?name=shot.png" && atCalls[0][2] === "image/png"
    && atCalls[1][1] === "/projects/maity/attachments?name=notes.txt" && atCalls[1][2] === "text/plain"
    && main.querySelectorAll(".attach-pending li").length === 2 && text(main.querySelector(".attach-pending")).includes("shot.png"),
    "attachments: each file is uploaded raw, an image with its sniffed type, and shown as pending");
  btn(main.querySelectorAll(".attach-pending li")[1], "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(atCalls[2][0] === "DELETE" && /\/projects\/maity\/attachments\/att-/.test(atCalls[2][1]) && main.querySelectorAll(".attach-pending li").length === 1,
    "attachments: a pending one removed is deleted");
  main.querySelector("form.compose").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  const atSent = atCalls.find((c) => c[0] === "POST" && c[1] === "/projects/maity/conversations/agt-b/messages");
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
  await go("#/p/maity/chat/cnv-0007");
  expect(byId("group-files"), "attachments: a group chat's composer offers files");
  await go("#/p/maity/message");
  await atPick("message-files", [atFile("plan.pdf", [0x25, 0x50, 0x44, 0x46], 900, "application/pdf")]);
  byId("message-body").value = "the plan"; main.querySelector("form.message-form").dispatch("submit"); for (let k = 0; k < 6; k++) await tick();
  const atEvent = atCalls.filter((c) => c[0] === "POST" && c[1] === "/projects/maity/events").pop();
  expect(atEvent && atEvent[2].attachments.length === 1 && atEvent[2].body === "the plan", "attachments: a project message names its file");
  // The mock as the hub: an id that is no pending upload of the poster is refused.
  let atBad = null;
  try { await atPost("/projects/maity/events", { kind: "message", type: "notice", to: "all", body: "x", attachments: ["att-9999"] }); } catch (err) { atBad = err; }
  expect(atBad && atBad.details.fields.attachments["att-9999"] === "unknown", "attachments: the mock refuses an id that is no pending upload of the poster");
  // Project settings: everyone's pending uploads, another member's without name or type.
  await atRaw("/projects/maity/attachments?name=draft.png", fakeFile(PNG, 64), "image/png");
  const atAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/attachments?status=pending"
    ? atAll(p).then((r) => ({ items: r.items.concat([{ id: "att-other", uploaded_by: "agt-b", size: 4096, uploaded_at: "2026-10-23T00:00:00Z", expires_at: "2026-10-24T00:00:00Z",
      name: null, type: null, kind: null, sha256: null, width: null, height: null, message_seq: null }]), next_cursor: null }))
    : atAll(p));
  await go("#/p/maity/inbox"); await projectSettings(); for (let k = 0; k < 4; k++) await tick();
  const atAdmin = header.querySelector(".attach-admin");
  expect(atAdmin && text(atAdmin).includes("draft.png") && text(atAdmin).includes("4.0 KB · Agent B") && !text(atAdmin).includes("null"),
    "attachments: the admin sees everyone's pending uploads, another member's by size and uploader only");
  win.Maity.api.getAll = atAll;
  await projectSettings();
  // The mock never reuses an id after a deletion.
  const atX = await atRaw("/projects/maity/attachments?name=x.txt", fakeFile([0x78], 1, "text/plain"), "text/plain");
  const atY = await atRaw("/projects/maity/attachments?name=y.txt", fakeFile([0x79], 1, "text/plain"), "text/plain");
  await atDel("/projects/maity/attachments/" + atX.id);
  const atZ = await atRaw("/projects/maity/attachments?name=z.txt", fakeFile([0x7a], 1, "text/plain"), "text/plain");
  expect(atZ.id !== atY.id && atZ.id !== atX.id, "attachments: the mock gives a new id after a deletion");
  // One's own uploads no message names yet, offered in the composer to attach or remove.
  await go("#/p/maity/chat/agt-b");
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
  const atRest = atCalls.filter((c) => c[0] === "POST" && c[1] === "/projects/maity/conversations/agt-b/messages").pop();
  expect(atRest[2].attachments.length === 1 && atRest[2].attachments[0] === atY.id && !main.querySelectorAll(".attach-pending li").length,
    "attachments: it is sent with the message");
  // An image that fails to load: said, its download link kept.
  const atImg = main.querySelectorAll("li.msg").find((li) => li.querySelector("img.attach-image"));
  atImg.querySelector("img.attach-image").dispatch("error");
  expect(!atImg.querySelector("img.attach-image") && text(atImg).includes("shot.png: could not be shown.") && atImg.querySelector("a.attach-link") && btn(atImg, "Delete"),
    "attachments: an image that did not load is said, not called removed");
  // Inline only a raster type the hub produced; any id the hub gives.
  const atSvg = win.Maity.attachments.render({ slug: "maity" }, { body: "", attachments: [{ id: "f1", name: "a.svg", size: 10, type: "image/svg+xml", kind: "image" }] }, null);
  expect(!atSvg.querySelector("img") && atSvg.querySelector("a.attach-link"), "attachments: an image of another type is only a download");
  expect(win.Maity.dom.h("img", { src: "/api/v1/projects/maity/attachments/file_7Q/content" }), "attachments: the id is the hub's, not parsed");
  // A closed project takes no new files.
  const atState = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maity" ? atState(p).then((x) => Object.assign({}, x, { state: "archived" })) : atState(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/agt-b");
  expect(!byId("chat-files") && main.querySelector("img.attach-image"), "attachments: a closed project offers no new file, and still shows the ones there");
  win.Maity.api.get = atState;
  // Only the hub's own attachment path is a link or an image source.
  let atForeign = null;
  try { win.Maity.dom.h("a", { href: "/api/v1/projects/maity/attachments/../../me" }); } catch (err) { atForeign = err; }
  expect(atForeign && win.Maity.dom.h("img", { src: "/api/v1/projects/maity/attachments/att-1/content" }), "attachments: only the attachment path itself is allowed");
  // A hub without attachments is asked for the waiting uploads once per page load.
  const atAll2 = win.Maity.api.getAll;
  let atAsked = 0;
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending&uploaded_by=/.test(p)
    ? (atAsked++, Promise.reject(new win.Maity.api.ApiError("n", 404, p, "not_found", {}))) : atAll2(p));
  await go("#/p/maity/chat/agt-b"); await go("#/p/maity/message"); await go("#/p/maity/chat/agt-b");
  expect(atAsked === 1 && !main.querySelectorAll(".attach-earlier li").length, "attachments: a hub without them is asked once, nothing offered");
  // Project settings then asks no more either.
  let atAskedAll = 0;
  win.Maity.api.getAll = (p) => (/\/attachments\?status=pending/.test(p) ? (atAskedAll++, atAll2(p)) : atAll2(p));
  await go("#/p/maity/inbox"); await projectSettings(); for (let k = 0; k < 4; k++) await tick();
  expect(atAskedAll === 0 && text(header.querySelector(".attach-admin")).includes("This hub keeps no files yet."), "attachments: settings ask a hub without them no more");
  await projectSettings();
  win.Maity.api.getAll = atAll2;
  win.Maity.api.postRaw = atRaw; win.Maity.api.post = atPost; win.Maity.api.del = atDel; win.Maity.api.attachmentUrl = atUrl;
  await go("#/p/maity/chat/agt-b"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".attach") && main.querySelector(".attach").hidden, "attachments: once the hub answered 404, the composer offers no Attach files");
  await go("#/p/maity/inbox");

  // Messages (§8.4): the project's messages, newest first, by type, with mentions, files and removal.
  // A hub that keeps files again: the earlier 404 case left this page thinking it has none.
  if (win.Maity.attachments.forget) win.Maity.attachments.forget();
  await go("#/p/maity/messages");
  const pmTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Messages");
  const pmItems = () => main.querySelectorAll("ol.project-messages li.pmsg");
  const pmSeq = (seq) => pmItems().find((li) => li.attrs["data-seq"] === String(seq));
  expect(pmTab && pmTab.getAttribute("aria-current") === "page" && pmItems().map((li) => li.attrs["data-seq"]).filter((x) => x < "9000").join() === "6009,6005,6001"
    && Number(pmItems()[0].attrs["data-seq"]) > 9000, "messages: a tab with the project's messages, newest first");
  // While the view reads /events a removed message is never shown: a removed chat message looks the same there (§8.5, §8.8).
  expect(!pmSeq(6003) && !pmSeq(6012) && !text(main).includes("a token"), "messages: no removed message, a chat's or a project's");
  const pmHand = pmSeq(6005);
  expect(text(pmHand).includes("Handover") && text(pmHand).includes("Agent B to Maintainer") && pmHand.querySelectorAll("a").find((a) => !a.classList.contains("member-ref")).getAttribute("href") === "#/p/maity/board"
    && pmHand.querySelector("li.attach-item") && text(pmHand.querySelector(".attach-meta")).includes("exchange.log · 4.1 KB · text/plain") && btn(pmHand, "Delete"),
    "messages: type, sender, addressee, card and its file; an admin deletes the file");
  expect(pmSeq(6001).querySelector(".pmsg-mentions a").getAttribute("href") === "#/p/maity/members/hum-maintainer", "messages: the members it mentions, as links");
  byId("messages-type").value = "blocker"; byId("messages-type").dispatch("change");
  expect(pmItems().length === 1 && text(pmItems()[0]).includes("waits for the PyPI token"), "messages: filtered by type");
  byId("messages-type").value = ""; byId("messages-type").dispatch("change");
  // A file deleted by someone else arrives with the feed and stays removed on a redraw.
  await win.Maity.api.del("/projects/maity/attachments/att-0901");
  await fireIntervals(); await tick(); await tick();
  expect(text(pmSeq(6005)).includes("exchange.log: removed.") && !pmSeq(6005).querySelector(".attach-meta"), "messages: a file deleted elsewhere is said removed");
  byId("messages-type").value = "handover"; byId("messages-type").dispatch("change");
  byId("messages-type").value = ""; byId("messages-type").dispatch("change");
  expect(text(pmSeq(6005)).includes("exchange.log: removed.") && !btn(pmSeq(6005), "Delete"), "messages: a deleted file does not come back on a redraw");
  // A new message arrives in place, at the top; the list is not rebuilt.
  const pmKeep = pmSeq(6001);
  await win.Maity.api.post("/projects/maity/events", { kind: "message", type: "notice", to: "all", body: "new from the composer" });
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
  await win.Maity.api.post("/projects/maity/events/6001/redact", { reason: "outdated" });
  await fireIntervals(); await tick(); await tick();
  expect(!pmSeq(6001) && pmSeq(6005), "messages: a removal elsewhere takes it out");
  // The scan reads the latest window and says so; a cursor that does not move fails loud.
  const pmGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/projects/maity/events?after=latest&wait=0" ? Promise.resolve({ items: [], cursor: 20000 }) : pmGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/messages");
  expect(text(main).includes("Only the messages among the project's latest 5000 events are shown") && text(main).includes("No project messages yet."),
    "messages: a long log is read from its latest events, and that is said");
  let pmCalls = 0;
  win.Maity.api.get = (p) => (/\/events\?after=\d+&wait=0&limit=200$/.test(p)
    ? (pmCalls++, Promise.resolve({ items: Array.from({ length: 200 }, () => ({ seq: 5, kind: "member_joined", payload: {} })), cursor: 5 })) : pmGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/messages"); for (let k = 0; k < 4; k++) await tick();
  expect(pmCalls === 1 && text(main).includes("did not move"), "messages: a cursor that does not move stops the scan, said");
  // A member without events:admin: only what it may read, no Remove, Delete only on what it sent.
  win.Maity.api.get = (p) => (p === "/me" ? pmGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").role = "member"; return x; }) : pmGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/messages");
  expect(!pmSeq(6009) && pmSeq(6005) && !main.querySelectorAll("ol.project-messages button").some((b) => b.textContent === "Remove"),
    "messages: a member reads only what is addressed to it, and removes nothing");
  win.Maity.api.get = pmGet;
  await go("#/p/maity/inbox");

  // Ticker (docs/api.md §17): for me / everything, filters, why in words, follow and mute, a manual post.
  await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  const tkItems = () => main.querySelectorAll("ol.ticker-list li.ticker-item");
  const tkSeqs = () => tkItems().map((li) => li.attrs["data-seq"]).join();
  const tkSeq = (seq) => tkItems().find((li) => li.attrs["data-seq"] === String(seq));
  const tkTab = header.querySelectorAll("nav.views a").find((a) => a.textContent === "Ticker");
  const tkStatus = () => main.querySelector(".view-ticker .send-status");
  expect(tkTab && tkTab.getAttribute("aria-current") === "page" && tkSeqs() === "4330,4310",
    "ticker: a tab; For me lists the items with a reason for the viewer, newest first");
  expect(text(tkSeq(4310)).includes("For you: you own the whole repository, you follow web/.") && text(tkSeq(4310)).includes("Contract change")
    && tkSeq(4310).querySelector("a").getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/pull/214",
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
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => ({ items: tkBad.map((u, i) => Object.assign({}, r.items[0], { seq: 9990 + i, text: i ? "x" : "<b>bold</b>", url: u })), next_cursor: null })) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkItems().length === 5 && tkItems().every((li) => !li.querySelectorAll("a").some((a) => !a.classList.contains("member-ref"))) && text(tkSeq(9990)).includes("<b>bold</b>") && !tkSeq(9990).querySelector("b"),
    "ticker: text as text; javascript:, data:, http:, a leading space or a user in the URL is no link");
  // A decision answered in words has no reply label.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => ({ items: [Object.assign({}, r.items.find((x) => x.type === "merge"), { seq: 9995, type: "decision", contract: null,
    detail: { request_title: "Which hash?", reply_label: null } })], next_cursor: null })) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkSeq(9995)).includes("Decided: answered in writing — Which hash?") && !text(tkSeq(9995)).includes("null"), "ticker: a decision answered in words");
  win.Maity.api.get = tkGet;
  // Older follows the hub's cursor; a quick second click reads nothing twice; a filter change drops an answer still on its way.
  const tkCalls = [];
  let tkHold = null;
  win.Maity.api.get = (p) => {
    if (!p.startsWith("/projects/maity/ticker?")) return tkGet(p);
    tkCalls.push(p);
    const r = tkGet(p.replace("limit=50", "limit=2"));
    return tkHold && p.includes("cursor=") ? new Promise((done) => { tkHold = () => r.then(done); }) : r;
  };
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
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
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  const tkSub = () => main.querySelector("section.ticker-sub");
  expect(text(tkSub()).includes("web/") && text(tkSub()).includes("Releases") && text(tkSub()).includes("Notes"), "ticker: one's own follow and mute");
  const tkPatches = [];
  const tkPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { tkPatches.push([p, b]); return tkPatch(p, b); };
  btn(tkSub(), "Remove").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(tkPatches[0]) === JSON.stringify(["/projects/maity/ticker/subscription", { remove: { follow: { areas: ["web/"] } } }]) && text(tkSub()).includes("No longer following web/."),
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
  expect(JSON.stringify(tkCe) === JSON.stringify(["/projects/maity/ticker"])
    && main.querySelectorAll("label").find((l) => l.getAttribute("for") === "ticker-post-text").textContent.includes("Ctrl+Enter posts"),
    "Ctrl+Enter: the ticker post is posted, and its label says so");
  win.Maity.api.post = tkCePost;
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
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
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "from the feed", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkItems()[0]).includes("from the feed") && tkSeq(4320) === tkKeep && text(tkStatus()).includes("1 new item.") && /for=all/.test(tkLive[0]) && /after=\d+/.test(tkLive[0]),
    "ticker: a new item arrives with the feed, read with after=, on top, the rest kept");
  // The feed's event is only the signal: the listing's text is what shows.
  const tkSeen = tkItems().length;
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? tkGet(p).then((r) => ({ items: r.items.map((x) => Object.assign({}, x, { text: "as the listing says" })), next_cursor: null })) : tkGet(p));
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "raw event text", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkItems()[0]).includes("as the listing says") && !text(main).includes("raw event text") && tkItems().length === tkSeen + 1, "ticker: items are the listing's, not built from the raw event");
  // In a filter that does not take it, a new item stays out.
  win.Maity.api.get = tkGet;
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "not a deploy", to: "all" });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(!text(main).includes("not a deploy") && tkItems().every((li) => li.className.includes("type-deploy")), "ticker: a new item outside the filter stays out");
  // More new items than one page: every one arrives.
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  const tkMany = tkItems().length;
  for (let i = 0; i < 60; i++) await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "burst " + i, to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 12; k++) await tick();
  expect(tkItems().length === tkMany + 60 && text(tkItems()[0]).includes("burst 59"), "ticker: more than a page of new items, every one arrives");
  // A failed live read is said.
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "lost?", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the new items: down"), "ticker: a failed live read is said");
  win.Maity.api.get = tkGet;
  // An item that comes twice in a page is shown once; a reason by role reads with its article.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/ticker?") && !p.includes("after=") ? tkGet(p).then((r) => {
    const x = Object.assign({}, r.items[0], { seq: 9980, for_me: true, why: ["role:owner", "role:admin"] });
    return { items: [x, x], next_cursor: null };
  }) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkItems().length === 1 && text(tkSeq(9980)).includes("you are an owner, you are an admin"), "ticker: one item once; role reasons with their article");
  win.Maity.api.get = tkGet;
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
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
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "late live", to: ["role:admin"] });
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
    if (p.startsWith("/projects/maity/ticker?") && tkFirst === true) return new Promise((done) => { tkFirst = () => tkGet(p).then(done); });
    return tkGet(p);
  };
  tkFirst = true;
  byId("ticker-type").value = "note"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 2; k++) await tick();
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "during the reset", to: ["role:admin"] });
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
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "first signal", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  const tkGo = tkHeld; tkHeld = null;
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "second signal", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  tkGo(); for (let k = 0; k < 10; k++) await tick();
  expect(text(main).includes("first signal") && text(main).includes("second signal"), "ticker: a signal during a live read is not lost");
  win.Maity.api.get = tkGet;
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  // A first page that failed: a signal reads that page again, never everything from the start.
  let tkFailFirst = true;
  const tkReads = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/projects/maity/ticker?")) tkReads.push(p);
    if (p.startsWith("/projects/maity/ticker?") && !p.includes("after=") && tkFailFirst) { tkFailFirst = false; return Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})); }
    return tkGet(p);
  };
  byId("ticker-type").value = "note"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the ticker: down") && !tkItems().length, "ticker: a failed first page is said");
  tkReads.length = 0;
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "after a failed page", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(tkReads.length >= 1 && tkReads.every((p) => !p.includes("after=")) && text(main).includes("after a failed page") && tkItems().length > 1,
    "ticker: the next signal reads the first page again, not after=0");
  expect(!text(tkStatus()).includes("Could not read the ticker"), "ticker: the page read again clears the failure");
  // After that, signals read after= again, and the new item goes on top.
  tkReads.length = 0;
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "after the re-read", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 8; k++) await tick();
  expect(tkReads.some((p) => /after=\d+/.test(p) && !/after=0(&|$)/.test(p)) && text(tkItems()[0]).includes("after the re-read"),
    "ticker: once the page is in, a signal reads after= and puts the item on top");
  win.Maity.api.get = tkGet;
  // A live read with nothing new ends a failure said before.
  byId("ticker-type").value = "deploy"; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  win.Maity.api.get = (p) => (p.includes("/ticker?") && p.includes("after=") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "fails", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(text(tkStatus()).includes("Could not read the new items"), "ticker: a failed live read is said");
  win.Maity.api.get = tkGet;
  await win.Maity.api.post("/projects/maity/ticker", { type: "note", text: "not for this filter", to: ["role:admin"] });
  await fireIntervals(); for (let k = 0; k < 6; k++) await tick();
  expect(!text(tkStatus()).includes("Could not read"), "ticker: the next live read with nothing new clears it");
  byId("ticker-type").value = ""; byId("ticker-type").dispatch("change"); for (let k = 0; k < 4; k++) await tick();
  // A member: no post form.
  win.Maity.api.get = (p) => (p === "/me" ? tkGet(p).then((x) => { x.projects.find((y) => y.slug === "maity").role = "member"; return x; }) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!tkPost() && tkSub(), "ticker: a member follows and mutes, and posts nothing");
  win.Maity.api.get = tkGet;
  // A 404 that the hub's machine form does not explain is an error, not "no ticker"; another failure too.
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/ticker?") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(main).includes("This hub has no ticker yet.") && main.querySelector(".error"), "ticker: a 404 while the hub lists the ticker is an error");
  win.Maity.api.get = (p) => (p.startsWith("/projects/maity/ticker?") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : tkGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(main).includes("This hub has no ticker yet.") && main.querySelector(".error"), "ticker: a 500 is an error, not no ticker");
  // A hub whose machine form has no ticker: said, decided once per page load.
  let tkAsked = 0;
  win.Maity.api.get = (p) => {
    if (p === "/openapi.json") return Promise.resolve({ openapi: "3.1.0", paths: {} });
    if (p.startsWith("/projects/maity/ticker?")) { tkAsked += 1; return Promise.reject(new win.Maity.api.ApiError("n", 404, p, "not_found", {})); }
    return tkGet(p);
  };
  win.Maity.api.forgetRoutes();
  await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); await go("#/p/maity/inbox"); await go("#/p/maity/ticker"); for (let k = 0; k < 4; k++) await tick();
  expect(tkAsked === 1 && text(main).includes("This hub has no ticker yet."), "ticker: a hub without it in its machine form is asked once, and that is said");
  win.Maity.api.get = tkGet;
  win.Maity.api.forgetRoutes();
  await go("#/p/maity/inbox");

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
  await go("#/p/maity/overview");
  const ovTab = () => header.querySelectorAll("nav.views a").find((a) => a.textContent === "Overview");
  expect(ovTab() && ovTab().getAttribute("href") === "#/p/maity/overview" && header.querySelectorAll("nav.views a")[1] === ovTab()
    && ovTab().getAttribute("aria-current") === "page", "overview: a tab, next to the inbox, marked while open");
  const ov = await ovGet(ovGets[0]);
  expect(ovGets.length === 1 && /^\/projects\/maity\/overview\?closed_after=\d{4}-\d\d-\d\dT[\d:]+Z$/.test(decodeURIComponent(ovGets[0]))
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
  expect(text(ovPart("overview-members")).includes("owner") && text(ovPart("overview-members")).includes("Maintainer")
    && ovPart("overview-members").querySelector("a").getAttribute("href") === "#/p/maity/members", "overview: members by role, linking to Members");
  const ovCounts = ovPart("overview-board").querySelectorAll(".overview-counts li");
  expect(ovCounts.length === 7 && ovCounts.every((li) => li.querySelector("a").getAttribute("href") === "#/p/maity/board")
    && text(ovCounts.find((li) => li.attrs["data-status"] === "in_progress")).startsWith(String(ov.board.counts.in_progress)),
    "overview: every column's count, each linking to the board");
  // The fixtures' requests are answered by now: the count and its empty state.
  expect(text(ovPart("overview-requests")).includes(String(ov.requests.open))
    && (ov.requests.open ? text(ovPart("overview-requests")).includes(" for you") : text(ovPart("overview-requests")).includes("Nothing waits for an answer."))
    && ovPart("overview-requests").querySelector("a").getAttribute("href") === "#/p/maity/inbox", "overview: the open requests, those for oneself, linking to the inbox");
  const ovReport = ovPart("overview-reports").querySelector("li");
  expect(ovReport && text(ovReport).includes("Agent B") && text(ovReport).includes("tsk-0005")
    && ovReport.querySelectorAll("a").some((a) => a.getAttribute("href") === "https://github.com/oliver-zehentleitner/maity/pull/3") && text(ovReport).includes("PR #3 open"),
    "overview: the latest report with its card, its author and its pull request as the probe saw it");
  // Re-read on a card, a request or the probe; not on anything else; no Reload offered.
  ovFeed = [{ seq: 10100, kind: "member_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); await tick(); await tick();
  expect(ovGets.length === 1, "overview: a member event does not re-read the counts");
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
    : p === "/projects/maity" ? ovGet(p).then((x) => Object.assign({}, x, { repository: null, keep_the_why_export: null })) : ovGet(p));
  await go("#/p/maity/overview");
  expect(text(ovPart("overview-board")).includes("No cards yet.") && text(ovPart("overview-requests")).includes("Nothing waits for an answer.")
    && text(ovPart("overview-links")).includes("No repository.") && text(ovPart("overview-links")).includes("No Keep the Why dashboard is published.")
    && text(ovPart("overview-links")).includes("dashboard-state line"), "overview: empty states, and for an owner where the Keep the Why link comes from");
  btn(ovPart("overview-links"), "Set the repository").click(); await tick();
  expect(header.all().some((e) => e.id === "project-panel"), "overview: Set the repository opens Project settings");
  const badPr = ovPart("overview-reports").querySelector("li");
  expect(!badPr.querySelectorAll("a").some((a) => (a.getAttribute("href") || "").startsWith("javascript")) && text(badPr).includes("PR #9 merged")
    && text(badPr).includes("does not match what was reported"), "overview: a pull request URL that is no https link stays text; a mismatch is said");
  // A hub without the endpoint: links and members still, the counts said missing.
  win.Maity.api.get = (p) => (p.includes("/overview") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : ovGet(p));
  await go("#/p/maity/overview");
  expect(!main.querySelector(".error") && ovPart("overview-links") && ovPart("overview-members") && !ovPart("overview-board")
    && main.querySelector(".overview-missing") && text(main).includes("This hub has no overview yet") && !main.querySelector(".send-status.failed"),
    "overview: without the endpoint the rest stays, the counts said missing quietly, never as an error");
  // A refresh that meets the 404 again stays quiet too; any other failure is an error.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p.includes("/overview") ? Promise.reject(new win.Maity.api.ApiError("down", 500, p, "internal", {})) : ovGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/overview");
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
  await go("#/p/maity/overview");
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
    if (p === "/me") return ovMe(p).then((m) => { m.projects.find((x) => x.slug === "maity").role = "member"; return m; });
    if (p.includes("/overview") && ovSlow) { ovGets.push(p); return new Promise((done) => { ovSlow.push(() => ovGet(p).then(done)); }); }
    return ovMe(p);
  };
  await go("#/p/maity/inbox"); await go("#/p/maity/overview");
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
  await go("#/p/maity/inbox"); await go("#/p/maity/overview");
  expect(!text(ovPart("overview-reports")).includes("does not match"), "overview: mismatch null is no warning");
  win.Maity.api.get = ovGet;
  await go("#/p/maity/inbox");

  // The mock as the hub: closed cards counted after closed_after only; a bad limit is invalid.
  const allTime = await ovGet("/projects/maity/overview");
  const recent = await ovGet("/projects/maity/overview?closed_after=2030-01-01T00:00:00Z");
  let badLimit = null;
  try { await ovGet("/projects/maity/overview?limit=0"); } catch (err) { badLimit = err; }
  expect(allTime.board.closed_after === null && recent.board.counts.done === 0 && recent.board.counts.open === allTime.board.counts.open
    && badLimit && badLimit.details.fields.limit, "overview: the mock counts closed cards in the window, open ones in full, and refuses a bad limit");

  // The mock as the hub answers an admin agent (?as=agt-a, docs/api.md §2.3 ᵃ).
  win.location.search = "?as=agt-a";
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  const asAgent = async (call) => { try { return await call(); } catch (err) { return err; } };
  const aRole = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-r", { role: "member" }));
  const aPause = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-r", { paused: { reason: "quota" } }));
  const aRemove = await asAgent(() => win.Maity.api.del("/projects/maity/members/agt-b"));
  const aMember = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-b", { areas: ["web/"], paused: { reason: "quota" } }));
  const aCaps = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-b", { capabilities: ["tag"] }));
  const aProxy = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-b", { role: "proxy" }));
  const aHuman = await asAgent(() => win.Maity.api.patch("/projects/maity/members/hum-maintainer", { areas: ["x/"] }));
  const aSelf = await asAgent(() => win.Maity.api.patch("/projects/maity/members/agt-a", { areas: ["x/"] }));
  const aAfter = (await win.Maity.api.getAll("/projects/maity/members")).items;
  const humansOnly = (e) => e && e.code === "forbidden" && e.details.reason === "humans_only";
  expect(aRole.class === "consent" && aRole.to === "owner" && aRole.title === "Change reviewer to member"
    && aPause.title === "Pause reviewer" && aRemove.title === "Remove agent-b"
    && aAfter.find((x) => x.id === "agt-r").role === "reviewer" && !aAfter.find((x) => x.id === "agt-r").paused && aAfter.some((x) => x.id === "agt-b"),
    "mock as an admin agent: a reviewer's role or pause and any removal wait for the owner's consent (202), nothing changed yet");
  expect(aMember.id === "agt-b" && aMember.paused && aMember.areas.join() === "web/", "mock as an admin agent: a member agent's areas and pause apply at once");
  expect(humansOnly(aCaps) && humansOnly(aProxy) && humansOnly(aHuman) && humansOnly(aSelf),
    "mock as an admin agent: capabilities, proxy, a human's and its own membership are a human's");
  win.location.search = "";

  // Notifications (docs/api.md §18): the bell, the counts, browser notifications.
  await go("#/p/maity/inbox");
  const bellBtn = () => header.querySelector("button.bell");
  const tabCountOf = (name) => { const a = header.querySelectorAll("nav.views a").find((x) => x.textContent.startsWith(name)); const c = a && a.querySelector(".count"); return c ? c.textContent : null; };
  // Unread on the bell: every kind but the open requests (the inbox shows those); a sign-in alert counts.
  expect(bellBtn() && bellBtn().getAttribute("aria-label") === "Notifications, 4 unread" && text(bellBtn()).includes("4")
    && tabCountOf("Chat") === "1", "notifications: the bell says how many are unread; the chat tab its unread chats");
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
    && JSON.stringify(bellLinks) === JSON.stringify(["#/p/maity/agents", "#/account/sessions", "#/p/maity/board", "#/p/maity/chat/agt-a", "#/all", "#/p/sample/inbox", "#/p/maity/board"])
    && bellPanel().querySelectorAll(".bell-items li.unread").length === 6 && text(bellPanel()).includes("Mentions 1"),
    "notifications: the bell lists the latest, each linking to where it happened by its target, unread ones marked");
  // Escape closes it with the focus still on the bell.
  bellBtn().dispatch("keydown", { key: "Escape" });
  expect(bellPanel().hidden && bellBtn().getAttribute("aria-expanded") === "false", "notifications: Escape on the bell closes the panel");
  bellBtn().click(); await tick(); await tick();
  const maityBefore = Number(chipCount("Maity"));
  bellItem("Agent A in agent-a").querySelector("a").click(); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(nPosts[0]) === JSON.stringify(["/me/notifications/read", { ids: ["ntf-4237"] }]) && bellBtn().getAttribute("aria-label") === "Notifications, 3 unread"
    && Number(chipCount("Maity")) === maityBefore - 1, "notifications: opening an item marks it read, and the counts follow");
  // A sign-in alert is never confirmed by opening it (§2.6.5, §18.3).
  bellBtn().click(); await tick(); await tick();
  expect(text(bellPanel()).includes("stays unread: opening it here does not confirm it") && text(bellPanel()).includes("This was me under Sessions"),
    "notifications: the panel says a sign-in alert stays unread until This was me under Sessions");
  bellItem("New sign-in").querySelector("a").click(); for (let k = 0; k < 4; k++) await tick();
  expect(nPosts.length === 1 && bellBtn().getAttribute("aria-label") === "Notifications, 3 unread", "notifications: opening a sign-in alert marks nothing");
  bellBtn().click(); await tick(); await tick();
  btn(bellPanel(), "Mark all read").click(); for (let k = 0; k < 4; k++) await tick();
  const maityOpen = (await win.Maity.api.get("/me")).projects.find((x) => x.slug === "maity").open_requests;
  expect(JSON.stringify(nPosts[1]) === JSON.stringify(["/me/notifications/read", { up_to: "4241.7" }]) && bellBtn().getAttribute("aria-label") === "Notifications, 1 unread"
    && Number(chipCount("Maity")) === maityOpen,
    "notifications: Mark all read marks up to the bell's position, never the sign-in alert; the project's count is its open requests again");
  bellBtn().click(); await tick(); await tick();
  expect(!btn(bellPanel(), "Mark all read") && bellItem("New sign-in").className === "unread", "notifications: with only a sign-in alert left, no Mark all read");
  bellBtn().dispatch("keydown", { key: "Escape" });
  win.Maity.api.post = nPost;
  // A hub without notifications: no bell, the counts from /me as before.
  const nGet = win.Maity.api.get;
  win.Maity.api.get = (p) => (p.startsWith("/me/notifications") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : nGet(p));
  await go("#/p/maity/board"); await go("#/p/maity/inbox");
  expect(!bellBtn() && !text(main).includes("Could not read your notifications") && !tabCountOf("Chat"), "notifications: a hub without them shows no bell and no error");
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
  await go("#/p/maity/board");
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
    && byId("notify-kind-card").attrs.disabled !== undefined, "notifications: the settings, off, the browser not asked on opening them");
  const fresh = [
    { id: "ntf-5001", seq: 5001, kind: "chat", at: "2026-10-22T15:00:00Z", project: { slug: "maity", name: "Maity" }, actor: { member_id: "agt-a" }, title: "Agent A in agent-a", target: { type: "conversation", id: "agt-a" }, read: false, redacted: false, content: "secret text" },
    { id: "ntf-5002", seq: 5002, kind: "card", at: "2026-10-22T15:01:00Z", project: { slug: "maity", name: "Maity" }, actor: { member_id: "agt-b" }, title: "tsk-0004 …: reported", target: { type: "task", id: "tsk-0004" }, read: false, redacted: false },
    { id: "ntf-5003", seq: 5003, kind: "mention", at: "2026-10-22T15:02:00Z", project: { slug: "maity", name: "Maity" }, actor: { member_id: "hum-maintainer" }, title: "own", target: { type: "task", id: "tsk-0004" }, read: false, redacted: false },
  ];
  const polls = [];
  win.Maity.api.get = (p) => {
    if (p.startsWith("/me/notifications?after=")) { polls.push(p); const items = fresh.splice(0); return Promise.resolve({ counts: {}, items, next_cursor: null }); }
    return nGet(p);
  };
  byId("notify-browser").checked = true; byId("notify-browser").dispatch("change"); for (let k = 0; k < 8; k++) await tick();
  expect(asked === 1 && byId("notify-browser").checked && text(main).includes("Browser notifications are on.") && text(main).includes("This browser shows them."),
    "notifications: turning them on asks the browser once, and saves the wish");
  expect(polls.length >= 1 && /after=4241\.7&wait=55/.test(polls[0]) && shownNotes.length === 1 && shownNotes[0][0] === "Agent A in agent-a"
    && shownNotes[0][1].tag === "ntf-5001" && !shownNotes[0][1].body.includes("secret text"),
    "notifications: a new chat is shown with its id as tag, without its text; a card (off) and one's own are not");
  shownNotes.length = 0;
  // Something arrives on the hub before the next start: a restart begins at the hub's head then, not at the page's first one.
  const headNow = "4300.7";
  const nPoll = win.Maity.api.get;
  win.Maity.api.get = (p) => (p === "/me/notifications?limit=0" ? nGet(p).then((a) => Object.assign(a, { next_after: headNow })) : nPoll(p));
  polls.length = 0;
  fresh.push(Object.assign({}, { id: "ntf-5004", seq: 5004, kind: "chat", at: "2026-10-22T15:03:00Z", project: { slug: "maity", name: "Maity" }, actor: { member_id: "agt-a" }, title: "Agent A in agent-a", target: { type: "conversation", id: "agt-a" }, read: false, redacted: false, content: "x".repeat(300) }));
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
  await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
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
  await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
  expect(btn(sesBanner(), "End this session").attrs.disabled !== undefined && text(sesBanner()).includes("This session is too new to end older ones."),
    "sessions: the banner's End follows the same rules as the list");
  win.Maity.api.get = sesGet;
  // The banner stays while a session the mail sign-in approved is active, though the sign-in itself ended (§2.6.5).
  const approved = { id: "hss-41e0", method: "device_code", created_at: "2026-10-22T13:30:00Z", last_seen_at: "2026-10-22T13:31:00Z", browser: "Edge", os: "Windows",
    ip: "192.0.2.81", approved_by: "hss-41d2", good_standing: false, created: { record: "acr-8", ip: "192.0.2.81", browser: "Edge", os: "Windows" }, ended_at: null, ended_by: null };
  win.Maity.api.get = (p) => (p === "/auth/sessions?ended=true" ? sesGet(p).then((r) => ({ items: [approved].concat(r.items.map((x) => (x.id === "hss-41d2"
    ? Object.assign({}, x, { ended_at: "2026-10-22T13:40:00Z", ended_by: "logout" }) : x))) })) : sesGet(p));
  await go("#/p/maity/board"); await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
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
  await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
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
  await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
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
  await go("#/p/maity/inbox"); for (let k = 0; k < 6; k++) await tick();
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
  await go("#/p/maity/inbox"); await tick();
  const ceFree = main.querySelector(".current .free-text textarea");
  expect(text(ceLabel(ceFree.id)).includes("Ctrl+Enter sends"), "Ctrl+Enter: the inbox's free text says so");
  await ceCase("inbox answer", ceFree, "In my own words", "/projects/maity/requests/" + main.querySelector(".current .free-text textarea").id.split("-").slice(2).join("-") + "/answer", btn(main.querySelector(".current .free-text"), "Send"));
  // The chat, the group chat, the project message.
  await go("#/p/maity/chat/agt-b"); await tick();
  expect(text(ceLabel("chat-text")).includes("Ctrl+Enter sends"), "Ctrl+Enter: the chat says so");
  await ceCase("chat", byId("chat-text"), "hello", "/projects/maity/conversations/agt-b/messages", ceSubmitOf(byId("chat-text")));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-0007"); for (let k = 0; k < 4; k++) await tick();
  await ceCase("group chat", byId("chat-text"), "hello all", "/projects/maity/conversations/cnv-0007/messages", ceSubmitOf(byId("chat-text")));
  await go("#/p/maity/message"); await tick();
  expect(text(ceLabel("message-body")).includes("Ctrl+Enter sends"), "Ctrl+Enter: the project message says so");
  await ceCase("project message", byId("message-body"), "A note to all", "/projects/maity/events", ceSubmitOf(byId("message-body")));
  // A new card, a briefing, a join's briefing (the ticker post: in the Ticker's own part).
  await go("#/p/maity/board"); await tick();
  btn(main, "New card").click(); await tick();
  byId("new-card-title").value = "From the keyboard";
  await ceCase("new card", byId("new-card-body"), "Body text", "/projects/maity/tasks", ceSubmitOf(byId("new-card-body")));
  await go("#/p/maity/agents"); for (let k = 0; k < 4; k++) await tick(); await tick();
  const ceBox = main.querySelectorAll(".briefing")[0];
  (btn(ceBox, "Edit briefing") || btn(ceBox, "Write a briefing")).click(); await tick();
  const ceBrief = main.querySelector("form.briefing-form textarea");
  expect(text(ceLabel(ceBrief.id)).includes("Ctrl+Enter saves"), "Ctrl+Enter: the briefing says so");
  await ceCase("briefing", ceBrief, "Review first.", "/projects/maity/members/" + ceBrief.id.slice("briefing-".length), ceSubmitOf(ceBrief));
  await go("#/p/maity/join"); for (let k = 0; k < 4; k++) await tick(); await tick();
  byId("join-agent").value = byId("join-agent").querySelectorAll("option").map((o) => o.attrs.value).filter(Boolean)[0] || "";
  await ceCase("join", byId("join-briefing"), "Start with the open PRs.", "/projects/maity/joins", ceSubmitOf(byId("join-briefing")));
  win.Maity.api.post = cePost; win.Maity.api.patch = cePatch;
  await go("#/p/maity/inbox");

  // A member is always clickable (the maintainer's rule): every view names members through one
  // helper, a link to their view with the full name as tooltip; following it marks their row.
  const mrFollow = async (route, label) => {
    await go("#/p/maity/inbox"); await go(route); for (let k = 0; k < 6; k++) await tick();
    const refs = main.querySelectorAll("a.member-ref");
    const ref = refs[0];
    expect(ref && /^#\/p\/maity\/members\/[^/]+$/.test(ref.getAttribute("href")) && ref.getAttribute("title") && ref.getAttribute("data-member"),
      "member links: " + label + " names members as links with the full name as tooltip (" + refs.length + ")");
    if (!ref) return;
    const id = ref.getAttribute("data-member");
    await go(ref.getAttribute("href")); for (let k = 0; k < 4; k++) await tick();
    const row = main.querySelectorAll("tr.member").find((tr) => tr.attrs["data-member"] === id);
    expect(row && row.classList.contains("wanted"), "member links: from " + label + " the link lands on that member's row");
  };
  await mrFollow("#/p/maity/overview", "the overview");
  await mrFollow("#/p/maity/chat/agt-a", "the chat");
  await mrFollow("#/p/maity/messages", "the project messages");
  await mrFollow("#/p/maity/agents", "the agents");
  await mrFollow("#/p/maity/org", "the organisation");
  await mrFollow("#/p/maity/members", "the members list");
  await mrFollow("#/p/maity/board", "the board");
  // The inbox: the entry's asker.
  await go("#/p/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const mrAsker = main.querySelector(".current .facts a.member-ref");
  expect(mrAsker && mrAsker.getAttribute("href") === "#/p/maity/members/" + mrAsker.getAttribute("data-member"), "member links: the inbox names its asker as a link");
  // Across projects the page has no member list of the request's project: names stay text, never a guessed link.
  await go("#/all"); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".current") && !main.querySelectorAll(".entries a.member-ref").length,
    "member links: in all projects no member is linked, since no member list of their project was read");
  // The direct chat's heading names its agent as a link; a needs-in-session note names its member.
  await go("#/p/maity/chat/agt-a"); for (let k = 0; k < 4; k++) await tick();
  const mrHead = main.querySelector(".chat-pane") && main.querySelector(".chat-pane").querySelector("a.member-ref");
  expect(mrHead && mrHead.parentNode.tagName === "H2" && mrHead.getAttribute("data-member") === "agt-a",
    "member links: the direct chat's heading links its agent");
  await go("#/p/maity/inbox"); for (let k = 0; k < 4; k++) await tick();
  const mrNis = main.querySelectorAll(".entry-head").find((b) => (b.textContent || "").includes("Merge PR #2"));
  if (mrNis && mrNis.attrs["aria-expanded"] !== "true") { mrNis.click(); await tick(); }
  expect(main.querySelector(".current .flag a.member-ref"), "member links: a needs-in-session note links its member");
  // Someone the project does not list (removed, outside) is plain text, never a link.
  const mrPlain = win.Maity.dom.memberRef({ memberById: {}, link: () => "#/x", nameOf: () => "Gone" }, { member_id: "agt-gone", display_name: "Gone Agent" });
  expect(mrPlain.tagName === "SPAN" && mrPlain.classList.contains("plain") && text(mrPlain) === "Gone Agent" && mrPlain.getAttribute("title") === "Gone Agent",
    "member links: a member the project does not list is plain text");
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
  await go("#/p/maity/board"); for (let k = 0; k < 4; k++) await tick();
  const nhFirst = nhAsked["/me/notifications"] || 0;
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(nhFirst >= 1 && nhAsked["/me/notifications"] === nhFirst, "not on this hub: notifications absent are not asked again by the 15 s refresh " + nhFirst + "/" + nhAsked["/me/notifications"]);
  // The overview with a 405: quiet, and its events ask no more.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = nhAbsent("/projects/maity/overview", 405);
  await go("#/p/maity/inbox"); await go("#/p/maity/overview"); for (let k = 0; k < 4; k++) await tick();
  const nhOv = nhAsked["/projects/maity/overview"] || 0;
  feed = [{ seq: 10700, kind: "task_updated", actor: { member_id: "agt-b" }, payload: {} }];
  await fireIntervals(); for (let k = 0; k < 4; k++) await tick();
  expect(main.querySelector(".overview-missing") && !main.querySelector(".send-status.failed") && nhOv === 1 && nhAsked["/projects/maity/overview"] === 1,
    "not on this hub: the overview with a 405 is quiet, and an event does not ask again");
  // A group chat's link on a hub without group chats is quiet, not a red error.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : nhGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/cnv-9999"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".not-on-hub") && text(main).includes("This hub has no group chats yet, so this link cannot open here.") && !main.querySelector(".chat-layout .error"),
    "not on this hub: a group chat link without group chats is said quietly");
  // A 404 on a route the hub lists is the resource's (a project left): an error, never cached as absent.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: { "/api/v1/projects/{slug}/overview": { get: {} } } })
    : p.startsWith("/projects/maity/overview") ? Promise.reject(new win.Maity.api.ApiError("Not found", 404, p, "not_found", {})) : nhGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/overview"); for (let k = 0; k < 6; k++) await tick();
  expect(main.querySelector(".send-status.failed") && !main.querySelector(".overview-missing") && !win.Maity.api.absent.has("GET", "/projects/maity/overview"),
    "not on this hub: a 404 on a listed route stays an error and is not cached");
  // A direct chat's link (agt-…) is never explained away by missing group chats.
  win.Maity.api.forgetRoutes();
  win.Maity.api.get = (p) => (p === "/openapi.json" ? Promise.resolve({ openapi: "3.1.0", paths: {} }) : nhGet(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/chat/agt-gone"); for (let k = 0; k < 6; k++) await tick();
  expect(!main.querySelector(".not-on-hub") && text(main).includes("No conversation of yours with the id agt-gone."), "not on this hub: an unknown direct chat stays an error");
  win.Maity.api.get = nhGet;
  win.Maity.api.forgetRoutes();
  await go("#/p/maity/inbox");

  // Lead routing and the direct/group boundary.
  const leadA = { id: "agt-lead-a", kind: "agent", role: "admin", handle: "a", display_name: "Lead A", owner_id: "hum-other", presence: "online", availability: { state: "available" } };
  const leadB = { ...leadA, id: "agt-lead-b", handle: "b", display_name: "Lead B", owner_id: "hum-me" };
  const leadOut = { ...leadA, availability: { state: "limited" }, covered_by: { member_id: leadB.id } };
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: "role:admin" } }, [leadB, leadA]).id === leadA.id, "lead: admin sorted by handle");
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: leadA.id } }, [leadOut, leadB]).id === leadB.id, "lead: active cover takes over");
  expect(win.Maity.leadChat.resolve({ policy: {} }, [leadA]) === null, "lead: missing policy does not guess");
  const leadSub = { ...leadA, id: "agt-sub", handle: "sub" };
  expect(win.Maity.leadChat.resolve({ policy: { coordinator: leadA.id, coordinator_substitute: leadSub.id } }, [leadOut, leadB, leadSub]).id === leadSub.id,
    "lead: explicit available substitute precedes cover");
  const leadCtx = { me: { id: "hum-me", kind: "human" }, base: "/projects/maity", project: { policy: { coordinator: leadA.id } },
    members: [leadA, leadB], memberById: { [leadA.id]: leadA, [leadB.id]: leadB }, link: (view, id) => "#/p/maity/" + view + "/" + id };
  const oldHubLeadBox = win.Maity.leadChat.control({ ...leadCtx, project: { policy: {} } });
  expect(oldHubLeadBox.querySelectorAll("option").length === 1 && oldHubLeadBox.querySelector("option").attrs.value === leadB.id,
    "lead: older hub picker offers only the caller's own admins and proxies");
  const leadGetAll = win.Maity.api.getAll, leadPost = win.Maity.api.post, leadServed = win.Maity.groupChat.served;
  const leadWrites = [];
  win.Maity.groupChat.served = async () => true;
  win.Maity.api.getAll = async () => ({ items: [
    { id: "cnv-wider", kind: "group", access: "participant", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }, { member_id: "hum-third" }] },
    { id: "cnv-closed", kind: "group", access: "participant", closed_at: "2026-10-23T00:00:00Z", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] },
    { id: "cnv-observed", kind: "group", access: "observer", participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] }
  ] });
  win.Maity.api.post = async (path, body) => { leadWrites.push([path, body]); return { id: "cnv-new-lead" }; };
  const leadBox = win.Maity.leadChat.control(leadCtx);
  btn(leadBox, "Talk to the lead").click(); await tick(); await tick();
  expect(JSON.stringify(leadWrites) === JSON.stringify([["/projects/maity/conversations", { title: "Talk to the lead", participants: [leadA.id] }]])
    && win.location.hash.endsWith("/cnv-new-lead"), "lead: foreign-owned agent gets a two-person group, never a broader existing chat");
  win.Maity.api.getAll = async () => ({ items: [{ id: "cnv-pair", kind: "group", access: "participant", closed_at: null, participants: [{ member_id: "hum-me" }, { member_id: leadA.id }] }] });
  btn(leadBox, "Talk to the lead").click(); await tick(); await tick();
  expect(leadWrites.length === 1 && win.location.hash.endsWith("/cnv-pair"), "lead: reuses an open exact pair");
  const ownLeadBox = win.Maity.leadChat.control({ ...leadCtx, project: { policy: { coordinator: leadB.id } } });
  expect(ownLeadBox.querySelectorAll("a").some((a) => a.textContent === "Talk to the lead" && a.attrs.href.endsWith("/" + leadB.id)), "lead: own agent uses direct link");
  expect(win.Maity.leadChat.control({ ...leadCtx, me: { id: leadA.id, kind: "agent" } }) === null, "lead: agents have no button");
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
  win.Maity.api.get = (path) => silentGet(path).then((value) => path === "/projects/maity/members" ? silenceMembers(value)
    : path === "/me" && !silentAdmin ? { ...value, projects: value.projects.map((p) => ({ ...p, role: "member" })) } : value);
  win.Maity.api.getAll = (path) => silentAll(path).then((value) => path === "/projects/maity/members" ? silenceMembers(value) : value);
  await go("#/p/maity/board");
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
  await go("#/p/maity/members");
  expect(main.querySelectorAll(".member-silence").length > 0 && !main.querySelectorAll(".member-silence.flag-inline").length,
    "silence: ordinary members see last-call hints without admin warnings");
  await go("#/p/maity/board");
  expect(!byId("board-silent") && !main.querySelectorAll(".member-silence.flag-inline").length, "silence: filter and warning styling are admin-only");
  win.Maity.api.get = silentGet; win.Maity.api.getAll = silentAll;

  // Waiting activity: unread paging, grouping, request folding and in-place refresh.
  const waitGet = win.Maity.api.get, waitPost = win.Maity.api.post;
  const waitRows = [
    { id: "ntf-w1", kind: "chat", at: "2026-10-24T01:00:00Z", title: "Older chat", content: "PRIVATE MESSAGE", project: { slug: "maity", name: "Maity" }, target: { type: "conversation", id: "agt-a" } },
    { id: "ntf-w2", kind: "chat", at: "2026-10-24T02:00:00Z", title: "Newest chat", project: { slug: "maity", name: "Maity" }, target: { type: "conversation", id: "agt-a" } },
    { id: "ntf-open", kind: "inbox", title: "Duplicate request", project: { slug: "maity", name: "Maity" }, target: { type: "request", id: "req-open" } },
    { id: "ntf-answer", kind: "inbox", title: "Answered request", project: { slug: "maity", name: "Maity" }, target: { type: "request", id: "req-done" } },
    { id: "ntf-security", kind: "security", title: "Security alert", target: { type: "session", id: "ses-1" } },
    ...Array.from({ length: 201 }, (_, i) => ({ id: "ntf-card-" + i, kind: "card", at: "2026-10-24T01:00:00Z", title: "Card " + i, project: { slug: "sample", name: "Sample" }, target: { type: "task", id: "tsk-" + i } }))
  ];
  const waitRequests = [{ slug: "maity", id: "req-open", status: "open" }];
  const waitingGroups = win.Maity.waiting.rows(waitRows, waitRequests, "");
  expect(waitingGroups.chat.length === 1 && waitingGroups.chat[0].count === 2 && waitingGroups.chat[0].item.title === "Newest chat",
    "waiting: one conversation row with unread count and newest title");
  expect(waitingGroups.inbox.length === 1 && waitingGroups.inbox[0].item.id === "ntf-answer" && waitingGroups.account.length === 1,
    "waiting: open requests fold once; answers and account alerts remain");
  const waitCalls = [], waitWrites = [], waitDisposers = [];
  let waitFilter = "", waitVersion = 0, waitRelease = null, waitPolls = 0;
  win.Maity.notify.state.available = true;
  win.Maity.api.get = (path) => {
    if (path.startsWith("/me/notifications?unread=true")) {
      waitCalls.push(path);
      const cursor = Number(new URLSearchParams(path.split("?")[1]).get("cursor") || 0);
      const data = waitVersion ? waitRows.filter((x) => x.kind !== "chat") : waitRows;
      return Promise.resolve({ items: data.slice(cursor, cursor + 50), next_cursor: cursor + 50 < data.length ? String(cursor + 50) : null });
    }
    if (path.startsWith("/me/notifications?after=")) { waitPolls++; return new Promise((resolve) => { waitRelease = resolve; }); }
    return waitGet(path);
  };
  win.Maity.api.post = (path, body) => { waitWrites.push([path, body]); return Promise.resolve({}); };
  const waitHost = document.createElement("div");
  const waitCtx = { scope: "all", me: { id: "hum-me" }, refreshCounts: async () => {}, onDispose: (fn) => waitDisposers.push(fn) };
  const waitingView = await win.Maity.waiting.mount(waitCtx, waitHost, waitRequests, () => waitFilter);
  expect(waitCalls.length === 5 && waitCalls.every((p) => p.includes("limit=50")) && waitHost.querySelectorAll(".waiting-item").length === 200,
    "waiting: pages all unread items at50, renders at most200 rows");
  expect(text(waitHost).includes("More notifications") && !text(waitHost).includes("PRIVATE MESSAGE") && !text(waitHost).includes("Duplicate request"),
    "waiting: overflow has a full-list link; message content and duplicate requests are absent");
  waitFilter = "maity"; waitingView.draw();
  expect(waitHost.querySelectorAll(".waiting-item").length === 2 && !text(waitHost).includes("Security alert"), "waiting: project filter applies across groups");
  const waitChat = waitHost.querySelectorAll(".waiting-item").find((el) => el.getAttribute("data-notification") === "ntf-w2");
  waitChat.querySelector("a").click(); await tick();
  expect(JSON.stringify(waitWrites[0]) === JSON.stringify(["/me/notifications/read", { ids: ["ntf-w2"] }]), "waiting: opening a conversation marks its newest item read");
  waitVersion = 1; win.Maity.notify.changed(); for (let i = 0; i < 8; i++) await tick();
  expect(!text(waitHost).includes("Newest chat"), "waiting: a read update removes the conversation without replacing requests");
  expect(waitPolls <= 1, "waiting: one shared long-poll while browser notifications are off");
  waitDisposers.forEach((fn) => fn());
  if (waitRelease) waitRelease({ items: [], next_after: "waiting-head" });
  await tick();
  win.Maity.api.get = waitGet; win.Maity.api.post = waitPost;

  // Languages: project writes are human-admin only; personal language is not mail-gated.
  const languageGet = win.Maity.api.get;
  const languagePatch = win.Maity.api.patch;
  const languageWrites = [];
  win.Maity.api.patch = (path, body) => { languageWrites.push([path, body]); return languagePatch(path, body); };
  await go("#/p/maity/board"); await projectSettings();
  expect(!!byId("project-language"), "language: human owner can edit project language");
  byId("project-language").value = "de";
  header.querySelector("form.project-language").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(languageWrites[0]) === JSON.stringify(["/projects/maity", { settings: { language: "de" } }]), "language: project patch changes only language");
  win.Maity.api.get = (path) => languageGet(path).then((value) => path === "/me"
    ? Object.assign({}, value, { projects: value.projects.map((p) => Object.assign({}, p, { role: "member" })) }) : value);
  await go("#/p/maity/inbox"); await projectSettings();
  expect(!byId("project-language") && text(header).includes("Project language: Deutsch") && !byId("state-select"), "language: member sees read-only language without admin controls");
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
  win.Maity.api.get = (path) => languageGet(path).then((value) => path === "/projects/maity/members"
    ? { ...value, items: value.items.map((m) => ({ ...m, language: "de" })).concat([
      { ...value.items.find((m) => m.kind === "human"), id: "hum-removed-language", handle: "removed", language: "de", removed_at: "2026-10-23T00:00:00Z" }
    ]) } : value);
  await go("#/p/maity/members");
  const languages = main.querySelectorAll(".member-language");
  expect(languages.length === 1 && text(languages[0]) === "Language: Deutsch", "language: only active human profile shows language");
  win.Maity.api.get = languageGet;

  // Onboarding settings preserve the full editable object and hide on older hubs.
  const onboardingGet = win.Maity.api.get, onboardingPatch = win.Maity.api.patch;
  const onboardingWrites = [];
  win.Maity.api.patch = (path, body) => { onboardingWrites.push([path, body]); return onboardingPatch(path, body); };
  await go("#/p/maity/board"); await projectSettings();
  expect(!!byId("onboarding-briefing") && byId("onboarding-target").querySelectorAll("option").some((o) => o.attrs.value === "coordinator" && "selected" in o.attrs), "onboarding: default coordinator is editable");
  byId("onboarding-briefing").value = "Report here: **welcome**";
  byId("onboarding-target").value = "role:reviewer";
  header.querySelector("form.project-onboarding").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(onboardingWrites[0]) === JSON.stringify(["/projects/maity", { settings: { onboarding: { briefing: "Report here: **welcome**", check_in_with: "role:reviewer" } } }]), "onboarding: only briefing and target are written");
  expect(text(header).includes("Version 1") && text(header).includes("Onboarding saved."), "onboarding: saved version and status appear");
  byId("onboarding-briefing").value = "😀".repeat(16385);
  header.querySelector("form.project-onboarding").dispatch("submit"); await tick();
  expect(onboardingWrites.length === 1 && text(header).includes("16,384"), "onboarding: Unicode character cap prevents oversized write");
  byId("onboarding-briefing").value = ""; byId("onboarding-target").value = "";
  header.querySelector("form.project-onboarding").dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(onboardingWrites[1][1]) === JSON.stringify({ settings: { onboarding: {} } }), "onboarding: empty object disables check-in and clears default text");
  win.Maity.api.get = (path) => onboardingGet(path).then((v) => path === "/projects/maity"
    ? { ...v, settings: Object.fromEntries(Object.entries(v.settings).filter(([k]) => k !== "onboarding")) } : v);
  await go("#/p/maity/inbox"); await projectSettings();
  expect(!byId("onboarding-briefing"), "onboarding: absent setting hides section on older hub");
  win.Maity.api.get = (path) => onboardingGet(path).then((v) => path === "/projects/maity/members"
    ? { ...v, items: v.items.map((m) => ({ ...m, briefing: m.kind === "agent" ? "Own instructions" : null })) } : v);
  await go("#/p/maity/members");
  expect(main.querySelectorAll(".briefing-override").length > 0, "onboarding: own agent briefings are marked in members");
  win.Maity.api.get = onboardingGet; win.Maity.api.patch = onboardingPatch;

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
  await go("#/p/maity/inbox"); await go("#/all"); await pfSettle();
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
  await go("#/p/maity/inbox"); await go("#/all"); await pfSettle();
  const pfHead0 = main.querySelectorAll(".entry-head").find((b) => b.textContent.includes("change to your preferences"));
  if (pfHead0.attrs["aria-expanded"] !== "true") { pfHead0.click(); await pfSettle(); }
  const pfFresh = main.querySelector(".current .pref-review");
  expect(pfFresh && btn(pfFresh, "Accept") && btn(pfFresh, "Edit, then accept") && btn(pfFresh, "Decline") && !text(pfFresh).includes("changed since"),
    "preferences review: on the current version it offers Accept, Edit then accept, and Decline");
  const pfPuts = [];
  const pfPut = win.Maity.api.put;
  win.Maity.api.put = (p, b) => { pfPuts.push([p, b]); return pfPut(p, b); };
  await go("#/p/maity/inbox"); await go("#/account/preferences"); await pfSettle();
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
  const pfSample = byId("preferences-in-sample");
  expect(byId("preferences-in-maity").checked && pfSample && !pfSample.checked, "preferences: on per project, as the hub has it");
  pfSample.checked = true; pfSample.dispatch("change"); await pfSettle();
  expect(JSON.stringify(pfPuts[pfPuts.length - 1]) === JSON.stringify(["/me/preferences/projects/sample", { include: true }]), "preferences: a project switched on is saved at once");
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
  await go("#/p/maity/inbox"); await go("#/account/preferences"); await pfSettle();
  expect(text(main).includes("This hub keeps no preferences yet.") && !main.querySelector(".preferences .error"), "preferences: a hub without them says so quietly");
  win.Maity.api.get = pfGet; win.Maity.api.forgetRoutes();

  // The review: the current text (version 5 now), the proposal on version 2: stale.
  await go("#/p/maity/inbox"); await go("#/all"); await pfSettle();
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

  // An agent's card, for its owner: give it the owner's preferences.
  const pfPatches = [];
  const pfPatch = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { pfPatches.push([p, b]); return pfPatch(p, b); };
  await go("#/p/maity/inbox"); await go("#/p/maity/agents"); await pfSettle();
  const pfToggle = byId("owner-preferences-agt-a");
  expect(pfToggle && !pfToggle.checked && main.querySelectorAll(".owner-preferences").length === 1,
    "preferences: the owner's switch on an agent card, where the hub knows it");
  pfToggle.checked = true; pfToggle.dispatch("change"); await pfSettle();
  expect(JSON.stringify(pfPatches[0]) === JSON.stringify(["/projects/maity/members/agt-a", { owner_preferences: true }]), "preferences: the switch is saved on the membership at once");
  win.Maity.api.patch = pfPatch;

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
    if (init.method === "POST") {
      if (mode === "reject") return json(403, { error: { code: "csrf_mismatch", message: "CSRF token mismatch", details: {} } });
      const r = F["maity/requests.json"].items.find((x) => p.includes(x.id));
      return json(200, Object.assign({}, r, { status: "answered", answer: { reply_id: "sha", by: "hum-maintainer", at: "2026-10-21T14:00:00Z" } }));
    }
    const map = { "/auth/session": "auth-session.json", "/me": "me.json", "/projects/maity": "maity/project.json", "/projects/maity/members": "maity/members.json", "/projects/maity/requests": "maity/requests.json" };
    if (p === "/projects/maity/events") return json(200, { items: [], cursor: 0, superseded: false });
    return map[p] ? json(200, F[map[p]]) : json(404, { error: { code: "not_found", message: "nope", details: {} } });
  };
  vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx);
  document.cookie = "other=1; maity_csrf=tok%3D123";
  await go("#/p/maity/inbox");
  expect(!main.querySelector(".error"), "API mode against a fake hub renders the inbox");
  expect(Math.abs(win.Maity.api.now() - Date.parse(HUB_TIME)) < 5000, "API mode: the hub's clock from Maity-Server-Time");
  expect(!text(header).includes("Fixtures"), "no fixture label in API mode");
  expect(!head.querySelector("script"), "API mode never loads the fixture bundle");
  expect(calls.filter((c) => c.method === "GET").every((c) => !("X-CSRF-Token" in c.headers)), "no CSRF header on GET");
  const ps = byId("inbox-sort"); ps.value = "priority"; ps.dispatch("change"); await tick();
  btn(main.querySelector(".current"), "SHA-256 + pepper").click(); await tick();
  const post = calls.find((c) => c.method === "POST");
  // After answering the second entry the next one is the third, not the first.
  await go("#/p/maity/inbox");
  const heads = main.querySelectorAll(".entry-head");
  const second = heads.find((b) => b.textContent.includes("Merge PR #2"));
  if (second.attrs["aria-expanded"] !== "true") { second.click(); await tick(); }
  btn(main.querySelector(".current"), "go").click(); await tick(); await tick();
  expect(text(main.querySelector(".current")).includes("CLI binary"), "next entry is the one after the answered one");
  expect(post && post.headers["X-CSRF-Token"] === "tok=123", "POST carries X-CSRF-Token from maity_csrf");
  mode = "reject"; document.cookie = ""; calls.length = 0;
  await go("#/p/maity/inbox");
  const ps2 = byId("inbox-sort"); ps2.value = "priority"; ps2.dispatch("change"); await tick();
  btn(main.querySelector(".current"), "SHA-256 + pepper").click(); await tick();
  const post2 = calls.find((c) => c.method === "POST");
  expect(post2 && post2.headers["X-CSRF-Token"] === "fixture-csrf-token", "no cookie: token from /auth/session");
  expect(text(main).includes("Not sent: CSRF token mismatch (reload the page"), "csrf_mismatch shown on the entry");
  mode = "down";
  await go("#/p/maity/inbox");
  expect(main.querySelector(".error") && text(main).includes("did not answer"), "API mode without hub fails loud");
  expect(!main.querySelectorAll("a").some((a) => (a.attrs.href || "").includes("fixtures")), "the error offers no way into fixture mode");

  console.log(failures ? failures + " failure(s)" : "all ok");
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.log("CRASH", e.stack); process.exit(2); });
