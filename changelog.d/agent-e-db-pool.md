### Changed

- hub: server-database connections are kept and reused (pool 16 + 16 overflow, most recently used first, replaced after 30 minutes, `MAITY_DB_POOL_RECYCLE`), and a connect that fails because the host name does not resolve is tried once more after a short pause; fewer `database_unavailable` answers when the cluster's DNS answers in bursts
