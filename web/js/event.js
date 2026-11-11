// One event by its number (/<owner>/<slug>/events/<seq>, docs/api.md §8.9, tsk-6g2h8dag2fkg):
// the page a `seq 68216` in a text links to (js/ids.js). It reads the event once and opens it
// where it lives, the address replaced by that place's with `#seq-<n>` after it: the chat it
// was said in (direct or group) when the hub names its conversation, else the project's
// messages for a project message that is not removed, one about a card included, whose card
// Messages links beside it, else the card or the request it is about; the place then shows it
// marked (js/chat.js reveal, js/messages.js). An event that lives nowhere the reader may open
// is shown here, a removed message without a card among them. A 404 says "not visible", the
// same words for an event the reader may not see and one that does not exist, as the hub's
// answer is the same (§8.9): the page never tells the two apart either.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatTime } = M.dom;

  // The path's number as the hub parses it (§8.9): `0` or digits without a leading zero, at
  // most 2⁶³ − 1. Anything else is never sent; the page says what it says for a 404.
  const SEQ_MAX = BigInt("9223372036854775807");
  const seqOf = (raw) => (typeof raw === "string" && /^(0|[1-9][0-9]{0,18})$/.test(raw) && BigInt(raw) <= SEQ_MAX ? raw : null);

  // Where the event lives (§8.9 "The answer"): its conversation when the hub names one for
  // this reader, else the project's messages for a message whose type says it is a project
  // message and that is not removed, one about a card included (the owner's decision of
  // 2026-11-11, req-cxyyb2w01s8m o2: the card panel lists no messages, Messages shows the text
  // and links the card beside it), else its subject (a card, a request); null for none of them,
  // and the page draws the event itself. A removed message never opens in Messages
  // (req-5zfznap3s3bj o1): a removed project message and a chat's tombstone the reader can no
  // longer open in its chat both come with no conversation and no type (review of #1629), and
  // §8.9 now places the two alike, on their card or else on this page, so nothing here tells
  // them apart and no second read is made (context/messages.md a96ea52b).
  function placeOf(ctx, e) {
    if (e.conversation_id) return ctx.link("chat", e.conversation_id);
    const type = e.payload && e.payload.type;
    if (e.kind === "message" && !e.redacted && typeof type === "string" && type && type !== "chat") return ctx.link("messages");
    const s = e.subject;
    if (s && s.type === "task" && s.id) return ctx.link("tasks", s.id);
    if (s && s.type === "request" && s.id) return ctx.link("inbox", s.id);
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
    const place = placeOf(ctx, e);
    if (place && M.route.isRoute(place)) { M.route.go(place + "#seq-" + seq, { replace: true }); return; }
    append(root, heading, h("p", { class: "muted" }, M.t("event.here")), drawn(ctx, e));
  };

  M.event = { placeOf, seqOf };
})(window.Maity);
