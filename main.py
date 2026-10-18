"""Direct launcher for LGJ Propulsion Analysis."""

from __future__ import annotations

import ctypes
import logging
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
    try:
        _configure_windows_app_identity()
        _configure_windows_dpi()
        from lpa.logging_config import configure_logging

        configure_logging()
        logger = logging.getLogger("lpa")
        logger.info("Starting GUI with Python %s (%s)", sys.version.split()[0], sys.executable)
        from lpa.app import run

        run()
    except KeyboardInterrupt:
        # Ctrl+C / VS Code Stop can also arrive while importing Matplotlib
        # or constructing the GUI, before app.run() owns the event loop.
        logging.getLogger("lpa").info("Startup cancelled by an interrupt")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
