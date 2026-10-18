"""Rotating local diagnostics for Beta method/property investigations."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path


def configure_logging(directory: str | Path | None = None) -> Path | None:
    logger = logging.getLogger("lpa")
    for handler in logger.handlers:
        if isinstance(handler,RotatingFileHandler):
            return Path(handler.baseFilename)
    folder = Path(directory) if directory is not None else Path(os.environ.get("LOCALAPPDATA",Path.home()/".local"/"state"))/"LPA"/"logs"
    try:
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/"lpa.log"
        handler=RotatingFileHandler(path,maxBytes=2_000_000,backupCount=4,encoding="utf-8")
    except OSError:
        # A read-only profile must not prevent the application from starting.
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    from . import __version__
    logger.info("LPA %s Beta diagnostics started",__version__)
    return path
