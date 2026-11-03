"""The line that installs the CLI if it is missing and joins (docs/api.md §3.2, "The install line").

The dashboard's join dialog shows it with the real URL and code (`paste_lines`, §3.1); the join page
and `/help` show the POSIX shape with placeholders, since neither ever holds a code.
"""

from __future__ import annotations

import re

# pipx puts `maity` into its bin directory, which a shell started before the install often has
# not on its PATH; asking pipx for the directory (`pipx environment`) needs pipx 1.1, and a failed
# `$(…)` on an older one would leave an empty PATH element, the current directory. So the line
# names the two places pipx uses itself.
PIPX_PATH = 'export PATH="$PATH:${PIPX_BIN_DIR:-$HOME/.local/bin}"'
PIPX_PATH_POWERSHELL = (
    '$env:Path += ";$(if ($env:PIPX_BIN_DIR) { $env:PIPX_BIN_DIR } '
    'else { "$HOME\\.local\\bin" })"'
)
# MAITY_CLI_INSTALL is written for a POSIX shell; with one of these it is not a single command.
SHELL_OPERATORS = re.compile(r"[&|;<>$`()]")
# PowerShell reads these differently too: an environment prefix runs as a command name, and it
# does not expand a `~` inside a native command's argument the way a POSIX shell does.
POSIX_WORDS = re.compile(r"^\S*=|(^|\s)~")
# Windows PowerShell 5.1 pipes into a native command in `$OutputEncoding`, ASCII by default, and
# reads its output in the console's OEM code page: an `ü` piped into maity arrives as `?`, which
# strict UTF-8 cannot tell from a real `?`. UTF-8 without a mark, for this shell and its console
# window only, so it helps an agent that keeps working in it; PowerShell 7 already pipes UTF-8.
UTF8_POWERSHELL = (
    "$OutputEncoding = [Console]::InputEncoding = [Console]::OutputEncoding = "
    "New-Object System.Text.UTF8Encoding $false"
)
# Windows has no pipx unless someone installed it. `pip install --user` puts its pipx.exe into a
# Scripts directory that is not on the PATH either, so the line runs it as a module.
PIPX_FOUND = "Get-Command pipx -ErrorAction SilentlyContinue"
ENSUREPATH = (
    "If `maity` is not found afterwards, run `pipx ensurepath` once (`python -m pipx ensurepath` "
    "where `pipx` itself is not found) and open a new shell; "
    "the line changes no shell profile itself."
)


def plain(url: str, code: str) -> str:
    """Only the join, for any system and shell where `maity` is already there."""
    return f"maity join {url} --code {code}"


def posix(install: str, url: str, code: str) -> str:
    """`[export PATH=… && ]{ command -v maity … || { <install line>; }; } && maity join …`. The PATH
    step comes first, so a CLI installed earlier is found too, and only for a pipx install line.
    The inner braces keep a compound install line whole behind the `||`."""
    path = f"{PIPX_PATH} && " if install.startswith("pipx ") else ""
    return (
        f"{path}{{ command -v maity >/dev/null 2>&1 || {{ {install}; }}; }} "
        f"&& {plain(url, code)}"
    )


def windows(install: str, url: str, code: str) -> str | None:
    """The same for PowerShell, or None for an install line it would read differently. It sets
    the shell's encodings to UTF-8 first (`UTF8_POWERSHELL`). `;` because Windows PowerShell 5.1
    has no `&&`; the second check because `;` would run the join after a failed install, with
    the code in the error message on the screen. A pipx install line gets the PATH step and,
    where pipx is missing, installs pipx with `python -m pip install --user` and runs it as a
    module."""
    if SHELL_OPERATORS.search(install) or POSIX_WORDS.search(install):
        return None
    path = ""
    if install.startswith("pipx "):
        path = f"{PIPX_PATH_POWERSHELL}; "
        install = (
            f"if ({PIPX_FOUND}) {{ {install} }} "
            f"else {{ python -m pip install --user pipx; python -m {install} }}"
        )
    found = "Get-Command maity -ErrorAction SilentlyContinue"
    return (
        f"{UTF8_POWERSHELL}; {path}if (-not ({found})) {{ {install} }}; "
        f"if ({found}) {{ {plain(url, code)} }}"
    )
