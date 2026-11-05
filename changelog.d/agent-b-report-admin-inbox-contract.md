### Changed

- docs/api.md §16.8, §7, §18: a new abuse report reaches the instance admin as a personal request
  without a project (`filed_by: hub`, `report: {id, reason, type}`, no replies), listed in the
  personal inbox and mailed by the `inbox` mode; it cannot be answered (`resolve_the_report`, 409)
  and the hub withdraws it when the report is resolved or expires. The account record `report_open`
  is gone. The affected account is told as before.
