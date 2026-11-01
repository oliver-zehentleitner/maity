"""Who can reach a file on Windows, where mode bits say nothing (context/credentials.md).

`st_mode` there reports 0666 or 0444 whatever the access list says, and `os.chmod` sets only the
read-only flag. So the state directory gets an access list of its own, inherited by what is
created in it, and `state.check_private` reads the real one. Standard library only: `ctypes` on
`advapi32`, because the CLI has no dependencies and `icacls` prints localized text.

The rule is pure and testable anywhere; the calls exist on Windows only.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

SYSTEM = "S-1-5-18"
ADMINISTRATORS = "S-1-5-32-544"
# The counterpart of root: they can take any file, so naming them on a list changes nothing.
ALWAYS = frozenset({SYSTEM, ADMINISTRATORS})
OWNER_RIGHTS = "S-1-3-4"  # whoever owns the file; Python's own mkdir(mode=0o700) writes this one

ACCESS_ALLOWED = 0
ACCESS_DENIED = 1
INHERIT_ONLY = 0x08  # says what children get, grants nothing on the object itself


@dataclass(frozen=True)
class Entry:
    """One entry of an access list. `sid` is empty when the entry's type doesn't hold one where
    a plain entry does."""

    kind: int
    flags: int
    mask: int
    sid: str


@dataclass(frozen=True)
class Reach:
    """What stands between a file and "only this user": an owner who is someone else, and
    everyone else the list lets in."""

    foreign_owner: str | None
    others: tuple[str, ...]


def judge(me: str, owner: str, entries: list[Entry] | None) -> Reach:
    """`entries` None is a file with no access list at all, which Windows opens to everyone (a
    file system without lists, such as exFAT). An entry of a type this code doesn't read counts
    as someone else: a refusal can be fixed, a silent pass can't be seen."""
    mine = ALWAYS | {me}
    foreign_owner = None if owner in mine else owner
    mine |= {OWNER_RIGHTS}  # someone else as the owner is named above
    if entries is None:
        return Reach(foreign_owner, ("everyone (no access list)",))
    others: list[str] = []
    for entry in entries:
        if entry.kind == ACCESS_DENIED or entry.flags & INHERIT_ONLY or not entry.mask:
            continue
        if entry.kind != ACCESS_ALLOWED:
            who = f"an access entry of type {entry.kind}"
        elif entry.sid in mine:
            continue
        else:
            who = entry.sid
        if who not in others:
            others.append(who)
    return Reach(foreign_owner, tuple(others))


def private_sddl(me: str) -> str:
    """The list of a private directory: protected from what its parent would pass down, and
    passed on to what is created in it (`OICI`), which is what makes `mkstemp` private there."""
    return f"D:PAI(A;OICI;FA;;;{me})(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"


def fix_command(path: Path, me: str, others: tuple[str, ...]) -> str:
    """The way out a refusal names, with SIDs, because account names are localized. Cutting
    inheritance takes what the parent passed down; what was set on `path` itself goes by name."""
    inherit = "(OI)(CI)" if path.is_dir() else ""
    remove = "".join(f' /remove "*{sid}"' for sid in others if sid.startswith("S-"))
    return f'icacls "{path}" /inheritance:r /grant:r "*{me}:{inherit}F"{remove}'


if sys.platform == "win32":
    from ctypes import byref, wintypes
    from functools import lru_cache

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _SE_FILE_OBJECT = 1
    _OWNER_SECURITY_INFORMATION = 0x1
    _DACL_SECURITY_INFORMATION = 0x4
    _PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    _TOKEN_QUERY = 0x8
    _TOKEN_USER = 1
    _ACL_SIZE_INFORMATION = 2
    _SDDL_REVISION_1 = 1
    _SID_OFFSET = 8  # type, flags, size, mask; the SID starts where a plain entry ends

    class _AceHeader(ctypes.Structure):
        _fields_ = [
            ("kind", ctypes.c_ubyte),
            ("flags", ctypes.c_ubyte),
            ("size", ctypes.c_ushort),
            ("mask", ctypes.c_uint32),
        ]

    class _AclSize(ctypes.Structure):
        _fields_ = [
            ("count", wintypes.DWORD),
            ("used", wintypes.DWORD),
            ("free", wintypes.DWORD),
        ]

    _void = ctypes.c_void_p
    _out = ctypes.POINTER(ctypes.c_void_p)

    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, _out, _out, _out, _out, _out,
    ]  # fmt: skip
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, _void, _void, _void, _void,
    ]  # fmt: skip
    _advapi32.GetAclInformation.restype = wintypes.BOOL
    _advapi32.GetAclInformation.argtypes = [_void, _void, wintypes.DWORD, ctypes.c_int]
    _advapi32.GetAce.restype = wintypes.BOOL
    _advapi32.GetAce.argtypes = [_void, wintypes.DWORD, _out]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [_void, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, _out, _void,
    ]  # fmt: skip
    _advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    _advapi32.GetSecurityDescriptorDacl.argtypes = [
        _void, ctypes.POINTER(wintypes.BOOL), _out, ctypes.POINTER(wintypes.BOOL),
    ]  # fmt: skip
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]  # fmt: skip
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, _void, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]  # fmt: skip
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.LocalFree.restype = _void
    _kernel32.LocalFree.argtypes = [_void]

    def _sid_text(sid: int | None) -> str:
        text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(sid, byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return str(text.value)
        finally:
            _kernel32.LocalFree(ctypes.cast(text, _void))

    @lru_cache(maxsize=1)
    def current_user() -> str:
        """The SID of the user this process runs as."""
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(), _TOKEN_QUERY, byref(token)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            needed = wintypes.DWORD()
            _advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not _advapi32.GetTokenInformation(
                token, _TOKEN_USER, buffer, needed.value, byref(needed)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel32.CloseHandle(token)
        # TOKEN_USER starts with a SID_AND_ATTRIBUTES, which starts with the pointer to the SID.
        return _sid_text(ctypes.cast(buffer, ctypes.POINTER(_void)).contents.value)

    def _entries(dacl: int) -> list[Entry]:
        size = _AclSize()
        if not _advapi32.GetAclInformation(
            dacl, byref(size), ctypes.sizeof(size), _ACL_SIZE_INFORMATION
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        entries: list[Entry] = []
        for index in range(size.count):
            ace = _void()
            if not _advapi32.GetAce(dacl, index, byref(ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            head = ctypes.cast(ace, ctypes.POINTER(_AceHeader)).contents
            plain = head.kind in (ACCESS_ALLOWED, ACCESS_DENIED)
            sid = _sid_text((ace.value or 0) + _SID_OFFSET) if plain else ""
            entries.append(Entry(head.kind, head.flags, head.mask, sid))
        return entries

    def reach(path: Path) -> Reach:
        """Read the owner and the access list of `path` and judge them."""
        owner, dacl, descriptor = _void(), _void(), _void()
        code = _advapi32.GetNamedSecurityInfoW(
            str(path),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            byref(owner),
            None,
            byref(dacl),
            None,
            byref(descriptor),
        )
        if code:
            raise ctypes.WinError(code)
        try:
            entries = _entries(dacl.value) if dacl.value else None
            return judge(current_user(), _sid_text(owner.value), entries)
        finally:
            _kernel32.LocalFree(descriptor)

    def protect(path: Path) -> None:
        """Give the directory `path` the private list of `private_sddl`."""
        descriptor = _void()
        if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            private_sddl(current_user()), _SDDL_REVISION_1, byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), _void()
            if not _advapi32.GetSecurityDescriptorDacl(
                descriptor, byref(present), byref(dacl), byref(defaulted)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            code = _advapi32.SetNamedSecurityInfoW(
                str(path),
                _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
                None,
                None,
                dacl,
                None,
            )
            if code:
                raise ctypes.WinError(code)
        finally:
            _kernel32.LocalFree(descriptor)
