### Fixed

- The chat composer stays inside the viewport on a short phone: when the pane's fixed chrome fits in the window, `--chat-h` no longer floors itself taller than the window (which had pushed the input past the bottom edge so the page had to be scrolled). The message list still scrolls; with a tall sign-in banner on a very short screen the page may still scroll so the product line stays below the composer.
