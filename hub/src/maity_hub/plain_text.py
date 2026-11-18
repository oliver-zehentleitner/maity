"""The plain-text rule (docs/api.md §1.7.1): what a name, a note, a link, a subject, a bridge's
purpose or a human's preferences may hold. One module, so every field gets the same answer and
the rule changes in one place (hub/context/plain-text.md)."""

from __future__ import annotations

import unicodedata

# Every control character (Cc), every format character (Cf: zero width, bidi controls and
# marks, BOM, soft hyphen, the tag block U+E0000), a lone surrogate (Cs), a private-use
# character (Co), a code point this Python's Unicode data does not assign (Cn: unassigned ones
# and the noncharacters such as U+FFFF) and both Unicode line breaks (Zl, Zp). By category, as
# `routes/projects.py` `NOT_PLAIN` checks a checklist line and `routes/restricted.py` a
# restricted text, so a character nobody named is refused as well. A field that takes several
# lines keeps the line feed and the tab (`keep`).
NOT_PLAIN = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def plain(value: str, keep: str = "") -> bool:
    """Whether `value` is plain text: no character of `NOT_PLAIN` but those in `keep`."""
    return not any(unicodedata.category(ch) in NOT_PLAIN and ch not in keep for ch in value)


ZWJ = "‍"  # zero-width joiner: joins emoji into one picture (👩‍💻)
VS16 = "️"  # variation selector 16: an emoji's picture form (❤️)
# An emoji character, which a joiner of a name stands between. Python's `unicodedata` has no
# Extended_Pictographic property, so: category So in the blocks that hold the emoji, U+1F000
# and above (pictographs, the regional indicators U+1F1E6–U+1F1FF of a flag), the
# miscellaneous symbols and dingbats U+2600–U+27BF and the miscellaneous symbols and arrows
# U+2B00–U+2BFF (U+2B50, U+2B1B), and the skin-tone modifiers U+1F3FB–U+1F3FF, which are Sk
# (§1.7.1). A symbol of category So elsewhere (U+00A9, U+2122, the braille patterns
# U+2800–U+28FF) takes no joiner.
EMOJI_FROM = 0x1F000
SYMBOLS_AND_DINGBATS = range(0x2600, 0x27C0)
SYMBOLS_AND_ARROWS = range(0x2B00, 0x2C00)
SKIN_TONES = range(0x1F3FB, 0x1F400)
# U+FE0F asks for a character's emoji presentation, so it may also follow a symbol that has a
# text and an emoji form: category So in U+2000–U+2BFF (U+2122, U+231A) but the braille
# patterns, and U+00A9, U+00AE (§1.7.1).
VS16_SYMBOLS = range(0x2000, 0x2C00)
BRAILLE = range(0x2800, 0x2900)
TEXT_DEFAULT = frozenset(chr(code) for code in (0x00A9, 0x00AE))
# Characters that show as nothing but are letters (Lo) or symbols (So): the Hangul fillers
# U+115F, U+1160, U+3164, U+FFA0 and the blank braille pattern U+2800. A name of these and
# spaces (Zs) alone is refused; inside a name with something to read they pass (§1.7.1).
FILLERS = frozenset(chr(code) for code in (0x115F, 0x1160, 0x3164, 0xFFA0, 0x2800))


def is_emoji(ch: str) -> bool:
    code = ord(ch)
    if code in SKIN_TONES:
        return True
    in_block = code >= EMOJI_FROM or code in SYMBOLS_AND_DINGBATS or code in SYMBOLS_AND_ARROWS
    return in_block and unicodedata.category(ch) == "So"


def takes_vs16(ch: str) -> bool:
    """Whether U+FE0F may stand right after `ch` in a name: an emoji character, or a symbol
    with an emoji form (`VS16_SYMBOLS` but braille, `TEXT_DEFAULT`)."""
    if is_emoji(ch) or ch in TEXT_DEFAULT:
        return True
    code = ord(ch)
    symbol = code in VS16_SYMBOLS and code not in BRAILLE
    return symbol and unicodedata.category(ch) == "So"


def _blank(value: str) -> bool:
    """Nothing to read: spaces (Zs) and `FILLERS` only."""
    return all(unicodedata.category(ch) == "Zs" or ch in FILLERS for ch in value)


def plain_name(value: str) -> bool:
    """A name (§1.7.1): `plain`, except that U+200D stands only between two emoji characters
    (or after a symbol with U+FE0F, before an emoji character) and U+FE0F only right after a
    character that `takes_vs16`, so an emoji sequence (👩‍💻, ❤️, ©️) is a name's and a joiner
    between letters, at either end or after a selector of a letter is not. A name that is not
    empty but blank (`_blank`) is refused too; an empty one is left to the field's length."""
    if value and _blank(value):
        return False
    for at, ch in enumerate(value):
        before = value[at - 1] if at > 0 else ""
        after = value[at + 1] if at + 1 < len(value) else ""
        if ch == VS16:
            if not before or not takes_vs16(before):
                return False
        elif ch == ZWJ:
            emoji_before = bool(before) and (
                is_emoji(before) or (before == VS16 and at > 1 and takes_vs16(value[at - 2]))
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
