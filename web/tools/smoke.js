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
  focus() {}
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
  getElementById: (id) => ({ header, main })[id],
  querySelector: (s) => header.querySelector(s) || main.querySelector(s),
  addEventListener: (t, f) => { docListeners[t] = f; },
  title: "",
  cookie: "",
};
// Intervals are recorded, not run: the test fires them when it wants to.
const intervals = new Map();
let intervalId = 0;
const win = {
  location: { protocol: "file:", search: "", hash: "", replace(h) { this.hash = h; setTimeout(() => win.onhashchange(), 0); } },
  addEventListener: (t, f) => { win["on" + t] = f; },
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
  expect(win.location.hash === "#/all", "empty hash with two projects lands on #/all");
  expect(!main.querySelector(".error"), "cross-project inbox renders");
  expect(gets.some((p) => p.startsWith("/requests")) && !gets.some((p) => p.includes("/members")), "#/all renders from the requests alone");
  expect(!text(main).includes("null") && !text(header).includes("null"), "no stray 'null' text");
  expect(chipCount("All projects") === "4" && chipCount("Maity") === "3" && chipCount("Sample shop") === "1", "switcher counts 4 / 3 / 1");
  expect(main.querySelectorAll(".project-label").length === 4, "every entry labelled with its project");
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
  expect(chipCount("All projects") === "4", "Later sends nothing, counts unchanged");
  btn(cur, "SHA-256 + pepper").click(); await tick(); await tick();
  expect(chipCount("All projects") === "3" && chipCount("Maity") === "2", "answer re-reads /me counts");
  const projSort = byId("inbox-sort"); projSort.value = "project"; projSort.dispatch("change"); await tick();
  expect(main.querySelectorAll(".project-label")[0].textContent.startsWith("Maity"), "sort by project");

  await go("#/p/maity/inbox");
  expect(text(header).includes("Build") && text(header).includes("Fixtures") && text(header).includes("Sign out"), "project header: state, fixtures label, sign out");
  expect(chip("Maity").getAttribute("aria-current") === "page", "switcher marks the current project");
  let c2 = main.querySelector(".current");
  expect(c2 && text(c2).includes("Merge PR #2") && text(c2).includes("On behalf of") && text(c2).includes("Reviewer · reviewer"), "consent without options, on_behalf_of shown");
  expect(btn(c2, "go") && btn(c2, "no") && !btn(c2, "Discuss"), "replies go/no from the hub, no discuss");
  expect(btn(c2, "go").className === "reply primary" && btn(c2, "no").className === "reply", "only the hub's go of a consent is primary");
  expect(JSON.stringify(c2.querySelector(".replies").querySelectorAll("button").map((b) => b.textContent)) === JSON.stringify(["Later", "Neither — let's talk", "no", "go"]),
    "the replies at the right edge: Later and talk first, the primary one last");
  expect(main.querySelectorAll("button").every((b) => !/reply-/.test(b.className)), "no reply id becomes a class");
  expect(text(c2).includes("Needs you in the session") && text(c2).includes("ses-a-0007"), "needs_in_session with member and session");
  btn(c2, "Neither — let's talk").click(); await tick(); await tick();
  c2 = main.querySelector(".current");
  expect(c2 && text(c2).includes("CLI binary") && text(c2).includes("context/join.md") && text(c2).includes("proceeds provisionally"), "next: decision with ktw_ref and while_open");
  const ta = c2.querySelector("textarea"); ta.value = "maity, as documented";
  btn(c2, "Send").click(); await tick(); await tick();
  expect(text(main).includes("Nothing waits for you."), "inbox empty");
  const show = byId("inbox-show"); show.value = "all"; show.dispatch("change"); await tick();
  expect(main.querySelectorAll(".entry").length === 4, "show all: 4 entries in maity, answered ones too");
  const sortSel = byId("inbox-sort"); sortSel.value = "agent"; sortSel.dispatch("change"); await tick();
  const names = main.querySelectorAll(".entry-head .meta").map((e) => e.textContent.split(" · ")[0]);
  expect(JSON.stringify(names) === JSON.stringify(["Agent A for Reviewer", "Agent B", "Agent C", "Agent D"].filter((n) => names.includes(n))) && names.length >= 3, "sort by agent: " + names.join(", "));

  // malformed and unknown routes
  await go("#/p/%E0%A4%A");
  expect(main.querySelector(".error") && text(main).includes("URI"), "malformed hash shows an error box");
  await go("#/p/maity/constructor");
  expect(text(main).includes("No such view") && document.title === "No such view · Maity", "prototype key is no view, sane title");
  await go("#/p/maity/nonsense");
  expect(text(main).includes("No such view"), "unknown view");
  expect(throws(() => win.Maity.dom.h("a", { href: "javascript:alert(1)" })), "h() refuses a javascript: href");
  expect(throws(() => win.Maity.dom.h("a", { onclick: "alert(1)" })), "h() refuses a string handler");

  await go("#/p/maity/board");
  expect(!main.querySelector(".error"), "board renders");
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
  await go("#/p/maity/agents");
  expect(main.querySelectorAll(".profile").length === 5 && main.querySelectorAll(".error").length === 1, "one failing credentials call costs one card section");
  win.Maity.api.getAll = realGetAll;
  await go("#/p/maity/agents");
  expect(!main.querySelector(".error"), "agents render");
  expect(main.querySelectorAll(".profile").length === 5, "5 agent profiles");
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
  expect(patches.length === 1 && patches[0][0] === "/projects/maity/members/agt-b" && JSON.stringify(patches[0][1]) === JSON.stringify({ briefing: "Review hub PRs first." })
    && !byId("briefing-agt-b") && text(main).includes("Review hub PRs first."), "a saved briefing is PATCHed and shown");
  btn(bBox(), "Edit briefing").click(); await tick();
  byId("briefing-agt-b").value = "";
  byId("briefing-agt-b").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(patches[1][1]) === JSON.stringify({ briefing: null }) && text(main).includes("No briefing yet."), "an empty briefing clears it");
  win.Maity.api.patch = realPatch;
  // A hub without briefings (the sample fixtures carry no such key): nothing offered.
  await go("#/p/sample/agents");
  expect(main.querySelectorAll(".profile").length && !main.querySelector(".briefing"), "no briefing editor where the hub has no briefings");
  await go("#/p/sample/join");
  expect(byId("join-agent") && !byId("join-briefing"), "no briefing field in the join where the hub has no briefings");
  await go("#/p/maity/agents");
  const pauseInput = byId("pause-agt-b"); pauseInput.value = "quota";
  pauseInput.parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(main).includes("Paused") && text(main).includes("by Maintainer: quota"), "pause by the human");
  expect(text(main).includes("The agent was told at once and gets no new work"), "a human's pause says what it does");
  expect(!text(main.querySelectorAll(".profile").find((p) => text(p).includes("Waiting for the API contract"))).includes("The agent was told at once"),
    "an agent's own pause is a declaration, without that line");
  btn(main, "Revoke").click(); await tick(); await tick();
  expect(main.querySelectorAll(".credentials li.revoked").length === 2, "revoke keeps the credential listed as revoked");

  // Users of this hub (docs/api.md §16.1), for the instance admin only.
  const usersLink = header.querySelectorAll("a").find((a) => a.textContent === "Users");
  expect(usersLink && usersLink.getAttribute("href") === "#/admin/users", "users: a header link for the instance admin");
  await go("#/admin/users"); await tick();
  const userRows = () => main.querySelectorAll("table.users tbody tr");
  const userNames = () => userRows().map((tr) => tr.querySelector(".user-name").textContent);
  expect(document.title === "Users · Maity" && JSON.stringify(userNames()) === JSON.stringify(["Guest Reviewer", "Maintainer", "Ops on call"]),
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
  win.Maity.api.get = (p) => (p.startsWith("/admin/users") ? Promise.reject(new win.Maity.api.ApiError("nope", 404, p, "not_found")) : uGet(p));
  await go("#/all"); await go("#/admin/users"); await tick();
  expect(text(main).includes("This hub has no user list yet.") && !main.querySelector(".error"), "users: a hub without the list says so");
  win.Maity.api.get = (p) => (p === "/me" ? uGet(p).then((x) => { x.member.instance_admin = false; return x; }) : uGet(p));
  await go("#/all"); await go("#/admin/users"); await tick();
  expect(!header.querySelectorAll("a").some((a) => a.textContent === "Users") && text(main).includes("Only the instance admin sees the users of this hub."),
    "users: no link and no list for anyone else");
  win.Maity.api.get = uGet;
  await go("#/p/maity/inbox");

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
  expect(document.title === "Runners · Maity" && main.querySelectorAll("article.runner").length === 3, "runners: the view lists the runners");
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
  expect(document.title === "Why · Maity · Maity" && text(main).includes("1 entry needs attention · 71 entries in 4 parts of the project")
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
  await go("#/p/maity/agents");
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
  await go("#/p/maity/agents");
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
  expect(bCard("tsk-0008").attrs.draggable === "true" && !bCard("tsk-0003").attrs.draggable && !bCard("tsk-0003").querySelector("form.card-move"),
    "board: a card that may move is draggable and has a Move menu; a closed one has neither");
  const bProto = Object.getPrototypeOf(main);
  const bFocus = bProto.focus;
  bProto.focus = function () { document.activeElement = this; };
  const moveSel = bCard("tsk-0008").querySelector("form.card-move select");
  expect(JSON.stringify(moveSel.querySelectorAll("option").map((o) => o.textContent)) === JSON.stringify(["Open it", "Cancel it"]), "board: the Move menu offers the allowed moves in words");
  moveSel.value = "open";
  bCard("tsk-0008").querySelector("form.card-move").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
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
  bCard("tsk-0005").querySelector("form.card-move").dispatch("submit"); for (let k = 0; k < 3; k++) await tick();
  expect(text(main).includes("Moving failed: Not done yet: a card it depends on is still open."), "board: the hub's refusal is said in words");
  win.Maity.api.patch = (p, b) => { bWrites.push(["PATCH", p, b]); return bPatch(p, b); };
  // Assign, and the live lease refused.
  const asg = bCard("tsk-0006").querySelector("form.card-assign select"); asg.value = "agt-d";
  bCard("tsk-0006").querySelector("form.card-assign").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(bWrites[bWrites.length - 1]) === JSON.stringify(["POST", "/projects/maity/tasks/tsk-0006/assign", { assignee: "agt-d" }])
    && text(main).includes("tsk-0006 is assigned to Agent D."), "board: assigned");
  const asg1 = bCard("tsk-0001").querySelector("form.card-assign select"); asg1.value = "agt-b";
  bCard("tsk-0001").querySelector("form.card-assign").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Assigning failed: It is claimed with a live lease"), "board: a live lease is not taken over, said in words");
  // Filters by member and area.
  const fm = byId("board-member"); fm.value = "agt-b"; fm.dispatch("change");
  const visibleIds = () => main.querySelectorAll("article.card").map((a) => a.attrs["data-card"]).sort();
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0004", "tsk-0005"]), "board: filtered by member " + JSON.stringify(visibleIds()));
  fm.value = ""; fm.dispatch("change"); const fa = byId("board-area"); fa.value = "cli/"; fa.dispatch("change");
  expect(JSON.stringify(visibleIds()) === JSON.stringify(["tsk-0006"]), "board: filtered by area");
  fa.value = "web/"; fa.dispatch("change"); fm.value = "agt-b"; fm.dispatch("change");
  expect(!visibleIds().length && text(main).includes("No card matches the filter."), "board: no match, said");
  fm.value = ""; fm.dispatch("change"); fa.value = ""; fa.dispatch("change");
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
  const nSel = bCard("tsk-f001").querySelector("form.card-move select"); nSel.value = "cancelled";
  bCard("tsk-f001").querySelector("form.card-move").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(colOf("tsk-f001").attrs["data-status"] === "cancelled" && !bCard("tsk-f001").querySelector("form.card-move")
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
  expect(document.title === "Members · Maity · Maity" && tables.length === 2 && tables[0].querySelectorAll("tr.member").length === 1
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
  dManage.querySelector("form.member-role").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[0]) === JSON.stringify(["PATCH", "/projects/maity/members/agt-d", { role: "reviewer" }]) && text(mRow("Agent D")).includes("reviewer"),
    "members: the role changed");
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); await tick();
  expect(mWrites.length === 1, "members: no pause without a reason");
  main.querySelector("tr.member-manage form.member-pause input").value = "quota";
  main.querySelector("tr.member-manage form.member-pause").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(JSON.stringify(mWrites[1][2]) === JSON.stringify({ paused: { reason: "quota" } }) && text(mRow("Agent D")).includes("quota"), "members: an agent paused with a reason");
  btn(main.querySelector("tr.member-manage"), "Clear pause").click(); for (let k = 0; k < 4; k++) await tick();
  main.querySelector("tr.member-manage select").value = "member";
  main.querySelector("tr.member-manage form.member-role").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(!text(mRow("Agent D")).includes("quota") && text(mRow("Agent D")).includes("member"), "members: pause cleared, role back");
  btn(mRow("Agent D"), "Done").click(); await tick();
  btn(mRow("Maintainer"), "Manage").click(); await tick();
  const ownerSel = main.querySelector("tr.member-manage select");
  expect(ownerSel.querySelectorAll("option").length === 5 && !main.querySelector("tr.member-manage form.member-pause"), "members: a human can be owner, has no pause");
  ownerSel.value = "admin";
  main.querySelector("tr.member-manage form.member-role").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Changing the role failed: The project's last owner cannot be demoted or removed.") && text(mRow("Maintainer")).includes("owner"),
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
  // A write that went through is said as done when the re-read fails.
  win.Maity.api.patch = mPatch; win.Maity.api.del = mDel;
  btn(mRow("Reviewer"), "Manage").click(); await tick();
  const rAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => (p === "/projects/maity/members" ? Promise.reject(new win.Maity.api.ApiError("down", 0, p)) : rAll(p));
  main.querySelector("tr.member-manage select").value = "proxy";
  main.querySelector("tr.member-manage form.member-role").dispatch("submit"); for (let k = 0; k < 4; k++) await tick();
  expect(text(main).includes("Reviewer is now proxy. Could not refresh: down") && !text(main).includes("Changing the role failed"),
    "members: a failed re-read after a write is no failed write");
  win.Maity.api.getAll = rAll;
  await win.Maity.api.patch("/projects/maity/members/agt-r", { role: "reviewer" });
  // The mock as the hub: removal revokes, releases claims, and answers again as it is.
  const credsBefore = (await win.Maity.api.getAll("/projects/sample/members/agt-s1/credentials")).items.filter((c) => !c.revoked_at).length;
  const removedS = await win.Maity.api.del("/projects/sample/members/agt-s1");
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

  // Chat: the chats left, the open one right (docs/api.md §9).
  await go("#/p/maity/chat");
  const convs = () => main.querySelectorAll(".chat-list a.conv");
  const conv = (name) => convs().find((a) => a.querySelector(".conv-title").textContent === name);
  expect(convs().length === 5 && text(main).includes("Pick a conversation.") && !main.querySelector(".chat-pane"), "chat: the list of own agents, nothing open yet");
  expect(convs()[0].querySelector(".conv-title").textContent === "Agent D" && convs()[1].querySelector(".conv-title").textContent === "Agent A",
    "chat: the newest chat first, the ones without messages after");
  const convA = conv("Agent A");
  expect(convA.getAttribute("href") === "#/p/maity/chat/agt-a" && text(convA).includes("Endpoints for join, tasks and requests are drafted.")
    && convA.querySelector(".count") && convA.querySelector(".count").textContent === "1" && convA.classList.contains("unread")
    && text(convA).includes("online") && convA.querySelector(".avatar").textContent === "AA",
    "chat: an entry has the agent, the last message, its time, the unread count, presence and an avatar");
  expect(text(conv("Agent D")).includes("You: Keep the inbox usable"), "chat: one's own last message reads You:");
  expect(!conv("Agent B").querySelector(".preview") && text(conv("Agent C")).includes("paused"), "chat: no messages, no preview; presence in words");
  await go("#/p/maity/chat/agt-a");
  expect(main.querySelectorAll(".msg").length === 2, "conversation with A");
  expect(main.querySelector(".chat-list-pane") && conv("Agent A").getAttribute("aria-current") === "page" && conv("Agent A").classList.contains("current")
    && !conv("Agent A").querySelector(".count"), "chat: the list stays beside the open chat; the open one is marked, its unread gone");
  // A draft per chat survives switching to another chat and back.
  main.querySelector("textarea").value = "half a thought"; main.querySelector("textarea").dispatch("input");
  await go("#/p/maity/chat/agt-d");
  expect(main.querySelector("textarea").value === "" && text(conv("Agent A")).includes("Draft: half a thought"), "chat: switching keeps the draft, shown in the list");
  await go("#/p/maity/chat/agt-a");
  expect(main.querySelector("textarea").value === "half a thought", "chat: the draft is back in its chat");
  expect(!text(conv("Agent A")).includes("Draft:"), "chat: the open chat's draft is in its composer, not in its row");
  expect(!conv("Agent D").getAttribute("aria-label") && /^AD ?Agent D, .+, online: You: Keep the inbox/.test(text(conv("Agent D"))),
    "chat: a row's name is its text, its parts apart " + JSON.stringify(text(conv("Agent D"))));
  main.querySelector("textarea").value = ""; main.querySelector("textarea").dispatch("input");
  // A redacted last message.
  const cAll = win.Maity.api.getAll;
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maity/conversations" ? r : { items: r.items.map((c) => (c.agent_id !== "agt-d" ? c
    : Object.assign({}, c, { last_message: Object.assign({}, c.last_message, { body: null, redacted: true }) }))), next_cursor: null }));
  await go("#/p/maity/chat");
  expect(text(conv("Agent D")).includes("A message was removed.") && !text(conv("Agent D")).includes("null"), "chat: a redacted last message");
  // A hub before last_message: no preview, the rest stays.
  win.Maity.api.getAll = (p) => cAll(p).then((r) => (p !== "/projects/maity/conversations" ? r
    : { items: r.items.map((c) => { const o = Object.assign({}, c); delete o.last_message; return o; }), next_cursor: null }));
  await go("#/p/maity/chat");
  expect(convs().length === 5 && !main.querySelector(".chat-list .preview"), "chat: a hub without last_message shows no preview");
  // A refresh asked for while a read runs is read once more after it.
  let convReads = 0;
  win.Maity.api.getAll = (p) => {
    if (p !== "/projects/maity/conversations") return cAll(p);
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
  await go("#/p/maity/inbox"); await go("#/p/maity/chat");
  expect(text(main).includes("You own no agents in this project.") && !convs().length, "chat: no agents, said");
  win.Maity.api.get = cGet;
  await fireIntervals(); await tick(); await tick();
  expect(convs().length === 5 && main.querySelector(".chat-list-pane p.muted").hidden, "chat: agents that appear fill the list");
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
  expect(feedPaths[0] && /after=0&wait=0&limit=200$/.test(feedPaths[0]), "the feed reads from the head with wait=0");
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
  btn(header, "Project settings").click(); await tick();
  byId("state-reason").value = "typed, not sent";
  win.Maity.api.get = bump("maity");
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "typed, not sent" && text(main).includes("What waits for you changed"),
    "with the Project settings panel open the empty list is not reloaded; the panel and its text stay");
  btn(header, "Project settings").click(); await tick();
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
  expect(text(main).includes("No agent of yours"), "unknown agent id reported");

  await go("#/p/maity/join");
  expect(!main.querySelector(".error") && text(main).includes("join-0006"), "join view with existing joins");
  // Each join's state from its fields; only an open one can be revoked, and it comes first.
  const joinRow = (id) => main.querySelectorAll(".joins li").find((li) => li.textContent.includes(id));
  const openRows = main.querySelector(".open-joins").querySelectorAll("li");
  expect(openRows.length === 1 && joinRow("join-0010").classList.contains("join-open") && text(joinRow("join-0010")).startsWith("open join-0010")
    && text(joinRow("join-0010")).includes("open until") && btn(joinRow("join-0010"), "Revoke"), "joins: an open join is listed first, with Revoke");
  const closedRows = main.querySelector(".closed-joins").querySelectorAll("li");
  expect(closedRows.length === 4 && closedRows.every((li) => !btn(li, "Revoke")), "joins: used, expired, burned and revoked joins have no Revoke");
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
  main.querySelector("form").dispatch("submit"); await tick();
  expect(!joinPosts.length && text(main).includes("the briefing is longer than 16,384 characters"), "a join briefing over 16 KiB is refused before sending");
  byId("join-briefing").value = "  You review hub/.  ";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(joinPosts.length === 1 && joinPosts[0][1].briefing === "You review hub/.", "the join sends the briefing, trimmed");
  win.Maity.api.post = realPost2;
  expect(text(main).includes("maity join https://maity.example/j/FIXTURE") && text(main).includes("shown once"), "paste line shown once");
  expect(text(main).includes("as a message in its clone of the repository") && text(main).includes("follows the join page"), "the paste line says where it goes");
  btn(main, "Copy").click(); await tick();
  expect(ctx.copied && ctx.copied.startsWith("maity join"), "copy puts the line on the clipboard");
  btn(main, "Revoke").click(); await tick(); await tick();
  expect(text(main).includes("revoked"), "open join revoked");
  // A join for a new profile: the list names it and the select offers it, without a reload.
  const agentSel = byId("join-agent"); agentSel.value = ""; agentSel.dispatch("change");
  expect(text(main).includes("Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit.") && byId("join-handle").getAttribute("aria-describedby") === "join-handle-rule",
    "the handle's rule is said up front, tied to its field");
  const joinsBefore = main.querySelectorAll(".joins li").length;
  byId("join-handle").value = "Agent_New";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(main.querySelectorAll(".joins li").length === joinsBefore && text(main).includes("No join created: the handle: Lowercase letters, digits and -, 2–31 characters, starting with a letter or digit."),
    "a handle against the rule is refused before sending, with the rule");
  byId("join-handle").value = "agent-new"; byId("join-display").value = "Agent New";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  const newOpt = byId("join-agent").querySelectorAll("option").find((o) => o.textContent.startsWith("Agent New (@agent-new)"));
  expect(newOpt && byId("join-agent").value === newOpt.attrs.value && /^agt-/.test(newOpt.attrs.value),
    "a new profile is offered and selected after its join is created");
  expect(main.querySelectorAll(".joins li")[0].textContent.includes("Agent New as member"), "the joins list names the new profile");
  // A join that expires while the view is open moves to the others without a reload.
  const jAll = win.Maity.api.getAll;
  const soon = { id: "join-soon", agent_id: "agt-b", role: "member", created_by: "hum-maintainer", created_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 60).toISOString(), used_at: null, burned: false, revoked_at: null };
  win.Maity.api.getAll = (p) => (p === "/projects/maity/joins" ? Promise.resolve({ items: [soon], next_cursor: null }) : jAll(p));
  await go("#/p/maity/inbox"); await go("#/p/maity/join");
  expect(btn(joinRow("join-soon"), "Revoke") && main.querySelector(".open-joins"), "joins: open while it lasts");
  await new Promise((r) => setTimeout(r, 80)); await fireIntervals(); await tick();
  expect(!main.querySelector(".open-joins") && text(main).includes("No open join.") && text(joinRow("join-soon")).startsWith("expired"),
    "joins: expired while the view is open, without a reload");
  expect(btn(joinRow("join-soon"), "Revoke"), "joins: just expired, it keeps Revoke for a minute: the hub decides");
  const jNow = win.Maity.api.now;
  win.Maity.api.now = () => Date.now() + 61000;
  await fireIntervals(); await tick();
  expect(!btn(joinRow("join-soon"), "Revoke"), "joins: a minute after it expired, no Revoke");
  // Expiry is judged by the hub's clock (M.api.now; its skew is tested in API mode).
  soon.expires_at = new Date(Date.now() - 5 * 60000).toISOString();
  win.Maity.api.now = () => Date.now() - 10 * 60000;
  await go("#/p/maity/inbox"); await go("#/p/maity/join");
  expect(main.querySelector(".open-joins") && btn(joinRow("join-soon"), "Revoke"), "joins: a browser ahead of the hub still sees an open join open");
  // A Revoke the hub refuses (expired by its clock): said, kept on screen, the list re-read.
  win.Maity.api.getAll = jAll;
  win.Maity.api.now = () => Date.parse("2026-10-21T08:10:00Z");
  await go("#/p/maity/inbox"); await go("#/p/maity/join");
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
  btn(header, "Project settings").click(); await tick();
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
  btn(header, "Project settings").click(); await tick();
  byId("absence-until").value = "2026-10-25T08:00"; byId("absence-scope").value = "fixes only";
  byId("absence-until").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header).includes("Away until") && text(header).includes("fixes only"), "absence set");

  // policy.signing: before required, the agents a bearer token would cut off.
  const sigPatches = [];
  const realPatch4 = win.Maity.api.patch;
  win.Maity.api.patch = (p, b) => { sigPatches.push([p, b]); return realPatch4(p, b); };
  btn(header, "Project settings").click(); await tick();
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
  btn(header, "Project settings").click(); await tick();
  expect(byId("signing-select").value === "required", "signing: the switch reads required after the change");
  byId("signing-select").value = "optional"; byId("signing-select").dispatch("change"); await tick();
  expect(!text(header.querySelector(".signing-impact")).length, "signing: back to optional needs no check");
  byId("signing-reason").value = "back to optional";
  byId("signing-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(JSON.stringify(sigPatches[1][1]) === JSON.stringify({ policy: { signing: "optional" }, reason: "back to optional" }), "signing: back to optional is sent");
  win.Maity.api.patch = realPatch4;
  await go("#/p/sample/inbox");
  btn(header, "Project settings").click(); await tick();
  expect(byId("state-select") && !byId("signing-select"), "signing: no switch where the hub has no signing policy");
  btn(header, "Project settings").click(); await tick();
  await go("#/p/maity/agents");
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
  btn(header, "Project settings").click(); await tick();
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
  btn(header, "Project settings").click(); await tick();
  // A hub before /me's logo: the switcher falls back to GET /projects.
  const realGet7 = win.Maity.api.get;
  const fallbackGets = [];
  win.Maity.api.get = (p) => { fallbackGets.push(p); return p === "/me" ? realGet7(p).then((m) => { m.projects.forEach((x) => { delete x.logo; }); return m; }) : realGet7(p); };
  await go("#/all"); await go("#/p/maity/inbox");
  expect(fallbackGets.includes("/projects") && chip("Maity").querySelector(".project-mark").tagName === "IMG",
    "logo: without logos on /me, the project views are read and the logo still shows");
  win.Maity.api.get = realGet7;
  win.Maity.api.putImage = realPut; win.Maity.api.del = realDel;
  // Account: change the password (docs/api.md §2.1).
  const accountLink = header.querySelectorAll("a").find((a) => a.textContent === "Account");
  expect(accountLink && accountLink.getAttribute("href") === "#/account", "the header links to the account");
  await go("#/account");
  expect(document.title === "Your account · Maity" && text(main).includes("@maintainer") && byId("password-current"), "the account view");
  const pwPosts = [];
  const realPost5 = win.Maity.api.post;
  win.Maity.api.post = (p, b) => { pwPosts.push([p, b]); return realPost5(p, b); };
  const pwSubmit = () => main.querySelector("form").dispatch("submit");
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

  // sign out, sign in
  btn(header, "Sign out").click(); await tick(); await tick();
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
  const createLink = main.querySelectorAll("a").find((a) => a.textContent === "Create a project");
  expect(createLink && createLink.getAttribute("href") === "#/new", "empty state offers Create a project");
  expect(chip("+ New project") && chip("+ New project").getAttribute("href") === "#/new", "switcher links to #/new");
  await go("#/new");
  expect(document.title === "New project · Maity" && byId("project-slug"), "create-project view");
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
  expect(text(main).includes("No agents in this project yet") && main.querySelectorAll("a").some((a) => a.textContent === "Join an agent."),
    "the new project offers to join an agent");
  expect(chip("Dogfood Hub") && chip("Dogfood Hub").getAttribute("aria-current") === "page", "the new project is in the switcher");
  // A first-time human: the empty board and inbox say where their content comes from.
  await go("#/p/dogfood/board");
  expect(text(main).includes("Every open card, and the done and cancelled ones of the last 14 days.")
    && main.querySelector(".first-hint") && text(main).includes("No cards yet. Your agents put the work here"), "empty board: subtitle and first hint");
  await go("#/p/dogfood/inbox");
  expect(text(main).includes("Nothing waits for you.") && text(main).includes("Your agents ask here when they need you"), "empty inbox: first hint");
  win.Maity.api.get = (p) => { gets.push(p); return realGet(p); };
  win.Maity.api.post = realPost;

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
