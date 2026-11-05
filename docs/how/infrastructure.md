# The infrastructure

You should know what you'd run and trust before you run it. This page is about the program you run when you host Maity yourself: the hub, where it keeps data, and what it does while nobody is asking.

## The hub

You should be able to see what you would run. The hub is one Python program, and by default it is one process.

![The hub inside: one maity-hub process with the API, the dashboard and background passes, a database (SQLite by default, PostgreSQL or MariaDB), attachments in a directory or an S3-compatible store, and optional extra copies that need PostgreSQL and attachments outside a local directory.](../img/how-hub-inside.png)

**How it works.** The command is `maity-hub`. That process serves the API under `/api/v1` and the dashboard, the web pages, from the same process. The dashboard is a set of files the process serves. If the usual directory for those files is missing, the API still runs. A directory you name yourself, when that directory is missing, stops the hub. Several processes on one machine need PostgreSQL. Extra copies of the hub need PostgreSQL too, and attachments outside a local directory: an S3-compatible store, or attachments left off. Agents and browsers reach the hub under one address.

**An example.** On one machine, `maity-hub quickstart` creates a database file and an account, then serves. Its last line is the address of the dashboard. The same process answers the API.

## Databases

You can start with a file on one machine. The same hub also runs against a database server a team already operates.

**How it works.** The hub describes its tables with SQLAlchemy Core and no ORM. SQLAlchemy is the Python library it uses to talk to the database. Core means the statements are written out, and an ORM (an object-relational mapper) would turn objects into statements on its own. The same statements run on every engine the hub supports. Changes to the shape of the database are revisions applied by Alembic. `maity-hub serve` never migrates, and it refuses a schema that isn't at the revision this version expects. Migrations run through `maity-hub migrate`, the Compose service or the Helm job, and `maity-hub quickstart` migrates a new SQLite file that has no tables yet.

SQLite, a database in one file, is the default. The file is `maity-hub.db`, and the install guide says that file is enough for a team. The plain Python install can use that file, or an existing PostgreSQL or MariaDB. Docker Compose includes PostgreSQL 17. The Helm chart on Kubernetes expects a PostgreSQL you already run, and the chart does not install a database. The backup section of the install guide also covers MySQL.

**An example.** The [quickstart](../install/quickstart.md) uses the SQLite file in the directory you start from, and on a new file it migrates that file itself. A Docker Compose install uses the PostgreSQL container that Compose starts, and a one-shot service migrates before the hub serves.

## Background work

A few things should happen even when nobody is clicking: a hold that has gone quiet should be noticed, waiting mail should go out, and a merged pull request should be announced.

**How it works.** The hub runs these as background passes inside its own process. One pass, every minute, notices claims whose time limit has passed and says so. It does not take the card away. Another pass sends mail that is waiting to go out. Another, every two minutes, looks for pull requests merged into the default branch of a connected repository and, when that project's ticker is on, announces them. The passes run in every copy of the hub. Several copies are a PostgreSQL setup. There, each pass is claimed first, and the first copy to claim it is the one that runs it.

**An example.** An agent stops answering while it holds a card. The next minute's pass reports claims whose time limit has passed. The card stays with the agent until the agent gives it back, someone takes it over, an admin or the holder's manager hands it on once its time limit has passed, or the card is closed. A takeover can move the card while the limit still runs.

## Waking an agent

An agent should wake at the moment something is for it.

**How it works.** `maity wait` holds one open request to the hub, for up to 55 seconds at a time, and repeats that until an event arrives or the time you set runs out. The hub answers as soon as a relevant event is written, or when the wait ends. When several copies share PostgreSQL, the copy that wrote the change notifies the others, so a wait on another copy wakes too. A hub that is stopping answers its open waits at once, with whatever it already has, so a shutdown is not held open by them.

**An example.** The agent has finished a step and runs `maity wait`. You answer its question in the inbox. The open request returns with that event, and the agent continues.

## Where your data lives

You should know which store holds what, and how you take your own data with you.

**How it works.** The database holds the hub's records: accounts, projects, cards, messages, and the details of each file, such as its name and size. The files on messages, called attachments, are not in the database. On the default store, attachments are off until you name a directory for them; then the bytes are files there. You can instead point the hub at an S3-compatible store, which needs no directory, and it keeps the bytes there. The browser and the agent only ever talk to the hub, which reads the file and serves it.

A person can download their own data as one JSON document. When a second factor is on, the download asks for it first. The file leaves out secrets: password hashes, session cookies, credentials, and the secret and recovery codes of a second factor. Deleting an account takes two steps ([export and account deletion](../api.md#29-human-your-own-data--export-and-account-deletion)). You ask while signed in. An account with a password gives that password again within the last 10 minutes, and you type your handle. When a second factor is on, that code is given again within the last 10 minutes. An account without a password needs a session in good standing that is at least 24 hours old. If the hub cannot send mail, or the account has no verified address, the request is refused. The hub then mails a single-use link valid for 24 hours, and the page that link opens asks once more before the account is deleted in one go. Sessions and memberships end, the person's own details are removed, and every agent profile the account owns is deleted, while messages, cards and the rest of a project's record stay and show that person as "Deleted account", and the handle stays reserved. Nothing is deleted, and the page says which, when a project in that person's name is not archived, when they are the last owner of an organisation, or when they are the instance's last admin. Those already stop the request, and they stop the confirmation if they become true before it.

**An example.** A teammate attaches a screenshot to a message. The database stores its name and size. The bytes sit in the directory you set for attachments, or in the bucket if you chose the S3-compatible store. Later they download their data from their account, then delete the account. The screenshot stays on the message, shown as from "Deleted account".

## The Helm chart

If you already run Kubernetes, the chart is how you install the hub there.

**How it works.** The chart installs a job that runs `maity-hub migrate` before each install and each upgrade, a deployment of the hub, a service, an optional ingress, and a network policy that is on by default. It creates a service account with no token for the Kubernetes API, and the hub never calls that API. It does not create secrets, and it does not install a database. You create the secrets in the namespace yourself, including the database address, and the chart only refers to them. It expects a PostgreSQL you already run.

**An example.** You put the database address in a secret, install the chart, and the migration job finishes before the hub pod serves. An upgrade does the same: migrate first, then the new pod.

## Running it yourself

Maity is open source, under the MIT licence, and the same code runs on a machine of yours.

**How it works.** [Installing a hub](../install/README.md) names the paths:

- The [quickstart](../install/quickstart.md) is a personal hub with SQLite, on one machine, in about five minutes. It listens on this machine only, with no mail and no TLS.
- Plain Python is one machine you control. SQLite is the default, or you point it at an existing PostgreSQL or MariaDB. Anyone connecting from another machine needs a TLS proxy in front.
- Docker Compose is one host with Docker. It includes PostgreSQL 17 and the hub.
- Helm is a cluster you already run, against an existing PostgreSQL.
- Kubernetes on a single small instance uses k3s. The manifests live in [`deploy/k3s-single`](../../deploy/k3s-single/README.md), and the walkthrough is in the install guide.

The install guide also covers the proxy, backups and upgrades.

**An example.** You follow the quickstart on a laptop and open the dashboard on this machine. When other people need to reach the hub, you use one of the other paths and put TLS in front. The hub program is the same one.

## Security

You can read, area by area, what the hub protects and what it can still see.

**How it works.** A person signs in with a session cookie. A change sent with that cookie also carries a second token, checked against the session, so another site cannot submit the form. An agent does not use that cookie. It has its own credential, held in a file by the CLI on the machine where the agent runs, and the CLI signs each request. [The tools](tools.md) says where that file lives.

A person can add a second factor: a time-based code from an authenticator app, plus recovery codes for when the app is lost. Once it is on, every new sign-in asks for it, and a few sensitive actions ask again. An instance can instead make a code sent by mail the second factor for people who have not enrolled an authenticator app.

What a member may do comes from two settings on their membership. Trust is how far the project trusts them. Role is the work they do. The two together grant the rights each action checks. A guest can read and comment, whatever the role.

Connections that cross a public network are encrypted. A login, a cookie or a credential sent over plain HTTP is refused, except from this machine itself. You can allow plain HTTP for a hub that stays on one machine or a private network. The install guide tells you to remove that allowance from anything public. The short hop from a TLS proxy to the hub can stay plain, because the proxy is what faces the network. The CLI refuses a plain HTTP address except for a hub on this machine. The hub can still read the content, because the dashboard and the notifications work on it.

The connection to the database is separate. The hub sets no encryption on it. PostgreSQL and MariaDB are encrypted when the URL asks for it. For PostgreSQL, `sslmode=require` encrypts and does not check the server's certificate, and `sslmode=verify-full` checks it, as the [Helm chart](../../deploy/helm/maity-hub/README.md) shows. With no `sslmode`, PostgreSQL's driver may still try encryption and fall back to plain. Without encryption settings in the URL, MariaDB's driver tries encryption and falls back to plain, the same as PostgreSQL with no `sslmode`. The hub itself sets nothing for that. Requiring encryption, or checking the certificate, is up to the connection settings: the URL, and for PostgreSQL also the environment of libpq, the client library its driver uses, such as `PGSSLMODE`.

A human who administers memberships can isolate an agent. While it is isolated, its calls are refused, apart from the calls that tell it why, and the project's events do not reach it. Lifting the isolation restores its access.

When the hub fetches from an address that came from data, such as a published Keep the Why export, it checks that address and refuses one that is not on the public internet.

People can report a profile, a project, a message or a card. The report goes to the instance's admin.

**An example.** You sign in. The browser holds the session cookie, and the dashboard sends the second token with every change. Your agent never sees that cookie: the CLI signs the agent's requests with the credential in its file. You turn on an authenticator app, and the next sign-in asks for the code.
