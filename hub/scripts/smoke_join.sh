#!/usr/bin/env bash
# End-to-end join, both paths a pasted line can take (docs/api.md §3), then one
# request from each agent to its human, answered and picked up (§7), and a chat
# message from the human that wakes each agent's long-poll (§8.3, §9), then a release
# checklist ticked by its holder and a contract card finalised by its arbiter (§6.7, §6.8):
#   1. plain curl, exactly as the join page tells an agent with nothing installed;
#   2. the `maity` CLI: `maity join <url> --code <code>`, then `maity resume`.
# Runs a fresh hub on SQLite on loopback. Needs `maity-hub` and `maity` on PATH:
#   pip install -e hub -e cli   (one virtual environment is enough)
# Usage: hub/scripts/smoke_join.sh [port]    exit 0 = both paths worked
set -euo pipefail

port="${1:-18765}"
hub="http://127.0.0.1:${port}"
work="$(mktemp -d)"
server_pid=""
cleanup() {
    [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
step() { printf '\n== %s\n' "$*"; }

export MAITY_DATABASE_URL="sqlite:///${work}/hub.db" MAITY_BIND="127.0.0.1:${port}"
export MAITY_PUBLIC_URL="$hub"
step "hub: migrate, owner, serve on $hub"
maity-hub migrate >/dev/null 2>&1
printf 'smoke owner password\n' | maity-hub owner create --handle owner --display-name Owner
maity-hub serve >"$work/serve.log" 2>&1 &
server_pid=$!
for _ in $(seq 50); do curl -sf "$hub/api/v1/health" >/dev/null && break; sleep 0.2; done

step "human: login, project, two join links"
jar="$work/cookies"
curl -sS --fail -c "$jar" -o /dev/null -H 'Content-Type: application/json' \
    -d '{"handle":"owner","password":"smoke owner password"}' "$hub/api/v1/auth/login"
csrf="$(curl -sS --fail -b "$jar" "$hub/api/v1/auth/session" | json 'd["csrf_token"]')"
human() { curl -sS --fail -b "$jar" -H "X-CSRF-Token: $csrf" -H 'Content-Type: application/json' "$@"; }
human -o /dev/null -d '{"slug":"smoke","name":"Smoke test"}' "$hub/api/v1/projects"
join_for() {
    human -d "{\"agent\":{\"handle\":\"$1\",\"display_name\":\"$1\"},\"role\":\"member\",\"areas\":[\"$1/\"]}" \
        "$hub/api/v1/projects/smoke/joins"
}
curl_join="$(join_for curl-agent)"
cli_join="$(join_for cli-agent)"

step "path 1: plain curl, as the join page says"
url="$(printf '%s' "$curl_join" | json 'd["join_url"]')"
code="$(printf '%s' "$curl_join" | json 'd["code"]')"
token="${url##*/}"
page="$(curl -sS --fail "$url")"
grep -q '^# Join Smoke test on Maity' <<<"$page"
grep -qF -- "$token" <<<"$page"
# The page never carries the code. (Not `! grep`: set -e ignores a negated command.)
if grep -qF -- "$code" <<<"$page"; then echo "smoke: the join page shows the code" >&2; exit 1; fi
git init -q "$work/clone-curl" && cd "$work/clone-curl"
d="$(git rev-parse --git-common-dir)/maity"
(umask 077; mkdir -p "$d"; curl -sS --fail -D "$work/exchange-headers" -o "$d/credential" \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"code\":\"$code\",\"client\":\"curl\"}" "$hub/api/v1/join/$token")
grep -q '^HTTP/1.1 201' "$work/exchange-headers"
grep -qi '^Maity-Credential-Id: crd-' "$work/exchange-headers"
[ "$(stat -c %a "$d/credential")" = 600 ]
(umask 077; { printf '%s' 'header = "Authorization: Bearer '; cat "$d/credential"; printf '"\n'; } > "$d/curl.conf")
packet="$(curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' \
    -d '{"harness":"smoke","harness_version":"1","model":"none","client":"curl"}' \
    "$hub/api/v1/me/resume")"
printf '%s' "$packet" | json '"resumed as " + d["me"]["handle"] + ", session " + d["session"]["id"] + ", rules v" + str(d["rules"]["version"])'
# Read whole first: a `grep -q` in a pipe closes it early and curl fails writing (23).
help_text="$(curl -sS --fail "$hub/api/v1/help")"
grep -q '^# Maity hub API' <<<"$help_text"
again="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
    -d "{\"code\":\"$code\",\"client\":\"curl\"}" "$hub/api/v1/join/$token")"
[ "$again" = 404 ]   # single use

step "path 2: the maity CLI"
url="$(printf '%s' "$cli_join" | json 'd["join_url"]')"
code="$(printf '%s' "$cli_join" | json 'd["code"]')"
git init -q "$work/clone-cli" && cd "$work/clone-cli"
maity join "$url" --code "$code" --harness smoke --model none --no-pointer >"$work/cli-join.out" 2>&1
grep -q '^joined smoke as agt-' "$work/cli-join.out"
maity resume --json | json '"resumed as " + d["me"]["handle"] + ", session " + d["session"]["id"]'

step "requests: each agent asks its human, the human answers"
key() { python3 -c 'import uuid; print(uuid.uuid4())'; }
cd "$work/clone-curl"
d="$(git rev-parse --git-common-dir)/maity"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -H "Idempotency-Key: $(key)" \
    -d '{"class":"decision","title":"Which hash?","options":[{"id":"a","label":"A"},{"id":"b","label":"B"}]}' \
    "$hub/api/v1/projects/smoke/requests" | json '"curl agent asked " + d["id"] + " to " + d["to"]'
cd "$work/clone-cli"
maity ask "Tag 0.1.0 now?" --to human --class consent --option yes --option no
inbox="$(human -X GET "$hub/api/v1/requests")"
[ "$(printf '%s' "$inbox" | json 'len(d["items"])')" = 2 ]
for id in $(printf '%s' "$inbox" | json '" ".join(r["id"] for r in d["items"])'); do
    reply="$(printf '%s' "$inbox" | json "next(r['replies'][0]['id'] for r in d['items'] if r['id'] == '$id')")"
    human -o /dev/null -d "{\"reply_id\":\"$reply\"}" "$hub/api/v1/projects/smoke/requests/$id/answer"
done
maity resume --json | json '"cli agent got " + str(len(d["requests"]["answered_since_cursor"])) + " answer(s)"' \
    | tee "$work/cli-answers"
grep -q "got 1 answer" "$work/cli-answers"
cd "$work/clone-curl"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -d '{"client":"curl"}' \
    "$hub/api/v1/me/resume" | json '"curl agent got " + str(len(d["requests"]["answered_since_cursor"])) + " answer(s)"' \
    | tee "$work/curl-answers"
grep -q "got 1 answer" "$work/curl-answers"

step "events: each agent waits, its human writes to it, the wait wakes"
cli_agent="$(grep -o 'agt-[0-9a-z]*' "$work/cli-join.out" | head -1)"
curl_agent="$(printf '%s' "$curl_join" | json 'd["agent_id"]')"
cd "$work/clone-cli"
maity wait --timeout 30 >"$work/cli-wait.out" &
cli_wait=$!
cd "$work/clone-curl"
after="$(curl -sS --fail -K "$d/curl.conf" "$hub/api/v1/projects/smoke/events?after=latest" | json 'd["cursor"]')"
curl -sS --fail -K "$d/curl.conf" "$hub/api/v1/projects/smoke/events?after=$after&wait=30" >"$work/curl-wait.out" &
curl_wait=$!
sleep 1
human -o /dev/null -d '{"body":"how far are you?"}' "$hub/api/v1/projects/smoke/conversations/$cli_agent/messages"
human -o /dev/null -d '{"body":"and you?"}' "$hub/api/v1/projects/smoke/conversations/$curl_agent/messages"
wait "$cli_wait"
wait "$curl_wait"
json '"cli agent woke on: " + d["payload"]["body"]' <"$work/cli-wait.out" | tee "$work/cli-woke"
grep -q "how far are you" "$work/cli-woke"
json '"curl agent woke on: " + d["items"][0]["payload"]["body"]' <"$work/curl-wait.out" | tee "$work/curl-woke"
grep -q "and you" "$work/curl-woke"
human -X GET "$hub/api/v1/projects/smoke/conversations/$cli_agent/messages" \
    | json '"delivered: " + str(d["items"][-1]["delivered_at"] is not None)' | grep -q "delivered: True"

step "releases and contracts: the curl agent holds a release, the cli agent finalises a contract as its arbiter"
human -o /dev/null -X PATCH -d '{"settings":{"release_checklist":["CHANGELOG has a section"]}}' \
    "$hub/api/v1/projects/smoke"
rel="$(human -d '{"kind":"release","title":"0.1.0","release":{"version":"0.1.0"}}' \
    "$hub/api/v1/projects/smoke/tasks" | json 'd["id"]')"
cd "$work/clone-curl"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -H "Idempotency-Key: $(key)" \
    -d '{}' -o /dev/null "$hub/api/v1/projects/smoke/tasks/$rel/claim"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -H "Idempotency-Key: $(key)" \
    -d '{"done":true}' "$hub/api/v1/projects/smoke/tasks/$rel/checklist/chk-1" \
    | json '"release " + d["release"]["version"] + ": checklist done " + str(d["release"]["checklist"][0]["done"]) + ", blocking " + ",".join(b["reason"] for b in d["release"]["readiness"]["blocking"])' \
    | tee "$work/release"
grep -q "done True, blocking probe_not_configured$" "$work/release"
ctr="$(printf '{"title":"Shape of /probe","kind":"contract","contract":{"arbiter":"%s","watchers":["%s"]}}' \
    "$cli_agent" "$curl_agent" | human -d @- "$hub/api/v1/projects/smoke/tasks" | json 'd["id"]')"
cd "$work/clone-cli"
printf '{"contract":{"state":"final"}}' | maity api PATCH "/projects/smoke/tasks/$ctr" --json - \
    | json '"contract " + d["id"] + " is " + d["contract"]["state"]' | tee "$work/final"
grep -q "is final$" "$work/final"

step "pause: the human pauses the cli agent; it is told, takes no new work, and can still park its card"
cd "$work/clone-cli"
git -c user.name=smoke -c user.email=smoke@example.org commit -q --allow-empty -m "smoke"
held="$(human -d '{"title":"Pause: held card","area":"/"}' "$hub/api/v1/projects/smoke/tasks" | json 'd["id"]')"
spare="$(human -d '{"title":"Pause: spare card","area":"/"}' "$hub/api/v1/projects/smoke/tasks" | json 'd["id"]')"
maity claim "$held"
maity resume --json >/dev/null  # the wait starts after everything so far
maity wait --timeout 30 >"$work/pause-wait.out" 2>"$work/pause-wait.err" &
pause_wait=$!
sleep 1
human -o /dev/null -X PATCH -d '{"paused":{"reason":"smoke: hold on"}}' \
    "$hub/api/v1/projects/smoke/members/$cli_agent"
wait "$pause_wait"
grep -q '^maity: you were paused by .*: smoke: hold on' "$work/pause-wait.err"
json '"cli agent woke on: " + d["kind"]' <"$work/pause-wait.out" | tee "$work/pause-woke"
grep -q "woke on: session_paused$" "$work/pause-woke"
if maity claim "$spare" >"$work/pause-claim.out" 2>&1; then
    echo "smoke: a paused agent's claim was accepted" >&2
    exit 1
fi
cat "$work/pause-claim.out"
grep -q '^maity: refused: you are paused by .*: smoke: hold on' "$work/pause-claim.out"
maity checkpoint "$held" -m "paused mid-way" --next "continue after the pause"
human -o /dev/null -X PATCH -d '{"paused":null}' "$hub/api/v1/projects/smoke/members/$cli_agent"
maity claim "$spare"

step "probe: without a forge token both agents get probe_not_configured"
cd "$work/clone-curl"
code="$(curl -sS -o "$work/probe-curl" -w '%{http_code}' -K "$d/curl.conf" "$hub/api/v1/projects/smoke/probe?pr=1")"
[ "$code" = 409 ]
json '"curl agent: " + d["error"]["code"]' <"$work/probe-curl" | tee "$work/probe"
grep -q "probe_not_configured$" "$work/probe"
cd "$work/clone-cli"
if maity api GET /projects/smoke/probe --query pr=1 >"$work/probe-cli" 2>&1; then
    echo "smoke: maity api answered a probe without a token" >&2; exit 1
fi
grep -q probe_not_configured "$work/probe-cli"
echo "cli agent: probe_not_configured"

step "signing required: the curl agent's bearer call is refused, the cli agent signs and goes on"
human -o /dev/null -X PATCH -d '{"policy":{"signing":"required"},"reason":"agents sign from now on"}' \
    "$hub/api/v1/projects/smoke"
cd "$work/clone-curl"
code="$(curl -sS -o "$work/signing-curl" -w '%{http_code}' -K "$d/curl.conf" "$hub/api/v1/me")"
[ "$code" = 403 ]
json '"curl agent: " + d["error"]["code"]' <"$work/signing-curl" | tee "$work/signing"
grep -q "signature_required$" "$work/signing"
cd "$work/clone-cli"
maity api GET /me | json '"cli agent, signed: " + d["member"]["handle"]'

step "human: both agents are members"
human "$hub/api/v1/projects/smoke/members" -X GET \
    | json '", ".join(m["handle"] + "/" + m["presence"] for m in d["items"])'
printf '\nsmoke: both join paths worked, both agents got their answers, woke on a message, worked a release and a contract, the cli agent was paused and resumed, asked the probe, and signing was enforced\n'
