"""The line that installs the CLI and joins, in one command (docs/api.md §3.2, "The install line").

The dashboard's join dialog shows it with the real URL and code (`paste_line`, §3.1); the join page
and `/help` show the same shape with placeholders, since neither ever holds a code.
"""

from __future__ import annotations

# pipx puts `maity` into its bin directory, which a shell started before the install often has
# not on its PATH; asking pipx for the directory (`pipx environment`) needs pipx 1.1, and a failed
# `$(…)` on an older one would leave an empty PATH element, the current directory. So the line
# names the two places pipx uses itself.
PIPX_PATH = 'export PATH="$PATH:${PIPX_BIN_DIR:-$HOME/.local/bin}"'
ENSUREPATH = (
    "If `maity` is not found afterwards, run `pipx ensurepath` once and open a new shell; "
    "the line changes no shell profile itself."
)


def command(install: str, url: str, code: str) -> str:
    """`<install line> [&& export PATH=…] && maity join <url> --code <code>`: the PATH step
    only when the install line starts with `pipx `."""
    between = f" && {PIPX_PATH}" if install.startswith("pipx ") else ""
    return f"{install}{between} && maity join {url} --code {code}"
