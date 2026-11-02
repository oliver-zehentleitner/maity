### Fixed

- Public pages count a pull request from a forge link only when the event names the instance's token and
  the repository's last check found it public, as the contract says (§11.4). A public project read
  only through an App or an owner's token shows no merged pull requests there.
