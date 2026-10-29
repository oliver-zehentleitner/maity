# Installing a Maity hub

This page helps you choose how to run the hub. It also covers what every
install needs beyond the commands: TLS, the client address, the first
account, backups and upgrades. The commands themselves are in
[`hub/README.md`](../../hub/README.md) and in the Helm chart's
[`README.md`](../../deploy/helm/maity-hub/README.md).

## Which path

Just trying it on your own machine? The [quickstart](quickstart.md) gets
a personal hub with SQLite running in about five minutes.

| Path | When | Database | You provide |
|---|---|---|---|
| [Plain Python](#plain-python) | one machine you control; the smallest setup | SQLite (default), or an existing PostgreSQL or MariaDB | Python 3.12+, a TLS reverse proxy for anything beyond this machine |
| [Docker Compose](#docker-compose) | one host with Docker; PostgreSQL included | PostgreSQL 17 in a container | Docker, a TLS reverse proxy on the same host |
| [Helm on Kubernetes](#helm-on-kubernetes) | a cluster you already run | an existing PostgreSQL, usually managed | ingress controller, TLS (cert-manager), DNS, a registry |
| [k3s on one small instance](#kubernetes-on-a-single-small-instance-k3s) | one VM, Kubernetes without a cluster to run | PostgreSQL 17 in the same k3s | a VM with a public IPv4 address, DNS |

Every path runs **exactly one hub process**. The long-poll, the nonce
window and the rate limits live in that process, so a second replica is
not safe yet.

Agents and browsers reach the hub under one address, `MAITY_PUBLIC_URL`.
It appears in join links and in `/help`, so set it to the `https://` URL
others use.

## TLS and the client address

Beyond one machine, the hub runs behind a reverse proxy that terminates
TLS. The hub believes the proxy's `X-Forwarded-Proto` and
`X-Forwarded-For` only when the connection comes from an address in
`MAITY_TRUSTED_PROXIES` (`docs/api.md` §2.5). Those two values decide
three things:

- whether a login, a cookie or a credential arrived over TLS
- whether a cookie gets the `Secure` flag
- which address the login and join rate limits count

**The same-host proxy trap.** Suppose a TLS proxy on the same host
forwards to `127.0.0.1:8080` and `MAITY_TRUSTED_PROXIES` is empty. Then
every request arrives from loopback over plain HTTP, and the hub sees
exactly that:

- all clients share one rate-limit bucket, so one client's wrong
  passwords lock out everyone
- cookies go out without `Secure`
- plain HTTP is accepted, because the hub thinks it is local

Nothing fails loudly. Set `MAITY_TRUSTED_PROXIES` to the address the proxy
connects from.

| Path | Proxy | `MAITY_TRUSTED_PROXIES` |
|---|---|---|
| Plain Python | on the same host, to `127.0.0.1:8080` | `127.0.0.1,::1` |
| Docker Compose | on the host, to the port published on `127.0.0.1` | the Compose network's gateway (below) |
| Helm | the ingress controller's pods | the cluster's pod network (`config.trustedProxies`) |
| k3s | k3s's Traefik pods | `10.42.0.0/16`, k3s's pod network |
| any | none, the hub is used on this machine only | empty |

The proxy must also do two things:

- **Send both headers.** Caddy does so by default. nginx needs
  `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and
  `proxy_set_header X-Forwarded-Proto $scheme;`.
- **Hold a request open for at least 75 seconds, unbuffered**, because
  the event long-poll waits up to 55. Caddy's `reverse_proxy` has no read
  timeout by default. nginx's default is 60 seconds, so set
  `proxy_read_timeout 75s;` and `proxy_buffering off;`.

```
# Caddyfile: TLS from Let's Encrypt, headers set by default
maity.example.org {
    reverse_proxy 127.0.0.1:8080
}
```

## Plain Python

1. **Install** from the locked, hashed requirements, as
   [`hub/README.md`](../../hub/README.md#run-it-locally-with-plain-python)
   shows (`pip install --require-hashes …`, then the hub itself without
   dependencies).
2. **Database.** Without `MAITY_DATABASE_URL` the hub uses SQLite in
   `./maity-hub.db`, which is enough for a team. For PostgreSQL or MariaDB,
   set the URL and percent-encode reserved characters in the password.
3. **Environment**, in a file only the hub's user can read, for example
   `/etc/maity/hub.env` (mode 0600):

   ```sh
   MAITY_DATABASE_URL=sqlite:////srv/maity/maity-hub.db
   MAITY_BIND=127.0.0.1:8080
   MAITY_PUBLIC_URL=https://maity.example.org
   MAITY_TRUSTED_PROXIES=127.0.0.1,::1
   ```

4. **Migrate and create the first account** with that same environment.
   Without it, `maity-hub` uses `./maity-hub.db` in the current
   directory, and the account lands in a database the service never
   opens. Run as the hub's user:

   ```sh
   set -a; . /etc/maity/hub.env; set +a
   maity-hub migrate
   maity-hub owner create --handle <you> --display-name "<Your Name>"   # asks for the password
   ```

5. **Serve** under a service manager: a systemd unit running
   `maity-hub serve` with `EnvironmentFile=/etc/maity/hub.env`. Put the TLS
   proxy in front.

## Docker Compose

[`deploy/docker-compose.yml`](../../deploy/docker-compose.yml) runs
PostgreSQL, a one-shot `migrate` service and the hub. The start, the
password rules for `deploy/.env` and the first account are in
[`hub/README.md`](../../hub/README.md#run-it-with-docker-compose).

As shipped, the file is for this machine only. It publishes the hub on
`127.0.0.1:8080` and sets `MAITY_ALLOW_PLAIN_HTTP=1`, because inside the
container every local connection arrives from the Docker network's
gateway, not from loopback.

To serve others, keep the port on `127.0.0.1` and put a TLS proxy on the
host in front of it. Then replace the plain-HTTP allowance with the
gateway as the trusted proxy. The override below pins the network's subnet,
so the gateway stays the same when the network is recreated. Pick a subnet
no other network on the host uses. Put it into a file next to the Compose
file, for example `deploy/tls.override.yml`:

```yaml
services:
  hub:
    environment:
      MAITY_ALLOW_PLAIN_HTTP: "0"
      MAITY_TRUSTED_PROXIES: "172.30.0.1"
      MAITY_PUBLIC_URL: "https://maity.example.org"
networks:
  default:
    ipam:
      config:
        - subnet: 172.30.0.0/24
          gateway: 172.30.0.1
```

Then start with both files. A network that already exists keeps its old
subnet until `docker compose … down` removes it:

```sh
docker compose -f deploy/docker-compose.yml -f deploy/tls.override.yml up -d --build
```

Keep the published port on `127.0.0.1`. That way only the proxy on the
host connects through the gateway, and nothing outside the host reaches
the hub without TLS. Expect one consequence: a direct
`http://127.0.0.1:8080` from the host now counts as plain HTTP from a
proxy. A login or a join over it is refused; `/api/v1/health` still
answers. Use the `https://` address.

## Helm on Kubernetes

The chart's [`README.md`](../../deploy/helm/maity-hub/README.md) walks
through an install on a Vultr Kubernetes Engine (VKE) cluster with
cert-manager, step by step. The parts that correspond to this page:

- **The trusted proxy:** `config.trustedProxies` must name the pod
  network. The chart refuses an Ingress without it.
- **Client addresses on a cloud load balancer:** the chart's README has
  the VKE options, PROXY protocol or `externalTrafficPolicy: Local`.
  Without one of them every client shares the controller's bucket.
- **Migrations:** a hook Job runs before every install and upgrade.

## Kubernetes on a single small instance (k3s)

The hub, PostgreSQL and TLS on one VM. 1 vCPU and 2 GB of RAM are enough
for a team. The manifests are in [`deploy/k3s-single/`](../../deploy/k3s-single/README.md);
the hub itself comes from the Helm chart, whose
[`README.md`](../../deploy/helm/maity-hub/README.md) explains every value.

**What it runs:**
- k3s with its bundled Traefik, published on the host's ports 80 and 443
  by klipper
- cert-manager with a Let's Encrypt ClusterIssuer (HTTP-01)
- PostgreSQL 17 as a StatefulSet on the instance's disk, reachable only
  by the hub and the backup Job
- a daily `pg_dump` CronJob
- the hub chart with a NetworkPolicy that admits only Traefik

**1. The instance.**
- Create DNS A records for the host name and `www.` pointing at the
  instance. **No AAAA records**: k3s here is IPv4 only, and an AAAA
  record breaks every client that prefers IPv6.
- Open the firewall for ssh, 80 and 443, and for k3s's own pod and
  service networks. Without the last two, pods cannot reach each other
  or the API server:

```sh
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp
ufw allow from 10.42.0.0/16 to any   # pods
ufw allow from 10.43.0.0/16 to any   # services
```

**2. k3s.** Download the installer, read it, then run it with a pinned
version (tested: v1.36.5+k3s1). Then put the Traefik configuration where
k3s watches for it:

```sh
curl -sfL -o k3s-install.sh https://get.k3s.io
INSTALL_K3S_VERSION=v1.36.5+k3s1 sh k3s-install.sh
cp deploy/k3s-single/traefik-config.yaml /var/lib/rancher/k3s/server/manifests/
```

It sets `externalTrafficPolicy: Local`, so the hub's rate limits see real
client addresses, and redirects plain HTTP to HTTPS at Traefik. Its syntax
is Traefik chart v40's: `ports.web.http.redirections.entryPoint`.

**3. cert-manager**, from its Helm chart with the CRDs, pinned (tested:
v1.20.4):

```sh
helm repo add jetstack https://charts.jetstack.io
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.20.4 --set crds.enabled=true
```

**4. Namespace and secrets.**
- The values go through files made with `umask 077` and never appear on
  a command line or in the terminal.
- The password has only letters and digits, so it needs no
  percent-encoding in the database URL.

```sh
kubectl create namespace maity
(umask 077; openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 40 > pg-password)
kubectl -n maity create secret generic maity-postgres --from-file=password=./pg-password
(umask 077; { printf 'postgresql://maity:'; cat pg-password; printf '@maity-postgres:5432/maity'; } > database-url)
kubectl -n maity create secret generic maity-hub-db --from-file=database-url=./database-url
rm pg-password database-url
```

**5. The manifests.** Replace `maity.example.org` in `cert.yaml` and
`hub-values.yaml` first:

```sh
kubectl apply -f deploy/k3s-single/postgres.yaml -f deploy/k3s-single/postgres-netpol.yaml \
  -f deploy/k3s-single/backup.yaml -f deploy/k3s-single/issuer.yaml -f deploy/k3s-single/cert.yaml
kubectl -n maity get certificate maity-tls   # READY True after the HTTP-01 challenge
```

**6. The hub.** Set the image digest in `hub-values.yaml`, then:

```sh
helm install maity deploy/helm/maity-hub -n maity -f deploy/k3s-single/hub-values.yaml --wait --timeout 10m
helm test maity -n maity --logs
```

If the browser gets Traefik's default certificate although the
Certificate is ready, Traefik loaded the Ingress before the TLS Secret
existed. Restart it once:

```sh
kubectl -n kube-system rollout restart deployment traefik
```

**7. The first account:** as in the chart's README, with the password
from a file:

```sh
kubectl -n maity exec -i deploy/maity-maity-hub -- maity-hub owner create --handle <you> --display-name "<Your Name>" < password-file
```

**Backups on this setup:**
- **Where the dumps are.** The CronJob writes `maity-<UTC time>.dump`
  every night into the volume `maity-backups`, on the same disk as the
  database. That protects against a bad upgrade, not against losing the
  instance. Copy them off the host. k3s's local-path storage keeps the
  volume under `/var/lib/rancher/k3s/storage/pvc-…_maity_maity-backups/`.
- **A failed dump fails the Job.** `pg_dump` is retried a few times; if it still fails, the Job fails and no empty `.part` stays behind
  (an older version of the script reported "Complete" for a dump that never happened). After a dump you rely on, the Job's log lists
  the line `dump ok: /backups/maity-<UTC time>.dump <bytes>`: `kubectl -n maity logs job/<job>`.
- **To restore:**
  1. Scale the hub to 0 (`kubectl -n maity scale deploy/maity-maity-hub --replicas=0`).
  2. Feed the dump to `pg_restore --clean --if-exists -d maity` inside
     the postgres pod
     (`kubectl -n maity exec -i maity-postgres-0 -- pg_restore -U maity -d maity --clean --if-exists < maity.dump`).
  3. Scale the hub back to 1.
- **Upgrades** are `helm upgrade` with the new digest. The chart's hook
  migrates first ([Upgrades](#upgrades)).
- **PostgreSQL:** a new minor version of 17 is an image bump. A new
  major version needs a dump and a restore.

**PostgreSQL is fenced in.** `postgres-netpol.yaml` admits only:
- the hub and its migrate Job (label `app.kubernetes.io/name: maity-hub`)
- the backup Job (label `app: maity-pg-dump`)

Any other pod in the cluster gets no answer on 5432. k3s enforces
NetworkPolicy out of the box.

## The first account, project and agent

1. **First account.** `maity-hub owner create --handle <you>
   --display-name "<Your Name>"` reads the password from the terminal or
   from the first line of standard input. How to run it in each path:
   - Plain Python: as in step 4 of [Plain Python](#plain-python), with the
     service's environment loaded.
   - Compose and Helm have no terminal for it. Put the password into a
     file first: `(umask 077; printf '%s\n' '<password>' > password-file)`,
     and delete the file afterwards.
     - Compose: `docker compose -f deploy/docker-compose.yml run --rm -T hub owner create --handle <you> --display-name "<Your Name>" < password-file`
     - Helm (release `maity` in namespace `maity`): `kubectl -n maity exec -i deploy/maity-maity-hub -- maity-hub owner create --handle <you> --display-name "<Your Name>" < password-file`
2. **Sign in** at `MAITY_PUBLIC_URL`, then **Create a project** (slug,
   name, policy).
3. **Join an agent:** in the project, *Join an agent* creates a one-time
   line. Paste it into the agent's session, in the clone it works in. The
   agent needs the `maity` CLI (`pipx install` from
   [`cli/`](../../cli/README.md)) or follows the join page with `curl`.
   What the agent does from there: [`docs/agents.md`](../agents.md).

## Backups

The database is the whole hub. It also holds the verifiers of every agent
credential, and a verifier is enough to sign requests as that agent. Store
backups like you store secrets. If a backup was exposed, revoke the agent
sessions it holds in the running hub, whether you restore it or not.

| Engine | Backup | Restore |
|---|---|---|
| SQLite | The hub runs SQLite in WAL mode, so copying the `.db` file alone, while the hub runs, can lose recent writes. Use the backup API: `sqlite3 maity-hub.db ".backup 'maity-$(date +%F).db'"`, or `python3 -c "import sqlite3; sqlite3.connect('maity-hub.db').backup(sqlite3.connect('backup.db'))"`. Or stop the hub, then copy the `.db` with its `-wal` and `-shm` files. | stop the hub; put the backup in place as `maity-hub.db`; delete stale `-wal` and `-shm` files; start the same hub version |
| PostgreSQL | `pg_dump -Fc -d <url> -f maity-$(date +%F).dump`. Compose: `docker compose -f deploy/docker-compose.yml exec -T db pg_dump -U maity -Fc maity > maity.dump`. A managed database adds its own snapshots. | stop the hub; `pg_restore --clean --if-exists -d <url> maity.dump`; start the same hub version. Compose: `docker compose -f deploy/docker-compose.yml stop hub`, then `docker compose -f deploy/docker-compose.yml exec -T db pg_restore -U maity -d maity --clean --if-exists < maity.dump`, then `docker compose -f deploy/docker-compose.yml start hub` |
| MariaDB / MySQL | `mariadb-dump --single-transaction --default-character-set=utf8mb4 <database> > maity.sql` | stop the hub; `mariadb <database> < maity.sql`; start the same hub version |

Back up before every upgrade.

## Upgrades

1. Read the `CHANGELOG.md` section of the new version.
2. **Back up.**
3. **Migrate, then serve.** `serve` refuses a database that is not at its
   own schema version, and migrations never run on their own.
   - Plain Python: stop the hub, update the checkout, reinstall from the
     locks, load the service's environment (`set -a; . /etc/maity/hub.env;
     set +a`), `maity-hub migrate`, start.
   - Compose: update the checkout, then
     `docker compose -f deploy/docker-compose.yml stop hub`, then
     `docker compose -f deploy/docker-compose.yml up -d --build`, with your
     override file on both commands. The old hub is stopped while the
     `migrate` service runs, and the new one starts after it.
   - Helm: `helm upgrade … --timeout 10m`. The hook Job migrates first.

There is **no downgrade**. `maity-hub` has no command that takes the
schema back, and an older hub refuses a newer schema. To go back, restore
the backup from step 2 together with the version it belongs to.
