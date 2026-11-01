"""Encrypts small secrets (like the Google sign-in token) with Windows' own data protection (DPAPI).

The result can only be decrypted by the same Windows user account on this PC. That protects the file if it is copied
off the disk, backed up, synced or read by another Windows user. It does not stop another program running as you from
asking Windows to decrypt it, because that is how DPAPI works for every program you run. No extra packages needed.
"""
from __future__ import annotations

import base64
import ctypes
import json
import sys
from ctypes import wintypes

_ENTROPY = b"JARVIS-secretbox-v1"   # extra input, so a blob from another program can't be mistaken for ours


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf   # keep buf alive as long as the blob is used


def _call(fn_name: str, data: bytes) -> bytes:
    if not available():
        raise OSError("encryption needs Windows")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    fn = getattr(crypt32, fn_name)
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    inb, keep_in = _blob(data)
    ent, keep_ent = _blob(_ENTROPY)
    out = _Blob()
    if fn_name == "CryptProtectData":
        ok = fn(ctypes.byref(inb), "JARVIS", ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    else:
        ok = fn(ctypes.byref(inb), None, ctypes.byref(ent), None, None, 0, ctypes.byref(out))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
        del keep_in, keep_ent


def protect(data: bytes) -> bytes:
    return _call("CryptProtectData", data)


def unprotect(data: bytes) -> bytes:
    return _call("CryptUnprotectData", data)


def seal(obj) -> str:
    """JSON-able object -> encrypted text safe to put in a file."""
    return base64.b64encode(protect(json.dumps(obj).encode("utf-8"))).decode("ascii")


def unseal(text: str):
    """The reverse of seal. Raises OSError if this Windows account can't decrypt it (or it isn't ours)."""
    try:
        return json.loads(unprotect(base64.b64decode(text)).decode("utf-8"))
    except (ValueError, OSError) as e:
        raise OSError(f"couldn't decrypt: {e}") from None
