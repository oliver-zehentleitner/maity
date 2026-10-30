# Plan: production on OVHcloud, today's Vultr system becomes the test system

Status: proposal for the maintainer's go (card `tsk-4ee6s3ch3kp3`). Nothing in it has been ordered or run.
Agents never execute on production and never print a secret; every step that changes production is a command the
maintainer runs, one after the other, each ending in a verdict line (the pattern of the Vultr deploys).

Facts about OVHcloud below were read in OVHcloud's documentation on 2026-10-30 (links at the end). Where the pages
disagreed or said nothing, this plan says so and names how to settle it before ordering.

## 1. Decision and what changes

| | Test (today's Vultr k3s) | Prod (new, OVH Frankfurt) |
|---|---|---|
| Deploys | continuously from `main` | tagged releases, about once a day |
| Address | a new test domain (the maintainer picks) | `maity.team`, `www`, `join.maity.team` |
| Database | PostgreSQL StatefulSet in the cluster | managed PostgreSQL outside the cluster |
| Mail | into a sink, never to real people | sends |
| Data | test data, may be reset | the real data, moved from Vultr once |

The hub's Helm chart is the same for both. What differs is the values file, so the same chart is exercised on test
before every prod release.

## 2. OVH region and services: what the documentation says

- **Frankfurt (`DE1`) offers Managed Kubernetes on the Free plan only, in one availability zone.** The datacenter table
  has `DE1` with Free ticked, Standard not, `1-AZ`. Free means a **99.5 % SLO** (no SLA), a shared etcd capped at
  **400 MB**, up to 100 nodes. Standard (99.9 % SLA in a 1-AZ region, 99.99 % in a 3-AZ region, dedicated etcd up to
  8 GB) is not offered in `DE1`.
- Worker flavors `B3`, `C3`, `R3` and `D2` are listed for `DE1`; block storage classes `csi-cinder-high-speed(-gen2)`
  and `csi-cinder-classic`, with LUKS-encrypted variants in `DE1`.
- **Managed PostgreSQL** is "available in all Public Cloud 1-AZ and 3-AZ regions"; the backup page names `DE` with
  `GRA` as its default off-site region. Versions 15 to 18 (we run 17). Plans: Essential 1 node, **Business 2 nodes**,
  Enterprise 3 nodes. Daily backups with retention 2 / 14 / 30 days, and **point-in-time recovery** from continuous
  capture to object storage ("recovery point of a few minutes"). Access by an IP allow-list or the private network
  (vRack), TLS on the connection, about 100 connections per 4 GB of RAM.
- One open point: pages in other languages list different regions for the database product. **Before ordering, open
  the order form for `DE1` and confirm that PostgreSQL is offered there.** If it is not, the nearest region with both
  is to be named here, and the points below apply unchanged except the latency.

**Consequence the maintainer should weigh:** in Frankfurt the control plane has no SLA and the cluster sits in one
zone. For a launch that is a risk to accept knowingly, not a technical blocker: the data is in a two-node managed
database with its own PITR, and the hub is one replica anyway. The alternative is a region with Standard plan; I could
not confirm from the documentation which EU regions offer Standard together with managed PostgreSQL (a search summary
said other European regions also list Free only; unverified). Decision for the maintainer: Frankfurt on Free, or
look at the order form's region list for a Standard region.

## 3. Cluster and sizing

What we measured on Vultr, in `/workspace/tmp/a/hub-mem.csv` (every 5 minutes): the hub pod's working set stays
between about 120 and 200 MiB over days; a fresh pod starts near 120 MiB. The chart asks for `800m` CPU and `768Mi`
and limits memory to `2Gi`. PostgreSQL moves out of the cluster, so the cluster runs the hub, Traefik, cert-manager
and the monitoring below.

Proposal: **two worker nodes of the smallest `B3` flavor with at least 4 GB** (two, so a node update or failure does
not take the hub down while it is rescheduled), the hub as one replica with the `Recreate` strategy it has today. The
exact flavor name and the price are read off the order form; I did not take either from a search result. The
attachment store is a `ReadWriteOnce` volume on `csi-cinder-high-speed-gen2`, 10 Gi as now, which is why the hub
stays at one replica.

## 4. Ingress, load balancer, TLS, DNS

- **Traefik** as the ingress controller (as on Vultr, so the chart values carry over). The NGINX ingress controller is
  not used: OVH's own guides move people from it to Traefik.
- **OVH Public Cloud Load Balancer** (Octavia): a Service of type `LoadBalancer` in front of Traefik. No API gateway.
  On clusters above Kubernetes 1.30 this is the default; flavor `small` is the default and `medium`, `large`, `xl`
  exist. The comparison table gives up to 4 Gbit/s and 20 000 connections for it, more than the hub needs.
- **The client address.** OVH's guide uses `externalTrafficPolicy: Local` and the annotations
  `service.beta.kubernetes.io/ovh-loadbalancer-proxy-protocol: "v2"` and `loadbalancer.openstack.org/proxy-protocol: "v2"`,
  with the controller trusting the load balancer's egress IPs (listed in the Service annotation
  `lb.k8s.ovh.net/egress-ips`). The guide shows it for NGINX and says a Traefik section is planned, so the Traefik
  side (`proxyProtocol.trustedIPs`) is mine to prove on the cluster. This matters for the hub: the login and join rate
  limits count the address the hub sees (`docs/install/README.md`, "The same-host proxy trap"), and
  `MAITY_TRUSTED_PROXIES` must name the pods that connect to it. **Acceptance test before any DNS change:** two
  requests from two different outside addresses show two different addresses in the access log, and a cookie carries
  `Secure`.
- **Long requests.** The hub has no event stream; the longest request is the events long-poll, which the hub ends
  after **55 seconds** (`docs/api.md` §8, "`wait` ... 55 seconds"), and the device-login long-polls. OVH's migration
  guide lists the old load balancer's defaults as `timeout-client-data` and `timeout-member-data` of 180 000 ms and
  `timeout-member-connect` of 20 000 ms, and does not state the Octavia defaults. So the plan **sets them explicitly**
  on the Service (`loadbalancer.openstack.org/timeout-client-data` and `...-member-data` at 120 000 ms, above the 55 s
  with room) and tests it: `maity wait` with the maximum wait, ten times, through the load balancer, none cut early.
  If a proxy such as Cloudflare is put in front later, its idle limit is the next thing to check (the long-poll is
  well under common limits of 100 s, but the numbers are the proxy's to confirm).
- **TLS**: cert-manager with Let's Encrypt (DNS-01 for the prod names before the switch, section 9; HTTP-01 for the test domain), one Certificate for the apex, `www` and
  the join host (`deploy/k3s-single/cert.yaml` is the model). Cloudflare stays **DNS only** (grey cloud), so the load balancer is reached directly. Add a CAA record for `letsencrypt.org`.
- **DNS** at Cloudflare: `maity.team`, `www`, `join` as A records to the load balancer's address (IPv4 only, as on
  Vultr, until IPv6 is tested end to end), and the test domain to the Vultr server. TTL 300 from one day before the
  switch.

## 5. Database

- Managed PostgreSQL 17, **Business plan** (two nodes), in `DE1`, access by the allow-list of the cluster nodes'
  addresses first; the private network (vRack) is the stronger setting and is worth the setup if the order form allows
  it for Free-plan Kubernetes (to settle at order time). The connection string stays in the Secret `maity-hub-db`.
- **Backups, two layers.** (a) The provider's daily backup and PITR, with the off-site copy in a second region
  (`DE` replicates to `GRA` by default; set `backups.regions` to two entries as the page recommends). (b) Our own
  nightly `pg_dump` and attachment tar, as now, but uploaded to **object storage in a second location** (an S3 bucket
  at another provider or another OVH region), with credentials that can write and not delete. (b) is the copy that
  does not depend on the provider's account, and the only copy of the attachments outside the volume. The dump
  CronJob changes from "talk to `maity-postgres`" to "talk to the managed host over TLS"; that is a change to
  `deploy/k3s-single/backup.yaml` for the OVH variant, tested on the rehearsal.
- **Before every prod migration:** a fresh `pg_dump` plus tar (as `helm-upgrade.sh` does with `DUMP_CRONJOB`) and a
  note of the time for PITR. The hub is stopped while the migrations run, as now.
- Restore rehearsal before launch: a restore of the dump into a scratch database on the managed service, and a PITR
  restore, each timed and written down. How the provider's PITR restore is delivered (a new service or in place) is read
  from the console during that rehearsal, not assumed here.

## 6. Mail

- Prod sends: the SMTP settings as chart values (`mail.*`), the password in a Secret, as on Vultr today.
- Test must not reach real people. The hub has no recipient allow-list, so no code change is assumed: test's SMTP
  host is a **sink in the cluster** (Mailpit or an equivalent catch-all), which also shows what was sent. If a real
  allow-list is wanted (mail only to named test addresses), that is a hub change and a card of its own.

## 7. Monitoring and alerts

Today there is a health probe and the hub's own checks; nothing alerts. Proposed, kept small:
- an external probe of `https://maity.team/api/v1/health` and of the join host from outside OVH;
- in the cluster, Prometheus and Alertmanager (a single instance of each) with alerts on: hub working set above 70 %
  of its limit, restarts, 5xx rate at Traefik, certificate expiry under 14 days (cert-manager's metric), the database
  being unreachable in `/api/v1/health`, free space on the attachment volume;
- alerts by mail to the maintainer, and to the Maity chat through an agent that reads them; no alert text carries a
  secret.
The managed database's own metrics and alerts in the OVH console are added to the same list.

## 8. Release flow

1. A change merges to `main`; test deploys it automatically (migrations run on test first, so they have run on every
   release's schema before prod sees it).
2. A release is a tag. The tag builds the image (the `publish-image` workflow, by digest), rolls the changelog
   fragments into the release section, and creates the release notes.
3. Prod: the maintainer says go; the ops agent prepares the package for the tag (`check`, `pre`, `rehearse` on a copy
   of the newest dump, then `upgrade`) and the maintainer runs it. `helm upgrade` is always preceded by the dump.
4. After the upgrade, `post-upgrade-checks.sh` and `join-host.sh verify`.
Rollback after migrations is the dump plus attachment restore plus `helm rollback`; the old hub cannot serve a newer
schema, so "fix forward" is the first answer and the restore the second.

## 9. Moving the data and switching `maity.team`

Preparation (nothing on Vultr changes):
1. Cluster, database, load balancer, Secrets (the same `MAITY_SECRET_KEY`, mail signing key and instance key values as
   Vultr, copied by the maintainer; I never see them), cert-manager, Traefik, monitoring.
2. Deploy the hub on a temporary address (`prod-staging.<test domain>`), load the newest Vultr dump into the managed
   database, untar the attachments, run `post-upgrade-checks.sh` against it. Time the dump, the restore and the tar.
3. The two acceptance tests of section 4 (client address, long-polls) and the restore rehearsal of section 5.
4. A day before: TTL 300, announcement in the team chat.

The switch (a window of a few minutes; the hub is stopped, so writes stop):
1. Vultr: scale the hub to 0. Fresh `pg_dump` plus attachment tar. Note the time.
2. OVH: restore into the managed database, untar to the volume, start the hub (migrations run to the same head,
   nothing to do).
3. `post-upgrade-checks.sh` and a login against OVH with `--resolve maity.team:443:<OVH address>`.
4. DNS: `maity.team`, `www`, `join` to the OVH address. The certificate is already there: it is issued before the day
   by DNS-01 (cert-manager with a Cloudflare API token limited to the zone's DNS), because HTTP-01 cannot succeed
   before the names point at OVH. HTTP-01 stays the method for the test domain.
5. Watch the 5xx rate and the first logins for an hour. The Vultr hub stays scaled to 0 with its data for 7 days.

Rollback: until the first write on OVH, point the DNS back and scale the Vultr hub up; nothing is lost. After writes on
OVH, going back means a dump from OVH restored on Vultr, so the point of no return is named in the chat before step 4.

Then Vultr becomes test: new domain and certificate, the mail sink, a values file with test settings, and the
`main`-to-test deploy.

## 10. What the maintainer does himself

- OVHcloud account, payment method, project, and an API user/role for the console and `kubectl`, with the kubeconfig put
  on the ops machine as a file (never pasted).
- Ordering the Managed Kubernetes cluster, the managed PostgreSQL service and the load balancer after the region check.
- Object storage or the second-location bucket, and its write-only credentials.
- A Cloudflare API token limited to editing DNS of the zone, placed as a Secret in the cluster (for DNS-01).
- The test domain, and the DNS records at the registrar/Cloudflare, including the TTL change and the final switch.
- Copying the Secret values (secret key, mail signing key, instance key, SMTP password, forge token) into OVH Secrets.
- The go for each step of sections 8 and 9, and the choice in section 2.

## 11. Open points and risks

- PostgreSQL in `DE1` (section 2) and the Free plan's missing SLA.
- The Traefik side of the client address behind the load balancer (section 4), the one thing here I have not seen work.
- The Octavia timeout defaults are not stated; the plan sets them.
- The in-cluster `NetworkPolicy` of the chart (it admits only Traefik) needs the cluster's CNI to enforce it; checked on
  the staging step.
- The container image is pulled from `ghcr.io`; if the package is not public, the cluster needs a pull Secret.
- Costs are not in this plan: they come from the order form, not from me.

## Sources

- [Available datacenters, worker nodes and persistent storage flavors](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/datacenters-nodes-storage-flavors)
- [Choosing the right Managed Kubernetes plan](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/mks-plans.md)
- [Public Cloud Databases for PostgreSQL: capabilities](https://docs.ovhcloud.com/en/guides/public-cloud/databases/postgresql-capabilities)
- [Automated backups for Public Cloud Databases](https://docs.ovhcloud.com/en/guides/public-cloud/databases/backups)
- [Migrate from Load Balancer for MKS to the Public Cloud Load Balancer](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/migrate-iolb-to-public-cloud-loadbalancer.md)
- [Getting the source IP behind the LoadBalancer](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/getting-source-ip-behind-loadbalancer.md)
