// The tab's presence for the notification mail's hold (docs/api.md §18.4, §18.5): while the tab
// is visible and had input within ten minutes, `POST /me/presence` every 60 seconds, and at once
// when it becomes present again; the session's tabs and page loads share the minute. A hidden or
// idle tab sends nothing, so the hub lets the mail of an immediate item go about two minutes
// after the last call and the grace after that. Nothing on the page reads it: it is no presence
// anyone sees, and it keeps no session alive (§2.4).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const EVERY_MS = 60 * 1000;
  const IDLE_MS = 10 * 60 * 1000;
  // Input in the sense of §18.4: pointer, key, scroll or focus. Scroll does not bubble, so every
  // listener is on the capture phase.
  const INPUT = ["pointerdown", "keydown", "wheel", "scroll", "focus"];
  // The time of the session's last call, shared by its tabs and page loads in this browser: the
  // hub takes ten calls a minute per session (§1.7), and every page load would start with one.
  const SENT_KEY = "maity-presence-sent";

  let running = false;
  let lastInput = 0;
  let lastSent = 0;
  let timer = null;

  const now = () => Date.now();
  const present = () => document.visibilityState === "visible" && now() - lastInput < IDLE_MS;
  // The latest call of any tab, never later than now (a clock set back would hold the calls).
  function last() {
    let shared = 0;
    try { shared = Number(window.localStorage.getItem(SENT_KEY)) || 0; } catch (err) { /* this browser keeps nothing */ }
    return Math.min(now(), Math.max(lastSent, shared));
  }

  function later() {
    window.clearTimeout(timer);
    timer = null;
    if (running && present()) timer = window.setTimeout(tick, Math.max(0, last() + EVERY_MS - now()));
  }

  // One call, then the next a minute after it while the tab stays present; none while another
  // tab or an earlier page load called within the minute, whose two minutes still cover this
  // one. A refusal (a 429, a lost connection) waits for that minute too; a 401 ends the
  // session's page (js/api.js), which stops this.
  function tick() {
    timer = null;
    if (!running || !present()) return;
    if (now() - last() >= EVERY_MS) {
      lastSent = now();
      try { window.localStorage.setItem(SENT_KEY, String(lastSent)); } catch (err) { /* this tab counts alone */ }
      M.api.post("/me/presence").catch(() => {});
    }
    later();
  }

  // Present again (input after ten idle minutes, or the tab shown again): at once, unless a call
  // went within the minute, whose two minutes still cover the tab.
  function again() {
    if (!running || !present()) return;
    if (now() - last() >= EVERY_MS) tick();
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

  // After `/me` for an account that does not wait for approval (js/app.js): a human's dashboard
  // session against a hub only, since an agent has no mail hold and fixture mode holds no mail.
  // Opening or signing in counts as input: the human is at the page.
  function start(me) {
    if (running || M.api.source !== "api" || !me || !me.member || me.member.kind !== "human") return;
    running = true;
    INPUT.forEach((type) => window.addEventListener(type, onInput, { capture: true, passive: true }));
    document.addEventListener("visibilitychange", onVisibility);
    lastInput = now();
    again();
  }

  // Signed out, or the session ended under the page: the next session starts with a call.
  function stop() {
    if (!running) return;
    running = false;
    try { window.localStorage.removeItem(SENT_KEY); } catch (err) { /* nothing kept */ }
    INPUT.forEach((type) => window.removeEventListener(type, onInput, { capture: true }));
    document.removeEventListener("visibilitychange", onVisibility);
    window.clearTimeout(timer);
    timer = null;
    lastSent = 0;
  }

  M.presence = { start, stop, running: () => running };
})(window.Maity);
