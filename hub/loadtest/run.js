// The load test of hub/context/replicas.md cac80c88. See README.md; SCENARIO names one of it.
import crypto from "k6/crypto";
import exec from "k6/execution";
import http from "k6/http";
import { SharedArray } from "k6/data";
import { Counter, Trend } from "k6/metrics";
import { sleep } from "k6";
import { canonicalQuery, signedHeaders } from "./sign.js";

const CONFIRMED = (__ENV.LOADTEST_CONFIRMED_TEST_SYSTEM || "").split(",");
const PODS = (__ENV.LOADTEST_TARGETS || "").split(",").filter(Boolean);
const SCALE = Number(__ENV.LOADTEST_SCALE || "0.25");
const GENERATOR = Number(__ENV.LOADTEST_GENERATOR || "0");
const GENERATORS = Number(__ENV.LOADTEST_GENERATORS || "1");
const SCENARIO = __ENV.SCENARIO || "idle";
const WAIT = 55;

// The assumed peak (cac80c88), before SCALE and the share of this generator.
const EVENT_WAITS = 40000;
const BELL_WAITS = 20000;
const WRITES_PER_SECOND = 670;
const READS_PER_SECOND = (EVENT_WAITS + BELL_WAITS) / 60;
const LOGIN_LIMIT = 10; // routes/auth.py, per address and per handle, per minute

const hostOf = (url) =>
  url.replace(/^https?:\/\//i, "").split("/")[0].split("@").pop().split(":")[0].toLowerCase().replace(/\.$/, "");

function refuseAnythingButATestSystem() {
  if (PODS.length === 0) throw new Error("LOADTEST_TARGETS names no address");
  for (const pod of PODS) {
    const host = hostOf(pod);
    if (host === "maity.team" || host.endsWith(".maity.team")) throw new Error(`${host} may be production`);
    if (!CONFIRMED.includes(host)) throw new Error(`LOADTEST_CONFIRMED_TEST_SYSTEM does not name ${host}`);
  }
}
refuseAnythingButATestSystem();

const seeded = new SharedArray("humans", () => {
  const all = JSON.parse(open(__ENV.LOADTEST_ACCOUNTS));
  return all.filter((_, i) => i % GENERATORS === GENERATOR); // each generator its own humans
});

const wakeUp = new Trend("wake_up_across_pods", true);
const replayAccepted = new Counter("replay_accepted");
const loginsAccepted = new Counter("logins_accepted");
const unexpected = new Counter("unexpected_answers");

const hash = {
  sha256Hex: (text) => crypto.sha256(text, "hex"),
  hmacHex: (keyHex, text) => {
    const key = new Uint8Array(keyHex.match(/../g).map((b) => parseInt(b, 16))).buffer;
    return crypto.hmac("sha256", key, text, "hex");
  },
};

// Hex: the alphabet of a nonce is base64url, and hex is part of it.
function nonce() {
  return Array.from(new Uint8Array(crypto.randomBytes(16)), (b) => b.toString(16).padStart(2, "0")).join("");
}

function signed(account, method, pod, path, pairs, body, params = {}) {
  const text = body === null ? "" : JSON.stringify(body);
  const stamp = Math.floor(Date.now() / 1000);
  const headers = signedHeaders(account, method, path, pairs, text, stamp, nonce(), hash);
  if (body !== null) {
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = nonce();
  }
  const query = canonicalQuery(pairs);
  const url = `${pod}${path}${query ? `?${query}` : ""}`;
  return { method, url, text, headers, send: () => http.request(method, url, body === null ? null : text, { headers, ...params }) };
}

const held = { timeout: `${WAIT + 30}s`, tags: { held: "yes" } };
// Two waits per human, each on the human's pod; the message goes to the second through the next pod.
const humanIndex = () => Math.floor((exec.vu.idInTest - 1) / 2) % seeded.length;
const human = () => seeded[humanIndex()];
const eventsPath = (h) => `/api/v1/projects/${h.owner}/${h.slug}/events`;
const pod = (n) => PODS[n % PODS.length];

function latestCursor(account, h, target) {
  const answer = signed(account, "GET", target, eventsPath(h), [["after", "latest"]], null).send();
  return answer.status === 200 ? answer.json("cursor") : 0;
}

export function eventWait() {
  const h = human();
  const addressed = (exec.vu.idInTest - 1) % 2 === 1;
  const account = h.agents[addressed ? 1 : 0];
  const target = pod(humanIndex());
  let cursor = latestCursor(account, h, target);
  for (let i = 0; i < 1000; i++) {
    const answer = signed(account, "GET", target, eventsPath(h), [["after", String(cursor)], ["wait", String(WAIT)]], null, held).send();
    if (answer.status !== 200) {
      unexpected.add(1);
      sleep(1);
      continue;
    }
    cursor = answer.json("cursor");
    for (const item of answer.json("items") || []) {
      const sent = Number(String((item.payload || {}).body || "").split("sent:")[1]);
      if (sent && addressed) wakeUp.add(Date.now() - sent);
    }
  }
}

export function bellWait() {
  const h = human();
  const target = pod(humanIndex());
  const params = { headers: { Cookie: `maity_session=${h.session}` } };
  const first = http.get(`${target}/api/v1/me/notifications?limit=0`, params);
  if (first.status !== 200) {
    unexpected.add(1);
    sleep(1);
    return;
  }
  let after = first.json("next_after");
  for (let i = 0; i < 1000; i++) {
    const answer = http.get(`${target}/api/v1/me/notifications?limit=50&after=${encodeURIComponent(after)}&wait=${WAIT}`, { ...params, ...held });
    if (answer.status !== 200) {
      unexpected.add(1);
      sleep(1);
      continue;
    }
    after = answer.json("next_after") || after;
  }
}

// The first agent writes through the pod after its human's, so a write and its wake-up are on
// different pods as soon as there are two. Clocks: the waiter reads the time this generator wrote.
export function write() {
  const index = exec.scenario.iterationInTest % seeded.length;
  const h = seeded[index];
  const target = pod(index + 1);
  const body = { kind: "message", type: "notice", to: h.agents[1].agent_id, body: `load sent:${Date.now()}` };
  const answer = signed(h.agents[0], "POST", target, eventsPath(h), [], body, { tags: { kind: "write" } }).send();
  if (answer.status !== 201) unexpected.add(1);
}

export function read() {
  const h = seeded[exec.scenario.iterationInTest % seeded.length];
  const path = `/api/v1/projects/${h.owner}/${h.slug}/tasks`;
  const answer = signed(h.agents[0], "GET", pod(exec.scenario.iterationInTest), path, [], null, { tags: { kind: "read" } }).send();
  if (answer.status !== 200) unexpected.add(1);
}

// One address over all pods: more than a limit's worth of logins must not get through.
export function logins() {
  const h = seeded[0];
  const answer = http.post(`${pod(exec.scenario.iterationInTest)}/api/v1/auth/login`, JSON.stringify({ handle: h.handle, password: "wrong" }), {
    headers: { "Content-Type": "application/json" },
    responseCallback: http.expectedStatuses(401, 429),
  });
  if (answer.status !== 429) loginsAccepted.add(1);
}

// One request, once accepted, replayed on every pod for the nonce's whole window; the operator
// restarts the database and fails it over meanwhile (README.md).
export function replay() {
  const h = seeded[0];
  const first = signed(h.agents[0], "GET", PODS[0], eventsPath(h), [["after", "latest"]], null);
  if (first.send().status !== 200) throw new Error("the request to replay was refused");
  const end = Date.now() + 280 * 1000; // inside the timestamp's window of 300 s
  while (Date.now() < end) {
    for (const target of PODS) {
      const again = http.get(first.url.replace(PODS[0], target), {
        headers: first.headers,
        responseCallback: http.expectedStatuses(401),
      });
      if (again.status === 200) replayAccepted.add(1);
    }
    sleep(5);
  }
}

const share = (n) => Math.max(1, Math.ceil((n * SCALE) / GENERATORS));
const ramp = "10m";
const holding = {
  eventWaits: { executor: "ramping-vus", exec: "eventWait", startVUs: 0, stages: [{ duration: ramp, target: share(EVENT_WAITS) }, { duration: "20m", target: share(EVENT_WAITS) }] },
  bellWaits: { executor: "ramping-vus", exec: "bellWait", startVUs: 0, stages: [{ duration: ramp, target: share(BELL_WAITS) }, { duration: "20m", target: share(BELL_WAITS) }] },
};
const rate = (fn, perSecond) => ({
  executor: "constant-arrival-rate",
  exec: fn,
  rate: share(perSecond),
  timeUnit: "1s",
  startTime: ramp,
  duration: "20m",
  preAllocatedVUs: Math.max(10, share(perSecond)),
  maxVUs: Math.max(50, share(perSecond) * 5),
});
const SCENARIOS = {
  idle: holding,
  // Few writes, so that a wake-up's time is the hub's and not a queue's.
  wakeup: { ...holding, writes: rate("write", 5) },
  mixed: { ...holding, writes: rate("write", WRITES_PER_SECOND), reads: rate("read", READS_PER_SECOND) },
  limits: {
    logins: { executor: "shared-iterations", exec: "logins", vus: 20, iterations: 200, maxDuration: "50s" },
    replay: { executor: "per-vu-iterations", exec: "replay", vus: 1, iterations: 1, maxDuration: "5m" },
  },
};

// The thresholds cac80c88 fixes before the run, for 100 % on 4 pods. The rest of its targets are
// read on the server (README.md).
const THRESHOLDS = {
  idle: { unexpected_answers: ["count==0"] },
  wakeup: { wake_up_across_pods: ["p(95)<1000", "p(99)<2000"], unexpected_answers: ["count==0"] },
  mixed: {
    "http_req_duration{kind:write}": ["p(95)<300"],
    "http_req_duration{kind:read}": ["p(95)<200"],
    wake_up_across_pods: ["p(95)<1000", "p(99)<2000"],
    unexpected_answers: ["count==0"],
  },
  limits: { replay_accepted: ["count==0"], logins_accepted: [`count<=${LOGIN_LIMIT}`] },
};

if (!SCENARIOS[SCENARIO]) throw new Error(`no scenario ${SCENARIO}`);
export const options = {
  scenarios: SCENARIOS[SCENARIO],
  thresholds: THRESHOLDS[SCENARIO],
  systemTags: ["status", "method", "scenario", "expected_response"], // no url: 60 000 series otherwise
};
