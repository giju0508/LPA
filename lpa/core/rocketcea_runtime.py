"""Windows runtime compatibility for RocketCEA's writable CEA work files.

RocketCEA 1.2.3 cannot safely pass a Windows home path containing spaces or
non-ASCII characters to its legacy Fortran work-file layer and may redirect
the work directory to ``C:\\UserData``.  Creating that directory requires
elevated permissions on a typical PC.  LPA keeps the data in the normal user
profile and presents the path to RocketCEA through an ASCII, space-free alias
only while RocketCEA is imported.
"""

from __future__ import annotations

import atexit
import ctypes
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_SAFE_FORTRAN_PATH = re.compile(r"[A-Za-z0-9_~.\\/:\-]+\Z")
_IMPORT_LOCK = threading.RLock()


@dataclass(slots=True)
class _DriveAlias:
    name: str
    target: str
    closed: bool = False

    def close(self) -> None:
        if self.closed or os.name != "nt":
            return
        define_device = _define_dos_device()
        flags = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008
        define_device(flags, self.name, self.target)
        self.closed = True


_runtime_home: Path | None = None
_runtime_import_home: str | None = None
_runtime_drive_alias: _DriveAlias | None = None


def _is_fortran_safe_path(path: str | os.PathLike[str]) -> bool:
    """Return whether the legacy CEA interface can safely parse this path."""

    return bool(_SAFE_FORTRAN_PATH.fullmatch(os.fspath(path)))


def _define_dos_device():  # type: ignore[no-untyped-def]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.DefineDosDeviceW
    function.argtypes = (ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p)
    function.restype = ctypes.c_int
    return function


def _query_dos_device():  # type: ignore[no-untyped-def]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.QueryDosDeviceW
    function.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_uint
    return function


def _short_path(path: Path) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = kernel32.GetShortPathNameW
    function.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    function.restype = ctypes.c_uint
    required = function(str(path), None, 0)
    if not required:
        return None
    buffer = ctypes.create_unicode_buffer(required + 1)
    if not function(str(path), buffer, len(buffer)):
        return None
    candidate = buffer.value
    return candidate if _is_fortran_safe_path(candidate) else None


def _nt_target(path: Path) -> str:
    text = str(path)
    if text.startswith("\\\\"):
        return "\\??\\UNC\\" + text.lstrip("\\")
    return "\\??\\" + text


def _create_drive_alias(path: Path) -> _DriveAlias:
    """Map a free drive letter to *path* without requiring administrator rights."""

    define_device = _define_dos_device()
    query_device = _query_dos_device()
    target = _nt_target(path)
    query_buffer = ctypes.create_unicode_buffer(32_768)
    flags = 0x00000001 | 0x00000008  # RAW_TARGET_PATH | NO_BROADCAST_SYSTEM

    for letter in reversed("DEFGHIJKLMNOPQRSTUVWXYZ"):
        name = f"{letter}:"
        ctypes.set_last_error(0)
        if query_device(name, query_buffer, len(query_buffer)):
            continue
        # ERROR_FILE_NOT_FOUND means the DOS device name is available.
        if ctypes.get_last_error() not in (0, 2):
            continue
        if define_device(flags, name, target):
            alias = _DriveAlias(name=name, target=target)
            atexit.register(alias.close)
            return alias

    raise OSError("No free drive letter is available for RocketCEA work files")


def _resolve_import_home(home: Path) -> tuple[str, _DriveAlias | None]:
    """Return a CEA-safe alias whose storage still resolves to *home*."""

    if _is_fortran_safe_path(home):
        return str(home), None

    # GetShortPathName is non-invasive when 8.3 names are enabled.  Modern
    # Windows installations may disable them, so a per-user DOS drive alias is
    # the reliable fallback; DefineDosDevice does not require elevation.
    short = _short_path(home)
    if short is not None:
        return short, None

    mapping = _create_drive_alias(home)
    return f"{mapping.name}\\", mapping


def _configured_import_home() -> str:
    global _runtime_home, _runtime_import_home, _runtime_drive_alias

    home = Path.home().resolve()
    if _runtime_import_home is not None and _runtime_home == home:
        return _runtime_import_home
    if _runtime_import_home is not None:
        raise OSError("The Windows user profile changed after RocketCEA initialization")

    import_home, mapping = _resolve_import_home(home)
    _runtime_home = home
    _runtime_import_home = import_home
    _runtime_drive_alias = mapping
    return import_home


@contextmanager
def rocketcea_import_environment() -> Iterator[None]:
    """Expose a safe home path during RocketCEA's one-time module import.

    Environment variables are restored immediately after import.  If a drive
    alias is required, it remains mapped until process exit because the
    compiled CEA library continues to access that alias during calculations.
    """

    if os.name != "nt":
        yield
        return

    with _IMPORT_LOCK:
        import_home = _configured_import_home()
        keys = ("USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH")
        original = {key: os.environ.get(key) for key in keys}
        drive, tail = os.path.splitdrive(import_home)
        try:
            os.environ["USERPROFILE"] = import_home
            os.environ["HOME"] = import_home
            os.environ["HOMEDRIVE"] = drive
            os.environ["HOMEPATH"] = tail or "\\"
            yield
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
