#!/usr/bin/env bash
# The chart without a cluster: lint, render every configuration in ci/, and
# make sure the refusals refuse. Needs helm 3.8+.
# Usage: deploy/helm/check.sh    exit 0 = all held
set -euo pipefail

chart="$(cd "$(dirname "$0")/maity-hub" && pwd)"
minimal="$chart/ci/minimal-values.yaml"
ingress="$chart/ci/ingress-values.yaml"
fails=0

ok() { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1" >&2; fails=$((fails + 1)); }

for values in "$chart"/ci/*-values.yaml; do
    if helm lint --strict "$chart" -f "$values" >/dev/null; then
        ok "lint $(basename "$values")"
    else
        bad "lint $(basename "$values")"
    fi
done

render() { helm template t "$chart" "$@"; }

# What a rendered configuration must contain: one line per fact, matched literally.
expect() {
    local name="$1" out="$2"
    shift 2
    for line in "$@"; do
        if ! grep -qF -- "$line" <<<"$out"; then
            bad "$name: missing $line"
            return
        fi
    done
    ok "$name"
}

out="$(render -f "$minimal")"
expect "minimal: one pod, recreated, migrate hook first" "$out" \
    "replicas: 1" "type: Recreate" "helm.sh/hook: pre-install,pre-upgrade" 'args: ["migrate"]' \
    'value: "https://maity.example.org"' "readOnlyRootFilesystem: true" \
    "image: maity-hub@sha256:1111111111111111111111111111111111111111111111111111111111111111"
expect "minimal: hub pods selected by component" "$out" "app.kubernetes.io/component: hub"
# A tag only as an explicit opt-in, and then it also names the version label.
expect "tag: pulled by tag only with image.allowTag, version label from the tag" \
    "$(render -f "$minimal" --set image.digest= --set image.allowTag=true --set image.tag=ci)" \
    "image: maity-hub:ci" 'app.kubernetes.io/version: "ci"'
selector="$(sed -n '/^kind: Service$/,/^---/p' <<<"$out" | sed -n '/selector:/,$p')"
expect "minimal: the Service selects only the hub" "$selector" "app.kubernetes.io/component: hub"
expect "minimal: one serving process unless set" "$out" "name: MAITY_WORKERS" 'value: "1"'
expect "workers: the setting reaches the hub" "$(render -f "$minimal" --set config.workers=4)" 'value: "4"'
render -f "$minimal" --set config.workers=0 >/dev/null 2>&1 && bad "config.workers=0 accepted" \
    || ok "config.workers below 1 refused"
grep -q "kind: PodDisruptionBudget\|topologySpreadConstraints\|MAITY_DB_POOL_SIZE" <<<"$out" \
    && bad "minimal: a budget, spread or pool setting for one pod" || ok "minimal: no budget, spread or pool"
out_many="$(render -f "$minimal" --set replicas=3 --set database.poolSize=8 --set database.maxOverflow=0)"
expect "replicas: rolled one at a time, a budget, spread, the pool" "$out_many" \
    "replicas: 3" "type: RollingUpdate" "maxUnavailable: 0" "kind: PodDisruptionBudget" \
    "minAvailable: 1" "topologyKey: kubernetes.io/hostname" "name: MAITY_REPLICAS" \
    "name: MAITY_DB_POOL_SIZE" 'value: "8"' "name: MAITY_DB_MAX_OVERFLOW" 'value: "0"'
render -f "$ingress" --set replicas=2 >/dev/null 2>&1 && bad "replicas=2 with an attachment claim accepted" \
    || ok "replicas above 1 with an attachment claim refused"
expect "minimal: every probe field rendered" "$out" "timeoutSeconds: 5" "failureThreshold: 30"
expect "minimal: a NetworkPolicy by default, open to ingress-nginx and the test pod" "$out" \
    "kind: NetworkPolicy" "kubernetes.io/metadata.name: ingress-nginx" "app.kubernetes.io/component: test"
out_np="$(render -f "$minimal" --set networkPolicy.enabled=false)"
grep -q "kind: NetworkPolicy" <<<"$out_np" && bad "networkPolicy.enabled=false still renders one" \
    || ok "no NetworkPolicy when disabled"
grep -q "kind: Ingress" <<<"$out" && bad "minimal: an Ingress without ingress.enabled" || ok "minimal: no Ingress"
grep -q "MAITY_FORGE_GITHUB_TOKEN" <<<"$out" && bad "minimal: a token without a Secret" || ok "minimal: no forge token"
grep -q "MAITY_FORGE_INSTANCE_NAMESPACES" <<<"$out" && bad "minimal: namespaces without a list" || ok "minimal: no instance namespaces"
grep -q "MAITY_ATTACHMENT\|name: attachments" <<<"$out" && bad "minimal: attachment settings without a claim" || ok "minimal: no attachment settings"
grep -q "MAITY_SECRET_KEY" <<<"$out" && bad "minimal: an instance key without a Secret" || ok "minimal: no instance key"
grep -q "MAITY_SMTP\|MAITY_MAIL_SIGNING_KEY" <<<"$out" && bad "minimal: mail env without mail values" || ok "minimal: no mail env"
grep -q "MAITY_TRUSTED_PROXIES" <<<"$out" && bad "minimal: trusted proxies unset but rendered" || ok "minimal: no trusted proxies"

out="$(render -f "$ingress")"
expect "ingress: TLS host, defaults merged with the operator's annotation, digest, token" "$out" \
    "ingressClassName: nginx" "secretName: t-maity-hub-tls" 'value: "https://maity.example.org"' \
    'nginx.ingress.kubernetes.io/proxy-buffering: "off"' "cert-manager.io/cluster-issuer: letsencrypt" \
    "@sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    "name: MAITY_FORGE_GITHUB_TOKEN" 'value: "10.244.0.0/16"' \
    "name: MAITY_FORGE_INSTANCE_NAMESPACES" 'value: "maity-org"'
# The default body size for ingress-nginx lets the largest upload the hub takes through. Its
# value is bytes, or k, m or g (any case); 0 means no limit.
size="$(sed -n 's/^ *nginx.ingress.kubernetes.io\/proxy-body-size: "\{0,1\}\([0-9][0-9]*[kKmMgG]\{0,1\}\)"\{0,1\}$/\1/p' <<<"$out")"
cap="$(sed -n 's/^ATTACHMENT_CAP = \([0-9]*\) \* 1024 \* 1024$/\1/p' "$chart/../../../hub/src/maity_hub/middleware.py")"
bytes=""
case "$size" in
    *[kK]) bytes=$(( 10#${size%?} * 1024 )) ;;
    *[mM]) bytes=$(( 10#${size%?} * 1024 * 1024 )) ;;
    *[gG]) bytes=$(( 10#${size%?} * 1024 * 1024 * 1024 )) ;;
    [0-9]*) bytes=$(( 10#$size )) ;;
esac
if [ -n "$bytes" ] && [ -n "$cap" ] && [ "$bytes" -eq 0 ]; then
    ok "ingress: proxy-body-size 0, no limit at the ingress"
elif [ -n "$bytes" ] && [ -n "$cap" ] && [ "$bytes" -gt $(( cap * 1024 * 1024 )) ]; then
    ok "ingress: proxy-body-size $size above the hub's attachment cap of ${cap} MiB"
else
    bad "ingress: proxy-body-size '$size' not above the hub's attachment cap '${cap}' MiB"
fi
grep -q "nginx.ingress.kubernetes.io/limit-" <<<"$out" && bad "ingress: a request limit while it is off" \
    || ok "ingress: no request limit by default"
expect "ingress: the request limit on, as ingress-nginx annotations" \
    "$(render -f "$ingress" --set ingress.requestLimit.enabled=true)" \
    'nginx.ingress.kubernetes.io/limit-rps: "50"' 'nginx.ingress.kubernetes.io/limit-burst-multiplier: "4"' \
    'nginx.ingress.kubernetes.io/limit-connections: "100"' "cert-manager.io/cluster-issuer: letsencrypt"
expect "ingress: a burst that is no multiple of the rate rounds up" \
    "$(render -f "$ingress" --set ingress.requestLimit.enabled=true --set ingress.requestLimit.burst=120)" \
    'nginx.ingress.kubernetes.io/limit-burst-multiplier: "3"'
render -f "$ingress" --set ingress.requestLimit.enabled=true --set ingress.requestLimit.burst=10 >/dev/null 2>&1 \
    && bad "ingress: a burst below the rate accepted" || ok "ingress: a burst below the rate refused"
render -f "$ingress" --set ingress.requestLimit.enabled=true --set ingress.requestLimit.inFlight=0 >/dev/null 2>&1 \
    && bad "ingress: no open request allowed accepted" || ok "ingress: inFlight below 1 refused"
grep -q "helm.sh/hook: pre-install" <<<"$out" && bad "ingress: migrate Job with migrate.enabled false" \
    || ok "ingress: no migrate Job when disabled"
expect "ingress: the attachment volume, its mount and the directory" "$out" \
    "name: MAITY_ATTACHMENT_DIR" 'value: "/data/attachments"' 'claimName: "maity-attachments"' \
    'mountPath: "/data/attachments"'
expect "ingress: the instance key from a Secret by reference" "$out" "name: MAITY_SECRET_KEY" "key: secret-key"
expect "ingress: mail from Secrets by reference and plain values" "$out" \
    "name: MAITY_MAIL_SIGNING_KEY" "name: MAITY_SMTP_PASSWORD" "key: smtp-pass" 'value: "smtp.example.org"' \
    'value: "465"' 'value: "implicit"' 'value: "noreply@example.org"' 'value: "Maity <noreply@example.org>"' \
    'value: "info@example.org"'
out_mig="$(render -f "$minimal" --set mail.host=smtp.example.org --set mail.passwordSecret.existingSecret=s \
    --set mail.signingKeySecret.existingSecret=s)"
[ "$(grep -c 'name: MAITY_SMTP_PASSWORD' <<<"$out_mig")" = 2 ] && [ "$(grep -c 'name: MAITY_MAIL_SIGNING_KEY' <<<"$out_mig")" = 2 ] \
    && ok "mail env reaches the hub and the migrate Job, once each" || bad "mail env is not in both the hub and the migrate Job"
out_sk="$(render -f "$minimal" --set secretKey.existingSecret=s)"
[ "$(grep -c 'name: MAITY_SECRET_KEY' <<<"$out_sk")" = 2 ] && ok "the instance key reaches the hub and the migrate Job, once each" \
    || bad "the instance key is not in both the hub and the migrate Job"
out_att="$(render -f "$minimal" --set attachments.existingClaim=c)"
[ "$(grep -c 'name: MAITY_ATTACHMENT_DIR' <<<"$out_att")" = 1 ] && [ "$(grep -c 'claimName: "c"' <<<"$out_att")" = 1 ] \
    && [ "$(grep -c 'mountPath: "/var/lib/maity/attachments"' <<<"$out_att")" = 1 ] \
    && ok "the attachment volume reaches the hub once, at the default path" \
    || bad "the attachment volume is not in the hub exactly once"
out_ee="$(render -f "$minimal" --set attachments.existingClaim=c --set "extraEnv[0].name=MAITY_ATTACHMENT_DIR" --set-string "extraEnv[0].value=/elsewhere" --show-only templates/deployment.yaml)"
[ "$(grep -A1 'name: MAITY_ATTACHMENT_DIR' <<<"$out_ee" | grep 'value:' | tail -1 | tr -d ' "')" = 'value:/elsewhere' ] \
    && ok "extraEnv still overrides the attachment settings" || bad "extraEnv no longer overrides the attachment settings"
# A ReadWriteOnce claim in the Job blocks an upgrade on a second node (Multi-Attach).
grep -q "MAITY_ATTACHMENT\|claimName\|name: attachments" <<<"$(render -f "$minimal" --set attachments.existingClaim=c --show-only templates/migrate-job.yaml)" \
    && bad "the migrate Job has the attachment volume or its settings" || ok "the migrate Job has no attachment volume or settings"
# A project's attachment storage is the hub's limit max_attachment_storage_per_project (docs/api.md §16.5): set
# under Limits, or by MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT in extraEnv; the chart has no value of its own.
grep -q "MAITY_ATTACHMENT_QUOTA" <<<"$out_att" && bad "the removed MAITY_ATTACHMENT_QUOTA rendered" || ok "no MAITY_ATTACHMENT_QUOTA"
out_s3="$(render -f "$minimal" --set attachments.store=s3 --set attachments.s3.bucket=b --set attachments.s3.endpoint=https://s3.example \
    --set attachments.s3.region=r --set attachments.s3.existingSecret=maity-s3 --show-only templates/deployment.yaml)"
expect "s3: the store, the bucket, the endpoint and the credentials by reference" "$out_s3" \
    'value: "s3"' 'value: "b"' 'value: "https://s3.example"' 'value: "r"' 'name: "maity-s3"' \
    'key: "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID"' 'key: "MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY"'
grep -q "MAITY_ATTACHMENT_DIR\|claimName\|MAITY_ATTACHMENT_S3_ALLOW_HTTP\|MAITY_ATTACHMENT_S3_PREFIX" <<<"$out_s3" \
    && bad "s3 without a claim still renders the volume, the directory or unset options" || ok "s3 without a claim: no volume, no directory"
out_s3c="$(render -f "$minimal" --set attachments.store=s3 --set attachments.s3.bucket=b --set attachments.existingClaim=c --show-only templates/deployment.yaml)"
expect "s3 with the claim kept for the copy: both" "$out_s3c" 'value: "s3"' "name: MAITY_ATTACHMENT_DIR" 'claimName: "c"'
grep -q "MAITY_ATTACHMENT_S3_ACCESS_KEY_ID\|MAITY_ATTACHMENT_S3_SECRET_ACCESS_KEY" <<<"$out_s3c" && bad "s3 without existingSecret renders a secret reference" || ok "s3 without existingSecret: the client's own credentials"
render -f "$minimal" --set attachments.s3=null >/dev/null 2>&1 && ok "attachments.s3: null renders" || bad "attachments.s3: null breaks the template"
render -f "$minimal" --set attachments.store=s3 >/dev/null 2>&1 && bad "s3 without a bucket is accepted" || ok "s3 without a bucket is refused"
out_pre="$(render -f "$minimal" --set attachments.s3.bucket=b --set attachments.existingClaim=c --show-only templates/deployment.yaml)"
expect "local with a bucket set, for the copy: its settings, not the store" "$out_pre" 'value: "b"' "name: MAITY_ATTACHMENT_DIR"
grep -q "name: MAITY_ATTACHMENT_STORE" <<<"$out_pre" && bad "a bucket alone switches the store" || ok "a bucket alone does not switch the store"
render -f "$minimal" --set attachments.store=tape >/dev/null 2>&1 && bad "an unknown attachments.store is accepted" || ok "an unknown attachments.store is refused by the schema"
grep -q "MAITY_ATTACHMENT" <<<"$(render -f "$minimal" --set attachments.store=s3 --set attachments.s3.bucket=b --show-only templates/migrate-job.yaml)" \
    && bad "the migrate Job has the s3 settings" || ok "the migrate Job has no s3 settings"
render -f "$minimal" --set attachments.mountPath=relative >/dev/null 2>&1 && bad "a relative attachments.mountPath is accepted" || ok "a relative attachments.mountPath is refused by the schema"
render -f "$minimal" --set attachments.quotaBytes=5000 >/dev/null 2>&1 && bad "the removed attachments.quotaBytes is accepted" || ok "the removed attachments.quotaBytes is refused by the schema"
out_nopw="$(render -f "$ingress" --set mail.passwordSecret.existingSecret=)"
grep -q "MAITY_SMTP_PASSWORD" <<<"$out_nopw" && bad "ingress: a password without a Secret" || ok "ingress: no password env without a Secret"
out_nohost="$(render -f "$ingress" --set mail.host=)"
grep -q "MAITY_SMTP" <<<"$out_nohost" && bad "ingress: SMTP env without a host" || ok "ingress: no SMTP env without a host"
render -f "$ingress" --set mail.tls=ssl >/dev/null 2>&1 && bad "mail.tls=ssl is accepted" || ok "mail.tls=ssl is refused by the schema"
expect "ingress: pull secret, service annotation, extra volume, own policy peer" "$out" \
    "- name: registry" "example.org/owner: maity" "secretName: maity-hub-db-ca" \
    "mountPath: /etc/maity/db-ca" "kubernetes.io/metadata.name: traefik"
out="$(render -f "$minimal" --set "extraVolumes[0].name=ca" --set "extraVolumes[0].emptyDir.medium=Memory" \
    --set "extraVolumeMounts[0].name=ca" --set "extraVolumeMounts[0].mountPath=/ca")"
[ "$(grep -c 'mountPath: /ca' <<<"$out")" = 2 ] && ok "extra mounts reach the hub and the migrate Job" \
    || bad "extra mounts are not in both the hub and the migrate Job"

out="$(render -f "$minimal" --set config.dashboard=false)"
expect "dashboard off: MAITY_WEB_DIR emptied" "$out" "name: MAITY_WEB_DIR"

# Each refusal: its name, the text the error must contain (any case: helm 3
# and 4 word schema errors differently), then the arguments.
refuse() {
    local name="$1" text="$2"
    shift 2
    local err
    if err="$(render "$@" 2>&1)"; then
        bad "$name: rendered"
    elif grep -qiF -- "$text" <<<"$err"; then
        ok "$name"
    else
        bad "$name: other error: $err"
    fi
}

refuse "no image" "image.repository is required" -f "$minimal" --set image.repository=
refuse "no database Secret" "database.existingSecret is required" -f "$minimal" --set database.existingSecret=
refuse "no public URL" "config.publicUrl is required" -f "$minimal" --set config.publicUrl=
refuse "Ingress without host" "ingress.host is required" -f "$minimal" --set ingress.enabled=true \
    --set config.trustedProxies=10.0.0.0/8
refuse "Ingress without trusted proxies" "config.trustedProxies is required" -f "$minimal" \
    --set ingress.enabled=true --set ingress.host=maity.example.org
refuse "a typo in a value" "additional propert" -f "$minimal" --set config.publicURL=https://x.example
refuse "a short digest" "match pattern" -f "$minimal" --set image.digest=sha256:abc
# By digest by default: no tag of its own (not the appVersion), and a tag alone is not enough.
refuse "no digest" "image.digest is required" -f "$minimal" --set image.digest=
refuse "a tag without image.allowTag" "image.digest is required" -f "$minimal" --set image.digest= --set image.tag=ci
refuse "image.allowTag without a tag" "image.tag is required" -f "$minimal" --set image.digest= --set image.allowTag=true
refuse "a replica count" "additional propert" -f "$minimal" --set replicaCount=2
refuse "a pull secret as a bare string" "imagePullSecrets" -f "$minimal" --set "imagePullSecrets[0]=registry"
refuse "Ingress without trusted proxies, plain HTTP allowed" "config.trustedProxies is required" \
    -f "$minimal" --set ingress.enabled=true --set ingress.host=maity.example.org --set config.allowPlainHttp=true
refuse "plain HTTP with an Ingress" "config.allowPlainHttp is only" -f "$minimal" --set ingress.enabled=true \
    --set ingress.host=maity.example.org --set config.trustedProxies=10.0.0.0/8 --set config.allowPlainHttp=true
refuse "plain HTTP on a LoadBalancer" "config.allowPlainHttp is only" -f "$minimal" \
    --set service.type=LoadBalancer --set config.allowPlainHttp=true

# The Deployment validates on its own, not only through the migrate Job.
refuse "no trusted proxies, migrate off" "config.trustedProxies is required" -f "$minimal" \
    --set migrate.enabled=false --set ingress.enabled=true --set ingress.host=maity.example.org
refuse "plain HTTP on a NodePort, migrate off" "config.allowPlainHttp is only" -f "$minimal" \
    --set migrate.enabled=false --set service.type=NodePort --set config.allowPlainHttp=true
out="$(render -f "$minimal" --set config.allowPlainHttp=true)"
expect "plain HTTP on a ClusterIP Service renders" "$out" 'name: MAITY_ALLOW_PLAIN_HTTP' 'value: "1"'

if [ "$fails" -ne 0 ]; then
    printf '\nhelm check: %d failure(s)\n' "$fails" >&2
    exit 1
fi
printf '\nhelm check: all held\n'
