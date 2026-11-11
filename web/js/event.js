// One event by its number (/<owner>/<slug>/events/<seq>, docs/api.md §8.9, tsk-6g2h8dag2fkg):
// the page a `seq 68216` in a text links to (js/ids.js). It reads the event once and opens it
// where it lives, the address replaced by that place's with `#seq-<n>` after it: the chat it
// was said in (direct or group) when the hub names its conversation, else the card or the
// request it is about, else the project's messages for a message; the place then shows it
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
  // message that is not a chat's; null for none of them.
  function placeOf(ctx, e) {
    if (e.conversation_id) return ctx.link("chat", e.conversation_id);
    const s = e.subject;
    if (s && s.type === "task" && s.id) return ctx.link("tasks", s.id);
    if (s && s.type === "request" && s.id) return ctx.link("inbox", s.id);
    if (e.kind === "message" && e.payload && e.payload.type !== "chat") return ctx.link("messages");
    return null;
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
    let e;
    try {
      e = await M.api.get(ctx.base + "/events/" + seq);
    } catch (err) {
      // §8.9: hidden and missing are one answer, and so are they here.
      if (err.status === 404 || (err.status === 400 && err.code === "invalid")) { notVisible(); return; }
      throw err;
    }
    const place = placeOf(ctx, e);
    if (place && M.route.isRoute(place)) { M.route.go(place + "#seq-" + seq, { replace: true }); return; }
    append(root, heading, h("p", { class: "muted" }, M.t("event.here")), drawn(ctx, e));
  };

  M.event = { placeOf, seqOf };
})(window.Maity);
