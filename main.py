"""Direct launcher for LGJ Propulsion Analysis."""

from __future__ import annotations

import ctypes
import os
import sys


WINDOWS_APP_USER_MODEL_ID = "LGJ.LPA"


def _configure_windows_app_identity() -> None:
    """Give Windows a stable identity for taskbar grouping and icon selection."""

    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def _configure_windows_dpi() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main() -> int:
    _configure_windows_app_identity()
    _configure_windows_dpi()
    from lpa.logging_config import configure_logging
    configure_logging()
    from lpa.app import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
