### Added

- docs: §11.4 forge access per owner. A project's repository is read with the namespace owner's GitHub App installation, then the owner's own token, then the instance token for public repositories only. Linking an installation checks with the installing user's OAuth authorisation that they can access it. New `/me/forge` endpoints, `probe_via` on the repository, `forge_access_changed` account records, step-up for linking and storing a token.
