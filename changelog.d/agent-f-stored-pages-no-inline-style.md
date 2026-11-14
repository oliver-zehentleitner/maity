### Fixed

- hub: a project's public page draws its "Cards done per day" bars again, and a person
  without a picture gets the placeholder at its size: both were inline styles that the app
  shell's policy refused where a visitor reads the page. The bars are now an SVG sized by its
  attributes, the placeholder a class of the page's stylesheet; no stored page carries an
  inline style, and the end-to-end run listens for policy refusals on every stored page.
