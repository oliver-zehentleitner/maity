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
class Text_ extends Node_ { constructor(t) { super(); this.t = t; } get textContent() { return this.t; } }
class El extends Node_ {
  constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.attrs = {}; this.listeners = {}; this.className = ""; this.value = ""; this.disabled = false; }
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
    if (sel.includes(",")) return this.all().filter((e) => e.matches(sel));
    let set = [this];
    parts.forEach((p) => { set = [...new Set(set.flatMap((n) => n.all().filter((e) => e.matches(p))))]; });
    return set;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const header = new El("header"); header.id = "header";
const head = new El("head");
const main = new El("main"); main.id = "main";
const docListeners = {};
const document = {
  createElement: (t) => new El(t),
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
  setInterval: (fn) => { intervalId += 1; intervals.set(intervalId, fn); return intervalId; },
  clearInterval: (id) => { intervals.delete(id); },
};
const fireIntervals = async () => { for (const fn of [...intervals.values()]) await fn(); };
const ctx = { window: win, document, Node: Node_, URLSearchParams, console, Promise, JSON, Date, Set, Object, Array, Number, String, Error };
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
  const chip = (label) => header.querySelectorAll(".switcher a").find((a) => a.textContent.startsWith(label));
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

  await go("#/p/maity/chat");
  expect(main.querySelectorAll(".chat-picker li").length === 5, "chat picker lists own agents");
  await go("#/p/maity/chat/agt-a");
  expect(main.querySelectorAll(".msg").length === 2, "conversation with A");
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
  expect(text(main).includes("The board changed.") && text(main).includes("state, absence or policy changed"), "state change added to the notice");
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
  // The same with the State & absence panel open and typed in: no reload, the offer instead.
  win.Maity.api.get = realGet2; await go("#/p/maity/board"); await go("#/p/maity/inbox");
  btn(header, "State & absence").click(); await tick();
  byId("state-reason").value = "typed, not sent";
  win.Maity.api.get = bump("maity");
  await fireIntervals(); await tick(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "typed, not sent" && text(main).includes("What waits for you changed"),
    "with the State & absence panel open the empty list is not reloaded; the panel and its text stay");
  btn(header, "State & absence").click(); await tick();
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
  byId("join-handle").value = "agent-new"; byId("join-display").value = "Agent New";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  const newOpt = byId("join-agent").querySelectorAll("option").find((o) => o.textContent.startsWith("Agent New (@agent-new)"));
  expect(newOpt && byId("join-agent").value === newOpt.attrs.value && /^agt-/.test(newOpt.attrs.value),
    "a new profile is offered and selected after its join is created");
  expect(main.querySelectorAll(".joins li")[0].textContent.includes("Agent New as member"), "the joins list names the new profile");
  await go("#/p/maity/inbox");
  expect(!text(main).includes("FIXTURE"), "the line is gone after leaving the view");
  // count polling: a change offers a reload instead of replacing the list
  await fireIntervals(); await tick();
  expect(!main.querySelector(".notice .flag"), "no notice while nothing changed");

  // state and absence
  btn(header, "State & absence").click(); await tick();
  const sel = byId("state-select"); sel.value = "freeze";
  byId("state-reason").value = "release 0.1.0";
  // The 15-s count re-read replaces the switcher only; the open panel and what is typed stay.
  const switcherBefore = header.querySelector("nav.switcher");
  await fireIntervals(); await tick(); await tick();
  expect(byId("state-reason") && byId("state-reason").value === "release 0.1.0" && byId("state-select").value === "freeze",
    "the count re-read keeps the open State & absence panel and its input");
  expect(header.querySelector("nav.switcher") !== switcherBefore && header.querySelectorAll("nav.switcher").length === 1,
    "the count re-read replaces the switcher, once");
  byId("state-select").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header).includes("Freeze"), "state changed to freeze");
  btn(header, "State & absence").click(); await tick();
  byId("absence-until").value = "2026-10-25T08:00"; byId("absence-scope").value = "fixes only";
  byId("absence-until").parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(header).includes("Away until") && text(header).includes("fixes only"), "absence set");

  // sign out, sign in
  btn(header, "Sign out").click(); await tick(); await tick();
  expect(byId("login-handle"), "sign out shows the login");
  byId("login-handle").value = "maintainer"; byId("login-password").value = "wrong-but-nonempty";
  main.querySelector("form").dispatch("submit"); await tick(); await tick(); await tick();
  expect(!byId("login-handle") && !main.querySelector(".error"), "sign in returns to the dashboard");

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
  expect(!posts.length && fieldError("project-slug").includes("Lower-case") && byId("project-slug").getAttribute("aria-invalid") === "true",
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
  let mode = "ok";
  ctx.fetch = async (url, init) => {
    if (mode === "down") throw new Error("connection refused");
    calls.push({ url, method: init.method, headers: Object.assign({}, init.headers) });
    const [p, q] = url.replace("/api/v1", "").split("?");
    const json = (status, data) => ({ ok: status < 400, status, statusText: "x", headers: { get: (k) => (k === "Maity-Error" && data.error ? data.error.code : null) }, json: async () => data });
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
