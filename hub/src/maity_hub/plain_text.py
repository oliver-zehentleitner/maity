"""The plain-text rule (docs/api.md §1.7.1): what a name, a note, a link, a subject, a bridge's
purpose or a human's preferences may hold. One module, so every field gets the same answer and
the rule changes in one place (hub/context/plain-text.md)."""

from __future__ import annotations

import unicodedata

# Every control character (Cc), every format character (Cf: zero width, bidi controls and
# marks, BOM, soft hyphen, the tag block U+E0000), a lone surrogate (Cs), a private-use
# character (Co) and both Unicode line breaks (Zl, Zp). By category, as `routes/projects.py`
# `NOT_PLAIN` checks a checklist line and `routes/restricted.py` a restricted text, so a
# character nobody named is refused as well. A field that takes several lines keeps the line
# feed and the tab (`keep`).
NOT_PLAIN = frozenset({"Cc", "Cf", "Cs", "Co", "Zl", "Zp"})


def plain(value: str, keep: str = "") -> bool:
    """Whether `value` is plain text: no character of `NOT_PLAIN` but those in `keep`."""
    return not any(unicodedata.category(ch) in NOT_PLAIN and ch not in keep for ch in value)


ZWJ = "\u200d"  # zero-width joiner: joins emoji into one picture (👩‍💻)
VS16 = "\ufe0f"  # variation selector 16: an emoji's picture form (❤️)
# An emoji character, for the two exceptions of a name. Python's `unicodedata` has no
# Extended_Pictographic property, so: category So (pictographs, dingbats, regional indicators)
# and the skin-tone modifiers U+1F3FB–U+1F3FF, which are Sk (§1.7.1).
SKIN_TONES = range(0x1F3FB, 0x1F400)


def is_emoji(ch: str) -> bool:
    return unicodedata.category(ch) == "So" or ord(ch) in SKIN_TONES


def plain_name(value: str) -> bool:
    """A name (§1.7.1): `plain`, except that U+200D stands only between two emoji characters and
    U+FE0F only right after one, so an emoji sequence (👩‍💻, ❤️) is a name's and a joiner
    between letters, at either end or after a selector of a letter is not."""
    for at, ch in enumerate(value):
        before = value[at - 1] if at > 0 else ""
        after = value[at + 1] if at + 1 < len(value) else ""
        if ch == VS16:
            if not before or not is_emoji(before):
                return False
        elif ch == ZWJ:
            emoji_before = bool(before) and (
                is_emoji(before) or (before == VS16 and at > 1 and is_emoji(value[at - 2]))
            )
            if not emoji_before or not after or not is_emoji(after):
                return False
        elif unicodedata.category(ch) in NOT_PLAIN:
            return False
    return True


def is_plain_line(value: str) -> bool:
    """One line of plain text (§2.3, a bridge's purpose): `plain` with nothing kept."""
    return plain(value)


def plain_line(value: str) -> str:
    """`value` with each run of refused characters as one space: a value stored before the
    rule, put into a text or Markdown line for agents, stays on that line (§1.7.1)."""
    out: list[str] = []
    for ch in value:
        if unicodedata.category(ch) in NOT_PLAIN:
            if out and out[-1] != " ":
                out.append(" ")
        else:
            out.append(ch)
    return "".join(out).strip()
