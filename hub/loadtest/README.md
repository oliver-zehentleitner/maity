# Hub load test

The plan, its assumptions and its targets are in `hub/context/replicas.md` cac80c88. Nothing runs
against a hub its operator has not named. `LOADTEST_CONFIRMED_TEST_SYSTEM` names a test system's
host. `maity.team` and every name under it may be production: only `LOADTEST_CONFIRMED_PRODUCTION`
names one, and `run.js` then reaches it through its one public address, never pod by pod.

**State:** `sign.js`, the target check and the seed are checked by `tests/test_loadtest.py`. `run.js`
has passed a syntax check only: it has not run under k6 yet. Start with a small run and expect to
fix it.

## Run

1. Seed where the hub runs, with its own configuration: the hub's `MAITY_PUBLIC_URL` is what the
   name is checked against. Each account is `lt-<n>`, a human without a mail address and without a
   password, with its own project and two agents. The output holds session cookies and signing
   keys: it is created new with mode 0600, never reused, and stays out of the repository.

       LOADTEST_CONFIRMED_TEST_SYSTEM=<host> maity-hub loadtest seed --humans 20000 --out /secure/accounts.json
       # on production instead: LOADTEST_CONFIRMED_PRODUCTION=<host>

   One human for three waits, at the scale of the run. A second seed adds accounts after the last.

2. Run one scenario per generator. `LOADTEST_TARGETS` lists each pod's address when pods can be
   reached one by one, so that a write and its wake-up land on different pods; through a balancer
   alone, the wake-up scenario does not prove that.

       SCENARIO=idle LOADTEST_SCALE=0.25 LOADTEST_GENERATOR=0 LOADTEST_GENERATORS=2 \
       LOADTEST_TARGETS=https://a,https://b LOADTEST_CONFIRMED_TEST_SYSTEM=<host> \
       LOADTEST_ACCOUNTS=/secure/accounts.json k6 run loadtest/run.js

   `LOADTEST_CONFIRMED_TEST_SYSTEM` lists every host of `LOADTEST_TARGETS`, comma separated. On
   production, `LOADTEST_CONFIRMED_PRODUCTION` names its host and `LOADTEST_TARGETS` is its one
   public address.

| `SCENARIO` | Plan | Note |
|---|---|---|
| `idle` | 1 | held waits only |
| `wakeup` | 2 | few writes, so a wake-up's time is the hub's and not a queue's; clocks: run it on one generator |
| `mixed` | 3 | writes and reads at the assumed peak beside the waits |
| `limits` | 4 | login burst and one request replayed on every pod for 280 s; restart the database and fail it over during it. The join exchange burst is not in yet |
| `mixed` plus an operator | 5 | kill a pod, then a `RollingUpdate`; a threshold fails on the kill's errors, read them against the 10 s of the plan |

## Afterwards

Delete the accounts where the hub runs, with the same name confirmed as for the seed. Without
`--apply` it only counts, per table, what it would delete:

    LOADTEST_CONFIRMED_TEST_SYSTEM=<host> maity-hub loadtest purge
    LOADTEST_CONFIRMED_TEST_SYSTEM=<host> maity-hub loadtest purge --apply

It deletes every row of the `lt-<n>` accounts in every table, their keys included, so the output
file of the seed is worthless afterwards; delete it too. It refuses when an account shares a project
or a row with anyone else.

## Read on the server, not by k6

Memory, CPU and connections per pod; on PostgreSQL `pg_stat_activity` (connections against the
limit), `pg_notification_queue_usage()`, the commit time of notifying writes and reads per second
while idle; the probe's and the image refresh's forge reads per interval at 1, 2 and 4 pods.

## Generators

Own machines, not the cluster that is measured and not the CI runners. One source address has about
64 000 ports, so several generators with their own addresses carry the 60 000 waits. The number per
generator, its memory and its `ulimit -n` come from the first small run; none is measured yet.
