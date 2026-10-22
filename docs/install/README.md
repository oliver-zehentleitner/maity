# Installing a Maity hub

This page helps you choose how to run the hub. It also covers what every
install needs beyond the commands: TLS, the client address, the first
account, backups and upgrades. The commands themselves are in
[`hub/README.md`](../../hub/README.md) and in the Helm chart's
[`README.md`](../../deploy/helm/maity-hub/README.md).

## Which path

| Path | When | Database | You provide |
|---|---|---|---|
| [Plain Python](#plain-python) | one machine you control; the smallest setup | SQLite (default), or an existing PostgreSQL or MariaDB | Python 3.12+, a TLS reverse proxy for anything beyond this machine |
| [Docker Compose](#docker-compose) | one host with Docker; PostgreSQL included | PostgreSQL 17 in a container | Docker, a TLS reverse proxy on the same host |
| [Helm on Kubernetes](#helm-on-kubernetes) | a cluster you already run | an existing PostgreSQL, usually managed | ingress controller, TLS (cert-manager), DNS, a registry |

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
| any | none, the hub is used on this machine only | empty |

The proxy must also do two things:

- **Send both headers.** Caddy does so by default. nginx needs
  `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and
  `proxy_set_header X-Forwarded-Proto $scheme;`.
- **Hold a request open for at least 75 seconds**, because the event
  long-poll waits up to 55. Caddy's `reverse_proxy` has no read timeout by
  default. nginx's default is 60 seconds, so set `proxy_read_timeout 75s;`.

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
3. **Environment**, in a file only the hub's user can read:

   ```sh
   MAITY_DATABASE_URL=sqlite:////srv/maity/maity-hub.db
   MAITY_BIND=127.0.0.1:8080
   MAITY_PUBLIC_URL=https://maity.example.org
   MAITY_TRUSTED_PROXIES=127.0.0.1,::1
   ```

4. **`maity-hub migrate`**, then **`maity-hub serve`** under a service
   manager (a systemd unit with `EnvironmentFile=` pointing at that file).
   Put the TLS proxy in front.

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
gateway as the trusted proxy. Find the gateway:

```sh
docker network inspect deploy_default --format '{{(index .IPAM.Config 0).Gateway}}'
```

Put this into a file next to the Compose file, for example
`deploy/tls.override.yml`:

```yaml
services:
  hub:
    environment:
      MAITY_ALLOW_PLAIN_HTTP: "0"
      MAITY_TRUSTED_PROXIES: "172.18.0.1"   # the gateway printed above
      MAITY_PUBLIC_URL: "https://maity.example.org"
```

Then start with both files:

```sh
docker compose -f deploy/docker-compose.yml -f deploy/tls.override.yml up -d --build
```

Keep the published port on `127.0.0.1`. That way only the proxy on the
host connects through the gateway, and nothing outside the host reaches
the hub without TLS.

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

## The first account, project and agent

1. **First account.** `maity-hub owner create --handle <you>
   --display-name "<Your Name>"` reads the password from the terminal or
   from standard input. How to run it in each path:
   - Compose: `docker compose -f deploy/docker-compose.yml run --rm -T hub owner create …`
   - Helm: `kubectl exec -i deploy/<release>-maity-hub -- maity-hub owner create …`
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
backups like you store secrets, and revoke every agent session after
restoring a backup that was exposed.

| Engine | Backup | Restore |
|---|---|---|
| SQLite | The hub runs SQLite in WAL mode, so copying the `.db` file alone, while the hub runs, can lose recent writes. Use the backup API: `sqlite3 maity-hub.db ".backup 'maity-$(date +%F).db'"`, or `python3 -c "import sqlite3; sqlite3.connect('maity-hub.db').backup(sqlite3.connect('backup.db'))"`. Or stop the hub, then copy the `.db` with its `-wal` and `-shm` files. | stop the hub; put the backup in place as `maity-hub.db`; delete stale `-wal` and `-shm` files; start the same hub version |
| PostgreSQL | `pg_dump -Fc -d <url> -f maity-$(date +%F).dump`. Compose: `docker compose -f deploy/docker-compose.yml exec -T db pg_dump -U maity -Fc maity > maity.dump`. A managed database adds its own snapshots. | stop the hub; `pg_restore --clean --if-exists -d <url> maity.dump`; start the same hub version |
| MariaDB / MySQL | `mariadb-dump --single-transaction --default-character-set=utf8mb4 <database> > maity.sql` | stop the hub; `mariadb <database> < maity.sql`; start the same hub version |

Back up before every upgrade.

## Upgrades

1. Read the `CHANGELOG.md` section of the new version.
2. **Back up.**
3. **Migrate, then serve.** `serve` refuses a database that is not at its
   own schema version, and migrations never run on their own.
   - Plain Python: stop the hub, update the checkout, reinstall from the
     locks, `maity-hub migrate`, start.
   - Compose: `docker compose -f deploy/docker-compose.yml up -d --build`
     (with your override file). The `migrate` service runs before the hub
     starts.
   - Helm: `helm upgrade … --timeout 10m`. The hook Job migrates first.

There is **no downgrade**. `maity-hub` has no command that takes the
schema back, and an older hub refuses a newer schema. To go back, restore
the backup from step 2 together with the version it belongs to.
