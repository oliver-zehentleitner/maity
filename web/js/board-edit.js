// Managing cards on the board (docs/api.md §6.4): a new card, moving a card
// between the columns a human may move it to (a status menu, and dragging
// for a pointer), and assigning it. Which moves are offered mirrors the
// hub's rules (hub cards.check_transition); the hub still decides, and its
// refusal is said in words. Within a column, tasks:admin places a card
// above or below another (POST …/move); the order is the hub's rank.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const CLOSED = new Set(["done", "cancelled"]);
  // Scopes by role (docs/api.md §2.3).
  const TASKS_ADMIN = new Set(["owner", "admin"]);
  const TASKS_REVIEW = new Set(["owner", "admin", "reviewer"]);
  const LABELS = [["", "no label"], ["feature", "feature"], ["fix", "fix"], ["chore", "chore"]];
  const KINDS = [["task", "Task"], ["maintenance_round", "Context round"]];
  const MOVE_WORDS = {
    open: "Open it", proposed: "Back to proposed", cancelled: "Cancel it",
    done: "Done", in_progress: "Back to work",
  };

  // The hub's refusals, in words; anything else is shown as it comes.
  const REFUSALS = {
    invalid_transition: "The hub does not allow that move.",
    dependencies_open: "Not done yet: a card it depends on is still open.",
    not_holder: "Only the holder moves this card to done.",
    lease_active: "It is claimed with a live lease; it can be assigned once the lease has run out.",
    release_not_ready: "The release is not ready; its card says what still blocks it.",
    release_card: "A release is never shipped with other cards; it ships them.",
    project_closed: "The project is closed; no new cards.",
    not_a_member: "Not a member of this project.",
    cycle: "That would make the cards depend on each other in a circle.",
    unknown: "Not a known value.",
    missing: "Required.",
  };

  function said(err) {
    if (REFUSALS[err.code]) return { message: REFUSALS[err.code] };
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) {
      const words = Object.entries(fields).map(([f, r]) => f.replace("_", " ") + ": " + (REFUSALS[r] || r));
      return { message: words.join("; ") };
    }
    return err;
  }

  const holds = (ctx, c) => !!(c.claim && c.claim.holder === ctx.me.id);
  const isAdmin = (ctx) => TASKS_ADMIN.has(ctx.role);

  function doneAuthority(ctx, c) {
    const a = (ctx.project.policy || {}).done_authority;
    if (a === "holder") return holds(ctx, c);
    if (a === "reviewer") return TASKS_REVIEW.has(ctx.role);
    return isAdmin(ctx);
  }

  // The statuses this human may move the card to, as the hub would allow.
  function targets(ctx, c) {
    const s = c.status;
    if (CLOSED.has(s)) return [];
    const editor = holds(ctx, c) || c.created_by === ctx.me.id || isAdmin(ctx);
    const out = [];
    if (editor && s === "proposed") out.push("open");
    if (editor && s === "open") out.push("proposed");
    if (s === "review" && doneAuthority(ctx, c)) out.push("done", "in_progress");
    if (s === "in_progress" && (ctx.project.policy || {}).done_authority === "holder" && holds(ctx, c)) out.push("done");
    if (isAdmin(ctx) || (s === "open" && c.created_by === ctx.me.id)) out.push("cancelled");
    return out;
  }

  // Card order within a status (§6.4): by rank, bytewise; then the cards
  // without one by created_at; then by id.
  function byOrder(a, b) {
    const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
    if (a.rank && b.rank) return cmp(a.rank, b.rank) || cmp(a.id, b.id);
    if (a.rank || b.rank) return a.rank ? -1 : 1;
    return cmp(a.created_at || "", b.created_at || "") || cmp(a.id, b.id);
  }

  // The keyboard's and the phone's way to place a card within its column:
  // the moves its place allows, each as the hub's move body. column: the
  // cards of its column as shown, in order.
  // Closed cards keep the order they had: nothing to plan there.
  const orderable = (ctx, c) => isAdmin(ctx) && !CLOSED.has(c.status);
  function orderControl(ctx, c, column, place) {
    if (!orderable(ctx, c) || column.length < 2) return null;
    const at = column.findIndex((x) => x.id === c.id);
    if (at < 0) return null;
    const ways = [];
    if (at > 0) ways.push(["up", "Move up", { before: column[at - 1].id }]);
    if (at < column.length - 1) ways.push(["down", "Move down", { after: column[at + 1].id }]);
    if (at > 1) ways.push(["top", "To the top", { to: "top" }]);
    if (at < column.length - 2) ways.push(["bottom", "To the bottom", { to: "bottom" }]);
    const id = "order-" + c.id;
    const select = h("select", { id, "data-focus": "order:" + c.id }, ways.map(([v, l]) => h("option", { value: v }, l)));
    select.value = ways[0][0];
    return h("form", {
      class: "card-order",
      onsubmit: (e) => {
        e.preventDefault();
        const way = ways.find(([v]) => v === select.value);
        place(c, way[2], "order:" + c.id);
      },
    }, h("label", { for: id }, "Place"), select, h("button", { type: "submit", class: "small" }, "Place"));
  }

  // The status menu: the keyboard's and the phone's way to move a card.
  function moveControl(ctx, c, move) {
    const allowed = targets(ctx, c);
    if (!allowed.length) return null;
    const id = "move-" + c.id;
    const select = h("select", { id, "data-focus": "move:" + c.id },
      allowed.map((s) => h("option", { value: s }, MOVE_WORDS[s] || s)));
    select.value = allowed[0];
    return h("form", {
      class: "card-move",
      onsubmit: (e) => {
        e.preventDefault();
        move(c, select.value, "move:" + c.id);
      },
    }, h("label", { for: id }, "Move"), select, h("button", { type: "submit", class: "small" }, "Move"));
  }

  function assignControl(ctx, c, assign) {
    if (!isAdmin(ctx) || CLOSED.has(c.status)) return null;
    const id = "assign-" + c.id;
    const select = h("select", { id, "data-focus": "assign:" + c.id }, h("option", { value: "" }, "choose a member"),
      ctx.members.filter((m) => m.id !== c.assigned_to).map((m) => h("option", { value: m.id }, m.display_name)));
    select.value = "";
    return h("form", {
      class: "card-assign",
      onsubmit: (e) => {
        e.preventDefault();
        if (!select.value) { select.focus(); return; }
        assign(c, select.value, "assign:" + c.id);
      },
    }, h("label", { for: id }, c.assigned_to ? "Reassign" : "Assign"), select, h("button", { type: "submit", class: "small" }, c.assigned_to ? "Reassign" : "Assign"));
  }

  // The new card (POST /tasks). assigned_to needs tasks:admin; a frozen or
  // fixes-only project needs a reason (docs/api.md §6.1).
  function newCardForm(ctx, cards, create, onCancel) {
    const id = (f) => "new-card-" + f;
    const title = h("input", { id: id("title"), required: true, maxlength: "200", autocomplete: "off" });
    const body = M.dom.sendOnCtrlEnter(h("textarea", { id: id("body"), rows: "4", placeholder: "What, acceptance, pointers (Markdown)" }));
    const label = h("select", { id: id("label") }, LABELS.map(([v, l]) => h("option", { value: v }, l)));
    label.value = "";
    const kind = h("select", { id: id("kind") }, KINDS.map(([v, l]) => h("option", { value: v }, l)));
    kind.value = "task";
    const areas = [...new Set(ctx.members.flatMap((m) => m.areas || []))].sort();
    const area = h("input", { id: id("area"), list: id("areas"), placeholder: "hub/", autocomplete: "off", spellcheck: "false" });
    const areaList = h("datalist", { id: id("areas") }, areas.map((a) => h("option", { value: a })));
    const status = h("select", { id: id("status") }, h("option", { value: "proposed" }, "Proposed: to talk about first"),
      h("option", { value: "open" }, "Open: ready to be claimed"));
    status.value = "proposed";
    const assignee = isAdmin(ctx)
      ? h("select", { id: id("assigned") }, h("option", { value: "" }, "by area (the hub routes it)"),
        ctx.members.map((m) => h("option", { value: m.id }, m.display_name)))
      : null;
    if (assignee) assignee.value = "";
    // A release ships cards; it is never one of the cards shipped together
    // (docs/api.md §6.7, hub cards.set_ships_with).
    const pick = (what, keep) => h("select", { id: id(what), multiple: true, size: "4" },
      cards.filter((x) => !CLOSED.has(x.status) && keep(x)).map((x) => h("option", { value: x.id }, x.id + " · " + x.title)));
    const deps = pick("depends", () => true);
    const ships = pick("ships", (x) => x.kind !== "release");
    const closedState = ctx.project.state === "freeze" || ctx.project.state === "fixes-only";
    const reason = closedState ? h("input", { id: id("reason"), required: true, autocomplete: "off" }) : null;
    const status_ = M.statusLine();
    const chosen = (sel) => Array.from(sel.querySelectorAll("option")).filter((o) => o.selected).map((o) => o.getAttribute("value"));
    const submit = h("button", { type: "submit" }, "Create card");
    const form = h("form", {
      class: "project-form new-card",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (!title.value.trim()) { status_.fail("Not created: ", { message: "the card needs a title" }); title.focus(); return; }
        if (reason && !reason.value.trim()) {
          status_.fail("Not created: ", { message: "the project is in " + ctx.project.state + "; say why this card is needed now" });
          reason.focus();
          return;
        }
        const card = { title: title.value.trim(), kind: kind.value, status: status.value };
        if (body.value.trim()) card.body = body.value;
        if (label.value) card.label = label.value;
        if (area.value.trim()) card.area = area.value.trim();
        if (assignee && assignee.value) card.assigned_to = assignee.value;
        const d = chosen(deps);
        const sw = chosen(ships);
        if (d.length) card.depends_on = d;
        if (sw.length) card.ships_with = sw;
        if (reason) card.reason = reason.value.trim();
        submit.disabled = true;
        status_.busy("Creating…");
        try {
          await create(card);
        } catch (err) {
          status_.fail("Not created: ", said(err));
        } finally {
          submit.disabled = false;
        }
      },
    },
    h("h3", null, "New card"),
    h("label", { for: id("title") }, "Title"), title,
    h("label", { for: id("body") }, "Body (" + M.dom.SEND_KEYS + " creates the card)"), body,
    h("label", { for: id("kind") }, "Kind"), kind,
    h("label", { for: id("label") }, "Label"), label,
    h("label", { for: id("area") }, "Area"), area, areaList,
    h("label", { for: id("status") }, "Status"), status,
    assignee ? [h("label", { for: id("assigned") }, "Assigned to"), assignee] : null,
    h("label", { for: id("depends") }, "Depends on (Ctrl or Shift to choose several)"), deps,
    h("label", { for: id("ships") }, "Ships with"), ships,
    reason ? [h("label", { for: id("reason") }, "Why now (the project is in " + ctx.project.state + ")"), reason] : null,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: onCancel }, "Cancel"), submit),
    status_.el);
    return { form, focus: () => title.focus(), body };
  }

  M.boardEdit = { targets, moveControl, assignControl, orderControl, orderable, byOrder, newCardForm, said, MOVE_WORDS };
})(window.Maity);
