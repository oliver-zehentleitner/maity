### Fixed

- Public pages count a pull request from a forge link only when the instance's token read it and
  the repository's last check found it public, as the contract says (§11.4). A public project read
  only through an App or an owner's token shows no merged pull requests there.
