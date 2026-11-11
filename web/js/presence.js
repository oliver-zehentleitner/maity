// The tab's presence for the notification mail's hold (docs/api.md §18.4, §18.5): while the tab
// is visible and had input within ten minutes, `POST /me/presence` every 60 seconds, and at once
// when it becomes present again. A hidden or idle tab sends nothing, so the hub lets the mail of
// an immediate item go about two minutes after the last call and the grace after that. Nothing on
// the page reads it: it is no presence anyone sees, and it keeps no session alive (§2.4).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const EVERY_MS = 60 * 1000;
  const IDLE_MS = 10 * 60 * 1000;
  // Input in the sense of §18.4: pointer, key, scroll or focus. Scroll does not bubble, so every
  // listener is on the capture phase.
  const INPUT = ["pointerdown", "keydown", "wheel", "scroll", "focus"];

  let running = false;
  let lastInput = 0;
  let lastSent = 0;
  let timer = null;

  const now = () => Date.now();
  const present = () => document.visibilityState === "visible" && now() - lastInput < IDLE_MS;

  function later() {
    window.clearTimeout(timer);
    timer = null;
    if (running && present()) timer = window.setTimeout(tick, Math.max(0, lastSent + EVERY_MS - now()));
  }

  // One call, then the next a minute after it while the tab stays present. A refusal (a 429,
  // a lost connection) waits for that minute too; a 401 ends the session's page (js/api.js),
  // which stops this.
  function tick() {
    timer = null;
    if (!running || !present()) return;
    lastSent = now();
    M.api.post("/me/presence").catch(() => {});
    later();
  }

  // Present again (input after ten idle minutes, or the tab shown again): at once, unless a call
  // went within the minute, whose two minutes still cover the tab.
  function again() {
    if (!running || !present()) return;
    if (now() - lastSent >= EVERY_MS) tick();
    else if (!timer) later();
  }

  function onInput() {
    const was = present();
    lastInput = now();
    if (!was) again();
  }

  function onVisibility() {
    if (document.visibilityState === "visible") again();
    else later(); // hidden: the pending call goes
  }

  // A human's dashboard session against a hub, signed in and not waiting for approval (js/app.js;
  // fixture mode holds no mail). Opening or signing in counts as input: the human is at the page.
  function start() {
    if (running) return;
    running = true;
    INPUT.forEach((type) => window.addEventListener(type, onInput, { capture: true, passive: true }));
    document.addEventListener("visibilitychange", onVisibility);
    lastInput = now();
    again();
  }

  // Signed out, or the session ended under the page.
  function stop() {
    if (!running) return;
    running = false;
    INPUT.forEach((type) => window.removeEventListener(type, onInput, { capture: true }));
    document.removeEventListener("visibilitychange", onVisibility);
    window.clearTimeout(timer);
    timer = null;
    lastSent = 0;
  }

  M.presence = { start, stop, running: () => running };
})(window.Maity);
