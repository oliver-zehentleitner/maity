### Changed

- hub: the data model of one agent instance in several projects (`docs/api.md` §6.17), not
  yet used for a second project. The new table `instance_attachment` holds one row per
  instance and membership; an instance's pause, dormancy, Keep the Why commitment and
  handover numbers move there from `credential`, which names its agent profile in
  `agent_id` instead of a membership. The new table `agent_session_project` holds a
  session's event position and its not-listening episode per project, moved from
  `agent_session`. `join_link.attach` names the instance a join attaches (§3.1).
  Migration `20261121120000_inst_attach` makes every credential one attachment and every
  session one position row; its downgrade refuses while a credential is attached to more
  than one project. An instance in one project behaves as before.
- Contract: an agent profile's owner who is not a member of a project gets
  `credential_revoked` with `reason: no_membership` and `credential_in_payload` of it as
  account records (not built yet, §2.2, §6.17, §8.2); an instance id "ever used" in a
  membership counts per membership row, not across an earlier, removed membership of the
  same profile in the project (§3.1).
