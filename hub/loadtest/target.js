// Which addresses the load test may reach. Apart from `run.js` so that `tests/test_loadtest.py`
// checks it without k6. A plain origin only: userinfo or a path could make the host a reader sees
// differ from the host that is reached. A host under maity.team may be production: only
// LOADTEST_CONFIRMED_PRODUCTION names one. Both confirmations are comma separated lists. Production
// is reached through its balancers' names only, one target per confirmed name, never pods one by
// one: with a second balancer for the run (replicas.md cac80c88) that is two names.
const ORIGIN = /^(https?):\/\/((?:[a-z0-9-]+\.)*[a-z0-9-]+)(?::(\d+))?$/i;
const DEFAULT_PORT = { http: "80", https: "443" };

export function production(host) {
  return host === "maity.team" || host.endsWith(".maity.team");
}

export function hostOf(target) {
  const found = ORIGIN.exec(target);
  return found ? found[2].toLowerCase() : null;
}

function named(list) {
  return list.split(",").map((host) => host.trim()).filter(Boolean);
}

// Host and port as reached, so that `https://a`, `https://A:443` are one target. Another scheme or
// port is another target: on a test system that may be another pod's port-forward.
export function reached(target) {
  const found = ORIGIN.exec(target);
  if (!found) return null;
  const scheme = found[1].toLowerCase();
  return `${found[2].toLowerCase()}:${found[3] ? String(Number(found[3])) : DEFAULT_PORT[scheme]}`;
}

export function refusal(target, confirmedList, confirmedProduction) {
  const host = hostOf(target);
  if (host === null) return `${target} is not a plain origin`;
  if (production(host)) {
    if (!named(confirmedProduction).includes(host)) {
      return `${host} may be production: LOADTEST_CONFIRMED_PRODUCTION does not name it`;
    }
    return null;
  }
  if (!named(confirmedList).includes(host)) {
    return `LOADTEST_CONFIRMED_TEST_SYSTEM does not name ${host}`;
  }
  return null;
}

// Why these targets are not run, or null: each one named, none twice, and production alone, with
// exactly one target for each confirmed name.
export function targetsRefusal(targets, confirmedList, confirmedProduction) {
  if (targets.length === 0) return "LOADTEST_TARGETS names no address";
  for (const target of targets) {
    const why = refusal(target, confirmedList, confirmedProduction);
    if (why) return why;
  }
  const hosts = targets.map(hostOf);
  if (new Set(targets.map(reached)).size !== targets.length) {
    return "LOADTEST_TARGETS names a target twice";
  }
  const onProduction = hosts.filter(production);
  if (onProduction.length === 0) return null;
  if (onProduction.length !== hosts.length) return "production is not run together with another system";
  const confirmed = new Set(named(confirmedProduction));
  if (new Set(onProduction).size !== onProduction.length || onProduction.length !== confirmed.size) {
    return "production takes one target for each name in LOADTEST_CONFIRMED_PRODUCTION";
  }
  return null;
}
