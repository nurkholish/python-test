"""Centralised logging setup shared by every module."""
from __future__ import annotations

import logging

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(
    level: int = logging.INFO,
    fmt: str = _DEFAULT_FORMAT,
) -> None:
    """Idempotent root-logger configuration.

    Safe to call multiple times: if the host application already configured
    handlers, only the level is adjusted.
    """
    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return
    logging.basicConfig(level=level, format=fmt)