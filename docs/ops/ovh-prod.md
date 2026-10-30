# Plan: production on OVHcloud, today's Vultr system becomes the test system

Status: proposal for the maintainer's go (card `tsk-4ee6s3ch3kp3`). Nothing in it has been ordered or run.
Agents never execute on production and never print a secret; every step that changes production is a command the
maintainer runs, one after the other, each ending in a verdict line (the pattern of the Vultr deploys).

Facts about OVHcloud below were read in OVHcloud's documentation on 2026-10-30 (links at the end). Where the pages
disagreed or said nothing, this plan says so and names how to settle it before ordering.

## 1. Decision and what changes

| | Test (today's Vultr k3s) | Prod (new, OVH Paris) |
|---|---|---|
| Deploys | continuously from `main` | tagged releases, about once a day |
| Address | a new test domain (the maintainer picks) | `maity.team`, `www`, `join.maity.team` |
| Database | PostgreSQL StatefulSet in the cluster | managed PostgreSQL outside the cluster |
| Mail | into a sink, never to real people | sends |
| Data | test data, may be reset | the real data, moved from Vultr once |

The hub's Helm chart is the same for both. What differs is the values file, so the same chart is exercised on test
before every prod release.

## 2. OVH region and services: what the documentation says

The maintainer chose **Paris (`EU-WEST-PAR`) with the Standard plan of Managed Kubernetes** (decision 2026-10-30,
instead of Frankfurt on the Free plan, which has no SLA and one zone). Managed PostgreSQL in the Business plan is
checked by him in the order form.

- **Paris is a 3-AZ region** (zones `eu-west-par-a`, `-b`, `-c`, each in its own data center). The datacenter table has it
  with the Standard plan only: control plane across the zones, **99.99 % SLA**, dedicated etcd up to 8 GB, up to 500
  nodes. (Frankfurt `DE1` is Free only, 99.5 % SLO, one zone, shared etcd of 400 MB.)
- **Worker flavors:** the table lists `D2-4` and `D2-8` and the `B2`, `C2`, `R2` families for every region; `B3`, `C3`
  and `R3` are listed for `DE1`, `GRA11`, `UK1` and `WAW1`, **not for Paris**. So the nodes are `D2` or `B2`/`C2`
  (exact flavor and price from the order form). Block storage classes `csi-cinder-high-speed(-gen2)` and
  `csi-cinder-classic`, with LUKS-encrypted variants in France.
- **Managed PostgreSQL** is "available in all Public Cloud 1-AZ and 3-AZ regions"; versions 15 to 18 (we run 17).
  Plans: Essential 1 node, **Business 2 nodes**, Enterprise 3 nodes. Daily backups with retention 2 / 14 / 30 days, and
  **point-in-time recovery** from continuous capture to object storage ("recovery point of a few minutes"), with an
  off-site copy in a second region (the backup page lists the default pairs; Paris is not in the part of the table I
  could read, so the second region is chosen explicitly with `backups.regions`). Access by an IP allow-list or the
  private network (vRack), TLS, about 100 connections per 4 GB of RAM. How the nodes of a Business or Enterprise service
  are spread over the three zones is not stated in the pages I read; the maintainer asks it in the order form.
- Pages in other languages list different regions for the database product: **confirm in the order form that
  Paris offers Business-plan PostgreSQL**, and what the plan costs.

**What the 3-AZ region changes for us.** Block volumes live in one zone, so the hub pod with the `ReadWriteOnce`
attachment volume can only run on a node in that volume's zone; a zone failure then takes the hub down until it is
restored elsewhere from the tar. That is acceptable for one pod and is another reason the attachment store moves to
shared storage with the multi-pod work (section 12). OVH's navigation lists a multi-attach block storage for 3-AZ
regions; I did not read it, so it is a candidate, not a plan. Worker nodes are set per node pool; the Terraform example
pins one pool per zone, and a pool across zones is to be confirmed on the cluster.

## 3. Cluster and sizing

What we measured on Vultr, in `/workspace/tmp/a/hub-mem.csv` (every 5 minutes): the hub pod's working set stays
between about 120 and 200 MiB over days; a fresh pod starts near 120 MiB. The chart asks for `800m` CPU and `768Mi`
and limits memory to `2Gi`. PostgreSQL moves out of the cluster, so the cluster runs the hub, Traefik, cert-manager
and the monitoring below.

Proposal: **two worker nodes of a `D2` or `B2` flavor with at least 4 GB, in different zones** (two, so a node update or failure does
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
- **The client address.** The path is: client, OVH load balancer, **PROXY protocol v2**, Traefik, hub. OVH's guide sets
  `externalTrafficPolicy: Local` and the annotations `service.beta.kubernetes.io/ovh-loadbalancer-proxy-protocol: "v2"` and
  `loadbalancer.openstack.org/proxy-protocol: "v2"` on the controller's Service; the controller must accept the PROXY
  protocol only from the load balancer's egress addresses (the Service annotation `lb.k8s.ovh.net/egress-ips`; with the
  private network, the subnet). The guide shows it for NGINX and says a Traefik section is planned; for Traefik that is
  the entry point's `proxyProtocol.trustedIPs`, which I have to prove on the cluster. Traefik then sets
  `X-Forwarded-For` and `X-Forwarded-Proto`, and **the hub trusts only Traefik**.
  How the hub decides today (`hub/src/maity_hub/net.py`, `docs/api.md` §2.5): forwarded headers count only when the
  socket peer is in `MAITY_TRUSTED_PROXIES` (the chart's `config.trustedProxies`, which is required with the Ingress
  and is the ingress controller's pod network, `10.42.0.0/16` on Vultr's k3s); the hub reads every
  `X-Forwarded-For` value from the right and takes the first one that is not a trusted proxy as the client, and the
  scheme at the same position. So on OVH `config.trustedProxies` is the **Traefik pods' network** (the cluster's pod
  CIDR, read from the cluster), never the load balancer's addresses (the load balancer does not connect to the hub) and
  never wider than needed; a client's own `X-Forwarded-For` ends up left of the real address and is ignored. The chart's
  NetworkPolicy already lets only Traefik reach the hub.
  This matters because the login and join rate limits and the bearer-over-TLS rule use that decision
  (`docs/install/README.md`, "The same-host proxy trap"): nothing fails loudly when it is wrong. **Acceptance test
  before any DNS change, in this order:** (1) a request from outside shows the real outside address in the hub's
  access log, not the load balancer's or a pod's; (2) two requests from two different outside addresses show two
  different addresses; (3) a request with a forged `X-Forwarded-For: 1.2.3.4` still shows the real address; (4) a
  forged `X-Forwarded-Proto: http` does not turn off `Secure` on a cookie, and a login over plain HTTP is refused
  with `insecure_transport`; (5) the same four on the join host.
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

- Managed PostgreSQL 17, **Business plan** (two nodes), in Paris, access by the allow-list of the cluster nodes'
  addresses first; the private network (vRack) is the stronger setting and is worth the setup if the order form allows
  it for the cluster (to settle at order time). The connection string stays in the Secret `maity-hub-db`.
- **Backups, two layers.** (a) The provider's daily backup and PITR, with the off-site copy in a second region
  (set `backups.regions` to two entries, Paris and a second region, as the page recommends). (b) Our own
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

- Business-plan PostgreSQL in Paris and how its nodes are spread over the zones (section 2).
- The Traefik side of the client address behind the load balancer (section 4), the one thing here I have not seen work; the five-step acceptance test decides.
- The Octavia timeout defaults are not stated; the plan sets them.
- The in-cluster `NetworkPolicy` of the chart (it admits only Traefik) needs the cluster's CNI to enforce it; checked on
  the staging step.
- The container image is pulled from `ghcr.io`; if the package is not public, the cluster needs a pull Secret.
- Costs are not in this plan: they come from the order form, not from me.

## 12. Growth: simple scaling toward about 200 000 users in two weeks

The maintainer's addition: scaling must be simple. The hub runs as one pod today; its multi-pod work is card
`tsk-f5jge5aw7ah1`. This plan is laid out for several pods so that card is the only thing missing, not the platform.
I cannot derive a capacity from the user count; the load test below produces the numbers that set the sizes.

**Nodes.** OVH's cluster autoscaler is switched on per node pool with minimum and maximum node counts. OVH's guide warns
not to autoscale monthly-billed pools and suggests the pattern used here: a **fixed base pool** (two nodes, monthly
billing allowed) for Traefik, cert-manager, monitoring and the first hub pods, and an **autoscaled hourly-billed pool**
(minimum 0 or 1, maximum set from the load test and the budget) for the hub pods that the HorizontalPodAutoscaler adds.
The Standard plan allows up to 500 nodes, far more than needed. Pools are per zone or across zones as the cluster allows (section 2).

**Hub pods.** HorizontalPodAutoscaler on CPU, a PodDisruptionBudget, topology spread across nodes, resource requests
that make the autoscaler's decisions meaningful. Needed from the hub side (B's card, listed so none is forgotten):
- every pod counts login and join rate limits in the same place, not in its own memory (otherwise N pods allow N times
  the limit); the events long-poll must wake on a write made through another pod;
- the attachment store is today a `ReadWriteOnce` volume, which only one node can mount. With several pods it must
  become shared storage (OVH's shared file storage or S3-compatible object storage); which one is a decision for that card.
- the migrate Job runs once per release, with the hub stopped, as now.

**Ingress.** Traefik at two or more replicas, spread over nodes; the load balancer's health check on the Traefik port;
`externalTrafficPolicy: Local` as in section 4, so each Traefik replica sees the real client address; no session
stickiness, because the hub holds no state a request must return to (this holds once the points above are done). Traefik
gets the same autoscaler as the hub if the load test shows it is the limit.

**PostgreSQL.** Start on the Business plan (two nodes) with a flavor that leaves room, because OVH lets a service's
flavor and plan be updated later (the pages exist; whether that is without downtime is read in the console during the
rehearsal). The limit to plan around is connections: about 100 per 4 GB of RAM, capped at 1000. The hub opens up to
16 + 16 per pod (`db_pool_size`, `db_max_overflow`), so ten pods can ask for 320 connections. Two ways to keep within
the limit: lower the per-pod pool, and **connection pooling by OVH's managed PgBouncer** (a pool is created per database
in the console and reached on its own port, with the pool name as the database name; session, transaction and statement
modes). Transaction mode breaks named prepared statements, and the hub's driver (`psycopg` 3) prepares statements on
its own after a few runs; use it only with `prepare_threshold=None` on the connection (a small hub change, tested on
test) or with PgBouncer's prepared-statement tracking. Until then use session mode on the pool. Migrations connect
directly to the database, not through the pool.

**Read replica.** I found nothing in OVH's PostgreSQL pages about a read-only replica service, and the hub does not
split reads from writes. So the plan does not rely on one: scale up the primary first, use the standby only for
failover, and decide on a replica (a read path in the hub plus a service) only if the load test shows reads, not
writes, as the limit.

**Load test before launch.** On the staging address of section 9: many `maity wait` long-polls, logins, join
exchanges and writes, at a multiple of the expected load, with the hub at 1, 2 and 4 pods. It sets the node pool
maximum, the HPA target, the database flavor and the pool size, and it is where the multi-pod behaviour is proved.

## Sources

- [Available datacenters, worker nodes and persistent storage flavors](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/datacenters-nodes-storage-flavors)
- [Choosing the right Managed Kubernetes plan](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/mks-plans.md)
- [Public Cloud Databases for PostgreSQL: capabilities](https://docs.ovhcloud.com/en/guides/public-cloud/databases/postgresql-capabilities)
- [Automated backups for Public Cloud Databases](https://docs.ovhcloud.com/en/guides/public-cloud/databases/backups)
- [Migrate from Load Balancer for MKS to the Public Cloud Load Balancer](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/migrate-iolb-to-public-cloud-loadbalancer.md)
- [Dynamically resizing a cluster with the cluster autoscaler](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/using-cluster-autoscaler)
- [Connection pools in Public Cloud Databases for PostgreSQL](https://docs.ovhcloud.com/en/guides/public-cloud/databases/postgresql-pool)
- [Getting the source IP behind the LoadBalancer](https://docs.ovhcloud.com/en/guides/public-cloud/containers-orchestration/managed-kubernetes/getting-source-ip-behind-loadbalancer.md)
