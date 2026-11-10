### Fixed

- The chat composer stays inside the viewport on a short phone: when the pane's fixed chrome plus about 24 px of history fits in the window, `--chat-h` no longer floors itself taller than the window (which had pushed the input past the bottom edge so the page had to be scrolled); the message list scrolls. Otherwise (a tall sign-in banner or a group's chrome on a very short screen) the page may still scroll, with the product line below the composer.
