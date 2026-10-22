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
  const CLOSED_STATES = ["accepted", "archived"];
  // The types the hub re-encodes an image to (§8.7): only these inline.
  const INLINE_TYPES = ["image/png", "image/jpeg", "image/webp"];
  // A hub that answered 404 or 405 to attachments has none: not asked again
  // until the page is loaded anew.
  let hubWithout = false;

  function sizeOf(n) {
    if (n === null || n === undefined) return "";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  // The hub's refusals of an upload, in words.
  const REFUSED = {
    unsupported_type: "the file's type does not match what it is",
    dimensions: "the image is larger than 8192 pixels on a side or 40 megapixels",
    undecodable: "the image could not be read",
    required: "the file has no name",
  };
  function said(err) {
    const why = err.code === "invalid" && err.details && err.details.fields && (err.details.fields.body || err.details.fields.name);
    if (why) return { message: REFUSED[why] || why };
    if (err.code === "payload_too_large") return { message: "larger than 10 MiB" };
    if (err.code === "attachment_quota") return { message: err.details && err.details.scope === "pending"
      ? "you have 20 files, or 100 MiB, waiting to be sent; send or remove some first" : "the project's storage for files is full" };
    if (err.code === "rate_limited") return { message: "too many uploads in a short time; try again in a few minutes" };
    if (err.code === "project_closed") return { message: "the project is closed: it takes no new files" };
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
    const list = h("ul", { class: "attach-pending", "aria-label": "Files to send" });
    const earlierList = h("ul", { class: "attach-earlier", "aria-label": "Your files waiting from before" });
    const earlierBox = h("div", { class: "attach-earlier-box", hidden: true },
      h("p", { class: "muted" }, "Your files waiting from before, not sent yet:"), earlierList);
    let earlier = [];
    const drawEarlier = () => {
      clear(earlierList);
      const shown = earlier.filter((a) => !pending.some((p) => p.att && p.att.id === a.id));
      earlierBox.hidden = !shown.length;
      shown.forEach((a) => append(earlierList, h("li", null,
        h("span", { class: "attach-name" }, a.name), " ", h("span", { class: "muted" }, sizeOf(a.size)), " ",
        h("button", {
          type: "button", class: "small", "aria-label": "Attach " + a.name + " to this message",
          onclick: () => {
            if (pending.length >= PER_MESSAGE) { status.fail("Not attached: ", { message: "at most " + PER_MESSAGE + " files in one message" }); return; }
            pending.push({ name: a.name, att: a });
            draw();
            input.focus();
          },
        }, "Attach"), " ",
        h("button", {
          type: "button", class: "small", "aria-label": "Remove " + a.name + " from the hub",
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
            } catch (err) {
              status.fail("Not removed: ", err);
              return;
            }
            earlier = earlier.filter((x) => x !== a);
            drawEarlier();
            input.focus();
          },
        }, "Remove"))));
    };
    const loadEarlier = async () => {
      if (hubWithout) return;
      try {
        earlier = (await M.api.getAll(ctx.base + "/attachments?status=pending&uploaded_by=" + encodeURIComponent(ctx.me.id))).items;
      } catch (err) {
        // A hub without attachments, or none to read: nothing to offer.
        earlier = [];
        if (err.status === 404 || err.status === 405) hubWithout = true;
      }
      drawEarlier();
    };
    const draw = () => {
      drawEarlier();
      clear(list);
      pending.forEach((p) => append(list, h("li", null,
        h("span", { class: "attach-name" }, p.att ? p.att.name : p.name), " ",
        h("span", { class: "muted" }, p.att ? sizeOf(p.att.size) : "uploading…"),
        p.att ? h("button", {
          type: "button", class: "small", "aria-label": "Remove " + p.att.name,
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(p.att.id));
            } catch (err) {
              status.fail("Not removed: ", err);
              return;
            }
            pending.splice(pending.indexOf(p), 1);
            draw();
            input.focus();
          },
        }, "Remove") : null)));
    };
    input.addEventListener("change", async () => {
      const files = Array.from(input.files || []);
      input.value = "";
      for (const file of files) {
        if (pending.length >= PER_MESSAGE) { status.fail("Not attached: ", { message: "at most " + PER_MESSAGE + " files in one message" }); break; }
        if (file.size > FILE_MAX) { status.fail("Not attached: ", { message: (file.name || "a file") + " is larger than 10 MiB" }); continue; }
        const p = { name: file.name || "file", att: null };
        pending.push(p);
        draw();
        status.busy("Uploading " + p.name + "…");
        try {
          p.att = await M.api.postRaw(ctx.base + "/attachments?name=" + encodeURIComponent(p.name), file, await typeOf(file));
          status.done();
        } catch (err) {
          pending.splice(pending.indexOf(p), 1);
          status.fail("Not attached: " + p.name + ": ", said(err));
          // Over the pending cap: show what waits, so it can be sent or removed.
          if (err.code === "attachment_quota") await loadEarlier();
        }
        draw();
      }
    });
    const el = h("div", { class: "attach" },
      h("label", { for: id, class: "button small attach-button" }, "Attach files"), input,
      list, earlierBox, status.el);
    loadEarlier();
    return {
      el,
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
      // Deleted here: said, and focus kept on the note.
      const gone = () => {
        clear(li);
        const note = h("span", { class: "muted", tabindex: "-1" }, a.name + ": removed.");
        append(li, note);
        note.focus();
      };
      let shown = null;
      const url = M.api.attachmentUrl(ctx.slug, a.id, false);
      if (a.kind === "image" && INLINE_TYPES.includes(a.type) && url) {
        const w = a.width && a.height ? Math.min(a.width, 360) : null;
        shown = h("img", { class: "attach-image", src: url, alt: a.name, loading: "lazy",
          width: w ? String(w) : null, height: w ? String(Math.round(a.height * (w / a.width))) : null });
        // Not loaded (deleted, an access that ended, or a failure on the way):
        // said instead of a broken image; the link stays to try again.
        shown.addEventListener("error", () => {
          const note = h("span", { class: "muted" }, a.name + ": could not be shown. ");
          if (shown.parentNode) { shown.parentNode.insertBefore(note, shown); shown.parentNode.removeChild(shown); }
        });
      }
      const dl = M.api.attachmentUrl(ctx.slug, a.id, true);
      append(li, shown,
        h("span", { class: "attach-meta" },
          dl ? h("a", { href: dl, download: a.name, class: "attach-link" }, a.name) : h("span", null, a.name),
          h("span", { class: "muted" }, " · " + sizeOf(a.size) + (a.kind === "image" ? "" : " · " + a.type))),
        canDelete && canDelete(a) ? h("button", {
          type: "button", class: "small", "aria-label": "Delete the file " + a.name + " for everyone",
          onclick: async () => {
            if (!window.confirm("Delete " + a.name + " for everyone who can read this message? The message stays.")) return;
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
              gone();
            } catch (err) {
              append(li, h("span", { class: "send-status failed" }, " Not deleted: " + (err.message || err.code)));
            }
          },
        }, "Delete") : null);
      append(box, li);
    });
    return box;
  }

  // An attachment_deleted of a message on screen: its file is said removed.
  function markDeleted(container, id) {
    const li = Array.from(container.querySelectorAll("li.attach-item")).find((x) => x.getAttribute("data-attachment") === id);
    if (!li) return;
    const name = (li.querySelector(".attach-link") || li.querySelector(".attach-meta span") || { textContent: "A file" }).textContent;
    clear(li);
    append(li, h("span", { class: "muted" }, name + ": removed."));
  }

  // Project settings: the pending uploads of everyone, for an owner or admin.
  // Another member's shows only its size, uploader and expiry (§8.7).
  function pendingPanel(ctx) {
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const list = h("ul", { class: "attach-admin" });
    const box = h("div", { class: "attach-admin-box" }, h("h2", { class: "panel-title" }, "Files waiting to be sent"),
      ctx.project.attachments ? h("p", { class: "muted" }, "Stored: " + sizeOf(ctx.project.attachments.used) + " of " + sizeOf(ctx.project.attachments.quota) + ".") : null,
      list, status.el);
    async function load() {
      let items;
      try {
        items = (await M.api.getAll(ctx.base + "/attachments?status=pending")).items;
      } catch (err) {
        if (err.status === 404) { clear(list); append(list, h("li", { class: "muted" }, "This hub keeps no files yet.")); return; }
        status.fail("Could not read them: ", err);
        return;
      }
      clear(list);
      if (!items.length) append(list, h("li", { class: "muted" }, "None."));
      items.forEach((a) => append(list, h("li", null,
        a.name ? a.name + " · " : "",
        sizeOf(a.size) + " · " + (ctx.nameOf ? ctx.nameOf(a.uploaded_by) : a.uploaded_by) + " · expires " + formatAgo(a.expires_at),
        " ", h("button", {
          type: "button", class: "small", "aria-label": "Delete the pending upload of " + sizeOf(a.size) + " by " + (ctx.nameOf ? ctx.nameOf(a.uploaded_by) : a.uploaded_by),
          onclick: async () => {
            try {
              await M.api.del(ctx.base + "/attachments/" + encodeURIComponent(a.id));
              status.done();
              append(status.el, h("span", { class: "ok" }, "Deleted."));
              status.el.focus();
              load();
            } catch (err) {
              status.fail("Not deleted: ", err);
            }
          },
        }, "Delete"))));
    }
    load();
    return box;
  }

  M.attachments = { picker, render, markDeleted, pendingPanel, sizeOf, said };
})(window.Maity);
