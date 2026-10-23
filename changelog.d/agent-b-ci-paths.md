### Changed

- ci: a pull request runs only the suites its changed paths can affect (hub, image,
  join smoke, dashboard, browser test, CLI, Helm chart; the changelog check always), a
  new push cancels the pull request's older run, main runs everything on every merge,
  and `ci-ok` is the one aggregate check to require
