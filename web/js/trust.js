// Trust × role (docs/api.md §2.3): a membership's trust says how far the
// project trusts the member, its role what the member does. The questions
// every view asks of a member or of the caller's own membership (ctx), in
// one place: who governs, who is an owner, who is a guest.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const TRUSTS = ["owner", "admin", "member", "guest"];
  // The built-in roles offered; a project may add its own on one of the first
  // six (§2.3). `manager` waits for the hub's line:lead (not offered yet); a
  // member who holds it keeps it shown.
  const ROLES = ["coder", "reviewer", "tester", "designer", "writer", "ops", "proxy"];
  // What an agent's own human may give it when bringing it (§3.1).
  const MEMBER_TRUSTS = ["member", "guest"];
  const MEMBER_ROLES = ["coder", "reviewer", "tester", "designer"];

  const trustOf = (x) => (x && x.trust) || null;
  // Owner and admin hold the governance scopes (members:admin, tasks:admin, …),
  // never a proxy: it relays and decides nothing itself (§2.3, hub/scopes.py).
  const governs = (x) => (trustOf(x) === "owner" || trustOf(x) === "admin") && !!x && x.role !== "proxy";
  const owner = (x) => trustOf(x) === "owner";
  const guest = (x) => trustOf(x) === "guest";
  // A project role counts as its base where a built-in role is asked for.
  const roleIs = (x, role) => !!x && (x.role === role || x.role_base === role);
  // tasks:review, tasks:test and releases:write: the role's, or the governance scopes.
  const reviews = (x) => !guest(x) && (governs(x) || roleIs(x, "reviewer"));
  const tests = (x) => !guest(x) && (governs(x) || roleIs(x, "tester"));
  const releases = (x) => !guest(x) && (governs(x) || roleIs(x, "reviewer") || roleIs(x, "ops"));

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

  M.trust = { TRUSTS, ROLES, MEMBER_TRUSTS, MEMBER_ROLES, governs, owner, guest, roleIs, reviews, tests, releases, words, tokenWords };
})(window.Maity);
