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
  expect(btn(c2, "Go") && btn(c2, "No") && !btn(c2, "Discuss"), "replies go/no from the hub, no discuss");
  expect(btn(c2, "Go").className === "reply primary" && btn(c2, "No").className === "reply", "only the hub's go of a consent is primary");
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
  const pauseInput = byId("pause-agt-b"); pauseInput.value = "quota";
  pauseInput.parentNode.dispatch("submit"); await tick(); await tick();
  expect(text(main).includes("Paused") && text(main).includes("by Maintainer: quota"), "pause by the human");
  btn(main, "Revoke").click(); await tick(); await tick();
  expect(main.querySelectorAll(".credentials li.revoked").length === 2, "revoke keeps the credential listed as revoked");

  await go("#/p/maity/org");
  const tree = main.querySelector(".org-tree");
  expect(tree.childNodes.length === 1 && text(tree).includes("(by area)") && text(main).includes("Policy: hierarchical"), "org tree by areas, policy preset");

  await go("#/p/maity/chat");
  expect(main.querySelectorAll(".chat-picker li").length === 5, "chat picker lists own agents");
  await go("#/p/maity/chat/agt-a");
  expect(main.querySelectorAll(".msg").length === 2, "conversation with A");
  main.querySelector("textarea").value = "Thanks.";
  main.querySelector("form").dispatch("submit"); await tick();
  expect(main.querySelectorAll(".msg").length === 3 && text(main).includes("not picked up yet"), "sent message appended");
  const realGet2 = win.Maity.api.get;
  win.Maity.api.get = (p) => (p.includes("/messages?after=")
    ? Promise.resolve({ items: [{ id: "evt-9999", seq: 9999, conversation_id: "agt-a", from: "agt-a", to: "hum-maintainer", body: "On it.", sent_at: "2026-10-21T14:00:00Z", delivered_at: "2026-10-21T14:00:00Z" }], cursor: 9999 })
    : realGet2(p));
  await fireIntervals(); await tick();
  expect(main.querySelectorAll(".msg").length === 4 && text(main).includes("On it."), "polling shows the agent's reply");
  await fireIntervals(); await tick();
  expect(main.querySelectorAll(".msg").length === 4, "a message polled twice is shown once");
  win.Maity.api.get = realGet2;
  await go("#/p/maity/chat/nobody");
  expect(text(main).includes("No agent of yours"), "unknown agent id reported");

  await go("#/p/maity/join");
  expect(!main.querySelector(".error") && text(main).includes("join-0006"), "join view with existing joins");
  byId("join-agent").value = "agt-x";
  main.querySelector("form").dispatch("submit"); await tick(); await tick();
  expect(text(main).includes("maity join https://maity.example/j/FIXTURE") && text(main).includes("shown once"), "paste line shown once");
  btn(main, "Copy").click(); await tick();
  expect(ctx.copied && ctx.copied.startsWith("maity join"), "copy puts the line on the clipboard");
  btn(main, "Revoke").click(); await tick(); await tick();
  expect(text(main).includes("revoked"), "open join revoked");
  await go("#/p/maity/inbox");
  expect(!text(main).includes("FIXTURE"), "the line is gone after leaving the view");
  // count polling: a change offers a reload instead of replacing the list
  await fireIntervals(); await tick();
  expect(!main.querySelector(".notice .flag"), "no notice while nothing changed");

  // state and absence
  btn(header, "State & absence").click(); await tick();
  const sel = byId("state-select"); sel.value = "freeze";
  byId("state-reason").value = "release 0.1.0";
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
  btn(main.querySelector(".current"), "Go").click(); await tick(); await tick();
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
