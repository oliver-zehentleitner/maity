// One event by its number (/<owner>/<slug>/events/<seq>, docs/api.md §8.9, tsk-6g2h8dag2fkg):
// the page a `seq 68216` in a text links to (js/ids.js). It reads the event once and opens it
// where it lives, the address replaced by that place's with `#seq-<n>` after it: the chat it
// was said in (direct or group) when the hub names its conversation, else the card or the
// request it is about, else the project's messages for a message that is not a conversation's
// (one whose type says so, or a tombstone the Messages listing holds); the place then shows it
// marked (js/chat.js reveal, js/messages.js). An event that lives nowhere the reader may open
// is shown here. A 404 says "not visible", the same words for an event the reader may not see
// and one that does not exist, as the hub's answer is the same (§8.9): the page never tells
// the two apart either.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatTime } = M.dom;

  // The path's number as the hub parses it (§8.9): `0` or digits without a leading zero, at
  // most 2⁶³ − 1. Anything else is never sent; the page says what it says for a 404.
  const SEQ_MAX = BigInt("9223372036854775807");
  const seqOf = (raw) => (typeof raw === "string" && /^(0|[1-9][0-9]{0,18})$/.test(raw) && BigInt(raw) <= SEQ_MAX ? raw : null);

  // Where the event lives (§8.9 "The answer"): its conversation when the hub names one for
  // this reader, else its subject (a card, a request), else the project's messages for a
  // message whose type says it is a project message; null for none of them. A missing type
  // says nothing: a removed project message and a chat's tombstone the reader can no longer
  // open in its chat both come with no conversation and no type (review of #1629), and
  // Messages lists only the first. The kept audience tells most of them apart, but not a
  // project message to one member, whose audience is member: tokens alone like a chat's
  // (spq4, #1629 R2). Such a tombstone is undecided here (listedTombstone).
  function placeOf(ctx, e) {
    if (e.conversation_id) return ctx.link("chat", e.conversation_id);
    const s = e.subject;
    if (s && s.type === "task" && s.id) return ctx.link("tasks", s.id);
    if (s && s.type === "request" && s.id) return ctx.link("inbox", s.id);
    const type = e.payload && e.payload.type;
    if (e.kind === "message" && typeof type === "string" && type && type !== "chat") return ctx.link("messages");
    return null;
  }

  // A message placeOf left without a place and without a type: a tombstone, of a project
  // message or of a chat the reader no longer opens. Never guessed (review of #1629).
  const undecided = (e) => e.kind === "message" && !(e.payload && typeof e.payload.type === "string" && e.payload.type);

  // Whether the project's messages (§8.8) list this seq for this reader: the hub keeps a
  // message's conversation through its redaction and never lists a chat's, so the listing
  // tells the two tombstones apart in every case, the member-only one included. One page of one item, oldest
  // first from just below the seq, without a type (a tombstone is listed only unfiltered):
  // the seq is the first event that page examines, so the scan budget cannot pass it by, and
  // `after` stays valid at 2⁶³ − 1 where `before` = seq + 1 would not. The listed seq arrives
  // as a JSON number, so String(first.seq) === seq is exact only up to 2⁵³, the same limit as
  // Messages' own mark (js/messages.js); no project is near it (spq4, #1629 R3). seq ≥ 1 here
  // (0 is always a 404). Any failure is "not listed": the tombstone is then drawn on this page.
  async function listedTombstone(ctx, seq) {
    try {
      const page = await M.api.get(ctx.base + "/messages?after=" + (BigInt(seq) - BigInt(1)).toString() + "&limit=1");
      const first = page && Array.isArray(page.items) ? page.items[0] : null;
      return !!first && String(first.seq) === seq;
    } catch (err) {
      return false;
    }
  }

  // The event itself, where it has no other place: what it is, who and when, and a message's
  // text (a removed one as the listing has it).
  function drawn(ctx, e) {
    const who = e.actor && e.actor.member_id ? M.dom.memberRef(ctx, e.actor.member_id, { instance: e.actor.instance }) : null;
    const body = e.payload && typeof e.payload.body === "string" ? e.payload.body : null;
    return h("article", { class: "event-one seq-target", "data-seq": String(e.seq) },
      h("p", { class: "event-head" }, h("span", { class: "badge" }, String(e.kind)), who ? [" · ", who] : null,
        e.at ? [" · ", h("span", { class: "muted" }, formatTime(e.at))] : null),
      e.redacted ? h("p", { class: "muted msg-redacted" }, M.t("messages.removed"))
        : body ? h("div", { class: "md" }, M.markdown(body, M.ids.where(ctx), { mentions: e.payload.mentions, hrefOf: (id) => ctx.link("team", id), ctx })) : null);
  }

  M.views.event = async function (ctx, root, args) {
    const raw = args && args[0];
    const seq = seqOf(raw);
    const heading = h("h2", null, M.t("event.title", { seq: raw || "" }));
    const notVisible = () => append(root, heading, h("p", { class: "event-not-visible" }, M.t("event.not_visible")));
    if (!seq || (args && args.length > 1)) { notVisible(); return; }
    // The page is left while its read is on its way (another link, back): the answer then
    // changes nothing, above all not the address, which is no longer this page's. The app
    // drops a left view's drawing only after the view returns, too late for a redirect.
    const at = M.route.current().path;
    let disposed = false;
    if (ctx.onDispose) ctx.onDispose(() => { disposed = true; });
    const left = () => disposed || M.route.current().path !== at;
    let e;
    try {
      e = await M.api.get(ctx.base + "/events/" + seq);
    } catch (err) {
      if (left()) return;
      // §8.9: hidden and missing are one answer, and so are they here.
      if (err.status === 404 || (err.status === 400 && err.code === "invalid")) { notVisible(); return; }
      throw err;
    }
    if (left()) return;
    let place = placeOf(ctx, e);
    if (!place && undecided(e)) {
      const listed = await listedTombstone(ctx, seq);
      // The second read may outlive the page as the first may (above).
      if (left()) return;
      if (listed) place = ctx.link("messages");
    }
    if (place && M.route.isRoute(place)) { M.route.go(place + "#seq-" + seq, { replace: true }); return; }
    append(root, heading, h("p", { class: "muted" }, M.t("event.here")), drawn(ctx, e));
  };

  M.event = { placeOf, seqOf, listedTombstone };
})(window.Maity);
