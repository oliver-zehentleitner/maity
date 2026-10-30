// Trust × role (docs/api.md §2.3): a membership's trust says how far the
// project trusts the member, its role what the member does. The questions
// every view asks of a member or of the caller's own membership (ctx), in
// one place: who governs, who is an owner, who is a guest.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const TRUSTS = ["owner", "admin", "member", "guest"];
  // Every built-in role of §2.3, in its table's order, with its label and
  // what the member does in a few words (the table's second column). A
  // project may add its own roles on one of the first six (§2.3).
  const ROLE_WORDS = {
    coder: ["Coder", "claims cards, builds, checkpoints and reports"],
    reviewer: ["Reviewer", "reviews: moves cards from review to done, prepares releases"],
    tester: ["Tester", "tests, files bug cards, moves review to done where the policy requires a test"],
    designer: ["Designer", "design passes; answers the requests to role:designer"],
    writer: ["Writer", "content: the README, documentation, the website's words, release notes"],
    ops: ["Ops", "merges and deploys: placements, runner changes, releases, deploys on the ticker"],
    proxy: ["Proxy", "the owner's interface: relays the owner's decisions, decides nothing itself"],
    manager: ["Manager", "leads a line of members and is their interface to a human"],
    "red-team": ["Red team", "attacks the project's own test or staging instance and files each weakness as a bug card"],
    "blue-team": ["Blue team", "defends: hardens the project and fixes the red team's findings"],
    "purple-team": ["Purple team", "checks that a fix closes the attack it was for and moves the finding to done"],
  };
  const ROLES = Object.keys(ROLE_WORDS);
  // What an agent's own human may give it when bringing it (§3.1): not ops, not proxy.
  const MEMBER_TRUSTS = ["member", "guest"];
  const MEMBER_ROLES = ROLES.filter((r) => r !== "ops" && r !== "proxy");
  const roleLabel = (r) => (ROLE_WORDS[r] ? ROLE_WORDS[r][0] : r);
  const roleHelp = (r) => (ROLE_WORDS[r] ? ROLE_WORDS[r][1] : "");

  // A role picker's options: each role by its label, its help as the
  // tooltip; `wanted` chosen where offered, else `fallback`.
  const hints = new WeakMap();
  function fillRoles(select, offered, wanted, fallback) {
    const { h, append, clear } = M.dom;
    append(clear(select), offered.map((r) => h("option", { value: r, title: roleHelp(r) }, roleLabel(r))));
    select.value = offered.includes(wanted) ? wanted : fallback;
    if (hints.has(select)) hints.get(select)();
  }
  // The help line under a role picker: what the chosen role does.
  function roleHint(select) {
    const el = M.dom.h("p", { class: "hint role-help", id: select.id + "-help" });
    const set = () => { el.textContent = roleHelp(select.value); };
    hints.set(select, set);
    select.setAttribute("aria-describedby", el.id);
    select.addEventListener("change", set);
    set();
    return el;
  }

  const trustOf = (x) => (x && x.trust) || null;
  // Owner and admin hold the governance scopes (members:admin, tasks:admin, …),
  // never a proxy: it relays and decides nothing itself (§2.3, hub/scopes.py).
  const governs = (x) => (trustOf(x) === "owner" || trustOf(x) === "admin") && !!x && x.role !== "proxy";
  const owner = (x) => trustOf(x) === "owner";
  const guest = (x) => trustOf(x) === "guest";
  // A project role counts as its base where a built-in role is asked for.
  const roleIs = (x, role) => !!x && (x.role === role || x.role_base === role);
  // tasks:review, tasks:test and releases:write: the role's (a security
  // team as the role whose scopes it has, §2.3), or the governance scopes.
  const reviews = (x) => !guest(x) && (governs(x) || roleIs(x, "reviewer") || roleIs(x, "purple-team"));
  const tests = (x) => !guest(x) && (governs(x) || roleIs(x, "tester") || roleIs(x, "red-team"));
  const releases = (x) => !guest(x) && (governs(x) || roleIs(x, "reviewer") || roleIs(x, "purple-team") || roleIs(x, "ops"));

  // "admin · reviewer"; the trust alone where the role says nothing more.
  function words(x) {
    if (!x) return "";
    const t = trustOf(x);
    if (!t) return x.role || "";
    return x.role ? t + " · " + x.role : t;
  }

  // A `role:`/`trust:` token in words: "every admin", "every reviewer".
  function tokenWords(token) {
    if (token.startsWith("trust:")) return "every " + token.slice(6);
    if (token.startsWith("role:")) return "every " + token.slice(5);
    return token;
  }

  M.trust = { TRUSTS, ROLES, MEMBER_TRUSTS, MEMBER_ROLES, roleLabel, roleHelp, fillRoles, roleHint, governs, owner, guest, roleIs, reviews, tests, releases, words, tokenWords };
})(window.Maity);
