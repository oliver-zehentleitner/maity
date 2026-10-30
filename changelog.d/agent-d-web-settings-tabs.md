### Changed

- Dashboard: a project has one **Settings** view with two tabs (§16.11, #741): **Project** for a member
  with `project:admin`, and **Mine** at `/<owner>/<slug>/settings/mine` for every human member, one's
  own settings for the project. A member without `project:admin` who opens Settings gets Mine.

### Removed

- Dashboard: the **My settings** tab and its path `/<owner>/<slug>/my-settings`, without a redirect.
