### Changed

- docs/api.md §6.26: an organisation's invitation item carries no request id and keeps the handle as
  typed, revoked by its own `id`; invitations for the role `owner` are revoked by owners only; owner
  and project changes of an organisation run under the lock on its row; an owner of both
  organisations keeps their membership through an organisation-to-organisation transfer; a new owner
  joins archived projects too; a suspension names the archived projects; §2.9: the export's forge
  links name `forge` and `status`; context/projects.md: the organisations decision gains its
  revisit point, the reasons and rejected alternatives of its details
