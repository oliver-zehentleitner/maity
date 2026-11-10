### Fixed

- hub: accepting an address-bound invitation reads the account's verified address (§18.4) instead of a stub that always answered none, so the invited person can accept; a different, pending or missing address is still `invitation_address_mismatch`
