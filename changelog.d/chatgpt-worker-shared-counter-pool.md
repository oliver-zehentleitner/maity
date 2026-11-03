### Fixed

- Give PostgreSQL rate-limit counters and shared forge budgets a separate bounded connection pool so requests do not compete with their own counter transactions for serving connections. Include the extra connections in the deployment budget.
