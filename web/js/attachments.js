// Attachments (docs/api.md §8.7): files on chat and project messages.
// A file is uploaded first (raw body, POST …/attachments?name=), pending
// until the message names it; an image is shown inline from the hub's own
// path, every other file only ever as a download link with its name, size
// and type — no preview, no viewer, nothing rendered. A message's
// attachment is deleted by who may (its uploader, a human in the chat, an
// admin for a project message); an admin lists and deletes the pending
// uploads of everyone, seeing only size and uploader for another's.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  const FILE_MAX = 10 * 1024 * 1024;
  const PER_MESSAGE = 10;
  const CLOSED_STATES = ["archived"];
  // The types the hub re-encodes an image to (§8.7): only these inline.
  const INLINE_TYPES = ["image/png", "image/jpeg", "image/webp"];
  // A hub that answered 409 attachments_not_configured has them off (§8.7:
  // no store set up): not asked again until the page is loaded anew. Any
  // other refusal, a 404 too, is an error like elsewhere.
  let hubOff = false;
  // Said where files are managed, in these words.
  const offWords = () => M.t("attach.off");
  function isOff(err) {
    if (err.status !== 409 || err.code !== "attachments_not_configured") return false;
    hubOff = true;
    return true;
  }

  function sizeOf(n) {
    if (n === null || n === undefined) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  // The hub's refusals of an upload, in words.
  const REFUSED = {
    unsupported_type: () => M.t("attach.refused.unsupported_type"),
    dimensions: () => M.t("attach.refused.dimensions"),
    undecodable: () => M.t("attach.refused.undecodable"),
    required: () => M.t("attach.refused.required"),
  };
  // `size`: the file's, said beside a refusal for size, since the hub's limit
  // in force (its 10 MiB for files, or a smaller body cap where it has no
  // upload route yet) is the hub's to name, not this page's.
  function said(err, size) {
    const why = err.code === "invalid" && err.details && err.details.fields && (err.details.fields.body || err.details.fields.name);
    if (why) return { message: Object.hasOwn(REFUSED, why) ? REFUSED[why]() : why };
    if (err.code === "payload_too_large") {
      // The hub's own words when it sent words; anything else is left out.
      return { message: typeof err.message === "string" && err.message
        ? M.t("attach.too_large.words", { size: sizeOf(size), words: err.message }) : M.t("attach.too_large", { size: sizeOf(size) }) };
    }
    if (err.code === "attachment_quota") return { message: err.details && err.details.scope === "pending"
      ? M.t("attach.quota.pending") : M.t("attach.quota.project") };
    if (err.code === "rate_limited") return { message: M.t("attach.rate_limited") };
    if (err.code === "project_closed") return { message: M.t("attach.project_closed") };
    if (err.code === "attachments_not_configured") return { message: offWords() };
    return err;
  }

  // The type to declare: an image's from its bytes (the hub sniffs and
  // compares, §8.7), any other file's as the browser knows it.
  async function typeOf(file) {
    const sniffed = M.dom.sniffImage ? await M.dom.sniffImage(file) : null;
    if (sniffed) return sniffed;
    const b = new Uint8Array(await file.slice(0, 6).arrayBuffer());
    if (b[0] === 0x47 && b[1] === 0x49 && b[2] === 0x46 && b[3] === 0x38) return "image/gif";
    return file.type || "application/octet-stream";
  }

  // The composer's part: choose files, each uploaded at once and shown as
  // pending with a Remove; ids() is what the message names. Not offered
  // in a closed project (§8.7: it takes no new files). One's uploads that
  // no message names yet (a composer left, a send that failed) are read
  // from the hub and offered apart, to attach here or to remove: they
  // count against the pending cap until sent or removed.
  function picker(ctx, idBase) {
    if (CLOSED_STATES.includes(ctx.project.state) || ctx.outsider) return null;
    const pending = [];
    const status = M.statusLine();
    const id = idBase + "-files";
    const input = h("input", { type: "file", id, multiple: true, class: "visually-hidden" });
    const list = h("ul", { class: "attach-pending", "aria-label": M.t("attach.pending") });
    const earlierList = h("ul", { class: "attach-earlier", "aria-label": M.t("attach.earlier") });
    const earlierBox = h("div", { class: "attach-earlier-box", hidden: true },
      h("p", { class: "muted" }, M.t("attach.earlier.hint")), earlierList);
    const tooMany = () => status.fail(M.t("attach.not_attached"), { message: M.t("attach.per_message", { count: PER_MESSAGE }) });
    let earlier = [];
    const drawEarlier = () => {
      clear(earlierList);
      const shown = earlier.filter((a) => !pending.some((p) => p.att && p.att.id === a.id));
      earlierBox.hidden = !shown.length;
      shown.forEach((a) => append(earlierList, h("li", null,
        h("span", { class: "attach-name" }, a.name), " ", h("span", { class: "muted" }, sizeOf(a.size)), " ",
        h("button", {
          type: "button", class: "small", "aria-label": M.t("attach.attach_earlier.label", { name: a.name }),
          onclick: () => {
            if (pending.length >= PER_MESSAGE) { tooMany(); return; }
            pending.push({ name: a.name, att: a });
            draw();
            input.focus();
          },
        }, M.t("attach.attach")), " ",
        h("button", {
          type: "button", class: "small", "aria-label": M.t("attach.remove_earlier.label", { name: a.name }),
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
            } catch (err) {
              status.fail(M.t("attach.not_removed"), said(err));
              // Off on the hub: the chooser goes, the line above says why.
              if (isOff(err)) { earlier = []; pending.length = 0; draw(); offer(false); el.hidden = false; }
              return;
            }
            earlier = earlier.filter((x) => x !== a);
            drawEarlier();
            input.focus();
          },
        }, M.t("attach.remove")))));
    };
    const loadEarlier = async () => {
      if (hubOff) return;
      try {
        earlier = (await M.api.getAll(ctx.base + "/attachments?status=pending&uploaded_by=" + encodeURIComponent(ctx.me.id))).items;
      } catch (err) {
        earlier = [];
        // Off on the hub: nothing to offer; any other failure is said.
        if (isOff(err)) offer(false); else status.fail(M.t("attach.earlier.failed"), err);
      }
      drawEarlier();
    };
    const draw = () => {
      drawEarlier();
      clear(list);
      pending.forEach((p) => append(list, h("li", null,
        h("span", { class: "attach-name" }, p.att ? p.att.name : p.name), " ",
        h("span", { class: "muted" }, p.att ? sizeOf(p.att.size) : M.t("attach.uploading_short")),
        p.att ? h("button", {
          type: "button", class: "small", "aria-label": M.t("attach.remove.label", { name: p.att.name }),
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(p.att.id));
            } catch (err) {
              status.fail(M.t("attach.not_removed"), said(err));
              // Off on the hub: the chooser goes, the line above says why.
              if (isOff(err)) { earlier = []; pending.length = 0; draw(); offer(false); el.hidden = false; }
              return;
            }
            pending.splice(pending.indexOf(p), 1);
            // Deleted on the hub: no longer waiting from before either.
            earlier = earlier.filter((a) => a.id !== p.att.id);
            draw();
            input.focus();
          },
        }, M.t("attach.remove")) : null)));
    };
    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      input.value = "";
      for (const file of files) {
        if (pending.length >= PER_MESSAGE) { tooMany(); break; }
        if (file.size > FILE_MAX) {
          status.fail(M.t("attach.not_attached"), { message: file.name ? M.t("attach.file_too_large", { name: file.name }) : M.t("attach.file_too_large.unnamed") });
          continue;
        }
        const p = { name: file.name || "file", att: null };
        pending.push(p);
        draw();
        status.busy(M.t("attach.uploading", { name: p.name }));
        try {
          p.att = await M.api.postRaw(ctx.base + "/attachments?name=" + encodeURIComponent(p.name), file, await typeOf(file));
          status.done();
        } catch (err) {
          pending.splice(pending.indexOf(p), 1);
          status.fail(M.t("attach.not_attached_named", { name: p.name }), said(err, file.size));
          // Off on the hub: the chooser goes, the line above says why.
          if (isOff(err)) { offer(false); el.hidden = false; draw(); break; }
          // Over the pending cap: show what waits, so it can be sent or removed.
          if (err.code === "attachment_quota") await loadEarlier();
        }
        draw();
      }
    });
    // Hidden, the whole part, while the hub has attachments off (§8.7): a
    // chooser whose every file would be refused is not offered, and no file
    // field is left in the page without its visible label. An upload's
    // failure says itself.
    const chooser = h("label", { for: id, class: "button small attach-button" }, M.t("attach.choose"));
    const el = h("div", { class: "attach", hidden: true }, chooser, input, list, earlierBox, status.el);
    function offer(yes) {
      el.hidden = !yes;
      chooser.hidden = !yes;
      input.disabled = !yes;
      input.hidden = !yes;
    }
    if (hubOff) offer(false);
    else {
      offer(true);
      loadEarlier();
    }
    return {
      el,
      // A composer may set the chooser in its action row (js/chat.js);
      // hidden with the rest while the hub takes no files.
      chooser,
      ids: () => pending.filter((p) => p.att).map((p) => p.att.id),
      busy: () => pending.some((p) => !p.att),
      // After the message was sent: the ones it named belong to it now; a
      // file picked while it was sending stays.
      clear: (sent) => {
        for (let i = pending.length - 1; i >= 0; i--) if (pending[i].att && sent.includes(pending[i].att.id)) pending.splice(i, 1);
        earlier = earlier.filter((a) => !sent.includes(a.id));
        draw();
      },
    };
  }

  // A message's attachments: images inline, files as download links.
  // canDelete(att) says whether this reader may take one out (§8.7).
  function render(ctx, msg, canDelete) {
    const atts = msg.attachments || [];
    if (!atts.length || msg.redacted || msg.body === null) return null;
    const box = h("ul", { class: "attach-list" });
    atts.forEach((a) => {
      const li = h("li", { class: "attach-item", "data-attachment": a.id });
      // Deleted here: said, and focus kept on the note. Marked on the
      // attachment itself, so a later redraw from the same data says it too.
      const gone = () => {
        a.removed = true;
        clear(li);
        const note = h("span", { class: "muted", tabindex: "-1" }, M.t("attach.removed", { name: a.name }));
        append(li, note);
        note.focus();
      };
      if (a.removed) {
        append(li, h("span", { class: "muted" }, M.t("attach.removed", { name: a.name })));
        append(box, li);
        return;
      }
      let shown = null;
      const url = M.api.attachmentUrl(ctx.slug, a.id, false);
      if (a.kind === "image" && INLINE_TYPES.includes(a.type) && url) {
        const w = a.width && a.height ? Math.min(a.width, 360) : null;
        shown = h("img", { class: "attach-image", src: url, alt: a.name, loading: "lazy",
          width: w ? String(w) : null, height: w ? String(Math.round(a.height * (w / a.width))) : null });
        // Not loaded (deleted, an access that ended, or a failure on the way):
        // said instead of a broken image; the link stays to try again.
        shown.addEventListener("error", () => {
          const note = h("span", { class: "muted" }, M.t("attach.not_shown", { name: a.name }), " ");
          if (shown.parentNode) { shown.parentNode.insertBefore(note, shown); shown.parentNode.removeChild(shown); }
        });
      }
      const dl = M.api.attachmentUrl(ctx.slug, a.id, true);
      append(li, shown,
        h("span", { class: "attach-meta" },
          dl ? h("a", { href: dl, download: a.name, class: "attach-link" }, a.name) : h("span", null, a.name),
          h("span", { class: "muted" }, " · " + sizeOf(a.size) + (a.kind === "image" ? "" : " · " + a.type))),
        // Attachments off on the instance (409): no delete that would fail.
        canDelete && !hubOff && canDelete(a) ? h("button", {
          type: "button", class: "small", "aria-label": M.t("attach.delete.label", { name: a.name }),
          onclick: async () => {
            if (!window.confirm(M.t("attach.delete.confirm", { name: a.name }))) return;
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
              gone();
            } catch (err) {
              // Off on the hub: no Delete left that would fail again, said calmly.
              if (isOff(err)) {
                const button = li.querySelector("button");
                if (button) li.removeChild(button);
                append(li, h("span", { class: "muted" }, " ", M.t("attach.not_deleted_off")));
                return;
              }
              append(li, h("span", { class: "send-status failed" }, " ", M.t("attach.not_deleted_reason", { reason: err.message || err.code })));
            }
          },
        }, M.t("attach.delete")) : null);
      append(box, li);
    });
    return box;
  }

  // An attachment_deleted of a message on screen: its file is said removed.
  function markDeleted(container, id) {
    const li = Array.from(container.querySelectorAll("li.attach-item")).find((x) => x.getAttribute("data-attachment") === id);
    if (!li) return;
    const named = li.querySelector(".attach-link") || li.querySelector(".attach-meta span");
    clear(li);
    append(li, h("span", { class: "muted" }, named ? M.t("attach.removed", { name: named.textContent }) : M.t("attach.removed.unnamed")));
  }

  // Project settings: the pending uploads of everyone, for an owner or admin.
  // Another member's shows only its size, uploader and expiry (§8.7).
  function pendingPanel(ctx) {
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const list = h("ul", { class: "attach-admin" });
    const box = h("div", { class: "attach-admin-box" }, h("h2", { class: "panel-title" }, M.t("attach.admin.title")),
      ctx.project.attachments ? h("p", { class: "muted" }, M.t("attach.admin.stored", { used: sizeOf(ctx.project.attachments.used), quota: sizeOf(ctx.project.attachments.quota) })) : null,
      list, status.el);
    async function load() {
      const none = () => { clear(list); append(list, h("li", { class: "muted" }, M.t("attach.admin.off"))); };
      if (hubOff) { none(); return; }
      let items;
      try {
        items = (await M.api.getAll(ctx.base + "/attachments?status=pending")).items;
      } catch (err) {
        if (isOff(err)) { none(); return; }
        status.fail(M.t("attach.admin.read_failed"), err);
        return;
      }
      clear(list);
      if (!items.length) append(list, h("li", { class: "muted" }, M.t("attach.admin.none")));
      items.forEach((a) => append(list, h("li", null,
        a.name ? a.name + " · " : "",
        sizeOf(a.size) + " · ", M.dom.memberRef(ctx, a.uploaded_by), " · ", M.t("attach.admin.expires", { ago: formatAgo(a.expires_at) }),
        " ", h("button", {
          type: "button", class: "small", "aria-label": M.t("attach.admin.delete.label", { size: sizeOf(a.size), who: ctx.nameOf ? ctx.nameOf(a.uploaded_by) : a.uploaded_by }),
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
              status.done();
              append(status.el, h("span", { class: "ok" }, M.t("attach.admin.deleted")));
              status.el.focus();
              load();
            } catch (err) {
              if (isOff(err)) { none(); return; }
              status.fail(M.t("attach.not_deleted"), err);
            }
          },
        }, M.t("attach.delete")))));
    }
    load();
    return box;
  }

  M.attachments = {
    // The hub is asked again whether it keeps files (the smoke test's hubs).
    forget: () => { hubOff = false; }, picker, render, markDeleted, pendingPanel, sizeOf, said };
})(window.Maity);
