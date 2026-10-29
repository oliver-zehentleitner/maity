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
    'value: "https://maity.example.org"' "image: maity-hub:ci" "readOnlyRootFilesystem: true"
expect "minimal: hub pods selected by component, version label from the tag" "$out" \
    "app.kubernetes.io/component: hub" 'app.kubernetes.io/version: "ci"'
selector="$(sed -n '/^kind: Service$/,/^---/p' <<<"$out" | sed -n '/selector:/,$p')"
expect "minimal: the Service selects only the hub" "$selector" "app.kubernetes.io/component: hub"
expect "minimal: every probe field rendered" "$out" "timeoutSeconds: 5" "failureThreshold: 30"
expect "minimal: a NetworkPolicy by default, open to ingress-nginx and the test pod" "$out" \
    "kind: NetworkPolicy" "kubernetes.io/metadata.name: ingress-nginx" "app.kubernetes.io/component: test"
out_np="$(render -f "$minimal" --set networkPolicy.enabled=false)"
grep -q "kind: NetworkPolicy" <<<"$out_np" && bad "networkPolicy.enabled=false still renders one" \
    || ok "no NetworkPolicy when disabled"
grep -q "kind: Ingress" <<<"$out" && bad "minimal: an Ingress without ingress.enabled" || ok "minimal: no Ingress"
grep -q "MAITY_FORGE_GITHUB_TOKEN" <<<"$out" && bad "minimal: a token without a Secret" || ok "minimal: no forge token"
grep -q "MAITY_SECRET_KEY" <<<"$out" && bad "minimal: an instance key without a Secret" || ok "minimal: no instance key"
grep -q "MAITY_SMTP\|MAITY_MAIL_SIGNING_KEY" <<<"$out" && bad "minimal: mail env without mail values" || ok "minimal: no mail env"
grep -q "MAITY_TRUSTED_PROXIES" <<<"$out" && bad "minimal: trusted proxies unset but rendered" || ok "minimal: no trusted proxies"

out="$(render -f "$ingress")"
expect "ingress: TLS host, defaults merged with the operator's annotation, digest, token" "$out" \
    "ingressClassName: nginx" "secretName: t-maity-hub-tls" 'value: "https://maity.example.org"' \
    'nginx.ingress.kubernetes.io/proxy-buffering: "off"' "cert-manager.io/cluster-issuer: letsencrypt" \
    "@sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    "name: MAITY_FORGE_GITHUB_TOKEN" 'value: "10.244.0.0/16"'
grep -q "helm.sh/hook: pre-install" <<<"$out" && bad "ingress: migrate Job with migrate.enabled false" \
    || ok "ingress: no migrate Job when disabled"
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
